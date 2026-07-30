from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QSizePolicy

from qrcap.app import (
    restore_window_display_mode,
    window_display_mode,
)
from qrcap.ui_components import StablePixmapLabel


class FakeWindow:
    def __init__(self, *, fullscreen=False, maximized=False):
        self.fullscreen = fullscreen
        self.maximized = maximized
        self.calls = []

    def isFullScreen(self):
        return self.fullscreen

    def isMaximized(self):
        return self.maximized

    def showFullScreen(self):
        self.calls.append("fullscreen")

    def showMaximized(self):
        self.calls.append("maximized")

    def showNormal(self):
        self.calls.append("normal")


class WindowStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_capture_mode_prefers_fullscreen_then_maximized(self):
        self.assertEqual(
            "fullscreen",
            window_display_mode(
                FakeWindow(fullscreen=True, maximized=True)
            ),
        )
        self.assertEqual(
            "maximized",
            window_display_mode(FakeWindow(maximized=True)),
        )
        self.assertEqual("normal", window_display_mode(FakeWindow()))

    def test_restore_uses_the_captured_window_mode(self):
        for mode in ("fullscreen", "maximized", "normal"):
            with self.subTest(mode=mode):
                window = FakeWindow()
                restore_window_display_mode(window, mode)
                self.assertEqual([mode], window.calls)

    def test_large_preview_does_not_change_layout_size_hint(self):
        preview = StablePixmapLabel()
        expected_size = QSize(200, 150)

        large_pixmap = QPixmap(2820, 1298)
        preview.setPixmap(
            large_pixmap.scaled(
                1200,
                900,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        self.assertEqual(expected_size, preview.sizeHint())
        self.assertEqual(expected_size, preview.minimumSizeHint())
        self.assertEqual(
            QSizePolicy.Policy.Ignored,
            preview.sizePolicy().horizontalPolicy(),
        )
        self.assertEqual(
            QSizePolicy.Policy.Ignored,
            preview.sizePolicy().verticalPolicy(),
        )


if __name__ == "__main__":
    unittest.main()
