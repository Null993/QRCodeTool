from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtGui import QTextCursor, QTextDocument

from qrcap.app import (
    render_decode_message_html,
    render_decode_results_html,
    resolve_initial_theme,
)
from qrcap.theme import detect_system_theme, theme_colors


class ThemeRenderingTests(unittest.TestCase):
    def test_initial_theme_uses_windows_until_user_selects_one(self):
        with patch(
            "qrcap.app.detect_system_theme",
            return_value="dark",
        ):
            self.assertEqual("dark", resolve_initial_theme({}))
            self.assertEqual(
                "dark",
                resolve_initial_theme({"hotkey": "f10"}),
            )
            self.assertEqual(
                "light",
                resolve_initial_theme({"theme": "light"}),
            )

    def test_windows_application_theme_mapping(self):
        with (
            patch("qrcap.theme.sys.platform", "win32"),
            patch(
                "qrcap.theme._windows_apps_use_light_theme",
                return_value=0,
            ),
        ):
            self.assertEqual("dark", detect_system_theme())

        with (
            patch("qrcap.theme.sys.platform", "win32"),
            patch(
                "qrcap.theme._windows_apps_use_light_theme",
                return_value=1,
            ),
        ):
            self.assertEqual("light", detect_system_theme())

    def test_dark_decode_results_use_explicit_readable_colors(self):
        colors = theme_colors("dark")
        rendered = render_decode_results_html(
            ("普通识别结果", "https://example.com"),
            "dark",
        )

        self.assertIn(f'color:{colors["text"]}', rendered)
        self.assertIn(f'color:{colors["link"]}', rendered)
        self.assertIn(
            f'border-bottom:1px solid {colors["border"]}',
            rendered,
        )
        self.assertNotIn("color:inherit", rendered)
        self.assertNotIn("color:#172033", rendered)

        document = QTextDocument()
        document.setHtml(rendered)
        plain_text = document.toPlainText()

        text_cursor = QTextCursor(document)
        text_cursor.setPosition(plain_text.index("普通") + 1)
        self.assertEqual(
            colors["text"].lower(),
            text_cursor.charFormat().foreground().color().name(),
        )

        link_cursor = QTextCursor(document)
        link_cursor.setPosition(plain_text.index("https") + 1)
        self.assertEqual(
            colors["link"].lower(),
            link_cursor.charFormat().foreground().color().name(),
        )

    def test_status_and_error_messages_follow_the_active_theme(self):
        dark_colors = theme_colors("dark")
        light_colors = theme_colors("light")

        self.assertIn(
            f'color:{dark_colors["muted"]}',
            render_decode_message_html("正在识别", "dark"),
        )
        self.assertIn(
            f'color:{dark_colors["error"]}',
            render_decode_message_html("识别失败", "dark", "error"),
        )
        self.assertIn(
            f'color:{light_colors["muted"]}',
            render_decode_message_html("正在识别", "light"),
        )


if __name__ == "__main__":
    unittest.main()
