from __future__ import annotations

import importlib
import io
import unicodedata
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .enhancement import EnhancementManager, EnhancementStatus


class RecognitionService(QObject):
    """Background recognition pipeline with an optional model runtime."""

    progress = Signal(int, str)
    finished = Signal(int, object, str, str)
    preload_finished = Signal(str)
    enhancement_verified = Signal(bool, str)

    def __init__(
        self,
        enhancement_manager: EnhancementManager,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.enhancement_manager = enhancement_manager
        self.detector = None
        self.qr_reader = None
        self.preload_running = False
        self.preload_ready = False
        self.preload_error = ""
        self._preload_started = False
        self._preload_pending = 0
        self._preload_errors: list[str] = []
        self._request_id = 0
        self._futures: dict[int, Future] = {}
        self._model_preload_future: Future | None = None
        self._qreader_patch_installed = False

        self.decode_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="qrcap-decode",
        )
        self.model_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="qrcap-model",
        )
        self.enhancement_manager.activate_runtime()

    def start_background_preload(self) -> None:
        if self._preload_started:
            return
        self._preload_started = True
        self.preload_running = True
        self._preload_errors = []

        futures = [self.decode_executor.submit(self._preload_fast_engine)]
        if self.enhancement_manager.inspect().can_load:
            model_future = self.model_executor.submit(self._preload_model_engine)
            self._model_preload_future = model_future
            futures.append(model_future)

        self._preload_pending = len(futures)
        for future in futures:
            future.add_done_callback(self._notify_preload_component_finished)

    def reload_enhancement(self) -> EnhancementStatus:
        status = self.enhancement_manager.activate_runtime()
        if not status.can_load:
            self.enhancement_verified.emit(
                False,
                "增强包组件不完整，已继续使用基础识别。",
            )
            return status

        if self.qr_reader is not None:
            self.enhancement_verified.emit(
                True,
                "当前模型已经加载；新导入的运行库将在重启程序后完全生效。",
            )
            return status

        if self._model_preload_future and not self._model_preload_future.done():
            return status

        self.preload_running = True
        future = self.model_executor.submit(self._preload_model_engine)
        self._model_preload_future = future
        future.add_done_callback(self._notify_optional_model_finished)
        return status

    def submit(self, image: QImage, source: str) -> int:
        self._request_id += 1
        request_id = self._request_id
        future = self.decode_executor.submit(
            self._run_decode_job,
            request_id,
            image.copy(),
            source,
        )
        self._futures[request_id] = future
        return request_id

    def discard_request(self, request_id: int) -> None:
        self._futures.pop(request_id, None)

    def shutdown(self) -> None:
        self.decode_executor.shutdown(wait=False, cancel_futures=True)
        self.model_executor.shutdown(wait=False, cancel_futures=True)

    def _preload_fast_engine(self) -> None:
        import zxingcpp  # noqa: F401
        from pyzbar.pyzbar import ZBarSymbol, decode  # noqa: F401

        try:
            import cv2
        except ImportError:
            return
        if self.detector is None:
            self.detector = cv2.QRCodeDetector()

    def _preload_model_engine(self) -> None:
        import numpy as np

        reader = self._get_qr_reader()
        dummy = np.full((256, 256, 3), 255, dtype=np.uint8)
        reader.detect_and_decode(image=dummy, is_bgr=True)
        versions = self.enhancement_manager.installed_versions()
        detail = "QReader/PyTorch 导入成功，模型首次推理通过。"
        self.enhancement_manager.record_runtime_verification(
            True,
            detail,
            versions,
        )
        self.enhancement_verified.emit(True, detail)

    def _notify_preload_component_finished(self, future: Future) -> None:
        error = ""
        try:
            future.result()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._record_model_failure_if_needed(future, error)

        if error:
            self._preload_errors.append(error)
        self._preload_pending -= 1
        if self._preload_pending > 0:
            return

        self.preload_running = False
        self.preload_error = "; ".join(self._preload_errors)
        self.preload_ready = not self.preload_error
        self.preload_finished.emit(self.preload_error)

    def _notify_optional_model_finished(self, future: Future) -> None:
        self.preload_running = False
        try:
            future.result()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.enhancement_manager.record_runtime_verification(False, error)
            self.enhancement_verified.emit(False, error)

    def _record_model_failure_if_needed(
        self,
        future: Future,
        error: str,
    ) -> None:
        if future is self._model_preload_future:
            self.enhancement_manager.record_runtime_verification(False, error)
            self.enhancement_verified.emit(False, error)

    def _get_qr_reader(self):
        if self.qr_reader is not None:
            return self.qr_reader

        status = self.enhancement_manager.activate_runtime()
        if not status.can_load:
            raise RuntimeError("未安装完整且兼容的增强包。")

        model_path = self.enhancement_manager.model_path
        if not model_path.is_file():
            raise FileNotFoundError(f"未找到增强识别模型：{model_path}")

        self._install_local_model_patch(model_path)
        QReader = importlib.import_module("qreader").QReader

        self.qr_reader = QReader(
            model_size="s",
            weights_folder=str(model_path.parent),
        )
        return self.qr_reader

    def _install_local_model_patch(self, model_path) -> None:
        if self._qreader_patch_installed:
            return

        requests = importlib.import_module("requests")
        requests_sessions = importlib.import_module("requests.sessions")
        RequestsResponse = importlib.import_module(
            "requests.models"
        ).Response

        original_get = requests.get
        original_session_request = requests_sessions.Session.request

        def build_response(url: str) -> RequestsResponse:
            data = model_path.read_bytes()
            response = RequestsResponse()
            response.status_code = 200
            response._content = data
            response.headers["Content-Length"] = str(len(data))
            response.url = url
            response.raw = io.BytesIO(data)

            def iter_content(chunk_size=8192):
                for offset in range(0, len(data), chunk_size):
                    yield data[offset:offset + chunk_size]

            response.iter_content = iter_content
            return response

        def local_get(url, *args, **kwargs):
            if (
                isinstance(url, str)
                and "qrdet-s.pt" in url
                and model_path.exists()
            ):
                return build_response(url)
            return original_get(url, *args, **kwargs)

        def local_request(session, method, url, *args, **kwargs):
            if (
                method
                and method.upper() == "GET"
                and isinstance(url, str)
                and "qrdet-s.pt" in url
            ):
                return local_get(url, *args, **kwargs)
            return original_session_request(
                session,
                method,
                url,
                *args,
                **kwargs,
            )

        requests.get = local_get
        requests_sessions.Session.request = local_request
        self._qreader_patch_installed = True

    def _run_decode_job(
        self,
        request_id: int,
        image: QImage,
        source: str,
    ) -> None:
        try:
            prepared_image = self._prepare_decode_image(image)
            result = self.decode_image_auto(
                prepared_image,
                lambda message: self.progress.emit(request_id, message),
            )
            self.finished.emit(request_id, result, source, "")
        except Exception as error:
            self.finished.emit(
                request_id,
                [],
                source,
                f"{type(error).__name__}: {error}",
            )

    @staticmethod
    def _prepare_decode_image(image):
        if not isinstance(image, QImage):
            return image

        return image.convertToFormat(QImage.Format.Format_RGB888).copy()

    @staticmethod
    def _qimage_to_bgr(image):
        import numpy as np

        qimage = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width = qimage.width()
        height = qimage.height()
        bytes_per_line = qimage.bytesPerLine()
        buffer = np.frombuffer(
            qimage.bits(),
            dtype=np.uint8,
            count=height * bytes_per_line,
        ).reshape((height, bytes_per_line))
        rgba = buffer[:, : width * 4].reshape((height, width, 4))
        return rgba[:, :, :3][:, :, ::-1].copy()

    def decode_image_auto(self, image, progress) -> list[str]:
        progress("正在使用基础互补解码器识别…")
        texts = self._decode_with_fast_decoders(image, include_all=True)
        if texts:
            return texts

        progress("正在增强低对比度和小尺寸二维码…")
        for _, variant in self._iter_fallback_images(image):
            texts = self._decode_with_fast_decoders(
                variant,
                include_all=False,
            )
            if texts:
                return texts

        status = self.enhancement_manager.inspect()
        if not status.can_load:
            progress("基础识别已完成；当前没有完整可用的增强包。")
            return []

        progress("正在使用可选增强模型识别…")
        try:
            model_future = self.model_executor.submit(
                self._decode_with_model,
                image.copy(),
            )
            return model_future.result()
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            self.enhancement_manager.record_runtime_verification(False, detail)
            self.enhancement_verified.emit(False, detail)
            return []

    def _decode_with_model(self, image) -> list[str]:
        reader = self._get_qr_reader()
        model_image = (
            self._qimage_to_bgr(image)
            if isinstance(image, QImage)
            else image
        )
        result = reader.detect_and_decode(image=model_image, is_bgr=True)
        return self._unique_texts(result or ())

    def _decode_with_fast_decoders(
        self,
        image,
        include_all: bool,
    ) -> list[str]:
        decoders = (
            self._decode_with_zxing,
            self._decode_with_pyzbar,
            self._decode_with_opencv,
        )
        texts: list[str] = []
        for decoder in decoders:
            try:
                texts.extend(decoder(image))
            except Exception:
                continue
            if texts and not include_all:
                break
        return self._unique_texts(texts)

    def _decode_with_opencv(self, image) -> list[str]:
        import cv2

        opencv_image = (
            self._qimage_to_bgr(image)
            if isinstance(image, QImage)
            else image
        )
        if self.detector is None:
            self.detector = cv2.QRCodeDetector()

        texts = []
        try:
            ok, decoded, _, _ = self.detector.detectAndDecodeMulti(
                opencv_image
            )
            if ok:
                texts.extend(decoded)
        except cv2.error:
            pass

        if not self._unique_texts(texts):
            try:
                text, _, _ = self.detector.detectAndDecode(opencv_image)
                texts.append(text)
            except cv2.error:
                pass

        if not self._unique_texts(texts):
            try:
                text, _, _ = self.detector.detectAndDecodeCurved(
                    opencv_image
                )
                texts.append(text)
            except (cv2.error, AttributeError):
                pass
        return self._unique_texts(texts)

    def _decode_with_zxing(self, image) -> list[str]:
        import zxingcpp

        texts = []
        for binarizer in (
            zxingcpp.Binarizer.LocalAverage,
            zxingcpp.Binarizer.GlobalHistogram,
            zxingcpp.Binarizer.FixedThreshold,
        ):
            for result in zxingcpp.read_barcodes(
                image,
                binarizer=binarizer,
            ):
                raw = bytes(result.bytes)
                texts.append(
                    self._decode_bytes(raw) if raw else result.text
                )
            if texts:
                break
        return self._unique_texts(texts)

    def _decode_with_pyzbar(self, image) -> list[str]:
        from pyzbar.pyzbar import ZBarSymbol, decode

        decode_image = image
        if isinstance(image, QImage):
            gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
            width = gray.width()
            height = gray.height()
            bytes_per_line = gray.bytesPerLine()
            raw = bytes(gray.constBits())
            if bytes_per_line == width:
                pixels = raw[: width * height]
            else:
                pixels = b"".join(
                    raw[
                        row * bytes_per_line:
                        row * bytes_per_line + width
                    ]
                    for row in range(height)
                )
            decode_image = (pixels, width, height)

        symbols = (
            ZBarSymbol.QRCODE,
            ZBarSymbol.CODE128,
            ZBarSymbol.EAN13,
            ZBarSymbol.EAN8,
        )
        return self._unique_texts(
            self._repair_pyzbar_text(
                self._decode_bytes(result.data)
            )
            for result in decode(decode_image, symbols=symbols)
        )

    @staticmethod
    def _repair_pyzbar_text(text: str) -> str:
        """Undo ZBar's UTF-8-as-Shift-JIS conversion when reversible."""
        try:
            repaired = text.encode("shift-jis").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return text
        return repaired or text

    @staticmethod
    def _decode_bytes(data) -> str:
        for encoding in ("utf-8", "gb18030", "shift-jis"):
            try:
                return bytes(data).decode(encoding)
            except UnicodeDecodeError:
                continue
        return bytes(data).decode("utf-8", errors="replace")

    @staticmethod
    def _unique_texts(texts) -> list[str]:
        return RecognitionService.unique_texts(texts)

    @staticmethod
    def unique_texts(texts) -> list[str]:
        result = []
        seen = set()
        for text in texts or ():
            if text is None:
                continue
            cleaned = unicodedata.normalize("NFC", str(text)).translate(
                {
                    ord("\ufeff"): None,
                    ord("\u200b"): None,
                    ord("\u200c"): None,
                    ord("\u200d"): None,
                    ord("\u2060"): None,
                }
            ).strip(" \t\r\n\x00")
            canonical = " ".join(
                unicodedata.normalize("NFKC", cleaned).split()
            )
            if canonical and canonical not in seen:
                seen.add(canonical)
                result.append(cleaned)
        return result

    @staticmethod
    def _iter_fallback_images(image):
        if isinstance(image, QImage):
            try:
                import cv2  # noqa: F401
                import numpy  # noqa: F401
            except ImportError:
                yield from RecognitionService._iter_qt_fallback_images(
                    image
                )
                return
            image = RecognitionService._qimage_to_bgr(image)

        import cv2
        import numpy as np

        gray = (
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            if image.ndim == 3
            else image
        )

        low, high = np.percentile(gray, (2, 98))
        if high > low:
            contrast = np.clip(
                (gray.astype(np.float32) - low)
                * (255.0 / (high - low)),
                0,
                255,
            ).astype(np.uint8)
            yield "低对比度增强", contrast

        clahe = cv2.createCLAHE(
            clipLimit=2.5,
            tileGridSize=(8, 8),
        ).apply(gray)
        yield "CLAHE", clahe

        block_size = max(15, min(51, (min(gray.shape[:2]) // 20) | 1))
        adaptive = cv2.adaptiveThreshold(
            clahe,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block_size,
            5,
        )
        yield "自适应阈值", adaptive

        if image.ndim == 3:
            for index, name in enumerate(("蓝色通道", "绿色通道", "红色通道")):
                yield name, image[:, :, index]

        border = max(16, round(min(gray.shape[:2]) * 0.08))
        padded = cv2.copyMakeBorder(
            gray,
            border,
            border,
            border,
            border,
            cv2.BORDER_CONSTANT,
            value=255,
        )
        yield "静区补白", padded

        max_axis = max(gray.shape[:2])
        if max_axis < 1200:
            scale = 3 if max_axis < 500 else 2
            upscaled = cv2.resize(
                gray,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_LANCZOS4,
            )
            blurred = cv2.GaussianBlur(upscaled, (0, 0), 1.0)
            sharpened = cv2.addWeighted(
                upscaled,
                1.6,
                blurred,
                -0.6,
                0,
            )
            yield "轻量超分辨率", sharpened

    @staticmethod
    def _iter_qt_fallback_images(image: QImage):
        """Compact fallback pipeline used when OpenCV is not bundled."""

        from array import array

        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QPainter

        gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
        width = gray.width()
        height = gray.height()
        bytes_per_line = gray.bytesPerLine()
        raw = bytes(gray.constBits())
        pixels = bytearray(width * height)
        for row in range(height):
            source_start = row * bytes_per_line
            target_start = row * width
            pixels[target_start:target_start + width] = raw[
                source_start:source_start + width
            ]

        def as_gray_image(data, image_width=width, image_height=height):
            return QImage(
                bytes(data),
                image_width,
                image_height,
                image_width,
                QImage.Format.Format_Grayscale8,
            ).copy()

        histogram = [0] * 256
        for value in pixels:
            histogram[value] += 1

        def percentile(percent):
            target = round(len(pixels) * percent)
            count = 0
            for value, frequency in enumerate(histogram):
                count += frequency
                if count >= target:
                    return value
            return 255

        low = percentile(0.02)
        high = percentile(0.98)
        if high > low:
            scale = 255.0 / (high - low)
            contrast = bytearray(
                0 if value <= low else
                255 if value >= high else
                round((value - low) * scale)
                for value in pixels
            )
            yield "低对比度增强", as_gray_image(contrast)

        cumulative = 0
        cdf_min = 0
        equalize_lut = [0] * 256
        for value, frequency in enumerate(histogram):
            cumulative += frequency
            if not cdf_min and cumulative:
                cdf_min = cumulative
            denominator = max(1, len(pixels) - cdf_min)
            equalize_lut[value] = max(
                0,
                min(255, round((cumulative - cdf_min) * 255 / denominator)),
            )
        equalized = bytearray(equalize_lut[value] for value in pixels)
        yield "直方图均衡", as_gray_image(equalized)

        threshold_source = gray
        threshold_width = width
        threshold_height = height
        if width * height > 1_500_000:
            threshold_source = gray.scaled(
                1200,
                1200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            threshold_width = threshold_source.width()
            threshold_height = threshold_source.height()

        threshold_bpl = threshold_source.bytesPerLine()
        threshold_raw = bytes(threshold_source.constBits())
        threshold_pixels = bytearray(
            threshold_width * threshold_height
        )
        for row in range(threshold_height):
            source_start = row * threshold_bpl
            target_start = row * threshold_width
            threshold_pixels[
                target_start:target_start + threshold_width
            ] = threshold_raw[
                source_start:source_start + threshold_width
            ]

        stride = threshold_width + 1
        integral = array(
            "Q",
            [0],
        ) * ((threshold_height + 1) * stride)
        for y in range(threshold_height):
            row_sum = 0
            source_row = y * threshold_width
            integral_row = (y + 1) * stride
            previous_row = y * stride
            for x in range(threshold_width):
                row_sum += threshold_pixels[source_row + x]
                integral[integral_row + x + 1] = (
                    integral[previous_row + x + 1] + row_sum
                )

        radius = max(
            7,
            min(25, min(threshold_width, threshold_height) // 40),
        )
        adaptive = bytearray(len(threshold_pixels))
        for y in range(threshold_height):
            y0 = max(0, y - radius)
            y1 = min(threshold_height, y + radius + 1)
            for x in range(threshold_width):
                x0 = max(0, x - radius)
                x1 = min(threshold_width, x + radius + 1)
                total = (
                    integral[y1 * stride + x1]
                    - integral[y0 * stride + x1]
                    - integral[y1 * stride + x0]
                    + integral[y0 * stride + x0]
                )
                mean = total / ((x1 - x0) * (y1 - y0))
                index = y * threshold_width + x
                adaptive[index] = (
                    255 if threshold_pixels[index] >= mean - 5 else 0
                )
        yield "自适应阈值", as_gray_image(
            adaptive,
            threshold_width,
            threshold_height,
        )

        if not image.isGrayscale():
            rgb = image.convertToFormat(QImage.Format.Format_RGB888)
            rgb_raw = bytes(rgb.constBits())
            rgb_bpl = rgb.bytesPerLine()
            for channel, name in (
                (0, "红色通道"),
                (1, "绿色通道"),
                (2, "蓝色通道"),
            ):
                channel_data = bytearray(width * height)
                for row in range(height):
                    row_start = row * rgb_bpl
                    target_start = row * width
                    channel_data[
                        target_start:target_start + width
                    ] = rgb_raw[
                        row_start + channel:
                        row_start + width * 3:
                        3
                    ]
                yield name, as_gray_image(channel_data)

        border = max(16, round(min(width, height) * 0.08))
        padded = QImage(
            width + border * 2,
            height + border * 2,
            QImage.Format.Format_Grayscale8,
        )
        padded.fill(255)
        painter = QPainter(padded)
        painter.drawImage(QPoint(border, border), gray)
        painter.end()
        yield "静区补白", padded

        max_axis = max(width, height)
        if max_axis < 1200:
            scale = 3 if max_axis < 500 else 2
            upscaled = gray.scaled(
                width * scale,
                height * scale,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            yield "轻量超分辨率", upscaled
