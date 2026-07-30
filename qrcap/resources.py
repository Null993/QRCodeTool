from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "QRCodeTool"
ENHANCEMENT_ENV = "QRCAP_ENHANCEMENT_DIR"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def program_root() -> Path:
    """Return the directory containing the executable or source entry."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_path(relative_path: str) -> str:
    """Return a bundled resource path in both source and PyInstaller modes."""
    bundle_root = Path(getattr(sys, "_MEIPASS", project_root()))
    return str(bundle_root / relative_path)


def enhancement_root() -> Path:
    """Return the writable root used for imported enhancement packages."""
    override = os.environ.get(ENHANCEMENT_ENV)
    if override:
        return Path(override).expanduser().resolve()

    return program_root()
