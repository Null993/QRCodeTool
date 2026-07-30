"""Small release-build verification that does not require a visible window."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

import qrcode
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from .enhancement import EnhancementManager
from .recognition import RecognitionService
from .resources import enhancement_root, program_root


def run_package_self_test() -> int:
    if getattr(sys, "frozen", False):
        executable_root = Path(sys.executable).resolve().parent
        if program_root() != executable_root:
            return 3
        if enhancement_root() != executable_root:
            return 3

    payload = "qrcap-v1.4-package-self-test"
    qr = qrcode.QRCode(box_size=6, border=4)
    qr.add_data(payload)
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

    with tempfile.TemporaryDirectory(prefix="qrcap-self-test-") as temp:
        jpeg_path = Path(temp) / "image-codec-test.jpg"
        if not image.save(str(jpeg_path), "JPG"):
            return 2
        if QImage(str(jpeg_path)).isNull():
            return 2

        manager = EnhancementManager(Path(temp))
        service = RecognitionService(manager)
        try:
            service._preload_fast_engine()
            result = service.decode_image_auto(image, lambda _: None)
        finally:
            service.shutdown()
            manager.deactivate_runtime()

    return 0 if payload in result else 1
