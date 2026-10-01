#!/usr/bin/env python3

from pathlib import Path
import gc
import json
import math

import numpy as np
import trimesh
import yaml
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "case"

config = yaml.safe_load(
    (ROOT / "config/parameters.yaml").read_text(
        encoding="utf-8"
    )
)

geometry = config.get("geometry", {})
morph = geometry.get("suspensionMorph", {}) or {}

if not bool(morph.get("enabled", False)):
    print("Suspension morphing disabled.")
    raise SystemExit(0)

distance_limit = float(
    morph.get("attachmentDistance", 0.010)
)

smoothing_iterations = int(
    morph.get("smoothingIterations", 8)
)

smoothing_factor = float(
    morph.get("smoothingFactor", 0.5)
)

max_repair_iterations = int(
    morph.get("maxRepairIterations", 20)
)

body_keys = list(
    morph.get(
        "bodyReferenceParts",
        [
            "body",
            "sidepodLeft",
            "sidepodRight",
            "underbody",
        ],
    )
)

wheel_map = dict(
    morph.get(
        "wheelMap",
        {
            "suspensionFL": "wheelFL",
            "suspensionFR": "wheelFR",
            "suspensionRL": "wheelRL",
            "suspensionRR": "wheelRR",
        },
    )
)

manifest = yaml.safe_load(
    (ROOT / "config/geometryManifest.yaml").read_text(
        encoding="utf-8"
    )
)

parts = manifest["parts"]
tri_dir = CASE / "constant/triSurface"

ride_height = float(
    geometry.get("rideHeight", 0.0)
)
pitch_angle = float(
    geometry.get("pitchAngle", 0.0)
)
roll_angle = float(
    geometry.get("rollAngle", 0.0)
)

metrics_path = CASE / "constant/geometryMetrics.json"

if metrics_path.exists():
    metrics = json.loads(
        metrics_path.read_text(encoding="utf-8")
    )
else:
    metrics = {}

moment_center = np.asarray(
    metrics.get("momentCenter", [0.0, 0.0, 0.0]),
    dtype=float,
)

np.random.seed(0)


def load_part(key):
    filename = parts[key]["file"]
    path = tri_dir / filename

    if not path.exists():
        raise SystemExit(f"Missing geometry part: {path}")

    return trimesh.load(
        path,
        force="mesh",
        process=False,
    )



def build_vertex_adjacency(faces, vertex_count):
    edge_pairs = np.vstack(
        [
            faces[:, [0, 1]],
            faces[:, [1, 2]],
            faces[:, [2, 0]],
        ]
    )

    rows = np.concatenate(
        [
            edge_pairs[:, 0],
            edge_pairs[:, 1],
        ]
    )

    columns = np.concatenate(
        [
            edge_pairs[:, 1],
            edge_pairs[:, 0],
        ]
    )

    values = np.ones(
        len(rows),
        dtype=np.float32,
    )

    adjacency = coo_matrix(
        (values, (rows, columns)),
        shape=(vertex_count, vertex_count),
    ).tocsr()

    adjacency.sum_duplicates()
    adjacency.data[:] = 1.0
    adjacency.setdiag(0.0)
    adjacency.eliminate_zeros()

    return adjacency

def sampled_surface_points(mesh, maximum):
    count = min(maximum, max(1000, len(mesh.faces)))

    try:
        points, _ = trimesh.sample.sample_surface(
            mesh,
            count=count,
        )
        return np.asarray(points, dtype=np.float32)
    except Exception:
        vertices = np.asarray(
            mesh.vertices,
            dtype=np.float32,
        )

        if len(vertices) > maximum:
            indices = np.linspace(
                0,
                len(vertices) - 1,
                maximum,
                dtype=int,
            )
            vertices = vertices[indices]

        return vertices


def build_tree_from_part_keys(keys, maximum):
    samples = []

    for key in keys:
        mesh = load_part(key)
        samples.append(
            sampled_surface_points(mesh, maximum)
        )
        del mesh
        gc.collect()

    points = np.vstack(samples)
    tree = cKDTree(points)

    del samples
    del points
    gc.collect()

    return tree


def transform_body_points(points):
    roll = trimesh.transformations.rotation_matrix(
        math.radians(roll_angle),
        [1.0, 0.0, 0.0],
        moment_center,
    )

    pitch = trimesh.transformations.rotation_matrix(
        math.radians(pitch_angle),
        [0.0, 1.0, 0.0],
        moment_center,
    )

    transform = pitch @ roll

    homogeneous = np.column_stack(
        [
            points,
            np.ones(len(points)),
        ]
    )

    transformed = homogeneous @ transform.T
    transformed = transformed[:, :3]
    transformed[:, 2] += ride_height

    return transformed


def query_tree(tree, points):
    points = np.asarray(points, dtype=np.float32)
    return np.asarray(tree.query(points, k=1)[0])


print("Building sampled body reference tree...")
body_tree = build_tree_from_part_keys(
    body_keys,
    maximum=25000,
)

report = {
    "enabled": True,
    "distanceMethod": "sampled-surface-kdtree",
    "attachmentDistance": distance_limit,
    "rideHeight": ride_height,
    "pitchAngle": pitch_angle,
    "rollAngle": roll_angle,
    "parts": {},
}

def flipped_face_indices(
    vertices,
    faces,
    reference_normals,
):
    candidate = trimesh.Trimesh(
        vertices=vertices,
        faces=faces,
        process=False,
    )

    dots = np.einsum(
        "ij,ij->i",
        reference_normals,
        candidate.face_normals,
    )

    return np.flatnonzero(dots < 0.0)


for suspension_key, wheel_key in wheel_map.items():
    print("Processing:", suspension_key, flush=True)

    suspension = load_part(suspension_key)

    wheel_tree = build_tree_from_part_keys(
        [wheel_key],
        maximum=30000,
    )

    vertices_before = suspension.vertices.copy()
    faces = suspension.faces.copy()

    distance_body = query_tree(
        body_tree,
        vertices_before,
    )

    distance_wheel = query_tree(
        wheel_tree,
        vertices_before,
    )

    del wheel_tree
    gc.collect()

    wheel_zone = distance_wheel <= distance_limit
    body_zone = distance_body <= distance_limit

    only_wheel = wheel_zone & ~body_zone
    only_body = body_zone & ~wheel_zone
    both_zones = wheel_zone & body_zone
    transition = ~wheel_zone & ~body_zone

    weights = np.empty(len(vertices_before))
    weights[only_wheel] = 0.0
    weights[only_body] = 1.0

    both_denominator = (
        distance_wheel[both_zones]
        + distance_body[both_zones]
    )

    weights[both_zones] = np.divide(
        distance_wheel[both_zones],
        both_denominator,
        out=np.full(
            np.count_nonzero(both_zones),
            0.5,
        ),
        where=both_denominator > 1e-12,
    )

    denominator = (
        distance_wheel[transition]
        + distance_body[transition]
        - 2.0 * distance_limit
    )

    weights[transition] = np.divide(
        distance_wheel[transition] - distance_limit,
        denominator,
        out=np.full(
            np.count_nonzero(transition),
            0.5,
        ),
        where=denominator > 1e-12,
    )

    weights = np.clip(weights, 0.0, 1.0)

    # Smooth only the transition zone. Wheel-locked and
    # body-locked vertices remain exactly fixed.
    adjacency = build_vertex_adjacency(
        faces,
        len(vertices_before),
    )

    degrees = np.asarray(
        adjacency.sum(axis=1)
    ).reshape(-1)

    degrees = np.maximum(degrees, 1.0)

    free_vertices = ~(wheel_zone | body_zone)

    for _ in range(smoothing_iterations):
        averaged = np.asarray(
            adjacency.dot(weights)
        ).reshape(-1) / degrees

        weights[free_vertices] = (
            (1.0 - smoothing_factor)
            * weights[free_vertices]
            + smoothing_factor
            * averaged[free_vertices]
        )

        weights[wheel_zone] = 0.0
        weights[body_zone] = 1.0

    weights = np.clip(weights, 0.0, 1.0)

    # Adaptive local repair of inverted faces.
    reference_mesh = trimesh.Trimesh(
        vertices=vertices_before,
        faces=faces,
        process=False,
    )

    reference_normals = reference_mesh.face_normals
    repair_iterations = 0
    remaining_flipped = 0

    for iteration in range(max_repair_iterations + 1):
        trial_body_position = transform_body_points(
            vertices_before
        )

        trial_vertices = (
            vertices_before
            + weights[:, None]
            * (trial_body_position - vertices_before)
        )

        bad_faces = flipped_face_indices(
            trial_vertices,
            faces,
            reference_normals,
        )

        remaining_flipped = int(len(bad_faces))
        repair_iterations = iteration

        if remaining_flipped == 0:
            break

        if iteration >= max_repair_iterations:
            break

        bad_vertices = np.unique(
            faces[bad_faces].reshape(-1)
        )

        adjustable = bad_vertices[
            free_vertices[bad_vertices]
        ]

        if len(adjustable) == 0:
            break

        old_weights = weights[adjustable].copy()

        neighbour_sum = np.asarray(
            adjacency.dot(weights)
        ).reshape(-1)

        neighbour_average = (
            neighbour_sum / degrees
        )

        smoothed_weights = (
            0.5 * old_weights
            + 0.5 * neighbour_average[adjustable]
        )

        # Force a conservative reduction for vertices
        # participating in an inverted face.
        weights[adjustable] = np.minimum(
            smoothed_weights,
            0.75 * old_weights,
        )

        weights[wheel_zone] = 0.0
        weights[body_zone] = 1.0
        weights = np.clip(weights, 0.0, 1.0)

    body_position = transform_body_points(
        vertices_before
    )

    vertices_after = (
        vertices_before
        + weights[:, None]
        * (body_position - vertices_before)
    )

    before_mesh = trimesh.Trimesh(
        vertices=vertices_before,
        faces=faces,
        process=False,
    )

    after_mesh = trimesh.Trimesh(
        vertices=vertices_after,
        faces=faces,
        process=False,
    )

    normal_dot = np.einsum(
        "ij,ij->i",
        before_mesh.face_normals,
        after_mesh.face_normals,
    )

    zero_area_faces = int(
        np.count_nonzero(
            after_mesh.area_faces <= 1e-14
        )
    )

    flipped_faces = int(
        np.count_nonzero(normal_dot < 0.0)
    )

    report["parts"][suspension_key] = {
        "wheelReference": wheel_key,
        "vertexCount": int(len(vertices_before)),
        "wheelLockedVertices": int(
            np.count_nonzero(only_wheel)
        ),
        "bodyLockedVertices": int(
            np.count_nonzero(only_body)
        ),
        "overlapVertices": int(
            np.count_nonzero(both_zones)
        ),
        "interpolatedVertices": int(
            np.count_nonzero(transition)
        ),
        "weightMin": float(weights.min()),
        "weightMax": float(weights.max()),
        "weightMean": float(weights.mean()),
        "maxDisplacement": float(
            np.linalg.norm(
                vertices_after - vertices_before,
                axis=1,
            ).max()
        ),
        "zeroAreaFaces": zero_area_faces,
        "flippedFaces": flipped_faces,
        "repairIterations": repair_iterations,
        "remainingFlippedFaces": remaining_flipped,
    }

    if zero_area_faces or flipped_faces:
        raise SystemExit(
            "Morphing quality check failed for "
            f"{suspension_key}: "
            f"zeroAreaFaces={zero_area_faces}, "
            f"flippedFaces={flipped_faces}"
        )

    target_path = tri_dir / parts[suspension_key]["file"]
    after_mesh.export(target_path)

    print(
        suspension_key,
        "wheelLocked=",
        report["parts"][suspension_key]["wheelLockedVertices"],
        "bodyLocked=",
        report["parts"][suspension_key]["bodyLockedVertices"],
        "interpolated=",
        report["parts"][suspension_key]["interpolatedVertices"],
        "flippedFaces=",
        flipped_faces,
        flush=True,
    )

    del suspension
    del before_mesh
    del after_mesh
    del vertices_before
    del vertices_after
    del faces
    del weights
    gc.collect()

del body_tree
gc.collect()

# Recalculate metrics without concatenating all large meshes.
minimum = np.array(
    [float("inf")] * 3,
    dtype=float,
)

maximum = np.array(
    [float("-inf")] * 3,
    dtype=float,
)

included_parts = []

for key, spec in parts.items():
    if not spec.get("include", True):
        continue

    path = tri_dir / spec["file"]

    if not path.exists():
        continue

    mesh = trimesh.load(
        path,
        force="mesh",
        process=False,
    )

    bounds = mesh.bounds
    minimum = np.minimum(minimum, bounds[0])
    maximum = np.maximum(maximum, bounds[1])
    included_parts.append(key)

    del mesh
    gc.collect()

metrics.update(
    {
        "bbox_m": [
            minimum.tolist(),
            maximum.tolist(),
        ],
        "vehicleLength": float(maximum[0] - minimum[0]),
        "vehicleWidth": float(maximum[1] - minimum[1]),
        "vehicleHeight": float(maximum[2] - minimum[2]),
        "suspensionMorph": report,
    }
)

metrics_path.write_text(
    json.dumps(metrics, indent=2),
    encoding="utf-8",
)

report_path = (
    ROOT / "results/suspension_morph_report.json"
)

report_path.write_text(
    json.dumps(report, indent=2),
    encoding="utf-8",
)

print("Suspension morph report:", report_path)
print("Updated geometry metrics:", metrics_path)
