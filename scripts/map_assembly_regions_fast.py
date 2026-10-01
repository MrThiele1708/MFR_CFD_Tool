
#!/usr/bin/env python3
"""Fast assembly-to-component surface mapping.

The assembly STL is the only source of output faces. Component STLs are used
only as reference geometries and automatic bounding volumes.
"""
from pathlib import Path
import argparse, csv, json, math, shutil
import numpy as np
import yaml
import trimesh
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]

def unit_scale(units):
    if str(units).lower() in ("mm", "millimeter", "millimetre"):
        return 0.001
    return 1.0

def box_overlap(a_min, a_max, b_min, b_max):
    return bool(np.all(a_max >= b_min) and np.all(b_max >= a_min))

def box_distance(point, bmin, bmax):
    delta = np.maximum(np.maximum(bmin - point, 0.0), point - bmax)
    return float(np.linalg.norm(delta))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config/assemblyMappingFast.yaml"))
    parser.add_argument("--mode", choices=["report", "apply"], default=None)
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    mode = args.mode or config.get("mode", "report")
    input_dir = ROOT / config["inputDirectory"]
    output_dir = ROOT / config["outputDirectory"]
    assembly_path = input_dir / config["assemblyFile"]
    scale = unit_scale(config.get("units", "mm"))
    margin = float(config.get("boundingBoxMarginMeters", 0.001)) / scale
    tolerance = float(config.get("distanceToleranceMeters", 0.001)) / scale
    angle_limit = math.cos(math.radians(float(config.get("normalAngleToleranceDeg", 25.0))))
    allow_fallback = bool(config.get("allowNearestBauraumFallback", True))

    if not assembly_path.exists():
        raise SystemExit(f"Missing assembly STL: {assembly_path}")

    assembly = trimesh.load(
        assembly_path,
        force="mesh",
        process=True,
    )
    if not isinstance(assembly, trimesh.Trimesh):
        raise SystemExit("assembly.stl is not a single mesh")

    part_names = config.get("parts", [])
    if not part_names:
        raise SystemExit("No component parts configured")

    refs = {}
    boxes = {}
    trees = {}
    face_trees = {}

    for filename in part_names:
        path = input_dir / filename
        if not path.exists():
            raise SystemExit(f"Missing reference STL: {path}")
        mesh = trimesh.load(path, force="mesh", process=False)
        refs[filename] = mesh
        bounds = mesh.bounds
        boxes[filename] = (
            bounds[0] - margin,
            bounds[1] + margin,
        )
        samples = np.vstack([mesh.vertices, mesh.triangles_center])
        trees[filename] = cKDTree(samples)
        face_trees[filename] = cKDTree(mesh.triangles_center)

    triangles = assembly.triangles
    centers = assembly.triangles_center
    normals = assembly.face_normals
    assignment = {name: [] for name in part_names}
    stats = {name: {"fast": 0, "detailed": 0, "fallback": 0} for name in part_names}
    ambiguous = []
    unassigned = []

    for index, (triangle, center, normal) in enumerate(zip(triangles, centers, normals)):
        tri_min = triangle.min(axis=0)
        tri_max = triangle.max(axis=0)
        candidates = [
            name for name in part_names
            if box_overlap(tri_min, tri_max, boxes[name][0], boxes[name][1])
        ]

        if len(candidates) == 1:
            assignment[candidates[0]].append(index)
            stats[candidates[0]]["fast"] += 1
            continue

        search_names = candidates
        if not search_names:
            distances = [
                (box_distance(center, boxes[name][0], boxes[name][1]), name)
                for name in part_names
            ]
            distances.sort()
            search_names = [distances[0][1]] if distances else []

        scored = []
        for name in search_names:
            distance, _ = trees[name].query(center, k=1)
            _, nearest_face = face_trees[name].query(center, k=1)
            alignment = abs(float(np.dot(normal, refs[name].face_normals[nearest_face])))
            scored.append((float(distance), alignment, name))

        valid = [item for item in scored if item[0] <= tolerance and item[1] >= angle_limit]
        valid.sort(key=lambda item: item[0])

        if len(valid) == 1:
            assignment[valid[0][2]].append(index)
            stats[valid[0][2]]["detailed"] += 1
            continue

        if len(valid) > 1 and (valid[1][0] - valid[0][0]) > tolerance * 0.25:
            assignment[valid[0][2]].append(index)
            stats[valid[0][2]]["detailed"] += 1
            continue

        if allow_fallback and scored:
            scored.sort(key=lambda item: (item[0], -item[1]))
            chosen = scored[0][2]
            assignment[chosen].append(index)
            stats[chosen]["fallback"] += 1
            ambiguous.append({
                "face": index,
                "assignedBy": "nearestFallback",
                "candidates": [item[2] for item in scored[:5]],
                "distancesInputUnits": [item[0] for item in scored[:5]],
            })
        else:
            unassigned.append(index)
            ambiguous.append({
                "face": index,
                "assignedBy": "unassigned",
                "candidates": [item[2] for item in scored[:5]],
                "distancesInputUnits": [item[0] for item in scored[:5]],
            })

    total_assigned = sum(len(values) for values in assignment.values())
    report = {
        "mode": mode,
        "assemblyFile": str(assembly_path),
        "inputDirectory": str(input_dir),
        "outputDirectory": str(output_dir),
        "units": config.get("units", "mm"),
        "boundingBoxMarginMeters": float(config.get("boundingBoxMarginMeters", 0.001)),
        "distanceToleranceMeters": float(config.get("distanceToleranceMeters", 0.001)),
        "assemblyTriangles": int(len(assembly.faces)),
        "assignedFaces": int(total_assigned),
        "unassignedFaces": int(len(unassigned)),
        "ambiguousOrFallbackFaces": int(len(ambiguous)),
        "parts": stats,
        "unassignedFaceIndices": unassigned[:1000],
        "ambiguousExamples": ambiguous[:1000],
    }

    report_path = ROOT / "results/assembly_mapping_fast_report.json"
    csv_path = ROOT / "results/assembly_mapping_fast_summary.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["part", "fastFaces", "detailedFaces", "fallbackFaces", "totalAssigned"])
        for name in part_names:
            item = stats[name]
            writer.writerow([name, item["fast"], item["detailed"], item["fallback"], sum(item.values())])

    print(json.dumps(report, indent=2))
    print("JSON report:", report_path)
    print("CSV summary:", csv_path)

    if mode == "apply":
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(assembly_path, output_dir / assembly_path.name)
        for name, indices in assignment.items():
            if not indices:
                continue
            mesh = trimesh.Trimesh(
                vertices=assembly.vertices.copy(),
                faces=assembly.faces[np.asarray(indices, dtype=int)],
                process=False,
            )
            mesh.remove_unreferenced_vertices()
            mesh.export(output_dir / name)
        print("Mapped Assembly-derived STLs written:", output_dir)

if __name__ == "__main__":
    main()
