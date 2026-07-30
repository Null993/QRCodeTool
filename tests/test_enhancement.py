from __future__ import annotations

import json
import platform
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from qrcap.enhancement import EnhancementManager, REQUIRED_MODULES
from qrcap.recognition import RecognitionService


def compatible_manifest() -> dict:
    machine = platform.machine().lower()
    architecture = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine)
    return {
        "schema_version": 1,
        "package_id": "test-enhancement",
        "name": "测试增强包",
        "version": "1.0.0",
        "platform": "windows" if sys.platform == "win32" else sys.platform,
        "architecture": architecture,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def write_package(
    archive: Path,
    *,
    model: bool = False,
    modules: tuple[str, ...] = (),
) -> None:
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(
            "manifest.json",
            json.dumps(compatible_manifest(), ensure_ascii=False),
        )
        if model:
            package.writestr("models/qrdet-s.pt", b"test-model")
        for module_name in modules:
            source = ""
            if module_name == "qreader":
                source = (
                    "class QReader:\n"
                    "    def __init__(self, **kwargs): pass\n"
                    "    def detect_and_decode(self, image, is_bgr=True): return ()\n"
                )
            package.writestr(
                f"runtime/site-packages/{module_name}/__init__.py",
                source,
            )


class EnhancementManagerTests(unittest.TestCase):
    def test_install_root_can_be_changed_without_moving_existing_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first"
            second = root / "second"
            manager = EnhancementManager(first)
            (manager.active_dir / "models").mkdir(parents=True)

            selected = manager.set_root(second)

            self.assertEqual(second.resolve(), selected)
            self.assertEqual(second.resolve(), manager.root)
            self.assertEqual(second.resolve() / "active", manager.active_dir)
            self.assertTrue((first / "active" / "models").is_dir())
            self.assertFalse(manager.inspect().installed)

    def test_no_package_is_safe_base_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = EnhancementManager(Path(temp))
            status = manager.inspect()

            self.assertFalse(status.installed)
            self.assertFalse(status.can_load)
            self.assertTrue(
                all(
                    not component.available
                    for component in status.components
                    if component.key in {"model", "qreader", "torch"}
                )
            )

    def test_model_only_package_is_installed_as_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "model-only.zip"
            write_package(archive, model=True)
            manager = EnhancementManager(root / "managed")

            report = manager.import_archive(archive)
            status = manager.inspect()

            self.assertTrue(report.success)
            self.assertFalse(report.structurally_complete)
            self.assertTrue(status.installed)
            self.assertFalse(status.can_load)
            model = next(
                component
                for component in status.components
                if component.key == "model"
            )
            self.assertTrue(model.available)
            manager.deactivate_runtime()

    def test_runtime_only_package_is_installed_as_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "runtime-only.zip"
            modules = tuple(name for name, _ in REQUIRED_MODULES)
            write_package(archive, modules=modules)
            manager = EnhancementManager(root / "managed")

            report = manager.import_archive(archive)
            status = manager.inspect()

            self.assertTrue(report.success)
            self.assertFalse(status.can_load)
            self.assertTrue(
                all(
                    component.available
                    for component in status.components
                    if component.key in modules
                )
            )
            model = next(
                component
                for component in status.components
                if component.key == "model"
            )
            self.assertFalse(model.available)
            manager.deactivate_runtime()

    def test_complete_package_passes_structure_and_runtime_preload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "complete.zip"
            modules = tuple(name for name, _ in REQUIRED_MODULES)
            write_package(archive, model=True, modules=modules)
            manager = EnhancementManager(root / "managed")
            report = manager.import_archive(archive)
            service = RecognitionService(manager)

            try:
                self.assertTrue(report.success)
                self.assertTrue(manager.inspect().can_load)
                service._preload_model_engine()
                status = manager.inspect()
                self.assertTrue(status.runtime_verified)
            finally:
                service.shutdown()
                manager.deactivate_runtime()
                for module_name in modules:
                    sys.modules.pop(module_name, None)

    def test_path_traversal_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr(
                    "manifest.json",
                    json.dumps(compatible_manifest()),
                )
                package.writestr("../outside.txt", "unsafe")

            manager = EnhancementManager(root / "managed")
            report = manager.import_archive(archive)

            self.assertFalse(report.success)
            self.assertFalse((root / "outside.txt").exists())
            self.assertFalse(manager.inspect().installed)


if __name__ == "__main__":
    unittest.main()
