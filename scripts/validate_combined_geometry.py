#!/usr/bin/env python3

from pathlib import Path
import argparse
import json
import math

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]


def unit_scale(units):
    if str(units).lower() in (
        "mm",
        "millimeter",
        "millimetre",
    ):
        return 0.001

    return 1.0


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        required=True,
    )

    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
    )

    parser.add_argument(
        "--units",
        default="mm",
    )

    parser.add_argument(
        "--output",
        default="results/combined_geometry_report.json",
    )

    parser.add_argument(
        "--merge-tolerance-meters",
        type=float,
        default=1.0e-9,
    )

    parser.add_argument(
        "--strict",
        action="store_true",
    )

    args = parser.parse_args()

    input_dir = Path(args.input)
    scale = unit_scale(args.units)

    if args.merge_tolerance_meters <= 0.0:
        raise SystemExit(
            "--merge-tolerance-meters must be positive"
        )

    merge_tolerance_input_units = (
        args.merge_tolerance_meters / scale
    )

    merge_digits = max(
        0,
        int(
            math.ceil(
                -math.log10(
                    merge_tolerance_input_units
                )
            )
        ),
    )

    files = [
        path
        for path in sorted(input_dir.glob("*.stl"))
        if path.name not in args.exclude
    ]

    if not files:
        raise SystemExit(
            f"No STL files found in {input_dir}"
        )

    meshes = []
    parts = []

    for path in files:
        mesh = trimesh.load(
            path,
            force="mesh",
            process=False,
        )

        parts.append(
            {
                "file": path.name,
                "triangles": int(len(mesh.faces)),
                "watertight": bool(mesh.is_watertight),
                "windingConsistent": bool(
                    mesh.is_winding_consistent
                ),
            }
        )

        meshes.append(mesh)

    combined = trimesh.util.concatenate(meshes)

    # Keep the legacy mapping-compatible merge behavior.
    # The merge is performed in the input units.
    combined.merge_vertices(
        digits_vertex=merge_digits
    )

    faces = np.sort(
        np.asarray(combined.faces),
        axis=1,
    )

    _, face_counts = np.unique(
        faces,
        axis=0,
        return_counts=True,
    )

    edges = np.sort(
        np.asarray(combined.edges_sorted).reshape(-1, 2),
        axis=1,
    )

    _, edge_counts = np.unique(
        edges,
        axis=0,
        return_counts=True,
    )

    minimum, maximum = combined.bounds

    report = {
        "input": str(input_dir),
        "excluded": args.exclude,
        "unitsAssumed": args.units,
        "mergeBehavior": "unit_aware_digits_from_meters",
        "mergeToleranceMeters": float(
            args.merge_tolerance_meters
        ),
        "mergeToleranceInputUnits": float(
            merge_tolerance_input_units
        ),
        "mergeDigitsVertex": int(merge_digits),
        "partCount": len(parts),
        "parts": parts,
        "combinedTriangleCount": int(
            len(combined.faces)
        ),
        "combinedBoundsMeters": {
            "min": (minimum * scale).tolist(),
            "max": (maximum * scale).tolist(),
            "lengths": (
                (maximum - minimum) * scale
            ).tolist(),
        },
        "combinedWatertight": bool(
            combined.is_watertight
        ),
        "combinedWindingConsistent": bool(
            combined.is_winding_consistent
        ),
        "duplicateFaceKeys": int(
            np.sum(face_counts > 1)
        ),
        "boundaryEdges": int(
            np.sum(edge_counts == 1)
        ),
        "nonManifoldEdges": int(
            np.sum(edge_counts > 2)
        ),
    }

    output = ROOT / args.output
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2))
    print("Report:", output)


    if args.strict and (
        not report["combinedWatertight"]
        or not report["combinedWindingConsistent"]
        or report["duplicateFaceKeys"]
        or report["boundaryEdges"]
        or report["nonManifoldEdges"]
    ):
        raise SystemExit(
            "Strict combined geometry validation failed: "
            f"watertight={report['combinedWatertight']}, "
            f"winding={report['combinedWindingConsistent']}, "
            f"duplicateFaces={report['duplicateFaceKeys']}, "
            f"boundaryEdges={report['boundaryEdges']}, "
            f"nonManifoldEdges={report['nonManifoldEdges']}"
        )


if __name__ == "__main__":
    main()
