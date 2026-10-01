#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PARAM = Path(
    os.environ.get(
        "CFD_CONFIG",
        str(ROOT / "config/parameters.yaml"),
    )
)
MAPCFG = ROOT / "config/assemblyMappingFast.yaml"
FAST = ROOT / "scripts/map_assembly_regions_fast.py"
POINT = ROOT / "scripts/map_assembly_regions_position_only.py"
VALIDATOR = ROOT / "scripts/validate_combined_geometry.py"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main():
    config = yaml.safe_load(
        PARAM.read_text(encoding="utf-8")
    )
    geometry = config.get("geometry", {}) or {}
    mapping = geometry.get("assemblyMapping", {}) or {}

    if not bool(mapping.get("enabled", False)):
        print("Automatic assembly mapping disabled.")
        return

    source = mapping.get("sourceProfile", "production")
    output = mapping.get(
        "outputProfile",
        "production_mapped",
    )
    method = str(
        mapping.get("method", "positionOnly")
    )

    source_dir = ROOT / "geometry" / source
    output_dir = ROOT / "geometry" / output

    mapcfg = yaml.safe_load(
        MAPCFG.read_text(encoding="utf-8")
    )
    mapcfg["inputDirectory"] = f"geometry/{source}"
    mapcfg["outputDirectory"] = f"geometry/{output}"
    mapcfg["mode"] = "report"
    MAPCFG.write_text(
        yaml.safe_dump(mapcfg, sort_keys=False),
        encoding="utf-8",
    )

    input_files = [
        source_dir / mapcfg["assemblyFile"]
    ]
    input_files.extend(
        source_dir / name
        for name in mapcfg.get("parts", [])
    )
    missing = [
        str(path)
        for path in input_files
        if not path.exists()
    ]
    if missing:
        raise SystemExit(
            "Missing mapping files: "
            + ", ".join(missing)
        )

    signature = hashlib.sha256(
        "".join(
            f"{path.name}:{sha(path)}\n"
            for path in sorted(input_files)
        ).encode()
    ).hexdigest()

    results_dir = Path(
        os.environ.get(
            "CFD_RESULTS",
            str(ROOT / "results"),
        )
    )
    results_dir.mkdir(parents=True, exist_ok=True)

    cache = results_dir / (
        "assembly_mapping_signature.json"
    )
    cached = None
    if cache.exists():
        try:
            cached = json.loads(
                cache.read_text(encoding="utf-8")
            )
        except Exception:
            cached = None

    force = bool(mapping.get("force", False))
    current = (
        cached is not None
        and cached.get("signature") == signature
        and cached.get("method") == method
        and output_dir.exists()
        and not force
    )

    if not current:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if method.lower() in (
            "positiononly",
            "position-only",
            "surfacepoints",
        ):
            subprocess.run(
                [
                    sys.executable,
                    str(POINT),
                    "--config",
                    str(MAPCFG),
                    "--mode",
                    "apply",
                    "--output-directory",
                    f"geometry/{output}",
                    "--spacing",
                    str(mapping.get("pointSpacing", 2.0)),
                    "--max-points-per-part",
                    str(mapping.get("maxPointsPerPart", 200000)),
                    "--chunk-faces",
                    str(mapping.get("chunkFaces", 50000)),
                ],
                cwd=ROOT,
                check=True,
            )

            position_report = json.loads(
                (
                    results_dir
                    / "assembly_mapping_position_only_report.json"
                ).read_text(encoding="utf-8")
            )
            ambiguous_limit = int(
                mapping.get("maxAmbiguousFaces", 3)
            )
            ambiguous = int(
                position_report.get("ambiguousFaces", 0)
            )
            if ambiguous > ambiguous_limit:
                raise SystemExit(
                    "Position-only mapping ambiguous-face "
                    f"limit exceeded: {ambiguous} > "
                    f"{ambiguous_limit}"
                )
        else:
            subprocess.run(
                [
                    sys.executable,
                    str(FAST),
                    "--mode",
                    "report",
                ],
                cwd=ROOT,
                check=True,
            )
            report = json.loads(
                (
                    results_dir
                    / "assembly_mapping_fast_report.json"
                ).read_text(encoding="utf-8")
            )
            if int(report.get("unassignedFaces", 0)) > 0:
                raise SystemExit(
                    "Fast mapping has unassigned faces"
                )
            subprocess.run(
                [
                    sys.executable,
                    str(FAST),
                    "--mode",
                    "apply",
                ],
                cwd=ROOT,
                check=True,
            )

        radiator = config.get("radiator", {}) or {}
        radiator_parts = radiator.get(
            "parts",
            {
                "radiatorLeft": "radiator_left_volume.stl",
                "radiatorRight": "radiator_right_volume.stl",
            },
        )
        if bool(radiator.get("enabled", False)):
            for filename in radiator_parts.values():
                source_path = source_dir / filename
                if source_path.exists():
                    shutil.copy2(
                        source_path,
                        output_dir / filename,
                    )

        validation = (
            results_dir
            / "assembly_mapping_combined_check.json"
        )
        subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--input",
                str(output_dir),
                "--units",
                str(mapcfg.get("units", "mm")),
                "--exclude",
                "assembly.stl",
                "radiator_left_volume.stl",
                "radiator_right_volume.stl",
                "--output",
                str(validation),
                "--strict",
            ],
            cwd=ROOT,
            check=True,
        )

        cache.write_text(
            json.dumps(
                {
                    "signature": signature,
                    "sourceProfile": source,
                    "outputProfile": output,
                    "method": method,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    geometry["profile"] = output
    geometry["inputUnits"] = mapcfg.get(
        "units",
        "mm",
    )
    config["geometry"] = geometry
    PARAM.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    print("Active geometry profile:", output)
    print("Mapping method:", method)


if __name__ == "__main__":
    main()
