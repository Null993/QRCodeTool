import sys
import os
import json
import io
import html
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from datetime import datetime
import webbrowser
import re
import warnings
warnings.filterwarnings("ignore", message="Double decoding failed")

# ---------- 常量 ----------
HISTORY_FILE = "history.json"
CONFIG_FILE = "config.json"
MODEL_FILE = "model/qrdet-s.pt"  # 本地模型相对路径（相对于 main.py 或打包后的 _MEIPASS）

def resource_path(relative_path):
    """获取打包后资源的正确路径"""
    if hasattr(sys, '_MEIPASS'):
        return str(os.path.join(sys._MEIPASS, relative_path))
    return str(os.path.join(os.path.abspath("."), relative_path))

# ---------- 正则：识别文本中的第一个 URL（支持不带 scheme 的裸域名 / www） ----------
_url_re = re.compile(
    r"""(?xi)
    (
      https?://[^\s'"]+ |                     # 带 http(s) 的完整 URL
      www\.[^\s'"]+ |                         # 以 www. 开头的
      [a-z0-9\-.]+\.(?:com|net|org|io|gov|cn|xyz|top|info|biz|site|tech|me)(?:/[^\s'"]*)? # 裸域名+常见TLD（带可选路径）
    )
    """
)
def extract_first_url(text: str) -> str | None:
    """从文本中提取第一个 URL，若无则返回 None。
       若提取到裸域名或以 www. 开头的，会补上 http:// 以便 webbrowser.open 使用。"""
    m = _url_re.search(text)
    if not m:
        return None
    url = m.group(1)
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    return url

_qreader_patch_installed = False


def install_qreader_model_patch():
    """增强识别首次使用时再加载 requests/qreader，避免阻塞主窗口启动。"""
    global _qreader_patch_installed
    if _qreader_patch_installed:
        return

    import requests
    import requests.sessions
    from requests.models import Response as RequestsResponse

    local_model_path = resource_path(MODEL_FILE)
    original_get = requests.get
    original_session_request = requests.sessions.Session.request

    def build_response_from_file(path: str, url: str) -> RequestsResponse:
        with open(path, "rb") as model_file:
            data = model_file.read()

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

    def local_model_get(url, *args, **kwargs):
        if isinstance(url, str) and "qrdet-s.pt" in url and os.path.exists(local_model_path):
            return build_response_from_file(local_model_path, url)
        return original_get(url, *args, **kwargs)

    def local_model_request(session, method, url, *args, **kwargs):
        if method and method.upper() == "GET" and isinstance(url, str) and "qrdet-s.pt" in url:
            return local_model_get(url, *args, **kwargs)
        return original_session_request(session, method, url, *args, **kwargs)

    requests.get = local_model_get
    requests.sessions.Session.request = local_model_request
    _qreader_patch_installed = True

# ---------------------------
# GUI 相关导入
# ---------------------------
from PySide6.QtWidgets import (
    QApplication, QWidget, QTabWidget, QVBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QLineEdit, QSystemTrayIcon, QStyle, QMenu,
    QListWidget, QListWidgetItem, QMessageBox, QHBoxLayout, QCheckBox, QSizePolicy
)
from PySide6.QtGui import (
    QPixmap, QAction, QGuiApplication, QPainter, QPen, QColor, QImage, QIcon
)
from PySide6.QtCore import Qt, QRect, QPoint, QTimer, Signal
from PySide6.QtCore import QObject, Slot, QRectF

# ================================
#       截图框选窗口（高 DPI 修复）
# ================================
class CaptureScreen(QWidget):
    def __init__(self, callback, cancel_callback=None):
        super().__init__()
        self.callback = callback
        self.cancel_callback = cancel_callback

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Qt 的 screen.geometry() 使用统一的逻辑坐标，可正确表示位于主屏左侧/
        # 上方（负坐标）的显示器。把所有屏幕拼成一个虚拟桌面供跨屏框选。
        screens = QGuiApplication.screens()
        virtual_rect = QRect()
        for screen in screens:
            virtual_rect = virtual_rect.united(screen.geometry())
        self.virtual_rect = virtual_rect
        self.setGeometry(virtual_rect)

        # 保留每块屏幕的原始物理像素。旧实现先合成为逻辑分辨率，
        # 在 150%/200% DPI 下会把截图预先缩小，导致裁剪和预览发糊。
        self.screen_captures = []
        self.capture_scale = 1.0
        for screen in screens:
            screen_pix = screen.grabWindow(0)
            geometry = screen.geometry()
            self.screen_captures.append((geometry, screen_pix))
            if geometry.width() > 0:
                self.capture_scale = max(
                    self.capture_scale,
                    screen_pix.width() / geometry.width()
                )

        physical_size = virtual_rect.size() * self.capture_scale
        self.full_pix = QPixmap(physical_size)
        self.full_pix.setDevicePixelRatio(self.capture_scale)
        self.full_pix.fill(Qt.GlobalColor.black)
        painter = QPainter(self.full_pix)
        for geometry, screen_pix in self.screen_captures:
            target = geometry.translated(-virtual_rect.topLeft())
            painter.drawPixmap(target, screen_pix, screen_pix.rect())
        painter.end()

        self.start = QPoint()
        self.end = QPoint()
        self.selecting = False
        self.finished = False

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.full_pix)

        if self.selecting:
            rect = QRect(self.start, self.end).normalized()
            p.setPen(QPen(QColor(0, 180, 255), 3))
            p.drawRect(rect)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Qt 6: e.position(); Qt 5: e.pos()
            try:
                p = e.position().toPoint()
            except Exception:
                p = e.pos()
            self.start = p
            self.end = p
            self.selecting = True
            self.update()

    def mouseMoveEvent(self, e):
        if self.selecting:
            try:
                self.end = e.position().toPoint()
            except Exception:
                self.end = e.pos()
            self.update()


    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.selecting = False
            try:
                self.end = e.position().toPoint()
            except Exception:
                self.end = e.pos()

            rect = QRect(self.start, self.end).normalized()
            if rect.width() > 5 and rect.height() > 5:
                cropped = self._crop_physical_selection(rect)
                self.finished = True
                QTimer.singleShot(0, lambda pix=cropped: self.callback(pix))
            elif self.cancel_callback:
                self.finished = True
                QTimer.singleShot(0, self.cancel_callback)

            self.close()

    def _crop_physical_selection(self, local_rect):
        """按每块屏幕的实际像素比例裁剪，并支持跨不同 DPI 屏幕拼接。"""
        local_rect = local_rect.intersected(QRect(QPoint(), self.virtual_rect.size()))
        global_rect = local_rect.translated(self.virtual_rect.topLeft())

        scales = []
        for geometry, screen_pix in self.screen_captures:
            if not global_rect.intersected(geometry).isEmpty() and geometry.width() > 0:
                scales.append(screen_pix.width() / geometry.width())
        output_scale = max(scales, default=self.capture_scale)

        output = QImage(
            max(1, round(local_rect.width() * output_scale)),
            max(1, round(local_rect.height() * output_scale)),
            QImage.Format.Format_RGB32
        )
        output.fill(Qt.GlobalColor.black)
        painter = QPainter(output)

        for geometry, screen_pix in self.screen_captures:
            intersection = global_rect.intersected(geometry)
            if intersection.isEmpty():
                continue

            scale_x = screen_pix.width() / geometry.width()
            scale_y = screen_pix.height() / geometry.height()
            source = QRectF(
                (intersection.x() - geometry.x()) * scale_x,
                (intersection.y() - geometry.y()) * scale_y,
                intersection.width() * scale_x,
                intersection.height() * scale_y,
            )
            target = QRectF(
                (intersection.x() - global_rect.x()) * output_scale,
                (intersection.y() - global_rect.y()) * output_scale,
                intersection.width() * output_scale,
                intersection.height() * output_scale,
            )
            painter.drawPixmap(target, screen_pix, source)

        painter.end()
        output.setDevicePixelRatio(1.0)
        return QPixmap.fromImage(output)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            if self.cancel_callback:
                self.finished = True
                self.cancel_callback()  # 通知主窗口恢复
            self.close()

    def closeEvent(self, event):
        # 兼容 Alt+F4 等非鼠标关闭方式，确保主窗口不会一直隐藏。
        if not self.finished and self.cancel_callback:
            self.finished = True
            QTimer.singleShot(0, self.cancel_callback)
        super().closeEvent(event)


class DecodeWorkerSignals(QObject):
    progress = Signal(int, str)
    finished = Signal(int, object, str, str)
    preload_component_finished = Signal(str)
    preload_finished = Signal(str)

# ================================
#           主程序
# ================================
class QRApp(QWidget):
    hotkey_triggered = Signal()

    def __init__(self):
        super().__init__()

        self.chk_all = None
        self.hotkey_handle = None
        self.setWindowTitle("二维码工具 v1.2  By Null993")
        self.resize(700, 520)
        self.config = self.load_config()

        self.detector = None
        self.qr_reader = None
        self.cap = None
        self._capture_pending = False
        self._decode_busy = False
        self._decode_request_id = 0
        self._decode_futures = {}
        self._preload_started = False
        self._preload_running = False
        self._preload_ready = False
        self._preload_error = ""
        self._preload_pending = 0
        self._preload_errors = []
        self._preload_futures = []
        self.decode_signals = DecodeWorkerSignals()
        self.decode_signals.progress.connect(self.on_decode_progress)
        self.decode_signals.finished.connect(self.on_decode_finished)
        self.decode_signals.preload_component_finished.connect(
            self.on_preload_component_finished
        )
        # QReader/PyTorch 的原生线程上下文必须与执行线程同生命周期。
        # 常驻单线程执行器避免 QRunnable 销毁后再次推理导致 Windows 堆损坏。
        self.decode_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="qrcap-decode"
        )
        # QReader/PyTorch 始终在独立常驻线程中创建和推理。
        # 模型后台预热不会阻塞 OpenCV/ZXing/ZBar 的快速识别。
        self.model_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="qrcap-model"
        )
        self.history = self.load_history()

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self.page_generate(), "生成二维码")
        self.tabs.addTab(self.page_decode(), "解析二维码")
        self.tabs.addTab(self.page_history(), "历史记录")
        self.tabs.addTab(self.page_hotkey(), "热键设置")

        self.hotkey_triggered.connect(self.start_capture)

        self.start_hotkey_listener()
        self.init_tray()
        # 窗口先显示，再在常驻识别线程中加载解码器和模型。
        # 既保留快速首屏，也消除首次扫码时的模块导入和模型预热开销。
        QTimer.singleShot(800, self.start_background_preload)

    def start_background_preload(self):
        if self._preload_started:
            return
        self._preload_started = True
        self._preload_running = True
        self._preload_pending = 2
        self._preload_errors = []
        self._preload_futures = [
            self.decode_executor.submit(self._preload_fast_engine),
            self.model_executor.submit(self._preload_model_engine),
        ]
        for future in self._preload_futures:
            future.add_done_callback(self._notify_preload_component_finished)

    def _preload_fast_engine(self):
        """缓存快速解码模块和 OpenCV 检测器。"""
        import cv2
        import zxingcpp  # noqa: F401
        from pyzbar.pyzbar import ZBarSymbol, decode  # noqa: F401

        if self.detector is None:
            self.detector = cv2.QRCodeDetector()

    def _preload_model_engine(self):
        """在专用模型线程中缓存 QReader、PyTorch 和首次推理工作区。"""
        import numpy as np

        reader = self.get_qr_reader()
        dummy = np.full((256, 256, 3), 255, dtype=np.uint8)
        reader.detect_and_decode(image=dummy, is_bgr=True)

    def _notify_preload_component_finished(self, future):
        error = ""
        try:
            future.result()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        self.decode_signals.preload_component_finished.emit(error)

    @Slot(str)
    def on_preload_component_finished(self, error):
        if error:
            self._preload_errors.append(error)
        self._preload_pending -= 1
        if self._preload_pending > 0:
            return

        self._preload_running = False
        self._preload_error = "; ".join(self._preload_errors)
        self._preload_ready = not self._preload_error
        self.decode_signals.preload_finished.emit(self._preload_error)

    def get_qr_reader(self):
        """按需初始化增强模型；普通启动和普通二维码识别不再加载模型。"""
        if self.qr_reader is not None:
            return self.qr_reader

        model_full = resource_path(MODEL_FILE)
        if not os.path.exists(model_full):
            raise FileNotFoundError(f"未找到增强识别模型：{model_full}")

        install_qreader_model_patch()
        from qreader import QReader

        self.qr_reader = QReader(
            model_size="s",
            weights_folder=os.path.dirname(model_full)
        )
        return self.qr_reader

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return {"hotkey": ""}
        try:
            config = json.load(open(CONFIG_FILE, "r", encoding="utf8"))
            config.pop("detect_all_plus", None)
            return config
        except:
            return {"hotkey": ""}

    def save_config(self):
        self.config.pop("detect_all_plus", None)
        json.dump(self.config, open(CONFIG_FILE, "w", encoding="utf8"),
                  ensure_ascii=False, indent=2)

    def start_hotkey_listener(self):
        import keyboard

        # 注销旧热键
        if hasattr(self, "hotkey_handle") and self.hotkey_handle:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
                print("Old hotkey removed")
            except:
                pass
            self.hotkey_handle = None

        hk = self.hotkey or self.config.get("hotkey", "")
        if not hk:
            return

        try:

            # 改为在回调中 emit 一个 Qt 信号，信号会在 GUI 线程触发 start_capture
            self.hotkey_handle = keyboard.add_hotkey(hk, lambda: self.hotkey_triggered.emit())
            print("Hotkey registered:", hk)
        except Exception as e:
            print("Hotkey registration failed:", e)

    def save_hotkey(self):
        hk = self.hotkey_input.text().strip()
        if hk == "":
            QMessageBox.warning(self, "错误", "快捷键不能为空")
            return
        self.config["hotkey"] = hk
        # json.dump({"hotkey": hk}, open(resource_path(CONFIG_FILE), "w", encoding="utf8"))
        self.save_config()
        self.hotkey = hk
        self.start_hotkey_listener()
        QMessageBox.information(self, "成功", f"已保存快捷键：{hk}")

    def update_decode_preview(self):
        """按预览控件的物理像素缩放，避免高 DPI 下二次放大造成模糊。"""
        if not hasattr(self, "_orig_decode_pixmap"):
            return

        pix = self._orig_decode_pixmap
        label = self.decode_preview

        # 如果 label 还没 layout 好（size 为 0），稍后重试
        if label.width() == 0 or label.height() == 0:
            QTimer.singleShot(100, self.update_decode_preview)
            return

        image = pix.toImage()
        image.setDevicePixelRatio(1.0)
        source_pix = QPixmap.fromImage(image)

        screen = label.screen() or self.screen()
        display_dpr = screen.devicePixelRatio() if screen else 1.0
        max_width = max(1, round(label.width() * display_dpr))
        max_height = max(1, round(label.height() * display_dpr))
        # 预览只允许缩小，不把截图放大到超过原始物理像素。
        # 小范围框选会以像素等比例大小居中显示，从根源上避免插值模糊。
        scale = min(
            max_width / source_pix.width(),
            max_height / source_pix.height(),
            1.0
        )
        target_width = max(1, round(source_pix.width() * scale))
        target_height = max(1, round(source_pix.height() * scale))
        scaled = source_pix.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        scaled.setDevicePixelRatio(display_dpr)
        label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_decode_preview()

    # ==========================
    #        历史记录
    # ==========================
    def load_history(self):
        """加载历史记录，兼容新旧格式"""
        if os.path.exists(resource_path(HISTORY_FILE)):
            try:
                history = json.load(open(resource_path(HISTORY_FILE), "r", encoding="utf8"))
                # 兼容旧格式：将旧格式转换为新格式
                converted_history = []
                for item in history:
                    if isinstance(item, dict) and "source" in item and "content" in item:
                        # 已经是新格式
                        converted_history.append(item)
                    else:
                        # 旧格式，尝试转换
                        if isinstance(item, dict) and "text" in item:
                            text = item["text"]
                            time = item.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            # 解析旧格式文本
                            if "截屏识别：" in text:
                                source = "截屏识别"
                                content = text.replace("截屏识别：", "")
                            elif "解析图片：" in text:
                                source = "解析图片"
                                content = text.replace("解析图片：", "")
                            elif "生成：" in text:
                                source = "生成"
                                content = text.replace("生成：", "")
                            else:
                                source = "未知"
                                content = text
                            converted_history.append({
                                "source": source,
                                "content": content,
                                "time": time
                            })
                return converted_history
            except:
                return []
        return []

    def save_history(self):
        json.dump(self.history, open(resource_path(HISTORY_FILE), "w", encoding="utf8"),
                  ensure_ascii=False, indent=2)

    def add_history(self, source, content):
        """添加历史记录，分开存储来源和内容"""
        self.history.append({
            "source": source,
            "content": content,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        self.save_history()
        self.refresh_history()

    def page_history(self):
        w = QWidget()
        v = QVBoxLayout(w)

        # 顶部按钮
        h = QHBoxLayout()
        self.chk_all = QCheckBox("全选")
        # 允许显示部分选中状态（程序可以显示 PartiallyChecked）
        self.chk_all.setTristate(True)
        # 使用 clicked(bool) —— 只在用户点击时触发（区分程序性修改）
        self.chk_all.clicked.connect(self.toggle_all)
        h.addWidget(self.chk_all)

        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self.delete_selected)
        h.addWidget(btn_del)

        v.addLayout(h)

        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # 使用 itemChanged 信号处理勾选，避免与点击事件冲突
        self.list.itemChanged.connect(self.on_item_changed)

        # 双击打开链接（只在双击时打开，避免勾选时触发）
        self.list.itemDoubleClicked.connect(self.on_history_double_click)

        # 右键菜单
        self.list.customContextMenuRequested.connect(self.on_history_right_click)

        v.addWidget(self.list)

        self.refresh_history()
        return w

    def page_hotkey(self):
        w = QWidget()
        v = QVBoxLayout(w)


        # 第一行：提示文字
        lab = QLabel("按下你希望用于『截屏识别』的快捷键（如 F1、Ctrl+Shift+S）")
        # lab.setSizePolicy(
        #     QSizePolicy.Policy.Minimum,
        #     QSizePolicy.Policy.Minimum
        # )
        v.addWidget(lab, stretch=0)

        # 第二行：按钮 + 输入框
        h = QHBoxLayout()
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setPlaceholderText("按键将自动记录")
        h.addWidget(self.hotkey_input)

        save_btn = QPushButton("保存快捷键")
        save_btn.clicked.connect(self.save_hotkey)
        h.addWidget(save_btn)

        v.addLayout(h, stretch=0)
        v.addStretch(1)  # stretch=1，吸收所有剩余空间

        # 读取已保存热键
        self.hotkey = self.config.get("hotkey", "")
        if self.hotkey:
            self.hotkey_input.setText(self.hotkey)

        # 监听键盘记录快捷键（只记录组合，不实际触发）
        self.hotkey_input.keyPressEvent = self.record_hotkey

        return w

    def refresh_history(self):
        if not hasattr(self, "list"):
            return
        self.list.clear()

        # 暂停 itemChanged 信号，避免刷新时触发
        self.list.blockSignals(True)

        for h in reversed(self.history):
            # 显示格式：时间 - [来源] 内容
            display_text = f"{h['time']} - [{h['source']}] {h['content']}"
            item = QListWidgetItem(display_text)

            # 设置可勾选
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)

            # 保存原始数据到自定义数据角色
            item.setData(Qt.ItemDataRole.UserRole, h)

            self.list.addItem(item)

        # 恢复信号
        self.list.blockSignals(False)

        # 更新全选复选框状态
        self.update_select_all_checkbox()

    def on_item_changed(self, item):
        """处理项目状态变化（勾选/取消勾选）"""
        # 更新全选复选框状态
        self.update_select_all_checkbox()

    def record_hotkey(self, e):
        keys = []

        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            keys.append("ctrl")
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            keys.append("shift")
        if e.modifiers() & Qt.KeyboardModifier.AltModifier:
            keys.append("alt")

        key = e.key()

        # 处理 F1-F12
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
            keys.append(f"f{key - Qt.Key.Key_F1 + 1}")
        else:
            key_name = e.text().lower()
            if key_name:
                keys.append(key_name)

        self.hotkey_input.setText("+".join(keys))

    def update_select_all_checkbox(self):
        """程序性更新 chk_all 的显示（不会被当成用户点击）"""
        count = self.list.count()
        if count == 0:
            self.chk_all.blockSignals(True)
            self.chk_all.setCheckState(Qt.CheckState.Unchecked)
            self.chk_all.blockSignals(False)
            self.chk_all.setEnabled(False)
            return

        self.chk_all.setEnabled(True)

        checked_count = 0
        for i in range(count):
            if self.list.item(i).checkState() == Qt.CheckState.Checked:
                checked_count += 1

        # 程序性设置 chk_all 的显示时阻断信号，避免触发 toggle_all
        self.chk_all.blockSignals(True)

        if checked_count == 0:
            self.chk_all.setCheckState(Qt.CheckState.Unchecked)
        elif checked_count == count:
            self.chk_all.setCheckState(Qt.CheckState.Checked)
        else:
            self.chk_all.setCheckState(Qt.CheckState.PartiallyChecked)

        self.chk_all.blockSignals(False)

    # noinspection PyUnreachableCode
    def toggle_all(self, checked):
        """只在用户点击全选复选框时调用（checked 为用户点击后的状态）"""
        # 1) 阻断 list 的 itemChanged 信号，避免每次 item.setCheckState 触发 update_select_all_checkbox
        self.list.blockSignals(True)
        try:
            for i in range(self.list.count()):
                item = self.list.item(i)
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.list.blockSignals(False)

        # 2) 明确把 chk_all 设置为用户想要的状态，临时阻断其信号以避免重复触发

        self.chk_all.blockSignals(True)
        self.chk_all.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.chk_all.blockSignals(False)


    def delete_selected(self):
        """删除选中的记录"""
        items_to_delete = []

        # 收集要删除的项目
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                # 获取对应的历史记录索引（因为显示是倒序的）
                history_index = len(self.history) - 1 - i
                items_to_delete.append(history_index)

        if not items_to_delete:
            QMessageBox.information(self, "提示", "没有选中任何记录")
            return

        # 从后往前删除，避免索引变化
        items_to_delete.sort(reverse=True)
        for idx in items_to_delete:
            if 0 <= idx < len(self.history):
                del self.history[idx]

        self.save_history()
        self.refresh_history()

    # 双击历史项：如果包含 URL -> 打开
    def on_history_double_click(self, item: QListWidgetItem):
        """双击项目时打开链接"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and "content" in data:
            content = data["content"]
            url = extract_first_url(content)
            if url:
                webbrowser.open(url)
            else:
                # 如果不是URL，复制到剪贴板
                QApplication.clipboard().setText(content)
                QMessageBox.information(self, "已复制", "内容已复制到剪贴板")

    # 右键点击历史项：复制内容（不含前缀）
    def on_history_right_click(self, pos):
        """右键菜单：复制内容"""
        item = self.list.itemAt(pos)
        if not item:
            return

        # 从自定义数据中获取原始内容
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and "content" in data:
            content = data["content"]
            QApplication.clipboard().setText(content)

            # 显示简短提示
            if len(content) > 30:
                display_content = content[:27] + "..."
            else:
                display_content = content

            # 使用系统托盘显示消息（避免打断用户操作）
            if hasattr(self, 'tray'):
                self.tray.showMessage(
                    "已复制",
                    f"内容已复制到剪贴板：\n{display_content}",
                    QSystemTrayIcon.MessageIcon.Information,
                    1500
                )

    # ==========================
    #        生成二维码
    # ==========================
    def page_generate(self):
        w = QWidget()
        v = QVBoxLayout(w)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("输入内容")
        v.addWidget(self.input_text)

        btn = QPushButton("生成二维码")
        btn.clicked.connect(self.generate_qr)
        v.addWidget(btn)

        self.qr_label = QLabel("二维码预览")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.qr_label)

        save = QPushButton("保存二维码")
        save.clicked.connect(self.save_qr)
        v.addWidget(save)

        return w

    def generate_qr(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            return

        import qrcode

        qr = qrcode.main.QRCode(box_size=8, border=2)
        qr.add_data(text)
        qr.make()
        img = qr.make_image()

        buf = BytesIO()
        img.save(buf)
        self.qr_data = buf.getvalue()

        pix = QPixmap()
        pix.loadFromData(self.qr_data)
        self.qr_label.setPixmap(pix.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio))

        # 修改：使用新格式添加历史记录
        self.add_history("生成", text)

    def save_qr(self):
        if not hasattr(self, "qr_data"):
            return
        fn, _ = QFileDialog.getSaveFileName(self, "保存二维码", filter="PNG (*.png)")
        if fn:
            open(fn, "wb").write(self.qr_data)

    # ==========================
    #        解析二维码
    # ==========================
    def page_decode(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.decode_file_btn = QPushButton("选择图片解析")
        self.decode_file_btn.clicked.connect(self.open_decode)
        v.addWidget(self.decode_file_btn)

        self.capture_btn = QPushButton("截屏识别")
        self.capture_btn.clicked.connect(self.start_capture)
        v.addWidget(self.capture_btn)

        # 图片预览区域
        self.decode_preview = QLabel("图片预览")
        self.decode_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.decode_preview.setScaledContents(False)
        self.decode_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.decode_preview.setMinimumSize(200, 200)
        v.addWidget(self.decode_preview, stretch=1)  # 占据剩余空间

        # 文本结果显示区域
        self.decode_text = QTextEdit()
        self.decode_text.setReadOnly(True)
        self.decode_text.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred  # Preferred: 根据内容确定合适大小
        )
        self.decode_text.setMaximumHeight(300)  # 设置最大高度限制
        self.decode_text.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.decode_text.mousePressEvent = self.open_link_if_needed

        # 监听文本变化
        self.decode_text.textChanged.connect(self.update_decode_text_size)

        # 初始设置合适的高度
        self.decode_text.setFixedHeight(int(self.decode_text.document().size().height() + 20))

        v.addWidget(self.decode_text)

        return w

    def update_decode_text_size(self):
        """根据文本内容更新decode_text的大小"""
        # 获取文档的理想高度
        doc_height = self.decode_text.document().size().height()

        # 加上一些边距（大约20像素）
        needed_height = doc_height + 20

        # 限制最小和最大高度
        min_height = 30
        max_height = 300

        if needed_height < min_height:
            needed_height = min_height
        elif needed_height > max_height:
            needed_height = max_height

        # 设置固定高度
        self.decode_text.setFixedHeight(needed_height)

        # 强制更新布局，确保图片预览区域能重新计算可用空间
        self.decode_text.updateGeometry()
        if self.decode_preview.parent():
            self.decode_preview.parent().updateGeometry()

    # 点击可打开 URL
    def open_link_if_needed(self, e):
        try:
            pos = e.position().toPoint()
        except Exception:
            pos = e.pos()
        cursor = self.decode_text.cursorForPosition(pos)

        fmt = cursor.charFormat()
        href = fmt.anchorHref()

        if href:
            # 如果点中 HTML 链接（<a href="...">）
            webbrowser.open(href)
            return

        # 没点到链接，则复制文字
        cursor.select(cursor.SelectionType.WordUnderCursor)
        text = cursor.selectedText().strip()
        QApplication.clipboard().setText(text)

    def open_decode(self):
        if self._decode_busy:
            return

        fn, _ = QFileDialog.getOpenFileName(self, "选择图片", filter="Images (*.png *.jpg *.jpeg)")
        if not fn:
            return

        pix = QPixmap(fn)
        self._orig_decode_pixmap = pix
        self.update_decode_preview()
        self.start_decode(pix.toImage(), "解析图片")

    # ==========================
    #         截屏识别
    # ==========================
    def start_capture(self):
        if self._decode_busy or self._capture_pending or self.cap is not None:
            return

        # ⭐ 切换到“解析二维码”页签
        self.tabs.setCurrentIndex(1)
        self._capture_pending = True
        self.hide()
        QApplication.processEvents()

        # 给 Windows 合成器留出隐藏主窗口的时间，防止截图中残留本程序窗口。
        QTimer.singleShot(150, self._show_capture_overlay)

    def _show_capture_overlay(self):
        try:
            self.cap = CaptureScreen(self.on_capture, self.on_capture_cancel)
            self.cap.show()
            self.cap.raise_()
            self.cap.activateWindow()
        except Exception:
            self._capture_pending = False
            self.show_main_window()
            raise
        self._capture_pending = False

    def on_capture_cancel(self):
        self._capture_pending = False
        self.cap = None
        self.show_main_window()

    # ---------- on_capture：把 singleShot(0) 改成短延迟，保证窗口恢复并布局完成 ----------
    def on_capture(self, pixmap):
        self.cap = None
        self._orig_decode_pixmap = pixmap
        decode_image = pixmap.toImage()
        # 主窗口仍隐藏时先完成预览缩放和状态布局，再一次性恢复，避免白屏。
        self.update_decode_preview()
        self.decode_text.setHtml('<div style="color:#888888;">正在识别二维码…</div>')
        self.show_main_window()
        # 让恢复后的窗口先获得一次绘制机会，再把任务放入后台执行器。
        QTimer.singleShot(
            30,
            lambda image=decode_image: self.start_decode(image, "截屏识别")
        )


    def start_decode(self, image, source):
        """启动固定的自动识别流水线，所有耗时操作均在后台线程执行。"""
        if self._decode_busy:
            return

        self._decode_busy = True
        self._decode_request_id += 1
        request_id = self._decode_request_id
        status = (
            "正在完成识别引擎预加载…"
            if self._preload_running
            else "正在快速识别…"
        )
        self.decode_text.setHtml(
            f'<div style="color:#888888;">{status}</div>'
        )
        self.decode_file_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)
        if hasattr(self, "cap_act"):
            self.cap_act.setEnabled(False)

        future = self.decode_executor.submit(
            self._run_decode_job,
            request_id,
            image.copy(),
            source,
        )
        self._decode_futures[request_id] = future

    def _run_decode_job(self, request_id, image, source):
        try:
            image = self._prepare_decode_image(image)
            result = self.decode_image_auto(
                image,
                lambda message: self.decode_signals.progress.emit(request_id, message)
            )
            self.decode_signals.finished.emit(request_id, result, source, "")
        except Exception as error:
            self.decode_signals.finished.emit(
                request_id, [], source, f"{type(error).__name__}: {error}"
            )

    @staticmethod
    def _prepare_decode_image(image):
        """QImage 到 BGR NumPy 的转换只在后台识别线程中执行。"""
        if not isinstance(image, QImage):
            return image

        import numpy as np

        qimage = image.convertToFormat(QImage.Format.Format_RGBA8888)
        width = qimage.width()
        height = qimage.height()
        bytes_per_line = qimage.bytesPerLine()
        buffer = np.frombuffer(
            qimage.bits(),
            dtype=np.uint8,
            count=height * bytes_per_line
        ).reshape((height, bytes_per_line))
        rgba = buffer[:, :width * 4].reshape((height, width, 4))
        return rgba[:, :, :3][:, :, ::-1].copy()

    @Slot(int, str)
    def on_decode_progress(self, request_id, message):
        if request_id == self._decode_request_id:
            self.decode_text.setHtml(
                f'<div style="color:#888888;">{html.escape(message)}</div>'
            )

    @Slot(int, object, str, str)
    def on_decode_finished(self, request_id, texts, source, error):
        self._decode_futures.pop(request_id, None)
        if request_id != self._decode_request_id:
            return

        self._decode_busy = False
        self.decode_file_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        if hasattr(self, "cap_act"):
            self.cap_act.setEnabled(True)

        if error:
            self.decode_text.setHtml(
                f'<div style="color:#cc4444;">识别失败：{html.escape(error)}</div>'
            )
            return

        texts = self._unique_texts(texts)
        if not texts:
            self.decode_text.setHtml(
                '<div style="color:#bbbbbb;">未识别出二维码或受支持的条码</div>'
            )
            return

        cards = []
        for text in texts:
            safe_text = html.escape(text)
            url = extract_first_url(text)
            content = safe_text
            if url:
                content = (
                    f'<a href="{html.escape(url, quote=True)}" '
                    f'style="color:inherit;text-decoration:none;">{safe_text}</a>'
                )
            cards.append(
                '<div style="margin-bottom:12px;padding:10px 0;'
                'background:transparent;color:inherit;font-size:14px;'
                'word-wrap:break-word;border-bottom:1px solid #eeeeee;">'
                f'{content}</div>'
            )
        self.decode_text.setHtml("".join(cards))

        for text in texts:
            self.add_history(source, text)

    def decode_image_auto(self, image, progress):
        """快速互补解码 -> 失败后预处理 -> 最后模型识别。"""
        progress("正在使用互补解码器识别…")
        texts = self._decode_with_fast_decoders(image, include_all=True)
        if texts:
            return texts

        progress("正在增强低对比度和小尺寸二维码…")
        for _, variant in self._iter_fallback_images(image):
            texts = self._decode_with_fast_decoders(variant, include_all=False)
            if texts:
                return texts

        progress("正在进行深度模型识别，首次使用可能需要数秒…")
        model_future = self.model_executor.submit(
            self._decode_with_model,
            image.copy()
        )
        return model_future.result()

    def _decode_with_model(self, image):
        """此方法只在常驻模型线程中执行，保证 PyTorch 线程亲和性。"""
        reader = self.get_qr_reader()
        result = reader.detect_and_decode(image=image, is_bgr=True)
        return self._unique_texts(result or ())

    def _decode_with_fast_decoders(self, image, include_all):
        decoders = [
            self._decode_with_opencv,
            self._decode_with_zxing,
            self._decode_with_pyzbar,
        ]
        texts = []
        for decoder in decoders:
            try:
                texts.extend(decoder(image))
            except Exception:
                # 单个解码器失败不应中断其他互补解码器。
                continue
            if texts and not include_all:
                break
        return self._unique_texts(texts)

    def _decode_with_opencv(self, image):
        import cv2

        if self.detector is None:
            self.detector = cv2.QRCodeDetector()

        texts = []
        try:
            ok, decoded, _, _ = self.detector.detectAndDecodeMulti(image)
            if ok:
                texts.extend(decoded)
        except cv2.error:
            pass

        if not self._unique_texts(texts):
            try:
                text, _, _ = self.detector.detectAndDecode(image)
                texts.append(text)
            except cv2.error:
                pass

        if not self._unique_texts(texts):
            try:
                text, _, _ = self.detector.detectAndDecodeCurved(image)
                texts.append(text)
            except (cv2.error, AttributeError):
                pass
        return self._unique_texts(texts)

    def _decode_with_zxing(self, image):
        import zxingcpp

        texts = []
        for result in zxingcpp.read_barcodes(image):
            raw = bytes(result.bytes)
            texts.append(self._decode_bytes(raw) if raw else result.text)
        return self._unique_texts(texts)

    def _decode_with_pyzbar(self, image):
        from pyzbar.pyzbar import ZBarSymbol, decode

        symbols = [
            ZBarSymbol.QRCODE,
            ZBarSymbol.CODE128,
            ZBarSymbol.EAN13,
            ZBarSymbol.EAN8,
        ]
        return self._unique_texts(
            self._decode_bytes(result.data)
            for result in decode(image, symbols=symbols)
        )

    @staticmethod
    def _decode_bytes(data):
        for encoding in ("utf-8", "gb18030", "shift-jis"):
            try:
                return bytes(data).decode(encoding)
            except UnicodeDecodeError:
                continue
        return bytes(data).decode("utf-8", errors="replace")

    @staticmethod
    def _unique_texts(texts):
        result = []
        seen = set()
        for text in texts or ():
            if text is None:
                continue
            text = str(text).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    def _iter_fallback_images(self, image):
        """仅在原图解码失败后生成少量、互补的增强候选图。"""
        import cv2
        import numpy as np

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

        low, high = np.percentile(gray, (2, 98))
        if high > low:
            contrast = np.clip(
                (gray.astype(np.float32) - low) * (255.0 / (high - low)),
                0,
                255
            ).astype(np.uint8)
            yield "低对比度增强", contrast

        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
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
            gray, border, border, border, border,
            cv2.BORDER_CONSTANT, value=255
        )
        yield "静区补白", padded

        # 小图最后使用轻量超分辨率替代方案：Lanczos 放大后反锐化。
        # 只对较小输入执行，避免把整屏截图无意义地放大并拖慢识别。
        max_axis = max(gray.shape[:2])
        if max_axis < 1200:
            scale = 3 if max_axis < 500 else 2
            upscaled = cv2.resize(
                gray, None, fx=scale, fy=scale,
                interpolation=cv2.INTER_LANCZOS4
            )
            blurred = cv2.GaussianBlur(upscaled, (0, 0), 1.0)
            super_resolved = cv2.addWeighted(upscaled, 1.6, blurred, -0.6, 0)
            yield "轻量超分辨率", super_resolved

    def show_decode_text(self, text, src):

        self.decode_text.setText(text)

    # ==========================
    #        系统托盘（稳健版）
    # ==========================
    def init_tray(self):
        # 1) 尝试加载实际文件 ico（如果有）
        here = os.path.dirname(__file__)
        ico_path = os.path.join(here, resource_path("icon.ico"))
        if os.path.exists(ico_path):
            tray_icon = QIcon(ico_path)
        else:
            # 兜底：使用 style() 但包装进 QIcon
            tray_icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            if isinstance(tray_icon, QIcon):
                pass
            else:
                tray_icon = QIcon(tray_icon)

        # 2) 创建 tray 并保存为实例属性（防止被回收）
        self.tray = QSystemTrayIcon(tray_icon, parent=self)
        self.tray.setToolTip("二维码工具（右键）")

        # 3) 创建菜单并保存为实例属性（防止 GC）
        self.tray_menu = QMenu(parent=self)

        self.show_act = QAction("显示主窗口", parent=self)
        # self.show_act.triggered.connect(self.show)
        self.show_act.triggered.connect(self.show_main_window)

        self.tray_menu.addAction(self.show_act)

        self.cap_act = QAction("截屏识别", parent=self)
        self.cap_act.triggered.connect(self.start_capture)
        self.tray_menu.addAction(self.cap_act)

        self.quit_act = QAction("退出", parent=self)
        # self.quit_act.triggered.connect(QApplication.quit)

        self.quit_act.triggered.connect(self.force_quit)
        self.tray_menu.addAction(self.quit_act)


        # 4) 设置托盘上下文菜单
        self.tray.setContextMenu(self.tray_menu)

        # 5) 设置双击托盘打开界面
        self.tray.activated.connect(self.on_tray_activated)

        # 6) 显示托盘图标
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_window()


    def show_main_window(self):
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def force_quit(self):
        self._force_quit = True
        self.tray.hide()
        self.decode_executor.shutdown(wait=False, cancel_futures=True)
        self.model_executor.shutdown(wait=False, cancel_futures=True)
        QApplication.quit()

    def closeEvent(self, e):
        if getattr(self, "_force_quit", False):
            e.accept()
            return

        e.ignore()
        self.hide()
        self.tray.showMessage(
            "二维码工具",
            "程序已最小化到系统托盘",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

# ================================
#             启动
# ================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    w = QRApp()
    w.show()
    sys.exit(app.exec())
