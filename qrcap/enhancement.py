from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import stat
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .resources import enhancement_root


SCHEMA_VERSION = 1
MAX_ARCHIVE_FILES = 100_000
MAX_UNCOMPRESSED_BYTES = 8 * 1024**3
MANIFEST_NAME = "manifest.json"
MODEL_RELATIVE_PATH = Path("models") / "qrdet-s.pt"
RUNTIME_RELATIVE_PATH = Path("runtime") / "site-packages"

REQUIRED_MODULES = (
    ("qreader", "QReader"),
    ("qrdet", "QRDet"),
    ("torch", "PyTorch"),
    ("torchvision", "TorchVision"),
    ("ultralytics", "Ultralytics"),
)


@dataclass(frozen=True)
class ComponentStatus:
    key: str
    name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class EnhancementStatus:
    installed: bool
    compatible: bool
    structurally_complete: bool
    package_name: str
    package_version: str
    active_dir: Path
    components: tuple[ComponentStatus, ...]
    runtime_verified: bool
    verification_detail: str

    @property
    def can_load(self) -> bool:
        return self.installed and self.compatible and self.structurally_complete


@dataclass
class ImportReport:
    archive: Path
    installed: bool = False
    compatible: bool = False
    structurally_complete: bool = False
    restart_required: bool = False
    package_name: str = ""
    package_version: str = ""
    file_count: int = 0
    uncompressed_bytes: int = 0
    messages: list[str] = field(default_factory=list)
    components: tuple[ComponentStatus, ...] = ()

    @property
    def success(self) -> bool:
        return self.installed

    def to_text(self) -> str:
        lines = [
            f"压缩包：{self.archive}",
            f"导入结果：{'成功' if self.installed else '失败'}",
        ]
        if self.package_name or self.package_version:
            lines.append(
                f"增强包：{self.package_name or '未命名'} "
                f"{self.package_version or '未知版本'}"
            )
        if self.file_count:
            lines.append(
                f"内容：{self.file_count} 个文件，"
                f"{self.uncompressed_bytes / 1024**2:.1f} MiB（解压后）"
            )
        lines.append(f"兼容性：{'通过' if self.compatible else '未通过'}")
        lines.append(
            f"结构完整性：{'完整' if self.structurally_complete else '部分组件缺失'}"
        )
        if self.restart_required:
            lines.append("运行提示：增强运行库已在本进程加载，替换后需重启程序。")
        if self.components:
            lines.append("")
            lines.append("组件分析：")
            for component in self.components:
                mark = "✅" if component.available else "❌"
                lines.append(f"{mark} {component.name}：{component.detail}")
        if self.messages:
            lines.append("")
            lines.append("详细信息：")
            lines.extend(f"- {message}" for message in self.messages)
        return "\n".join(lines)


class EnhancementPackageError(RuntimeError):
    pass


class EnhancementManager:
    """Install, inspect and activate optional QReader/PyTorch enhancement packs."""

    def __init__(self, root: Path | str | None = None):
        self.root = (
            Path(root).expanduser().resolve()
            if root is not None
            else enhancement_root()
        )
        self.active_dir = self.root / "active"
        self._runtime_path: Path | None = None
        self._dll_handles: list[Any] = []
        self._last_status: EnhancementStatus | None = None

    def set_root(self, root: Path | str | None = None) -> Path:
        """Switch the package root without moving or deleting existing data."""

        target = (
            Path(root).expanduser().resolve()
            if root is not None
            else enhancement_root()
        )
        if target == self.root:
            return self.root

        self.deactivate_runtime()
        self.root = target
        self.active_dir = self.root / "active"
        self._last_status = None
        return self.root

    @property
    def runtime_path(self) -> Path:
        return self.active_dir / RUNTIME_RELATIVE_PATH

    @property
    def model_path(self) -> Path:
        return self.active_dir / MODEL_RELATIVE_PATH

    def inspect(self) -> EnhancementStatus:
        installed = self.active_dir.is_dir()
        manifest, manifest_error = self._read_installed_manifest()
        compatible, compatibility_detail = self._check_compatibility(manifest)

        components: list[ComponentStatus] = [
            ComponentStatus(
                "manifest",
                "增强包清单",
                manifest is not None,
                (
                    f"schema_version={manifest.get('schema_version')}"
                    if manifest is not None
                    else manifest_error or "尚未导入增强包"
                ),
            ),
            ComponentStatus(
                "compatibility",
                "平台与 Python 兼容性",
                compatible,
                compatibility_detail,
            ),
        ]

        for module_name, display_name in REQUIRED_MODULES:
            available, detail = self._module_component(module_name)
            components.append(
                ComponentStatus(module_name, display_name, available, detail)
            )

        model_available = self.model_path.is_file()
        components.append(
            ComponentStatus(
                "model",
                "QRDet 模型",
                model_available,
                (
                    f"{self.model_path.name}，{self.model_path.stat().st_size / 1024**2:.1f} MiB"
                    if model_available
                    else f"缺少 {MODEL_RELATIVE_PATH.as_posix()}"
                ),
            )
        )

        structural_keys = {name for name, _ in REQUIRED_MODULES} | {"model"}
        structurally_complete = all(
            component.available
            for component in components
            if component.key in structural_keys
        )

        verification = self._read_verification()
        runtime_verified = bool(verification.get("success"))
        verification_detail = str(
            verification.get("detail", "尚未完成运行时验证")
        )
        status = EnhancementStatus(
            installed=installed,
            compatible=compatible,
            structurally_complete=structurally_complete,
            package_name=str(
                (manifest or {}).get("name")
                or (manifest or {}).get("package_id")
                or ""
            ),
            package_version=str((manifest or {}).get("version") or ""),
            active_dir=self.active_dir,
            components=tuple(components),
            runtime_verified=runtime_verified,
            verification_detail=verification_detail,
        )
        self._last_status = status
        return status

    def import_archive(self, archive: Path | str) -> ImportReport:
        archive_path = Path(archive).expanduser().resolve()
        report = ImportReport(archive=archive_path)
        staging: Path | None = None
        backup: Path | None = None

        try:
            if not archive_path.is_file():
                raise EnhancementPackageError("压缩包不存在。")

            with zipfile.ZipFile(archive_path, "r") as package:
                infos = package.infolist()
                report.file_count = len(
                    [info for info in infos if not info.is_dir()]
                )
                report.uncompressed_bytes = sum(
                    info.file_size for info in infos if not info.is_dir()
                )
                self._validate_archive_members(infos)

                try:
                    manifest_bytes = package.read(MANIFEST_NAME)
                except KeyError as exc:
                    raise EnhancementPackageError(
                        f"压缩包根目录缺少 {MANIFEST_NAME}。"
                    ) from exc

                try:
                    manifest = json.loads(manifest_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise EnhancementPackageError("manifest.json 不是有效的 UTF-8 JSON。") from exc

                compatible, detail = self._check_compatibility(manifest)
                report.compatible = compatible
                report.package_name = str(
                    manifest.get("name") or manifest.get("package_id") or ""
                )
                report.package_version = str(manifest.get("version") or "")
                report.messages.append(detail)
                if not compatible:
                    raise EnhancementPackageError("增强包与当前程序运行环境不兼容。")

                self.root.mkdir(parents=True, exist_ok=True)
                staging = self.root / f".staging-{uuid.uuid4().hex}"
                staging.mkdir()
                self._extract_safely(package, staging)

            staged_manager = EnhancementManager(self.root)
            staged_manager.active_dir = staging
            staged_status = staged_manager.inspect()
            report.components = staged_status.components
            report.structurally_complete = staged_status.structurally_complete
            if not staged_status.structurally_complete:
                report.messages.append(
                    "压缩包已作为部分增强包导入；基础识别仍可正常使用。"
                )

            report.restart_required = any(
                module_name in sys.modules
                for module_name in ("qreader", "qrdet", "torch", "torchvision")
            )

            if self.active_dir.exists():
                backup = self.root / f".backup-{uuid.uuid4().hex}"
                os.replace(self.active_dir, backup)
            os.replace(staging, self.active_dir)
            staging = None
            report.installed = True
            self.activate_runtime()

            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
                backup = None
        except (OSError, zipfile.BadZipFile, EnhancementPackageError) as exc:
            report.messages.append(str(exc))
            if backup is not None and backup.exists() and not self.active_dir.exists():
                os.replace(backup, self.active_dir)
                backup = None
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if backup is not None and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)

        final_status = self.inspect()
        if report.installed:
            report.components = final_status.components
            report.structurally_complete = final_status.structurally_complete
        return report

    def activate_runtime(self) -> EnhancementStatus:
        status = self.inspect()
        runtime = self.runtime_path
        runtime_text = str(runtime)

        if self._runtime_path is not None:
            old_text = str(self._runtime_path)
            while old_text in sys.path:
                sys.path.remove(old_text)

        self._runtime_path = runtime if runtime.is_dir() else None
        if runtime.is_dir() and runtime_text not in sys.path:
            sys.path.insert(0, runtime_text)

        self._dll_handles.clear()
        if hasattr(os, "add_dll_directory"):
            dll_candidates = (
                self.active_dir / "runtime" / "dlls",
                runtime / "torch" / "lib",
                runtime / "Library" / "bin",
            )
            for candidate in dll_candidates:
                if candidate.is_dir():
                    try:
                        self._dll_handles.append(
                            os.add_dll_directory(str(candidate))
                        )
                    except OSError:
                        continue

        importlib.invalidate_caches()
        return status

    def deactivate_runtime(self) -> None:
        if self._runtime_path is not None:
            runtime_text = str(self._runtime_path)
            while runtime_text in sys.path:
                sys.path.remove(runtime_text)
        self._runtime_path = None
        self._dll_handles.clear()
        importlib.invalidate_caches()

    def record_runtime_verification(
        self,
        success: bool,
        detail: str,
        versions: dict[str, str] | None = None,
    ) -> None:
        if not self.active_dir.is_dir():
            return
        payload = {
            "success": bool(success),
            "detail": detail,
            "versions": versions or {},
        }
        verification_path = self.active_dir / "verification.json"
        verification_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._last_status = None

    def installed_versions(self) -> dict[str, str]:
        if not self.runtime_path.is_dir():
            return {}
        versions: dict[str, str] = {}
        try:
            distributions = importlib.metadata.distributions(
                path=[str(self.runtime_path)]
            )
            for distribution in distributions:
                name = distribution.metadata.get("Name")
                if name:
                    versions[name] = distribution.version
        except Exception:
            return {}
        return versions

    def _read_installed_manifest(self) -> tuple[dict[str, Any] | None, str]:
        manifest_path = self.active_dir / MANIFEST_NAME
        if not manifest_path.is_file():
            return None, f"缺少 {MANIFEST_NAME}"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, f"清单读取失败：{exc}"
        if not isinstance(manifest, dict):
            return None, "清单根节点必须是 JSON 对象"
        return manifest, ""

    @staticmethod
    def _check_compatibility(
        manifest: dict[str, Any] | None,
    ) -> tuple[bool, str]:
        if manifest is None:
            return False, "没有可用清单"

        if manifest.get("schema_version") != SCHEMA_VERSION:
            return False, (
                f"清单版本 {manifest.get('schema_version')!r}，"
                f"程序要求 {SCHEMA_VERSION}"
            )

        expected_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        package_python = str(manifest.get("python") or "")
        if package_python not in ("any", expected_python):
            return False, f"Python {package_python or '未声明'}，当前为 {expected_python}"

        expected_platform = "windows" if sys.platform == "win32" else sys.platform
        package_platform = str(manifest.get("platform") or "").lower()
        if package_platform not in ("any", expected_platform):
            return False, (
                f"平台 {package_platform or '未声明'}，当前为 {expected_platform}"
            )

        machine = platform.machine().lower()
        aliases = {
            "amd64": {"amd64", "x86_64"},
            "x86_64": {"amd64", "x86_64"},
            "arm64": {"arm64", "aarch64"},
            "aarch64": {"arm64", "aarch64"},
        }
        package_arch = str(manifest.get("architecture") or "").lower()
        accepted_arches = aliases.get(machine, {machine})
        if package_arch not in accepted_arches | {"any"}:
            return False, (
                f"架构 {package_arch or '未声明'}，当前为 {machine}"
            )

        return True, (
            f"{expected_platform} / {machine} / Python {expected_python}"
        )

    def _module_component(self, module_name: str) -> tuple[bool, str]:
        runtime = self.runtime_path
        if not runtime.is_dir():
            return False, f"缺少 {RUNTIME_RELATIVE_PATH.as_posix()}"

        candidates = [
            runtime / module_name,
            runtime / f"{module_name}.py",
        ]
        candidates.extend(runtime.glob(f"{module_name}*.pyd"))
        candidate = next((path for path in candidates if path.exists()), None)
        if candidate is None:
            return False, f"runtime 中未找到 {module_name}"
        return True, candidate.name

    def _read_verification(self) -> dict[str, Any]:
        verification_path = self.active_dir / "verification.json"
        if not verification_path.is_file():
            return {}
        try:
            payload = json.loads(verification_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _validate_archive_members(infos: list[zipfile.ZipInfo]) -> None:
        file_infos = [info for info in infos if not info.is_dir()]
        if len(file_infos) > MAX_ARCHIVE_FILES:
            raise EnhancementPackageError(
                f"压缩包文件数量超过限制：{len(file_infos)}"
            )
        total_size = sum(info.file_size for info in file_infos)
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise EnhancementPackageError(
                f"压缩包解压后超过 {MAX_UNCOMPRESSED_BYTES / 1024**3:.0f} GiB 限制。"
            )

        names: set[str] = set()
        for info in infos:
            normalized = info.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or ":" in path.parts[0]
            ):
                raise EnhancementPackageError(
                    f"压缩包包含不安全路径：{info.filename}"
                )
            if normalized in names:
                raise EnhancementPackageError(
                    f"压缩包包含重复路径：{info.filename}"
                )
            names.add(normalized)

            unix_mode = info.external_attr >> 16
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise EnhancementPackageError(
                    f"压缩包不允许符号链接：{info.filename}"
                )

    @staticmethod
    def _extract_safely(package: zipfile.ZipFile, destination: Path) -> None:
        destination_resolved = destination.resolve()
        for info in package.infolist():
            relative = PurePosixPath(info.filename.replace("\\", "/"))
            target = destination.joinpath(*relative.parts)
            target_resolved = target.resolve()
            if (
                target_resolved != destination_resolved
                and destination_resolved not in target_resolved.parents
            ):
                raise EnhancementPackageError(
                    f"拒绝解压到目标目录之外：{info.filename}"
                )
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
