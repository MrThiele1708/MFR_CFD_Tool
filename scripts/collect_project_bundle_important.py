#!/usr/bin/env python3
"""Create a compact FormulaStudentCFD handoff bundle.

The default output contains only files needed to understand the active
configuration, runner, mesh generation, restart state, geometry mapping and
current mesh/solver status. Large OpenFOAM field files are reduced to their
header and boundaryField section. STL/VTK/PNG/XLSX files are inventoried only.

Run from the project root:
    python3 scripts/collect_project_bundle_important.py

Output:
    results/project_bundle_important.txt
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


FIELD_NAMES = ("U", "p", "k", "omega", "nut")
NUMERIC_TIME_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")

# Active/canonical workflow files. Experimental and obsolete alternatives are
# intentionally omitted from the default bundle.
CORE_CONFIG = (
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
POSTPROCESSING_SCRIPTS = (
    "scripts/generate_slices_vtk.py",
    "scripts/create_excel_v6.py",
)
SYSTEM_FILES = (
    "case/system/controlDict",
    "case/system/blockMeshDict",
    "case/system/snappyHexMeshDict",
    "case/system/fvSchemes",
    "case/system/fvSolution",
    "case/system/surfaceFeaturesDict",
    "case/system/decomposeParDict",
)
CORE_CASE_FILES = (
    "case/constant/polyMesh/boundary",
    "case/constant/geometryMetrics.json",
)
IMPORTANT_REPORTS = (
    "results/assembly_mapping_fast_report.json",
    "results/assembly_mapping_fast_summary.csv",
    "results/mapped_combined_report_v2.json",
    "results/production_geometry_report.json",
)
LOG_NAMES = (
    "log.blockMesh",
    "log.snappyHexMesh",
    "log.checkMesh",
    "log.simpleFoam",
    "log.pimpleFoam",
    "log.foamToVTK",
    "log.decomposePar",
    "log.reconstructPar",
)


class CompactCollector:
    def __init__(self, root: Path, output: Path, max_chars: int, hash_stl: bool):
        self.root = root.resolve()
        self.output = output.resolve()
        self.max_chars = max_chars
        self.hash_stl = hash_stl
        self.files: dict[Path, str] = {}
        self.missing: list[str] = []
        self.optional_missing: list[str] = []
        self.binary_paths: set[Path] = set()
        self.notes: list[str] = []

    def rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root))
        except ValueError:
            return str(path)

    def add(self, relative: str, kind: str = "full", optional: bool = False) -> None:
        path = self.root / relative
        if path.is_file():
            self.files[path.resolve()] = kind
        elif optional:
            self.optional_missing.append(relative)
        else:
            self.missing.append(relative)

    def add_glob(self, relative_dir: str, pattern: str, kind: str = "full") -> None:
        base = self.root / relative_dir
        if not base.is_dir():
            return
        for path in sorted(base.glob(pattern)):
            if path.is_file() and path.resolve() != self.output:
                self.files[path.resolve()] = kind

    def add_text_files(self) -> None:
        for relative in CORE_CONFIG + CORE_SCRIPTS + SYSTEM_FILES + CORE_CASE_FILES:
            self.add(relative, optional=True)

        for time_name in ("0", "0.orig"):
            for field in FIELD_NAMES:
                self.add(f"case/{time_name}/{field}", kind="field", optional=True)

        for name in LOG_NAMES:
            self.add(f"case/{name}", kind="log", optional=True)

        for relative in IMPORTANT_REPORTS:
            self.add(relative, optional=True)

        # Force output is more useful than the large solver time directories.
        post = self.root / "case/postProcessing"
        if post.is_dir():
            force_paths = sorted(
                p for p in post.rglob("*")
                if p.is_file() and p.name in {"forces.dat", "forceCoeffs.dat"}
            )
            # Keep at most one/latest file per force-function directory.
            grouped: dict[str, list[Path]] = {}
            for path in force_paths:
                parts = path.relative_to(post).parts
                group = parts[0] if parts else path.name
                grouped.setdefault(group, []).append(path)
            for group, paths in sorted(grouped.items()):
                chosen = sorted(paths, key=lambda p: p.stat().st_mtime)[-1]
                self.files[chosen.resolve()] = "tail"

    def add_latest_time(self) -> str | None:
        case = self.root / "case"
        if not case.is_dir():
            self.notes.append("case/ does not exist.")
            return None
        candidates: list[tuple[float, Path]] = []
        for path in case.iterdir():
            if path.is_dir() and NUMERIC_TIME_RE.fullmatch(path.name):
                candidates.append((float(path.name), path))
        if not candidates:
            self.notes.append("No numeric OpenFOAM time directory found.")
            return None
        latest = max(candidates, key=lambda item: item[0])[1]
        for field in FIELD_NAMES:
            self.add(f"case/{latest.name}/{field}", kind="field", optional=True)
        return latest.name

    def add_binary_inventory(self) -> None:
        geometry_roots = [
            self.root / "geometry/production",
            self.root / "geometry/production_mapped",
            self.root / "geometry/production_repaired",
            self.root / "geometry/production_repaired_pairs",
        ]
        for base in geometry_roots:
            if base.is_dir():
                for path in base.rglob("*"):
                    if path.is_file() and path.suffix.lower() == ".stl":
                        self.binary_paths.add(path.resolve())

        for relative in ("results/FormulaStudent_results.xlsx",):
            path = self.root / relative
            if path.is_file():
                self.binary_paths.add(path.resolve())

        # Feature files are small text files, but only their presence/size is
        # relevant to this compact bundle.
        feature_roots = (
            self.root / "case/constant/triSurface",
            self.root / "case/constant/extendedFeatureEdgeMesh",
        )
        for base in feature_roots:
            if base.is_dir():
                for path in base.rglob("*"):
                    if path.is_file():
                        self.binary_paths.add(path.resolve())

    @staticmethod
    def read(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")

    @staticmethod
    def balanced_entry(text: str, key: str) -> str | None:
        match = re.search(r"\b" + re.escape(key) + r"\s*\{", text)
        if not match:
            return None
        opening = text.find("{", match.start(), match.end())
        if opening < 0:
            return None
        depth = 0
        state = "normal"
        i = opening
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if state == "normal":
                if ch == "/" and nxt == "/":
                    state = "line"
                    i += 2
                    continue
                if ch == "/" and nxt == "*":
                    state = "block"
                    i += 2
                    continue
                if ch == '"':
                    state = "string"
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[match.start():i + 1]
            elif state == "line":
                if ch == "\n":
                    state = "normal"
            elif state == "block":
                if ch == "*" and nxt == "/":
                    state = "normal"
                    i += 2
                    continue
            elif state == "string":
                if ch == "\\":
                    i += 2
                    continue
                if ch == '"':
                    state = "normal"
            i += 1
        return None

    @classmethod
    def field_summary(cls, text: str) -> str:
        lines: list[str] = ["[FIELD SUMMARY: internalField omitted]"]
        foam = cls.balanced_entry(text, "FoamFile")
        if foam:
            lines.extend(["", foam.strip()])
        dimensions = re.search(r"(?m)^\s*dimensions\s+.*?;", text)
        if dimensions:
            lines.append(dimensions.group(0).strip())
        internal = re.search(r"(?m)^\s*internalField\s+[^\n]*", text)
        if internal:
            value = internal.group(0).strip()
            if len(value) > 300:
                value = value[:300] + " ... [truncated]"
            lines.append(value)
        boundary = cls.balanced_entry(text, "boundaryField")
        if boundary:
            lines.extend(["", "--- boundaryField ---", boundary.strip()])
        else:
            lines.append("boundaryField: NOT FOUND")
        return "\n".join(lines)

    @staticmethod
    def summarize_log(text: str) -> str:
        lines = text.splitlines()
        key = re.compile(
            r"Mesh OK|Failed|cells:|points:|faces:|Max aspect|non-orthogonality|skewness|"
            r"concave|determinant|ExecutionTime|ClockTime|FOAM FATAL|End|forceCoeffs|forces"
        , re.IGNORECASE)
        highlights: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if key.search(line) and line not in seen:
                highlights.append(line)
                seen.add(line)
        tail = lines[-120:]
        return (
            "[LOG SUMMARY]\n"
            + "\n--- important matching lines ---\n"
            + "\n".join(highlights[-180:])
            + "\n\n--- last 120 lines ---\n"
            + "\n".join(tail)
        )

    def format_file(self, path: Path, kind: str) -> str:
        text = self.read(path)
        size = path.stat().st_size
        header = (
            "\n" + "=" * 88 + "\n"
            + f"FILE: {self.rel(path)}\nSIZE_BYTES: {size}\n"
            + "=" * 88 + "\n"
        )
        if kind == "field":
            return header + self.field_summary(text) + "\n"
        if kind == "log":
            return header + self.summarize_log(text) + "\n"
        if kind == "tail":
            return header + "[LAST 160 LINES]\n" + "\n".join(text.splitlines()[-160:]) + "\n"
        if len(text) > self.max_chars:
            half = self.max_chars // 2
            text = (
                "[TEXT TRUNCATED]\n"
                + text[:half]
                + "\n\n... MIDDLE OMITTED ...\n\n"
                + text[-half:]
            )
        return header + text.rstrip() + "\n"

    def environment(self) -> str:
        commands = (
            "foamVersion",
            "python3 --version",
            "command -v python3 || true",
            "command -v simpleFoam || true",
            "free -h",
            "nproc",
        )
        chunks: list[str] = []
        for command in commands:
            try:
                result = subprocess.run(
                    ["bash", "-lc", command],
                    cwd=self.root,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=20,
                    check=False,
                )
                chunks.append(f"$ {command}\n{result.stdout.strip()}\n[exit={result.returncode}]")
            except Exception as exc:
                chunks.append(f"$ {command}\nERROR: {exc}")
        return "\n\n".join(chunks)

    def checks(self) -> str:
        lines: list[str] = []
        runner = self.root / "scripts/run_case.sh"
        if runner.is_file():
            result = subprocess.run(
                ["bash", "-n", str(runner)],
                cwd=self.root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            lines.append(f"bash -n scripts/run_case.sh: exit={result.returncode}\n{result.stdout.strip()}")
        for path in sorted((self.root / "scripts").glob("*.py")) if (self.root / "scripts").is_dir() else []:
            try:
                compile(self.read(path), str(path), "exec")
                lines.append(f"Python compile {self.rel(path)}: OK")
            except Exception as exc:
                lines.append(f"Python compile {self.rel(path)}: FAILED: {exc}")
        return "\n".join(lines) if lines else "No static checks could be run."

    def time_summary(self, latest: str | None) -> str:
        case = self.root / "case"
        times: list[tuple[float, str]] = []
        if case.is_dir():
            for path in case.iterdir():
                if path.is_dir() and NUMERIC_TIME_RE.fullmatch(path.name):
                    times.append((float(path.name), path.name))
        names = [name for _, name in sorted(times)]
        tail = names[-12:]
        return (
            f"latest_numeric_time={latest or 'NONE'}\n"
            f"numeric_time_count={len(names)}\n"
            f"last_times={', '.join(tail) if tail else 'NONE'}"
        )

    def geometry_inventory(self) -> str:
        lines = ["[STL/FEATURE INVENTORY — contents omitted]"]
        for path in sorted(self.binary_paths, key=lambda p: self.rel(p).lower()):
            try:
                stat = path.stat()
                line = f"{self.rel(path)}\tsize={stat.st_size}\tmtime={datetime.fromtimestamp(stat.st_mtime).isoformat()}"
                if self.hash_stl and path.suffix.lower() == ".stl":
                    digest = hashlib.sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    line += f"\tsha256={digest.hexdigest()}"
                lines.append(line)
            except OSError as exc:
                lines.append(f"{self.rel(path)}\tERROR={exc}")
        return "\n".join(lines)

    def write(self, latest: str | None, include_postprocessing: bool) -> Path:
        if include_postprocessing:
            for relative in POSTPROCESSING_SCRIPTS:
                self.add(relative, optional=True)

        self.output.parent.mkdir(parents=True, exist_ok=True)
        pieces = [
            "FormulaStudentCFD — COMPACT PROJECT BUNDLE",
            "=" * 88,
            f"generated={datetime.now().astimezone().isoformat()}",
            f"project_root={self.root}",
            "Default mode intentionally includes only active/canonical project files.",
            "Large fields are summarized; binary files are inventoried only.",
            "",
            "=" * 88,
            "ENVIRONMENT",
            "=" * 88,
            self.environment(),
            "\n" + "=" * 88,
            "TIME SUMMARY",
            "=" * 88,
            self.time_summary(latest),
            "\n" + "=" * 88,
            "STATIC CHECKS",
            "=" * 88,
            self.checks(),
            "\n" + "=" * 88,
            "BINARY/GEOMETRY INVENTORY",
            "=" * 88,
            self.geometry_inventory(),
            "\n" + "=" * 88,
            "SELECTED FILE CONTENTS",
            "=" * 88,
        ]
        for path in sorted(self.files, key=lambda p: self.rel(p).lower()):
            pieces.append(self.format_file(path, self.files[path]))

        pieces.extend([
            "\n" + "=" * 88,
            "MISSING CORE/OPTIONAL FILES",
            "=" * 88,
            "Core missing:\n" + ("\n".join(sorted(set(self.missing))) or "None"),
            "\nOptional missing:\n" + ("\n".join(sorted(set(self.optional_missing))) or "None"),
            "\nNotes:\n" + ("\n".join(self.notes) or "None"),
        ])
        self.output.write_text("\n".join(pieces).rstrip() + "\n", encoding="utf-8")
        return self.output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("results/project_bundle_important.txt"))
    parser.add_argument("--max-file-kb", type=int, default=350)
    parser.add_argument("--hash-stl", action="store_true")
    parser.add_argument(
        "--include-postprocessing",
        action="store_true",
        help="also include generate_slices_vtk.py and create_excel_v6.py",
    )
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    output = args.output.expanduser()
    if not output.is_absolute():
        output = root / output
    if not root.is_dir():
        print(f"ERROR: root does not exist: {root}", file=sys.stderr)
        return 2

    collector = CompactCollector(root, output, args.max_file_kb * 1024, args.hash_stl)
    collector.add_text_files()
    latest = collector.add_latest_time()
    collector.add_binary_inventory()
    result = collector.write(latest, args.include_postprocessing)
    print(f"Bundle written: {result}")
    print(f"Selected files: {len(collector.files)}")
    print(f"Binary inventory entries: {len(collector.binary_paths)}")
    print(f"Core/optional files missing: {len(set(collector.missing + collector.optional_missing))}")
    print(f"Output size: {result.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
