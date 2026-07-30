from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTextEdit

from qrcap.enhancement import EnhancementManager, REQUIRED_MODULES
from qrcap.enhancement_ui import EnhancementPage
from qrcap.recognition import RecognitionService


def manifest() -> dict:
    machine = platform.machine().lower()
    architecture = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine)
    return {
        "schema_version": 1,
        "package_id": "ui-test",
        "name": "界面测试增强包",
        "version": "1.0.0",
        "platform": "windows" if sys.platform == "win32" else sys.platform,
        "architecture": architecture,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


class EnhancementPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_status_icons_cover_none_partial_and_complete_states(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = EnhancementManager(Path(temp))
            recognition = RecognitionService(manager)
            page = EnhancementPage(manager, recognition)

            try:
                self.assertIn("基础识别模式", page.status_label.toPlainText())
                self.assertIn("❌", page.status_label.toPlainText())

                active = manager.active_dir
                (active / "models").mkdir(parents=True)
                (active / "manifest.json").write_text(
                    json.dumps(manifest(), ensure_ascii=False),
                    encoding="utf-8",
                )
                (active / "models" / "qrdet-s.pt").write_bytes(b"model")
                page.refresh_status()
                partial_text = page.status_label.toPlainText()
                self.assertIn("✅", partial_text)
                self.assertIn("❌", partial_text)
                self.assertIn("不完整", partial_text)

                runtime = active / "runtime" / "site-packages"
                for module_name, _ in REQUIRED_MODULES:
                    module_dir = runtime / module_name
                    module_dir.mkdir(parents=True)
                    (module_dir / "__init__.py").write_text(
                        "",
                        encoding="utf-8",
                    )
                manager.record_runtime_verification(True, "测试验证通过")
                page.refresh_status()
                complete_text = page.status_label.toPlainText()
                self.assertIn("增强包可用", complete_text)
                self.assertNotIn("❌", complete_text)
            finally:
                recognition.shutdown()
                manager.deactivate_runtime()
                page.deleteLater()

    def test_long_status_details_scroll_without_resizing_the_page(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = EnhancementManager(Path(temp))
            recognition = RecognitionService(manager)
            page = EnhancementPage(manager, recognition)
            page.resize(590, 560)

            try:
                page.status_label.setHtml(
                    "<div>增强包明细</div>" * 80
                    + "<div>"
                    + "C:\\very-long-directory-name" * 80
                    + "</div>"
                )
                page.show()
                self.app.processEvents()

                self.assertIsInstance(page.status_label, QTextEdit)
                self.assertLessEqual(page.minimumSizeHint().height(), 560)
                self.assertLessEqual(page.status_label.maximumHeight(), 126)
                self.assertEqual(
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                    page.status_label.verticalScrollBarPolicy(),
                )
                self.assertGreater(
                    page.status_label.verticalScrollBar().maximum(),
                    0,
                )
                self.assertEqual(
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                    page.analysis.verticalScrollBarPolicy(),
                )
                self.assertEqual(590, page.width())
                self.assertEqual(560, page.height())
            finally:
                page.hide()
                recognition.shutdown()
                manager.deactivate_runtime()
                page.deleteLater()

    def test_custom_install_directory_updates_manager_and_emits_setting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = EnhancementManager(root / "first")
            recognition = RecognitionService(manager)
            page = EnhancementPage(manager, recognition)
            changed = []
            page.directory_changed.connect(changed.append)

            try:
                target = root / "custom"
                target.mkdir()
                page._apply_install_root(target)

                self.assertEqual(target.resolve(), manager.root)
                self.assertEqual(str(target.resolve()), page.directory_input.text())
                self.assertEqual([str(target.resolve())], changed)
                self.assertIn("目录已切换", page.analysis.toPlainText())
            finally:
                recognition.shutdown()
                manager.deactivate_runtime()
                page.deleteLater()


if __name__ == "__main__":
    unittest.main()
