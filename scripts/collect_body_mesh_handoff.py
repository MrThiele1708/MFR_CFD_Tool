#!/usr/bin/env python3
"""Collect the files needed for the FormulaStudentCFD body-mesh audit.

The collector writes one UTF-8 text document. Text/config/log files are copied
as readable excerpts. STL and other geometry files are represented by metadata
(path, size, SHA-256 and Trimesh diagnostics), not by their binary contents.

Usage from the project root:
    python3 scripts/collect_body_mesh_handoff.py

Optional:
    python3 scripts/collect_body_mesh_handoff.py \
        --output results/body_mesh_audit_handoff.txt
    python3 scripts/collect_body_mesh_handoff.py --root /path/to/project
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {
    ".cfg",
    ".csv",
    ".dict",
    ".foam",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".txt",
    ".yaml",
    ".yml",
}

CASE_TEXT_FILES = [
    "system/controlDict",
    "system/snappyHexMeshDict",
    "system/blockMeshDict",
    "system/topoSetDict",
    "system/fvOptions",
    "system/mapFieldsDict",
    "system/decomposeParDict",
    "constant/polyMesh/boundary",
    "constant/polyMesh/cellZones",
    "constant/polyMesh/faceZones",
    "constant/geometryMetrics.json",
    "effective.json",
]

CASE_LOG_NAMES = [
    "log.blockMesh",
    "log.snappyHexMesh",
    "log.checkMesh",
    "log.topoSet",
    "log.surfaceFeatures",
    "log.mapFields",
    "log.foamToVTK",
    "log.simpleFoam",
    "log.pimpleFoam",
]

RESULT_PATTERNS = [
    "assembly_mapping*.json",
    "assembly_mapping*.csv",
    "*geometry*.json",
    "*morph*.json",
    "*radiator*.json",
    "*mapping*.log",
    "*mesh*.log",
    "log.*",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def as_root_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return safe_resolve(path)


def read_yaml(path: Path) -> dict[str, Any] | None:
    try:
        import yaml
    except Exception:
        return None

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    return data if isinstance(data, dict) else None


def text_excerpt(path: Path, maximum_bytes: int) -> str:
    data = path.read_bytes()
    if len(data) <= maximum_bytes:
        return data.decode("utf-8", errors="replace")

    half = max(1, maximum_bytes // 2)
    beginning = data[:half].decode("utf-8", errors="replace")
    ending = data[-half:].decode("utf-8", errors="replace")
    return (
        beginning
        + "\n\n... [FILE TRUNCATED BY COLLECTOR] ...\n\n"
        + ending
    )


def is_probably_binary(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return True
    return b"\x00" in sample


def format_number(value: Any) -> Any:
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def stl_metadata(path: Path, include_trimesh: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }

    if not path.is_file():
        return result

    result.update(
        {
            "sizeBytes": path.stat().st_size,
            "sha256": sha256(path),
        }
    )

    if not include_trimesh:
        result["trimesh"] = "disabled"
        return result

    try:
        import trimesh
    except Exception as exc:
        result["trimeshError"] = f"trimesh unavailable: {exc}"
        return result

    try:
        raw = trimesh.load(path, force="mesh", process=False)
        result["raw"] = {
            "vertices": int(len(raw.vertices)),
            "faces": int(len(raw.faces)),
            "bounds": raw.bounds.tolist(),
            "extents": raw.extents.tolist(),
            "watertight": bool(raw.is_watertight),
            "windingConsistent": bool(raw.is_winding_consistent),
        }
    except Exception as exc:
        result["rawError"] = str(exc)

    try:
        normalized = trimesh.load(path, force="mesh", process=True)
        result["processed"] = {
            "vertices": int(len(normalized.vertices)),
            "faces": int(len(normalized.faces)),
            "bounds": normalized.bounds.tolist(),
            "extents": normalized.extents.tolist(),
            "watertight": bool(normalized.is_watertight),
            "windingConsistent": bool(normalized.is_winding_consistent),
        }
    except Exception as exc:
        result["processedError"] = str(exc)

    return result


def add_text_file(
    path: Path,
    required: bool,
    text_files: dict[Path, bool],
    missing: list[Path],
) -> None:
    path = safe_resolve(path)
    if path.is_file():
        text_files[path] = text_files.get(path, False) or required
    elif required:
        missing.append(path)


def add_stl_file(
    path: Path,
    required: bool,
    stl_files: dict[Path, bool],
    missing: list[Path],
) -> None:
    path = safe_resolve(path)
    if path.is_file():
        stl_files[path] = stl_files.get(path, False) or required
    elif required:
        missing.append(path)


def add_case_files(
    case: Path,
    text_files: dict[Path, bool],
    stl_files: dict[Path, bool],
    missing: list[Path],
) -> None:
    for relative in CASE_TEXT_FILES:
        add_text_file(case / relative, False, text_files, missing)

    for name in CASE_LOG_NAMES:
        add_text_file(case / name, False, text_files, missing)

    tri_surface = case / "constant/triSurface"
    if tri_surface.is_dir():
        for path in sorted(tri_surface.glob("*.stl")):
            add_stl_file(path, False, stl_files, missing)


def add_results_files(
    results: Path,
    text_files: dict[Path, bool],
    missing: list[Path],
) -> None:
    if not results.is_dir():
        return

    selected: set[Path] = set()
    for pattern in RESULT_PATTERNS:
        selected.update(results.glob(pattern))

    mesh_study = results / "meshStudy"
    if mesh_study.is_dir():
        for path in mesh_study.glob("*/log.checkMesh"):
            selected.add(path)
        for path in mesh_study.glob("*/log.snappyHexMesh"):
            selected.add(path)

    for path in sorted(selected):
        if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS:
            add_text_file(path, False, text_files, missing)


def collect_geometry(
    root: Path,
    text_files: dict[Path, bool],
    stl_files: dict[Path, bool],
    missing: list[Path],
) -> None:
    geometry = root / "geometry"
    if not geometry.is_dir():
        return

    for path in sorted(geometry.glob("*/*.stl")):
        add_stl_file(path, False, stl_files, missing)

    # These are especially important for the body-mesh diagnosis.
    for relative in (
        "geometry/production/body.stl",
        "geometry/production_mapped/body.stl",
        "geometry/single_part/testwing.stl",
    ):
        add_stl_file(root / relative, True, stl_files, missing)


def collect_project(root: Path) -> tuple[
    dict[Path, bool],
    dict[Path, bool],
    list[Path],
    list[dict[str, Any]],
]:
    text_files: dict[Path, bool] = {}
    stl_files: dict[Path, bool] = {}
    missing: list[Path] = []
    config_info: list[dict[str, Any]] = []

    # All project scripts and configuration files are useful for the path audit.
    scripts = root / "scripts"
    if scripts.is_dir():
        for path in sorted(scripts.glob("*.py")):
            add_text_file(path, False, text_files, missing)
        for path in sorted(scripts.glob("*.sh")):
            add_text_file(path, False, text_files, missing)

    config_dir = root / "config"
    if config_dir.is_dir():
        for path in sorted(config_dir.glob("*.yaml")):
            add_text_file(path, False, text_files, missing)
        for path in sorted(config_dir.glob("*.yml")):
            add_text_file(path, False, text_files, missing)

    for relative in (
        "requirements.txt",
        "README.md",
        "PROJECT_CONTEXT.yaml",
    ):
        add_text_file(root / relative, False, text_files, missing)

    # Explicitly required files from the audit plan.
    for relative in (
        "scripts/select_project_path.py",
        "scripts/write_effective.py",
        "scripts/run_case.sh",
        "scripts/run_production.sh",
        "scripts/run_single_part.sh",
        "scripts/prepare_case.py",
        "scripts/generate_snappy_v13.py",
        "scripts/apply_contact_aware_morph.py",
        "scripts/apply_solver_control.py",
        "scripts/apply_operating_conditions.py",
        "scripts/apply_wheel_rotation.py",
        "scripts/enable_layers.py",
        "scripts/generate_surface_features.py",
        "scripts/apply_feature_settings.py",
        "scripts/create_map_fields_dict.py",
        "scripts/auto_map_geometry.py",
        "scripts/map_assembly_regions_fast.py",
        "scripts/validate_geometry.py",
        "scripts/validate_combined_geometry.py",
        "config/parameters.yaml",
        "config/parameters_single_part.yaml",
        "config/geometryManifest.yaml",
        "config/geometryManifest_single_part.yaml",
        "case/constant/triSurface/body.stl",
        "case/system/snappyHexMeshDict",
        "case/log.snappyHexMesh",
        "case/log.checkMesh",
    ):
        path = root / relative
        if path.suffix.lower() == ".stl":
            add_stl_file(path, True, stl_files, missing)
        else:
            add_text_file(path, True, text_files, missing)

    for config_path in (
        root / "config/parameters.yaml",
        root / "config/parameters_single_part.yaml",
    ):
        if not config_path.is_file():
            continue

        config = read_yaml(config_path)
        info: dict[str, Any] = {"config": str(config_path)}
        if config is None:
            info["yaml"] = "unavailable or invalid"
            config_info.append(info)
            continue

        project = config.get("project", {}) or {}
        geometry_config = config.get("geometry", {}) or {}
        case_value = project.get("case")
        results_value = project.get("results")
        profile = geometry_config.get("profile")
        manifest = geometry_config.get("manifest", "config/geometryManifest.yaml")

        info.update(
            {
                "case": str(case_value),
                "results": str(results_value),
                "profile": str(profile),
                "manifest": str(manifest),
            }
        )
        config_info.append(info)

        if case_value:
            case = as_root_path(root, str(case_value))
            add_case_files(case, text_files, stl_files, missing)

        if results_value:
            add_results_files(as_root_path(root, str(results_value)), text_files, missing)

        if profile:
            profile_dir = root / "geometry" / str(profile)
            for path in sorted(profile_dir.glob("*.stl")):
                add_stl_file(path, False, stl_files, missing)

        mapping = geometry_config.get("assemblyMapping", {}) or {}
        for key in ("sourceProfile", "outputProfile"):
            value = mapping.get(key)
            if value:
                profile_dir = root / "geometry" / str(value)
                for path in sorted(profile_dir.glob("*.stl")):
                    add_stl_file(path, False, stl_files, missing)

    # Include an explicitly selected case as well, if the caller exported it.
    selected_case = os.environ.get("CFD_CASE")
    selected_results = os.environ.get("CFD_RESULTS")
    if selected_case:
        add_case_files(as_root_path(root, selected_case), text_files, stl_files, missing)
    if selected_results:
        add_results_files(as_root_path(root, selected_results), text_files, missing)

    collect_geometry(root, text_files, stl_files, missing)
    return text_files, stl_files, missing, config_info


def write_report(
    root: Path,
    output: Path,
    text_files: dict[Path, bool],
    stl_files: dict[Path, bool],
    missing: list[Path],
    config_info: list[dict[str, Any]],
    maximum_bytes: int,
    include_stl_metadata: bool,
) -> None:
    output = safe_resolve(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Do not collect the report itself if it is located below the project.
    text_files.pop(output, None)

    lines: list[str] = []
    lines.extend(
        [
            "FormulaStudentCFD_v0_8 – BODY MESH AUDIT HANDOFF",
            "=" * 72,
            f"Generated UTC: {datetime.now(timezone.utc).isoformat()}",
            f"Project root: {root}",
            f"Output file: {output}",
            "",
            "This document contains text/config/log excerpts and geometry metadata.",
            "Binary STL and OpenFOAM mesh contents are not embedded as raw binary.",
            "",
            "CONFIGURATION PATH SUMMARY",
            "-" * 72,
            json.dumps(config_info, indent=2, ensure_ascii=False),
            "",
            "COLLECTION SUMMARY",
            "-" * 72,
            f"Text files: {len(text_files)}",
            f"STL files: {len(stl_files)}",
            f"Missing required files: {len(set(missing))}",
            "",
        ]
    )

    unique_missing = sorted(set(missing))
    lines.append("MISSING REQUIRED FILES")
    lines.append("-" * 72)
    if unique_missing:
        lines.extend(str(path) for path in unique_missing)
    else:
        lines.append("None")
    lines.append("")

    lines.append("STL / GEOMETRY METADATA")
    lines.append("-" * 72)
    for path in sorted(stl_files):
        lines.append(json.dumps(stl_metadata(path, include_stl_metadata), indent=2))
        lines.append("")

    lines.append("TEXT FILES AND LOG EXCERPTS")
    lines.append("-" * 72)
    for path in sorted(text_files):
        required = text_files[path]
        lines.extend(
            [
                "",
                f"FILE: {path}",
                f"REQUIRED: {required}",
                f"SIZE_BYTES: {path.stat().st_size if path.is_file() else 'missing'}",
                f"SHA256: {sha256(path) if path.is_file() else 'missing'}",
                "BEGIN CONTENT",
            ]
        )

        if not path.is_file():
            lines.append("[MISSING]")
        elif is_probably_binary(path):
            lines.append("[BINARY FILE OMITTED; metadata only]")
        else:
            lines.append(text_excerpt(path, maximum_bytes))

        lines.extend(["END CONTENT", "=" * 72])

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Created: {output}")
    print(f"Text files: {len(text_files)}")
    print(f"STL files: {len(stl_files)}")
    print(f"Missing required files: {len(unique_missing)}")
    if unique_missing:
        print("Missing:")
        for path in unique_missing:
            print(f"  {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect FormulaStudentCFD body-mesh audit files into one text document."
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Project root; defaults to the parent of scripts/ when run from scripts.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output text file; default is results/body_mesh_audit_handoff.txt.",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=1_000_000,
        help="Maximum excerpt size per text/log file; default: 1000000.",
    )
    parser.add_argument(
        "--no-stl-metadata",
        action="store_true",
        help="Do not run Trimesh diagnostics on STL files; hashes are still included.",
    )
    args = parser.parse_args()

    if args.root:
        root = safe_resolve(Path(args.root))
    else:
        candidate = Path(__file__).resolve().parents[1]
        root = candidate if (candidate / "scripts").is_dir() else safe_resolve(Path.cwd())

    output = (
        safe_resolve(Path(args.output))
        if args.output
        else root / "results/body_mesh_audit_handoff.txt"
    )
    if not output.is_absolute():
        output = root / output

    if args.max_file_bytes < 1024:
        parser.error("--max-file-bytes must be at least 1024")

    text_files, stl_files, missing, config_info = collect_project(root)
    write_report(
        root=root,
        output=output,
        text_files=text_files,
        stl_files=stl_files,
        missing=missing,
        config_info=config_info,
        maximum_bytes=args.max_file_bytes,
        include_stl_metadata=not args.no_stl_metadata,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
