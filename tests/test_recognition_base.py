from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import qrcode
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from qrcap.enhancement import EnhancementManager
from qrcap.recognition import RecognitionService


def make_qr_image(text: str) -> QImage:
    qr = qrcode.QRCode(box_size=6, border=4)
    qr.add_data(text)
    qr.make()
    matrix = qr.get_matrix()
    size = len(matrix) * 6
    image = QImage(size, size, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.GlobalColor.black)
    for row_index, row in enumerate(matrix):
        for column_index, enabled in enumerate(row):
            if enabled:
                painter.drawRect(
                    column_index * 6,
                    row_index * 6,
                    6,
                    6,
                )
    painter.end()
    return image


class BaseRecognitionTests(unittest.TestCase):
    def test_invisible_bom_and_whitespace_are_deduplicated(self):
        values = RecognitionService.unique_texts(
            (
                "\ufeff88 二维码专用版",
                "88 二维码专用版",
                "88  二维码专用版 ",
            )
        )

        self.assertEqual(["88 二维码专用版"], values)

    def test_qr_style_image_returns_one_normalized_result(self):
        project_root = Path(__file__).resolve().parents[1]
        candidates = list(project_root.glob("*/qr_style.png"))
        if not candidates:
            self.skipTest("qr_style.png is not available")

        image = QImage()
        self.assertTrue(image.loadFromData(candidates[0].read_bytes()))
        with tempfile.TemporaryDirectory() as temp:
            manager = EnhancementManager(Path(temp))
            service = RecognitionService(manager)
            try:
                result = service._decode_with_fast_decoders(
                    service._prepare_decode_image(image),
                    include_all=True,
                )
            finally:
                service.shutdown()
                manager.deactivate_runtime()

        self.assertEqual(1, len(result))
        self.assertNotIn("\ufeff", result[0])

    def test_base_decoders_work_without_enhancement_package(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = EnhancementManager(Path(temp))
            service = RecognitionService(manager)
            image = make_qr_image("qrcap-base-mode")

            try:
                result = service.decode_image_auto(image, lambda _: None)
            finally:
                service.shutdown()
                manager.deactivate_runtime()

            self.assertIn("qrcap-base-mode", result)

    def test_blank_image_returns_normally_without_enhancement(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = EnhancementManager(Path(temp))
            service = RecognitionService(manager)
            blank = QImage(320, 240, QImage.Format.Format_RGB32)
            blank.fill(Qt.GlobalColor.white)

            try:
                result = service.decode_image_auto(blank, lambda _: None)
            finally:
                service.shutdown()
                manager.deactivate_runtime()

            self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
