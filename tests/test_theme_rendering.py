from __future__ import annotations

import unittest

from PySide6.QtGui import QTextCursor, QTextDocument

from qrcap.app import (
    render_decode_message_html,
    render_decode_results_html,
)
from qrcap.theme import theme_colors


class ThemeRenderingTests(unittest.TestCase):
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
