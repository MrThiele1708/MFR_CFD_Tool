#!/usr/bin/env python3
"""Report or remove near-coincident faces for configured STL contact pairs."""
from pathlib import Path
import shutil
import argparse
import csv
import json
import math

import numpy as np
import yaml
import trimesh
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]


def unit_scale(units):
    if str(units).lower() in ("mm", "millimeter", "millimetre"):
        return 0.001
    return 1.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "contactRepairPairs.yaml"),
    )
    parser.add_argument(
        "--mode",
        choices=["report", "apply"],
        default=None,
    )
    args = parser.parse_args()

    config = yaml.safe_load(
        Path(args.config).read_text(encoding="utf-8")
    )
    mode = args.mode or config.get("mode", "report")
    input_dir = ROOT / config["inputDirectory"]
    output_dir = ROOT / config["outputDirectory"]
    scale = unit_scale(config.get("units", "mm"))
    tolerance = float(
        config.get("distanceToleranceMeters", 0.0005)
    ) / scale
    angle = float(
        config.get("normalAngleToleranceDeg", 15.0)
    )
    cosine_limit = math.cos(math.radians(angle))
    pairs = config.get("contactPairs", [])

    if not pairs:
        raise SystemExit("No contactPairs configured.")

    part_names = sorted(
        {p["master"] for p in pairs}
        | {p["secondary"] for p in pairs}
    )

    meshes = {}
    for name in part_names:
        filename = input_dir / name
        if not filename.exists():
            raise SystemExit(f"Missing STL: {filename}")
        meshes[name] = trimesh.load(
            filename,
            force="mesh",
            process=False,
        )

    sample_trees = {}
    face_trees = {}
    for name, mesh in meshes.items():
        samples = np.vstack(
            [mesh.vertices, mesh.triangles_center]
        )
        sample_trees[name] = cKDTree(samples)
        face_trees[name] = cKDTree(mesh.triangles_center)

    remove_masks = {
        name: np.zeros(
            len(mesh.faces),
            dtype=bool,
        )
        for name, mesh in meshes.items()
    }

    report = {
        "mode": mode,
        "inputDirectory": str(input_dir),
        "outputDirectory": str(output_dir),
        "distanceToleranceMeters": float(
            config.get("distanceToleranceMeters", 0.0005)
        ),
        "normalAngleToleranceDeg": angle,
        "pairs": [],
    }

    for pair in pairs:
        master_name = pair["master"]
        secondary_name = pair["secondary"]
        master = meshes[master_name]
        secondary = meshes[secondary_name]
        centers = secondary.triangles_center
        normals = secondary.face_normals

        distances, _ = sample_trees[master_name].query(
            centers,
            k=1,
        )
        _, nearest_faces = face_trees[master_name].query(
            centers,
            k=1,
        )

        alignment = np.abs(
            np.einsum(
                "ij,ij->i",
                normals,
                master.face_normals[nearest_faces],
            )
        )

        candidates = (
            (distances <= tolerance)
            & (alignment >= cosine_limit)
        )
        remove_masks[secondary_name] |= candidates

        report["pairs"].append({
            "master": master_name,
            "secondary": secondary_name,
            "trianglesSecondary": int(
                len(secondary.faces)
            ),
            "candidateFaces": int(candidates.sum()),
            "candidateAreaInputUnits2": float(
                secondary.area_faces[candidates].sum()
            ),
            "minimumDistanceInputUnits": float(
                distances.min()
            ) if len(distances) else None,
        })

    if mode == "apply":
        output_dir.mkdir(parents=True, exist_ok=True)
        # Copy all unchanged STL files first.
        # Repaired pair files overwrite these later.
        for source_file in sorted(input_dir.glob("*.stl")):
            shutil.copy2(
                source_file,
                output_dir / source_file.name
            )

    report["parts"] = []
    for name, mesh in meshes.items():
        repaired = mesh
        if mode == "apply":
            if remove_masks[name].any():
                repaired = mesh.copy()
                repaired.update_faces(
                    ~remove_masks[name]
                )
                repaired.remove_unreferenced_vertices()
            repaired.export(output_dir / name)

        report["parts"].append({
            "file": name,
            "trianglesBefore": int(len(mesh.faces)),
            "candidateFaces": int(remove_masks[name].sum()),
            "trianglesAfter": int(len(repaired.faces)),
        })

    report_json = ROOT / "results" / "contact_surface_pairs_report.json"
    report_csv = ROOT / "results" / "contact_surface_pairs.csv"
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    fields = [
        "master",
        "secondary",
        "trianglesSecondary",
        "candidateFaces",
        "candidateAreaInputUnits2",
        "minimumDistanceInputUnits",
    ]
    with report_csv.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report["pairs"])

    print(json.dumps(report, indent=2))
    print("JSON report:", report_json)
    print("CSV report:", report_csv)
    if mode == "apply":
        print("Repaired files:", output_dir)


if __name__ == "__main__":
    main()
