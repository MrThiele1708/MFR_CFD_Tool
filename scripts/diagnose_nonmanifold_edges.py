#!/usr/bin/env python3

from pathlib import Path
import argparse
import json

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
        "--units",
        default="mm",
    )

    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[
            "assembly.stl",
            "radiator_left_volume.stl",
            "radiator_right_volume.stl",
        ],
    )

    parser.add_argument(
        "--output",
        default="results/nonmanifold_edge_diagnosis.json",
    )

    args = parser.parse_args()

    input_dir = Path(args.input)
    scale = unit_scale(args.units)

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
    part_ranges = []
    face_start = 0

    for path in files:
        mesh = trimesh.load(
            path,
            force="mesh",
            process=False,
        )

        mesh.apply_scale(scale)

        meshes.append(mesh)

        face_end = face_start + len(mesh.faces)

        part_ranges.append(
            {
                "file": path.name,
                "firstFace": face_start,
                "lastFace": face_end - 1,
            }
        )

        face_start = face_end

    combined = trimesh.util.concatenate(meshes)
    combined.merge_vertices(digits_vertex=6)

    faces = np.asarray(combined.faces)

    face_edges = np.vstack(
        [
            faces[:, [0, 1]],
            faces[:, [1, 2]],
            faces[:, [2, 0]],
        ]
    )

    face_edges = np.sort(face_edges, axis=1)

    face_ids = np.repeat(
        np.arange(len(faces)),
        3,
    )

    unique_edges, inverse, edge_counts = np.unique(
        face_edges,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )

    def part_for_face(face_id):
        for item in part_ranges:
            if (
                item["firstFace"]
                <= face_id
                <= item["lastFace"]
            ):
                return item["file"]

        return "unknown"

    nonmanifold_groups = np.flatnonzero(
        edge_counts > 2
    )

    boundary_groups = np.flatnonzero(
        edge_counts == 1
    )

    nonmanifold = []

    for group_id in nonmanifold_groups:
        occurrence_ids = np.flatnonzero(
            inverse == group_id
        )

        face_list = sorted(
            set(
                int(face_ids[index])
                for index in occurrence_ids
            )
        )

        parts = sorted(
            set(
                part_for_face(face_id)
                for face_id in face_list
            )
        )

        edge = unique_edges[group_id]
        points = combined.vertices[edge]

        nonmanifold.append(
            {
                "edgeIndex": int(group_id),
                "occurrenceCount": int(
                    edge_counts[group_id]
                ),
                "vertexIndices": [
                    int(edge[0]),
                    int(edge[1]),
                ],
                "edgePointsMeters": points.tolist(),
                "faceIndices": face_list,
                "parts": parts,
            }
        )

    report = {
        "input": str(input_dir),
        "unitsAssumed": args.units,
        "mergeScaleToMeters": scale,
        "partCount": len(files),
        "combinedTriangleCount": int(len(faces)),
        "combinedWatertight": bool(
            combined.is_watertight
        ),
        "combinedWindingConsistent": bool(
            combined.is_winding_consistent
        ),
        "boundaryEdgeCount": int(
            len(boundary_groups)
        ),
        "nonManifoldEdgeCount": int(
            len(nonmanifold_groups)
        ),
        "parts": part_ranges,
        "nonManifoldEdges": nonmanifold,
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


if __name__ == "__main__":
    main()
