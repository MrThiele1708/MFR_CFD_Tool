#!/usr/bin/env python3
"""Create a very small FormulaStudentCFD bundle containing only scripts/configs.

Default: active/core scripts and configs only.
Optional:
  --all-scripts  include every .py/.sh/.bash file below scripts/
  --all-configs  include every text config file below config/

Run from the project root:
  python3 scripts/collect_scripts_and_configs.py

Output:
  results/scripts_and_configs.txt
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys


# Only the active/canonical workflow is included by default. Obsolete and
# experimental variants such as configure_restart.py, old mappers and contact
# repair scripts are intentionally excluded.
CORE_CONFIGS = (
    "config/parameters.yaml",
    "config/geometryManifest.yaml",
    "config/assemblyMappingFast.yaml",
)

CORE_SCRIPTS = (
    "scripts/run_case.sh",
    "scripts/write_effective.py",
    "scripts/prepare_case.py",
    "scripts/generate_case_files.py",
    "scripts/generate_snappy_v13.py",
    "scripts/generate_turbulence_fields.py",
    "scripts/enable_layers.py",
    "scripts/generate_control.py",
    "scripts/add_forces_objects.py",
    "scripts/apply_wheel_rotation.py",
    "scripts/generate_surface_features.py",
    "scripts/apply_feature_settings.py",
    "scripts/run_surface_features.sh",
    "scripts/apply_solver_control.py",
    "scripts/apply_operating_conditions.py",
    "scripts/auto_map_geometry.py",
    "scripts/map_assembly_regions_fast.py",
    "scripts/validate_geometry.py",
    "scripts/validate_combined_geometry.py",
)

CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".ini", ".cfg", ".toml"}
SCRIPT_SUFFIXES = {".py", ".sh", ".bash"}
EXCLUDED_PARTS = {"__pycache__", ".venv", "node_modules", ".git", "archive"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")


def add_file(files: list[Path], root: Path, relative: str) -> None:
    path = (root / relative).resolve()
    if path.is_file() and path not in files:
        files.append(path)


def add_all(root: Path, directory: str, suffixes: set[str], files: list[Path]) -> None:
    base = root / directory
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in suffixes and path.resolve() not in files:
            files.append(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/scripts_and_configs.txt"),
        help="output text file",
    )
    parser.add_argument(
        "--all-scripts",
        action="store_true",
        help="include all Python/Bash files below scripts/",
    )
    parser.add_argument(
        "--all-configs",
        action="store_true",
        help="include all text config files below config/",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: project root does not exist: {root}", file=sys.stderr)
        return 2

    output = args.output.expanduser()
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    missing: list[str] = []

    if args.all_configs:
        add_all(root, "config", CONFIG_SUFFIXES, files)
    else:
        for relative in CORE_CONFIGS:
            path = root / relative
            if path.is_file():
                files.append(path.resolve())
            else:
                missing.append(relative)

    if args.all_scripts:
        add_all(root, "scripts", SCRIPT_SUFFIXES, files)
    else:
        for relative in CORE_SCRIPTS:
            path = root / relative
            if path.is_file():
                files.append(path.resolve())
            else:
                missing.append(relative)

    files = sorted(set(files), key=lambda p: str(p.relative_to(root)).lower())

    sections = [
        "# FormulaStudentCFD — SCRIPTS AND CONFIGS ONLY",
        f"# Generated: {datetime.now().astimezone().isoformat()}",
        "# No case files, meshes, STL files, logs, results or binary files are included.",
        "# Default mode contains only the active/core workflow files.",
        "",
    ]

    for path in files:
        relative = path.relative_to(root)
        sections.extend([
            "=" * 88,
            f"FILE: {relative}",
            "=" * 88,
            read_text(path).rstrip(),
            "",
        ])

    output.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    print(f"Bundle written: {output}")
    print(f"Included files: {len(files)}")
    print(f"Output size: {output.stat().st_size} bytes")
    if missing:
        print("Missing core files:")
        for relative in missing:
            print(f"  - {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
