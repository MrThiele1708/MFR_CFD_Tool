#!/usr/bin/env python3
"""Create a clean FormulaStudentCFD_v0_8 source distribution ZIP.

Generated cases, meshes, solver results, virtual environments and temporary
test profiles are intentionally excluded. The ZIP contains source geometry,
configuration, active scripts, minimal physics templates and installation
instructions for Ubuntu/WSL2 with OpenFOAM13.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import yaml


ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_SCRIPT_TOKENS = (
    "_test",
    "_debug",
    "_diagnostic",
    "_original",
    "_v1",
    "_v2",
    "_v3",
    "_v4",
    "harmonic",
    "hybrid",
    "surface_points",
    "contact_boundaries",
    "fallback_faces",
)

TEXT_DOCUMENTS = (
    "requirements.txt",
    "README.md",
    "PROJECT_CONTEXT.yaml",
)

PHYSICS_TEMPLATE_FILES = (
    "physicalProperties",
    "momentumTransport",
    "g",
)

DISTRIBUTION_README = r'''# FormulaStudentCFD_v0_8 distribution

## Requirements

- Ubuntu or WSL2
- OpenFOAM 13 available at `/opt/openfoam13/etc/bashrc`
- Python 3.10 or newer
- OpenMPI for optional parallel runs
- ParaView/pvpython for postprocessing

## Installation

From the extracted project root:

```bash
chmod +x install_dependencies.sh
./install_dependencies.sh
```

The installer creates `.venv` and installs `requirements.txt`. OpenFOAM and
ParaView are external system dependencies and are not installed by pip.

## Geometry

Production source geometry belongs in `geometry/production/`.
Single-Part geometry belongs in `geometry/single_part/`. For Single-Part,
place exactly one STL in that directory. The workflow automatically updates
the Single-Part manifest to the actual STL filename.

## Production commands

```bash
./scripts/run_production.sh config
ALLOW_MESH_WARNINGS=true ./scripts/run_production.sh mesh
ALLOW_MESH_WARNINGS=true ./scripts/run_production.sh full
```

`full` starts the configured solver after mesh generation. Use `mesh` first
and inspect `checkMesh` before using `full`.

## Single-Part commands

```bash
./scripts/run_single_part.sh config
ALLOW_MESH_WARNINGS=true ./scripts/run_single_part.sh mesh
ALLOW_MESH_WARNINGS=true ./scripts/run_single_part.sh full
```

Production and Single-Part cases/results are kept separate. Do not mix their
configuration, geometry, case or results directories.

## Parallel execution

```bash
PARALLEL=true NPROCS=6 ALLOW_MESH_WARNINGS=true \
    ./scripts/run_production.sh mesh
```

## Results

Generated cases and results are intentionally not included in this source
ZIP. They are produced locally by the workflows under `case/`,
`case_single_part/`, `results/` and `results_single_part/`.

The current production workflow uses position-only surface point mapping and
global rigid-transition assembly morphing. `flippedFaces` are reported as a
configured warning, while watertightness, boundary edges and non-manifold
edges remain geometry gates. `ALLOW_MESH_WARNINGS=true` is required to
continue past non-fatal `checkMesh` warnings.
'''

INSTALL_SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

chmod +x scripts/*.sh scripts/*.py 2>/dev/null || true

echo
 echo "Python environment ready: $ROOT/.venv"
 echo "Check OpenFOAM separately with: source /opt/openfoam13/etc/bashrc"
'''


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def add_bytes(entries, archive_path: str, data: bytes, mode: int = 0o644):
    entries.append((archive_path, data, mode))


def add_file(entries, path: Path, archive_path: str | None = None, mode: int | None = None):
    if not path.is_file():
        return
    data = path.read_bytes()
    if archive_path is None:
        archive_path = safe_rel(path)
    if mode is None:
        mode = 0o755 if path.suffix in (".sh", ".py") else 0o644
    entries.append((archive_path, data, mode))


def add_tree(entries, source: Path, archive_root: str, exclude_generated: bool = False):
    if not source.is_dir():
        return
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        relative = path.relative_to(source)
        parts = set(relative.parts)
        if name.endswith(".Zone.Identifier") or ":Zone.Identifier" in name:
            continue
        if exclude_generated and (
            "processor" in parts
            or "VTK" in parts
            or "postProcessing" in parts
            or "temp" in parts
            or name.startswith("log.")
        ):
            continue
        archive_path = f"{archive_root}/{relative.as_posix()}"
        mode = 0o755 if path.suffix in (".sh", ".py") else 0o644
        add_file(entries, path, archive_path, mode)


def sanitized_config(path: Path) -> bytes:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SystemExit(f"Invalid YAML configuration: {path}")
    project = config.setdefault("project", {})
    project["windowsResults"] = ""
    return yaml.safe_dump(
        config,
        sort_keys=False,
    ).encode("utf-8")


def collect_entries(include_mapped_profile: bool):
    entries = []

    for relative in TEXT_DOCUMENTS:
        add_file(entries, ROOT / relative)

    # Include the collector itself so the distribution can be recreated.
    add_file(
        entries,
        ROOT / "create_distribution_zip.py",
        "create_distribution_zip.py",
        0o755,
    )

    # Sanitize user-specific Windows result paths in the distributed configs.
    for relative in (
        "config/parameters.yaml",
        "config/parameters_single_part.yaml",
    ):
        path = ROOT / relative
        if path.is_file():
            add_bytes(entries, relative, sanitized_config(path))

    # Add config files individually. The two parameter YAML files are
    # inserted separately in sanitized form below.
    config_dir = ROOT / "config"
    if config_dir.is_dir():
        for path in sorted(config_dir.iterdir()):
            if not path.is_file():
                continue
            if path.name in (
                "parameters.yaml",
                "parameters_single_part.yaml",
            ):
                continue
            if path.name.endswith(".Zone.Identifier"):
                continue
            add_file(
                entries,
                path,
                f"config/{path.name}",
            )

    # The two source geometry profiles are required. Generated mapped profiles
    # are reproducible and are excluded by default.
    add_tree(entries, ROOT / "geometry/production", "geometry/production")
    add_tree(entries, ROOT / "geometry/single_part", "geometry/single_part")

    if include_mapped_profile:
        add_tree(
            entries,
            ROOT / "geometry/production_mapped",
            "geometry/production_mapped",
        )

    scripts = ROOT / "scripts"
    if scripts.is_dir():
        for path in sorted(scripts.glob("*.py")):
            if any(token in path.name for token in EXCLUDED_SCRIPT_TOKENS):
                continue
            add_file(entries, path, f"scripts/{path.name}", 0o755)
        for path in sorted(scripts.glob("*.sh")):
            if any(token in path.name for token in EXCLUDED_SCRIPT_TOKENS):
                continue
            add_file(entries, path, f"scripts/{path.name}", 0o755)

    # Minimal source physics templates required by
    # generate_physical_properties.py. Do not include polyMesh or solver times.
    for filename in PHYSICS_TEMPLATE_FILES:
        add_file(
            entries,
            ROOT / "case/constant" / filename,
            f"case/constant/{filename}",
        )

    add_bytes(
        entries,
        "case/README_TEMPLATE.txt",
        b"Generated production case directory.\n",
    )
    add_bytes(
        entries,
        "case_single_part/README_TEMPLATE.txt",
        b"Generated Single-Part case directory.\n",
    )
    add_bytes(
        entries,
        "DISTRIBUTION_README.md",
        DISTRIBUTION_README.encode("utf-8"),
    )
    add_bytes(
        entries,
        "install_dependencies.sh",
        INSTALL_SCRIPT.encode("utf-8"),
        0o755,
    )

    return entries


def write_zip(output: Path, entries):
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_lines = []

    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for archive_path, data, mode in sorted(entries, key=lambda item: item[0]):
            package_path = f"FormulaStudentCFD_v0_8/{archive_path}"
            info = ZipInfo(package_path)
            info.date_time = datetime.now().timetuple()[:6]
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (mode & 0xFFFF) << 16
            archive.writestr(info, data)
            manifest_lines.append(
                f"{sha256_bytes(data)}  {archive_path}\n"
            )

        manifest_data = "".join(manifest_lines).encode("utf-8")
        info = ZipInfo(
            "FormulaStudentCFD_v0_8/DISTRIBUTION_MANIFEST.sha256"
        )
        info.date_time = datetime.now().timetuple()[:6]
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, manifest_data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=None,
        help="ZIP path; default: dist/FormulaStudentCFD_v0_8_distribution_<timestamp>.zip",
    )
    parser.add_argument(
        "--include-mapped-profile",
        action="store_true",
        help="Include geometry/production_mapped as well as source geometry.",
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = (
        Path(args.output)
        if args.output
        else ROOT
        / "dist"
        / f"FormulaStudentCFD_v0_8_distribution_{timestamp}.zip"
    )
    if not output.is_absolute():
        output = ROOT / output

    entries = collect_entries(args.include_mapped_profile)
    if not entries:
        raise SystemExit("No distribution entries collected")

    write_zip(output, entries)

    print("Created:", output)
    print("Files:", len(entries))
    print("Mapped profile included:", args.include_mapped_profile)
    print("Size bytes:", output.stat().st_size)


if __name__ == "__main__":
    main()