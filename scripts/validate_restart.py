#!/usr/bin/env python3
import os
"""Validate an OpenFOAM restart time against the current mesh."""

from pathlib import Path
import argparse
import re
import subprocess
import sys
from restart_utils import latest_complete_time, is_complete

ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))
FIELDS = ("U", "p", "k", "omega", "nut")

KEY_RE = re.compile(
    r'\s*("([^"]+)"|([A-Za-z_][A-Za-z0-9_.-]*))\s*\{'
)


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def brace_keys(text, open_pos):
    """Return top-level dictionary keys inside a {...} block."""
    keys = []
    depth = 1
    i = open_pos + 1

    while i < len(text):
        if depth == 1:
            match = KEY_RE.match(text, i)
            if match:
                key = match.group(2) or match.group(3)
                keys.append(key)
                i = match.end()
                depth += 1
                continue

        char = text[i]

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break

        i += 1

    return keys


def paren_keys(text, open_pos):
    """Return patch names from the top-level (...) boundary list."""
    keys = []
    paren_depth = 1
    i = open_pos + 1

    while i < len(text):
        if paren_depth == 1:
            match = KEY_RE.match(text, i)
            if match:
                key = match.group(2) or match.group(3)
                keys.append(key)

                # Skip the complete patch dictionary.
                i = match.end()
                brace_depth = 1

                while i < len(text) and brace_depth:
                    if text[i] == "{":
                        brace_depth += 1
                    elif text[i] == "}":
                        brace_depth -= 1
                    i += 1

                continue

        char = text[i]

        if char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break

        i += 1

    return keys


def mesh_patch_names():
    path = CASE / "constant/polyMesh/boundary"

    if not path.exists():
        raise RuntimeError(f"Missing mesh boundary file: {path}")

    text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))

    # The boundary file contains an integer followed by the patch list.
    match = re.search(r"(?m)^\s*[0-9]+\s*\(", text)
    if not match:
        raise RuntimeError("Could not locate the mesh boundary patch list.")

    open_pos = text.find("(", match.start(), match.end())
    return paren_keys(text, open_pos)


def field_patch_names(path):
    text = strip_comments(
        path.read_text(encoding="utf-8", errors="replace")
    )

    match = re.search(r"\bboundaryField\s*\{", text)
    if not match:
        return []

    open_pos = text.find("{", match.start(), match.end())
    return brace_keys(text, open_pos)


def foam_dictionary(path, entry, capture=False):
    command = [
        "foamDictionary",
        str(path),
        "-entry",
        entry,
        "-value",
    ]

    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except FileNotFoundError:
        return False, "foamDictionary not found"
    except subprocess.TimeoutExpired:
        return False, "foamDictionary timeout"

    output = ""
    if capture:
        output = result.stdout.strip()

    if result.returncode == 0:
        return True, output

    error_lines = [
        line.strip()
        for line in result.stderr.splitlines()
        if line.strip()
    ]
    detail = " | ".join(error_lines[-3:])
    return False, detail or "foamDictionary failed"


def numeric_time_directories():
    result = []

    for path in CASE.iterdir():
        if not path.is_dir():
            continue

        try:
            value = float(path.name)
        except ValueError:
            continue

        result.append((value, path))

    return sorted(result, key=lambda item: item[0])


def choose_target(requested):
    if requested:
        target = CASE / requested

        if not target.is_dir():
            raise RuntimeError(
                f"Requested time directory missing: {target}"
            )

        if not is_complete(target):
            raise RuntimeError(
                f"Requested time is incomplete: {target.name}"
            )

        return target

    return latest_complete_time(CASE)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--time",
        help="Explicit solver time, for example 1400",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Validate the highest numeric time directory",
    )
    args = parser.parse_args()

    target = choose_target(args.time)
    errors = []

    print("=== Restart validation ===")
    print("Case:", CASE)
    print("Target time:", target.name)

    try:
        mesh_patches = mesh_patch_names()
    except Exception as exc:
        print("MESH PATCHES: FAIL:", exc)
        return 1

    mesh_patch_set = set(mesh_patches)

    print("Mesh patches:", len(mesh_patches))
    print("Mesh patch names:", " ".join(mesh_patches))

    if not mesh_patches:
        errors.append("No mesh patches found.")

    control = CASE / "system/controlDict"
    print()
    print("=== controlDict readability ===")

    for entry in (
        "application",
        "startFrom",
        "stopAt",
        "endTime",
        "writeInterval",
    ):
        ok, value = foam_dictionary(control, entry, capture=True)

        if ok:
            print(f"{entry}: {value}")
        else:
            print(f"{entry}: FAIL: {value}")
            errors.append(f"controlDict entry unreadable: {entry}")

    print()
    print("=== Field validation ===")

    for field in FIELDS:
        path = target / field

        if not path.exists():
            print(f"{field}: MISSING")
            errors.append(f"Missing field: {path}")
            continue

        whole_ok, detail = foam_dictionary(
            path,
            "boundaryField",
            capture=False,
        )

        parsed_patches = set(field_patch_names(path))
        missing = sorted(mesh_patch_set - parsed_patches)
        extra = sorted(parsed_patches - mesh_patch_set)

        invalid_entries = []

        for patch in mesh_patches:
            ok, message = foam_dictionary(
                path,
                f"boundaryField/{patch}",
                capture=False,
            )

            if not ok:
                invalid_entries.append(f"{patch}: {message}")

        status = "OK" if whole_ok and not missing and not extra and not invalid_entries else "FAIL"

        print(f"{field}: {status}")
        print(f"  file: {path}")
        print(f"  parsed boundary patches: {len(parsed_patches)}")

        if missing:
            print("  missing patches:", " ".join(missing))
            errors.append(f"{field}: missing patches: {', '.join(missing)}")

        if extra:
            print("  extra patches:", " ".join(extra))
            errors.append(f"{field}: extra patches: {', '.join(extra)}")

        if not whole_ok:
            print("  boundaryField dictionary:", detail)
            errors.append(f"{field}: boundaryField dictionary unreadable")

        if invalid_entries:
            print("  invalid patch entries:")
            for item in invalid_entries:
                print("   ", item)
            errors.append(f"{field}: invalid patch entries")

    print()
    if errors:
        print("RESTART VALIDATION FAILED")
        for error in errors:
            print(" -", error)
        return 1

    print("RESTART VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
