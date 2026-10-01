#!/usr/bin/env python3

from pathlib import Path
import shutil

from config_utils import load_config, case_dir

ROOT = Path(__file__).resolve().parents[1]
config = load_config()
case = case_dir(config)

source_constant = ROOT / "case/constant"
target_constant = case / "constant"

target_constant.mkdir(parents=True, exist_ok=True)

files = (
    "physicalProperties",
    "momentumTransport",
    "g",
)

for filename in files:
    source = source_constant / filename
    target = target_constant / filename

    if not source.is_file():
        raise SystemExit(
            f"Missing source physics file: {source}"
        )

    if source.resolve() == target.resolve():
        print("Already present:", target)
        continue

    shutil.copy2(source, target)
    print("Generated/copied:", target)
