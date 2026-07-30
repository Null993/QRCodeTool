"""Regenerate the multi-resolution Windows application icon."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile

from PIL import Image
from PySide6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qrcap.ui_components import static_application_icon


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def build_icon(destination: Path) -> None:
    application = QApplication.instance() or QApplication([])
    icon = static_application_icon()

    with tempfile.TemporaryDirectory() as temp:
        frames = []
        for size in ICON_SIZES:
            preview_path = Path(temp) / f"application-icon-{size}.png"
            if not icon.pixmap(size, size).save(str(preview_path), "PNG"):
                raise RuntimeError(
                    f"Unable to render the {size}px application icon"
                )
            with Image.open(preview_path) as image:
                frames.append(image.convert("RGBA").copy())

        frames[-1].save(
            destination,
            format="ICO",
            sizes=[(size, size) for size in ICON_SIZES],
            append_images=frames[:-1],
        )
    del application


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "destination",
        nargs="?",
        type=Path,
        default=Path("icon.ico"),
    )
    args = parser.parse_args()
    build_icon(args.destination.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
