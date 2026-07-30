"""Build a QRCodeTool optional QReader/PyTorch enhancement ZIP.

Run this script with the Python environment that contains qreader and its
runtime dependencies. The resulting archive can be imported from the
"增强包" tab without changing the base application installation.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import shutil
import sys
import tempfile
import zipfile
from collections import deque
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT_DISTRIBUTIONS = (
    "qreader",
    "qrdet",
    "torch",
    "torchvision",
    "ultralytics",
    "quadrilateral-fitter",
)

# These modules are already part of the compact base package. NumPy, OpenCV
# and Pillow intentionally remain enhancement dependencies so the base ZIP
# can stay below 30 MiB.
BASE_DISTRIBUTIONS = {
    canonicalize_name(name)
    for name in (
        "django-qrcode",
        "keyboard",
        "pyzbar",
        "pyside6",
        "shiboken6",
        "zxing-cpp",
    )
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a QRCodeTool optional enhancement package.",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("model/qrdet-s.pt"),
        help="Path to qrdet-s.pt.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/QRCodeTool-enhancement-qreader.zip"),
        help="Output ZIP path.",
    )
    parser.add_argument(
        "--version",
        default="1.0.0",
        help="Enhancement package version.",
    )
    parser.add_argument(
        "--name",
        default="QReader/PyTorch 增强识别包",
        help="Display name stored in manifest.json.",
    )
    return parser.parse_args()


def resolve_distributions() -> list[importlib.metadata.Distribution]:
    queue = deque(ROOT_DISTRIBUTIONS)
    resolved: dict[str, importlib.metadata.Distribution] = {}

    while queue:
        requested_name = queue.popleft()
        canonical_name = canonicalize_name(requested_name)
        if canonical_name in resolved or canonical_name in BASE_DISTRIBUTIONS:
            continue

        try:
            distribution = importlib.metadata.distribution(requested_name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(
                f"Missing distribution required for enhancement pack: {requested_name}"
            ) from exc

        actual_name = canonicalize_name(
            distribution.metadata.get("Name") or requested_name
        )
        if actual_name in resolved or actual_name in BASE_DISTRIBUTIONS:
            continue
        resolved[actual_name] = distribution

        for requirement_text in distribution.requires or ():
            requirement = Requirement(requirement_text)
            if requirement.marker and not requirement.marker.evaluate(
                {"extra": ""}
            ):
                continue
            dependency_name = canonicalize_name(requirement.name)
            if dependency_name not in BASE_DISTRIBUTIONS:
                queue.append(requirement.name)

    return sorted(
        resolved.values(),
        key=lambda item: canonicalize_name(item.metadata["Name"]),
    )


def copy_distribution(
    distribution: importlib.metadata.Distribution,
    site_packages: Path,
    destination: Path,
) -> int:
    copied = 0
    for relative_file in distribution.files or ():
        source = Path(distribution.locate_file(relative_file)).resolve()
        try:
            relative = source.relative_to(site_packages)
        except ValueError:
            # Skip console scripts and any file outside site-packages.
            continue
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def build_package(args: argparse.Namespace) -> None:
    model_path = args.model.expanduser().resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"Model not found: {model_path}")

    distributions = resolve_distributions()
    site_packages = Path(
        importlib.metadata.distribution("qreader").locate_file("")
    ).resolve()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    machine = platform.machine().lower()
    architecture = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine, machine)
    manifest = {
        "schema_version": 1,
        "package_id": "qrcap-qreader-pytorch",
        "name": args.name,
        "version": args.version,
        "platform": "windows" if sys.platform == "win32" else sys.platform,
        "architecture": architecture,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "model": "qrdet-s.pt",
        "distributions": {
            distribution.metadata["Name"]: distribution.version
            for distribution in distributions
        },
    }

    with tempfile.TemporaryDirectory(prefix="qrcap-enhancement-") as temp:
        staging = Path(temp)
        runtime_target = staging / "runtime" / "site-packages"
        runtime_target.mkdir(parents=True)

        copied_files = 0
        for distribution in distributions:
            copied_files += copy_distribution(
                distribution,
                site_packages,
                runtime_target,
            )

        model_target = staging / "models" / "qrdet-s.pt"
        model_target.parent.mkdir(parents=True)
        shutil.copy2(model_path, model_target)
        release_marker = model_path.parent / "current_release.txt"
        if release_marker.is_file():
            shutil.copy2(
                release_marker,
                model_target.parent / "current_release.txt",
            )
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())

    print(f"Created: {output}")
    print(f"Distributions: {len(distributions)}")
    print(f"Copied files: {copied_files}")
    print(f"Archive size: {output.stat().st_size / 1024**2:.1f} MiB")


def main() -> int:
    args = parse_args()
    try:
        build_package(args)
    except Exception as exc:
        print(f"Build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
