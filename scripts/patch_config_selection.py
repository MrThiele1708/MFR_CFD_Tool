#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path(__file__).resolve().parents[1]

files = [
    "auto_map_geometry.py",
    "apply_feature_settings.py",
    "apply_operating_conditions.py",
    "apply_solver_control.py",
    "apply_wheel_rotation.py",
    "apply_contact_aware_morph.py",
    "generate_case_files.py",
    "generate_control.py",
    "generate_radiator_sources.py",
    "generate_snappy_v13.py",
    "generate_surface_features.py",
    "generate_turbulence_fields.py",
    "enable_layers.py",
    "prepare_case.py",
    "write_effective.py",
    "validate_restart.py",
    "select_restart_time.py",
    "archive_incomplete_times.py",
    "clear_numeric_times.py",
    "create_mapped_restart_source.py",
    "promote_mapped_time.py",
    "create_map_fields_dict.py",
]

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_root = (
    ROOT
    / "results"
    / "config_selection_backups"
    / stamp
)

backup_root.mkdir(parents=True, exist_ok=True)

replacements = {
    'ROOT / "config/parameters.yaml"':
        'Path(os.environ.get("CFD_CONFIG", '
        'str(ROOT / "config/parameters.yaml")))',

    "ROOT / 'config/parameters.yaml'":
        'Path(os.environ.get("CFD_CONFIG", '
        'str(ROOT / "config/parameters.yaml")))',

    "ROOT/'config/parameters.yaml'":
        'Path(os.environ.get("CFD_CONFIG", '
        'str(ROOT / "config/parameters.yaml")))',

    "r/'config/parameters.yaml'":
        'Path(os.environ.get("CFD_CONFIG", '
        'str(r / "config/parameters.yaml")))',

    'ROOT / "config/geometryManifest.yaml"':
        'Path(os.environ.get("CFD_MANIFEST", '
        'str(ROOT / "config/geometryManifest.yaml")))',

    "ROOT / 'config/geometryManifest.yaml'":
        'Path(os.environ.get("CFD_MANIFEST", '
        'str(ROOT / "config/geometryManifest.yaml")))',

    "ROOT/'config/geometryManifest.yaml'":
        'Path(os.environ.get("CFD_MANIFEST", '
        'str(ROOT / "config/geometryManifest.yaml")))',

    "r/'config/geometryManifest.yaml'":
        'Path(os.environ.get("CFD_MANIFEST", '
        'str(r / "config/geometryManifest.yaml")))',

    'ROOT / "case"':
        'Path(os.environ.get("CFD_CASE", '
        'str(ROOT / "case")))',

    "ROOT / 'case'":
        'Path(os.environ.get("CFD_CASE", '
        "str(ROOT / 'case')))",

    "ROOT/'case'":
        'Path(os.environ.get("CFD_CASE", '
        "str(ROOT / 'case')))",

    "r/'case'":
        'Path(os.environ.get("CFD_CASE", '
        "str(r / 'case')))",

    'ROOT / "results"':
        'Path(os.environ.get("CFD_RESULTS", '
        'str(ROOT / "results")))',

    "ROOT / 'results'":
        'Path(os.environ.get("CFD_RESULTS", '
        "str(ROOT / 'results')))",

    "ROOT/'results'": 'Path(os.environ.get("CFD_RESULTS", str(ROOT / "results")))',
}

changed = []
skipped = []

for filename in files:
    path = ROOT / "scripts" / filename

    if not path.exists():
        skipped.append(f"{filename}: missing")
        continue

    original = path.read_text(encoding="utf-8")
    text = original

    # Ensure os is available for environment-based paths.
    if "import os" not in text:
        if text.startswith("#!"):
            first_newline = text.find("\n")
            text = (
                text[:first_newline + 1]
                + "import os\n"
                + text[first_newline + 1:]
            )
        else:
            text = "import os\n" + text

    for old, new in replacements.items():
        text = text.replace(old, new)

    if text != original:
        backup = backup_root / filename
        shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8")
        changed.append(filename)
    else:
        skipped.append(f"{filename}: no matching path expression")

print("Backup directory:", backup_root)
print()
print("Changed files:")
for filename in changed:
    print("  ", filename)

print()
print("Skipped or unchanged files:")
for item in skipped:
    print("  ", item)
