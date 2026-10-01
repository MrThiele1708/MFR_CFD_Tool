#!/usr/bin/env python3
"""Collect the relevant FormulaStudentCFD project files into one text bundle.

Run from the project root, for example:

    python3 scripts/collect_project_bundle.py

The collector intentionally does not copy the binary contents of STL, VTK,
PNG, XLSX, or other binary files. It records their inventory instead. Large
OpenFOAM field files are represented by their header and boundaryField block,
which is normally the useful part for patch/restart diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


TEXT_SUFFIXES = {
    ".py", ".sh", ".yaml", ".yml", ".json", ".txt", ".md", ".csv",
    ".dat", ".log", ".dict", ".foam", ".xml", ".cfg", ".ini",
}
BINARY_SUFFIXES = {
    ".stl", ".vtk", ".vtp", ".vtu", ".png", ".jpg", ".jpeg", ".gif",
    ".xlsx", ".xls", ".pdf", ".zip", ".gz", ".tar", ".7z", ".npy",
}
FIELD_NAMES = (
    "U", "p", "k", "omega", "nut", "epsilon", "alphat", "nuTilda",
    "nuSgs", "T", "p_rgh",
)
NUMERIC_TIME_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


class Collector:
    def __init__(self, root: Path, output: Path, max_bytes: int, hash_stl: bool):
        self.root = root.resolve()
        self.output = output.resolve()
        self.max_bytes = max_bytes
        self.hash_stl = hash_stl
        self.selected: set[Path] = set()
        self.missing: list[str] = []
        self.binary_inventory: list[Path] = []
        self.notes: list[str] = []

    def rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root))
        except ValueError:
            return str(path)

    def add_exact(self, relative: str) -> None:
        path = self.root / relative
        if path.is_file():
            self.selected.add(path.resolve())
        else:
            self.missing.append(relative)

    def add_glob(self, relative_dir: str, patterns: Iterable[str], recursive: bool = False) -> None:
        base = self.root / relative_dir
        if not base.exists():
            return
        paths: list[Path] = []
        for pattern in patterns:
            paths.extend(base.rglob(pattern) if recursive else base.glob(pattern))
        for path in paths:
            if not path.is_file():
                continue
            if self.output == path.resolve():
                continue
            if any(part in {"__pycache__", ".venv", "node_modules"} for part in path.parts):
                continue
            if "scripts/archive" in self.rel(path):
                continue
            self.selected.add(path.resolve())

    def add_binary_inventory(self, relative_dir: str) -> None:
        base = self.root / relative_dir
        if not base.exists():
            return
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix.lower() in BINARY_SUFFIXES:
                self.binary_inventory.append(path.resolve())

    def add_known_files(self) -> None:
        self.add_glob("config", ("*.yaml", "*.yml", "*.json", "*.txt", "*.md"))
        self.add_glob("scripts", tuple(f"*{suffix}" for suffix in sorted(TEXT_SUFFIXES)), recursive=True)
        self.add_glob("case/system", ("*",))
        self.add_exact("case/constant/geometryMetrics.json")
        self.add_exact("case/constant/polyMesh/boundary")
        for name in ("faceZones", "cellZones", "pointZones"):
            self.add_exact(f"case/constant/polyMesh/{name}")
        self.add_glob("case/constant/triSurface", ("*.eMesh", "*.obj", "*.ftr"))
        self.add_glob("case/constant/extendedFeatureEdgeMesh", ("*",), recursive=True)

        for time_name in ("0", "0.orig"):
            for field in FIELD_NAMES:
                self.add_exact(f"case/{time_name}/{field}")
            self.add_glob(f"case/{time_name}", ("*.orig",))

        self.add_glob("case", ("log.*",))
        self.add_glob("case/postProcessing", ("*.dat", "*.csv", "*.log"), recursive=True)
        self.add_glob(
            "results",
            ("*.txt", "*.json", "*.csv", "*.log", "*.md", "*.yaml", "*.yml"),
            recursive=True,
        )

        self.add_binary_inventory("geometry")
        self.add_binary_inventory("case")
        self.add_binary_inventory("results")

        for relative in (
            "results/assembly_mapping_fast_report.json",
            "results/assembly_mapping_fast_summary.csv",
            "results/mapped_combined_report_v2.json",
            "results/production_geometry_report.json",
            "results/FormulaStudent_results.xlsx",
        ):
            path = self.root / relative
            if path.suffix.lower() in BINARY_SUFFIXES:
                if path.is_file() and path.resolve() not in self.binary_inventory:
                    self.binary_inventory.append(path.resolve())
            else:
                self.add_exact(relative)

    def add_latest_time_fields(self) -> str | None:
        case = self.root / "case"
        if not case.is_dir():
            self.notes.append("case/ does not exist; latest time could not be detected.")
            return None
        candidates: list[tuple[float, Path]] = []
        for path in case.iterdir():
            if path.is_dir() and NUMERIC_TIME_RE.fullmatch(path.name):
                try:
                    candidates.append((float(path.name), path))
                except ValueError:
                    pass
        if not candidates:
            self.notes.append("No numeric case time directory was found.")
            return None
        latest = max(candidates, key=lambda item: item[0])[1]
        for field in FIELD_NAMES:
            path = latest / field
            if path.is_file():
                self.selected.add(path.resolve())
            else:
                self.missing.append(self.rel(path))
        self.add_exact("case/latestTime.txt")
        return latest.name

    def collect_environment(self) -> str:
        commands = [
            "foamVersion",
            "python3 --version",
            "command -v python3 || true",
            "command -v blockMesh || true",
            "command -v snappyHexMesh || true",
            "command -v checkMesh || true",
            "free -h",
            "nproc",
            "git status --short 2>/dev/null || true",
            "git log --oneline -5 2>/dev/null || true",
        ]
        chunks: list[str] = []
        for command in commands:
            try:
                result = subprocess.run(
                    ["bash", "-lc", command],
                    cwd=self.root,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                    check=False,
                )
                output = result.stdout.strip()
                chunks.append(f"$ {command}\n{output}\n[exit={result.returncode}]")
            except Exception as exc:
                chunks.append(f"$ {command}\nERROR: {exc}")
        return "\n\n".join(chunks)

    def run_static_checks(self) -> str:
        checks: list[str] = []
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
            checks.append(f"bash -n scripts/run_case.sh: exit={result.returncode}\n{result.stdout.strip()}")
        else:
            checks.append("bash -n scripts/run_case.sh: file missing")

        for path in sorted((self.root / "scripts").glob("*.py")) if (self.root / "scripts").is_dir() else []:
            if "archive" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                compile(path.read_text(encoding="utf-8", errors="replace"), str(path), "exec")
                checks.append(f"compile {self.rel(path)}: OK")
            except Exception as exc:
                checks.append(f"compile {self.rel(path)}: FAILED: {exc}")
        return "\n".join(checks)

    @staticmethod
    def extract_balanced(text: str, key: str) -> str | None:
        match = re.search(r"(?m)^[ \t]*" + re.escape(key) + r"[ \t]*\{", text)
        if not match:
            match = re.search(r"\b" + re.escape(key) + r"\s*\{", text)
        if not match:
            return None
        opening = text.find("{", match.start(), match.end())
        if opening < 0:
            return None
        depth = 0
        i = opening
        state = "normal"
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
                    i += 1
                    continue
                if ch == "{":
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
    def field_boundary_excerpt(cls, text: str) -> str | None:
        return cls.extract_balanced(text, "boundaryField")

    @staticmethod
    def read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")

    def format_file(self, path: Path) -> str:
        relative = self.rel(path)
        size = path.stat().st_size
        header = (
            f"\n{'=' * 100}\n"
            f"FILE: {relative}\n"
            f"SIZE_BYTES: {size}\n"
            f"{'=' * 100}\n"
        )
        try:
            text = self.read_text(path)
        except Exception as exc:
            return header + f"[READ ERROR: {exc}]\n"

        is_field = path.name in FIELD_NAMES and path.parent.name not in {"system", "constant"}
        if len(text.encode("utf-8", errors="replace")) <= self.max_bytes:
            return header + text.rstrip() + "\n"

        if is_field:
            boundary = self.field_boundary_excerpt(text)
            prefix = text[:12000]
            body = [
                "[LARGE FIELD FILE: internalField omitted from bundle]",
                f"[Original UTF-8 byte length: {len(text.encode('utf-8', errors='replace'))}]",
                "\n--- HEADER/PREFIX ---\n",
                prefix.rstrip(),
            ]
            if boundary:
                body.extend(["\n--- COMPLETE boundaryField EXCERPT ---\n", boundary.rstrip()])
            else:
                body.append("\n--- boundaryField EXCERPT NOT FOUND ---\n")
            return header + "\n".join(body) + "\n"

        head_chars = 60000
        tail_chars = 60000
        body = (
            "[LARGE TEXT FILE: truncated]\n"
            f"[Original UTF-8 byte length: {len(text.encode('utf-8', errors='replace'))}]\n\n"
            "--- BEGINNING ---\n"
            + text[:head_chars].rstrip()
            + "\n\n--- MIDDLE OMITTED ---\n\n"
            + text[-tail_chars:].lstrip()
            + "\n--- END ---\n"
        )
        return header + body

    def format_binary_inventory(self) -> str:
        unique = sorted(set(self.binary_inventory))
        lines = [
            "\n" + "=" * 100,
            "BINARY FILE INVENTORY (contents intentionally not embedded)",
            "=" * 100,
        ]
        for path in unique:
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
            except Exception as exc:
                lines.append(f"{self.rel(path)}\tERROR: {exc}")
        if len(lines) == 3:
            lines.append("No binary files found.")
        return "\n".join(lines) + "\n"

    def format_file_inventory(self) -> str:
        lines = [
            "\n" + "=" * 100,
            "PROJECT FILE INVENTORY",
            "=" * 100,
        ]
        ignored_parts = {".venv", "__pycache__", ".git", "node_modules"}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or self.output == path.resolve():
                continue
            if any(part in ignored_parts for part in path.parts):
                continue
            try:
                lines.append(f"{self.rel(path)}\tsize={path.stat().st_size}")
            except OSError:
                pass
        return "\n".join(lines) + "\n"

    def format_time_inventory(self, latest: str | None) -> str:
        case = self.root / "case"
        lines = [
            "\n" + "=" * 100,
            "OPENFOAM TIME DIRECTORY INVENTORY",
            "=" * 100,
            f"latest_numeric_time={latest or 'NONE'}",
        ]
        if case.is_dir():
            times = []
            for path in case.iterdir():
                if path.is_dir() and NUMERIC_TIME_RE.fullmatch(path.name):
                    times.append((float(path.name), path.name))
            for _, name in sorted(times):
                lines.append(name)
        else:
            lines.append("case/ missing")
        return "\n".join(lines) + "\n"

    def format_restart_check(self, latest: str | None) -> str:
        lines = [
            "\n" + "=" * 100,
            "RESTART/PATCH COMPATIBILITY QUICK CHECK",
            "=" * 100,
        ]
        boundary_path = self.root / "case/constant/polyMesh/boundary"
        mesh_text = self.read_text(boundary_path) if boundary_path.is_file() else ""
        mesh_patches = set(re.findall(r"(?m)^[ \t]*([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*(?:\n[ \t]*)?\{", mesh_text))
        lines.append(f"mesh_boundary_file={self.rel(boundary_path) if boundary_path.exists() else 'MISSING'}")
        lines.append(f"mesh_patch_count_detected={len(mesh_patches)}")
        if latest:
            latest_dir = self.root / "case" / latest
            for field in FIELD_NAMES:
                path = latest_dir / field
                if not path.is_file():
                    lines.append(f"{field}: MISSING")
                    continue
                text = self.read_text(path)
                block = self.field_boundary_excerpt(text)
                if block is None:
                    lines.append(f"{field}: boundaryField NOT FOUND")
                    continue
                field_patches = set(re.findall(r"(?m)^[ \t]*([A-Za-z_][A-Za-z0-9_.-]*)[ \t]*(?:\n[ \t]*)?\{", block))
                missing = sorted(mesh_patches - field_patches)
                extra = sorted(field_patches - mesh_patches)
                lines.append(
                    f"{field}: patches={len(field_patches)} missing_from_field={missing or '-'} extra_in_field={extra or '-'}"
                )
        else:
            lines.append("No latest numeric time available; restart fields were not checked.")
        return "\n".join(lines) + "\n"

    def write(self, latest: str | None) -> Path:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        generated = datetime.now(timezone.utc).astimezone().isoformat()
        lines = [
            "FormulaStudentCFD PROJECT BUNDLE",
            "=" * 100,
            f"generated={generated}",
            f"project_root={self.root}",
            "This file was generated automatically. Missing files are listed explicitly.",
            "Binary files (STL/VTK/PNG/XLSX/etc.) are inventoried but not embedded.",
            "Large OpenFOAM fields contain a structural excerpt rather than the full internalField.",
            "",
            "=" * 100,
            "ENVIRONMENT",
            "=" * 100,
            self.collect_environment(),
            self.format_time_inventory(latest),
            self.format_restart_check(latest),
            "\n" + "=" * 100,
            "STATIC CHECKS",
            "=" * 100,
            self.run_static_checks(),
            self.format_file_inventory(),
            self.format_binary_inventory(),
        ]

        if self.notes:
            lines.extend(["\n" + "=" * 100, "NOTES", "=" * 100, "\n".join(self.notes)])

        lines.extend(["\n" + "=" * 100, "SELECTED TEXT FILE CONTENTS", "=" * 100])
        for path in sorted(self.selected, key=lambda p: self.rel(p).lower()):
            lines.append(self.format_file(path))

        lines.extend(["\n" + "=" * 100, "MISSING EXPLICIT FILES", "=" * 100])
        missing = sorted(set(self.missing))
        lines.append("\n".join(missing) if missing else "None of the explicitly requested files is missing.")

        self.output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return self.output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="FormulaStudentCFD project root (default: current directory)")
    parser.add_argument("--output", type=Path, default=Path("results/project_bundle.txt"), help="Output text file")
    parser.add_argument("--max-file-mb", type=float, default=5.0, help="Maximum size for untruncated text files")
    parser.add_argument("--hash-stl", action="store_true", help="Add SHA-256 hashes for STL inventory entries")
    parser.add_argument("--extra", action="append", default=[], help="Additional relative file to include; may be repeated")
    args = parser.parse_args()

    root = args.root.expanduser().resolve()
    output = args.output.expanduser()
    if not output.is_absolute():
        output = root / output
    if not root.is_dir():
        print(f"ERROR: project root does not exist: {root}", file=sys.stderr)
        return 2

    collector = Collector(root, output, max(1, int(args.max_file_mb * 1024 * 1024)), args.hash_stl)
    collector.add_known_files()
    for extra in args.extra:
        collector.add_exact(extra)
    latest = collector.add_latest_time_fields()
    result = collector.write(latest)

    print(f"Bundle written: {result}")
    print(f"Selected text files: {len(collector.selected)}")
    print(f"Binary inventory entries: {len(set(collector.binary_inventory))}")
    print(f"Missing explicit files: {len(set(collector.missing))}")
    if latest:
        print(f"Latest numeric time: {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
