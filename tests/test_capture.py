from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from qrcap.capture import CaptureScreen


class CaptureCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mixed_dpi_screens_are_composed_without_black_regions(self):
        primary = QPixmap(150, 150)
        primary.fill(QColor("#d92d20"))
        secondary = QPixmap(100, 100)
        secondary.fill(QColor("#1570ef"))

        result = CaptureScreen._compose_selection(
            [
                (QRect(0, 0, 100, 100), primary),
                (QRect(100, 0, 100, 100), secondary),
            ],
            QRect(0, 0, 200, 100),
        ).toImage()

        self.assertEqual(300, result.width())
        self.assertEqual(150, result.height())
        self.assertEqual(QColor("#d92d20"), result.pixelColor(50, 50))
        self.assertEqual(QColor("#1570ef"), result.pixelColor(225, 50))


if __name__ == "__main__":
    unittest.main()
