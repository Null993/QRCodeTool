from __future__ import annotations

import unittest

from qrcap.app import (
    restore_window_display_mode,
    window_display_mode,
)


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


if __name__ == "__main__":
    unittest.main()
