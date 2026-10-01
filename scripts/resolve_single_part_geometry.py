#!/usr/bin/env python3
"""Resolve the active STL filename for the Single-Part workflow.

If the manifest's current singlePart filename exists, it is retained. If it
is missing and the single_part geometry directory contains exactly one STL,
the manifest is updated automatically. Production configurations are left
unchanged.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shutil

import yaml

ROOT=Path(__file__).resolve().parents[1]
CONFIG=Path(
 os.environ.get(
 "CFD_CONFIG",
 str(ROOT/"config/parameters.yaml"),
 )
)

config=yaml.safe_load(
 CONFIG.read_text(encoding="utf-8")
)

project=config.get("project",{}) or {}
geometry=config.get("geometry",{}) or {}
case_name=str(project.get("case",""))
profile=str(geometry.get("profile",""))

# No-op for the Production/Assembly workflow.
if case_name != "case_single_part" and profile != "single_part":
 print("Single-Part geometry resolver skipped.")
 raise SystemExit(0)

manifest_value=geometry.get(
 "manifest",
 "config/geometryManifest_single_part.yaml",
)
manifest_path=Path(manifest_value)
if not manifest_path.is_absolute():
 manifest_path=ROOT/manifest_path
manifest_path=manifest_path.resolve()

source_dir=ROOT/"geometry"/profile
if not source_dir.is_dir():
 raise SystemExit(
 f"Single-Part geometry directory missing: {source_dir}"
 )

manifest=yaml.safe_load(
 manifest_path.read_text(encoding="utf-8")
)
parts=manifest.get("parts",{}) or {}
if "singlePart" not in parts:
 raise SystemExit(
 f"Manifest has no singlePart entry: {manifest_path}"
 )

current_name=str(
 parts["singlePart"].get("file","")
)
current_path=source_dir/current_name

if current_name and current_path.is_file():
 print("Single-Part STL already selected:", current_path)
 raise SystemExit(0)

stls=sorted(
 path
 for path in source_dir.iterdir()
 if (
 path.is_file()
 and path.suffix.lower()==".stl"
 and not path.name.endswith(".repaired.tmp.stl")
 )
)

if len(stls)==0:
 raise SystemExit(
 f"No STL found in Single-Part geometry directory: {source_dir}"
 )

if len(stls)>1:
 names=", ".join(path.name for path in stls)
 raise SystemExit(
 "More than one STL found in Single-Part geometry directory; "
 "automatic selection is ambiguous: "
 + names
 )

selected=stls[0]

results_value=project.get("results","results_single_part")
results_dir=Path(results_value)
if not results_dir.is_absolute():
 results_dir=ROOT/results_dir
results_dir.mkdir(parents=True,exist_ok=True)

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=results_dir/(
 f"geometryManifest_single_part.before_auto_select_{stamp}.yaml"
)
shutil.copy2(manifest_path,backup)

parts["singlePart"]["file"]=selected.name
manifest["parts"]=parts
manifest_path.write_text(
 yaml.safe_dump(manifest,sort_keys=False),
 encoding="utf-8",
)

print("Auto-selected Single-Part STL:", selected)
print("Updated manifest:", manifest_path)
print("Manifest backup:", backup)
