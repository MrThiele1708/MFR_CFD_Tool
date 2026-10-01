#!/usr/bin/env python3
import os

from pathlib import Path
import json
import math

import numpy as np
import trimesh
import yaml
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))

config = yaml.safe_load(
    (Path(os.environ.get("CFD_CONFIG", str(ROOT / "config/parameters.yaml")))).read_text(
        encoding="utf-8"
    )
)

geometry = config.get("geometry", {})
morph = geometry.get("contactAwareMorph", {}) or {}

if not bool(morph.get("enabled", False)):
    print("Contact-aware morphing disabled.")
    raise SystemExit(0)

manifest = yaml.safe_load(
    (Path(os.environ.get("CFD_MANIFEST", str(ROOT / "config/geometryManifest.yaml")))).read_text(
        encoding="utf-8"
    )
)

parts = manifest["parts"]
tri_dir = CASE / "constant/triSurface"

profile = geometry["profile"]
source_dir = ROOT / "geometry" / profile

units = str(
    geometry.get("inputUnits", "m")
).lower()

scale = (
    0.001
    if units in ("mm", "millimeter", "millimetre")
    else 1.0
)

tolerance = float(
    morph.get("sharedVertexTolerance", 1e-6)
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

radiator_enabled = bool(
    config.get("radiator", {})
    .get("enabled", False)
)

radiator_keys = {
    "radiatorLeft",
    "radiatorRight",
} if radiator_enabled else set()

ride_height = float(
    geometry.get("rideHeight", 0.0)
)

pitch_angle = float(
    geometry.get("pitchAngle", 0.0)
)

roll_angle = float(
    geometry.get("rollAngle", 0.0)
)

steering_angle = float(
    geometry.get("steeringAngle", 0.0)
)


def load_source_part(key):
    filename = parts[key]["file"]
    path = source_dir / filename

    if not path.exists():
        raise SystemExit(f"Missing source STL: {path}")

    mesh = trimesh.load(
        path,
        force="mesh",
        process=False,
    )

    mesh.apply_scale(scale)
    return mesh



def flipped_face_indices(vertices, faces, reference_normals):
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


def body_transform(points, moment_center):
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


def vertex_adjacency(faces, vertex_count):
    edges = np.vstack(
        [
            faces[:, [0, 1]],
            faces[:, [1, 2]],
            faces[:, [2, 0]],
        ]
    )

    rows = np.concatenate(
        [
            edges[:, 0],
            edges[:, 1],
        ]
    )

    cols = np.concatenate(
        [
            edges[:, 1],
            edges[:, 0],
        ]
    )

    values = np.ones(
        len(rows),
        dtype=np.float32,
    )

    graph = coo_matrix(
        (values, (rows, cols)),
        shape=(vertex_count, vertex_count),
    ).tocsr()

    graph.sum_duplicates()
    graph.data[:] = 1.0
    graph.setdiag(0.0)
    graph.eliminate_zeros()

    return graph


def nearest_anchor_tree(tree, vertices):
    return np.asarray(
        tree.query(
            np.asarray(vertices, dtype=np.float32),
            k=1,
        )[0]
    )


# Load original, untransformed source geometry.
meshes = {
    key: load_source_part(key)
    for key, spec in parts.items()
    if (
        spec.get("include", True)
        or key in radiator_keys
    )
}

# Moment center from original wheel positions.
wheel_centers = {
    key: meshes[key].bounds.mean(axis=0)
    for key in (
        "wheelFL",
        "wheelFR",
        "wheelRL",
        "wheelRR",
    )
    if key in meshes
}

front_centers = [
    wheel_centers[key]
    for key in ("wheelFL", "wheelFR")
    if key in wheel_centers
]

rear_centers = [
    wheel_centers[key]
    for key in ("wheelRL", "wheelRR")
    if key in wheel_centers
]

moment_center = np.zeros(3)

if front_centers and rear_centers:
    moment_center[0] = 0.5 * (
        np.mean([p[0] for p in front_centers])
        + np.mean([p[0] for p in rear_centers])
    )

# Build exact shared-vertex reference trees from source geometry.
body_vertices = np.vstack(
    [
        meshes[key].vertices
        for key in body_keys
    ]
)

body_tree = cKDTree(body_vertices)

wheel_trees = {
    wheel_key: cKDTree(meshes[wheel_key].vertices)
    for wheel_key in set(wheel_map.values())
}

suspension_keys = set(wheel_map.keys())

report = {
    "enabled": True,
    "method": "shared-vertex-graph-morph",
    "profile": profile,
    "sharedVertexTolerance": tolerance,
    "rideHeight": ride_height,
    "pitchAngle": pitch_angle,
    "rollAngle": roll_angle,
    "steeringAngle": steering_angle,
    "momentCenter": moment_center.tolist(),
    "parts": {},
}

# Transform sprung components.
for key, mesh in meshes.items():
    if key in suspension_keys:
        continue

    spec = parts[key]
    group = spec.get("group", "unsprung")

    if group == "sprung" or key in radiator_keys:
        mesh.vertices = body_transform(
            mesh.vertices,
            moment_center,
        )

    if (
        key in ("wheelFL", "wheelFR")
        and abs(steering_angle) > 1e-12
    ):
        wheel_center = mesh.bounds.mean(axis=0)

        steering = (
            trimesh.transformations.rotation_matrix(
                math.radians(steering_angle),
                [0.0, 0.0, 1.0],
                wheel_center,
            )
        )

        mesh.apply_transform(steering)

# Morph each suspension using graph distances.
for suspension_key, wheel_key in wheel_map.items():
    print("Processing:", suspension_key, flush=True)

    suspension = meshes[suspension_key]
    vertices_before = suspension.vertices.copy()
    faces = suspension.faces.copy()

    body_distance = nearest_anchor_tree(
        body_tree,
        vertices_before,
    )

    wheel_distance = nearest_anchor_tree(
        wheel_trees[wheel_key],
        vertices_before,
    )

    body_anchor = body_distance <= tolerance
    wheel_anchor = wheel_distance <= tolerance
    overlap = body_anchor & wheel_anchor

    if not np.any(body_anchor):
        raise SystemExit(
            f"No body anchor vertices found for {suspension_key}"
        )

    if not np.any(wheel_anchor):
        raise SystemExit(
            f"No wheel anchor vertices found for {suspension_key}"
        )

    if np.any(overlap):
        raise SystemExit(
            f"Conflicting body/wheel anchors in {suspension_key}: "
            f"{np.count_nonzero(overlap)}"
        )

    graph = vertex_adjacency(
        faces,
        len(vertices_before),
    )

    component_count, component_labels = (
        connected_components(
            graph,
            directed=False,
        )
    )

    weights = np.full(
        len(vertices_before),
        np.nan,
        dtype=float,
    )

    unanchored_vertices = 0
    component_modes = []

    for component_id in range(component_count):
        component_vertices = np.flatnonzero(
            component_labels == component_id
        )

        local_body_anchor = body_anchor[
            component_vertices
        ]

        local_wheel_anchor = wheel_anchor[
            component_vertices
        ]

        body_count = int(
            np.count_nonzero(local_body_anchor)
        )

        wheel_count = int(
            np.count_nonzero(local_wheel_anchor)
        )

        if body_count and wheel_count:
            local_graph = graph[
                component_vertices
            ][:, component_vertices]

            local_wheel_indices = np.flatnonzero(
                local_wheel_anchor
            )

            local_body_indices = np.flatnonzero(
                local_body_anchor
            )

            distance_from_wheel = dijkstra(
                local_graph,
                directed=False,
                indices=local_wheel_indices,
                min_only=True,
            )

            distance_from_body = dijkstra(
                local_graph,
                directed=False,
                indices=local_body_indices,
                min_only=True,
            )

            denominator = (
                distance_from_wheel
                + distance_from_body
            )

            local_weights = np.divide(
                distance_from_wheel,
                denominator,
                out=np.full(
                    len(component_vertices),
                    0.5,
                ),
                where=denominator > 1e-12,
            )

            weights[component_vertices] = local_weights
            component_modes.append("graph")

        elif body_count:
            weights[component_vertices] = 1.0
            component_modes.append("body-fixed")

        elif wheel_count:
            weights[component_vertices] = 0.0
            component_modes.append("wheel-fixed")

        else:
            # Isolated geometry without a shared anchor:
            # use a conservative Euclidean fallback.
            points = vertices_before[
                component_vertices
            ]

            body_distances = body_tree.query(
                points,
                k=1,
            )[0]

            wheel_distances = wheel_trees[wheel_key].query(
                points,
                k=1,
            )[0]

            denominator = (
                body_distances
                + wheel_distances
            )

            local_weights = np.divide(
                wheel_distances,
                denominator,
                out=np.full(
                    len(component_vertices),
                    0.5,
                ),
                where=denominator > 1e-12,
            )

            weights[component_vertices] = local_weights
            unanchored_vertices += len(component_vertices)
            component_modes.append("euclidean-fallback")

    if np.any(~np.isfinite(weights)):
        raise SystemExit(
            f"Could not determine weights for "
            f"{suspension_key}"
        )

    weights = np.clip(weights, 0.0, 1.0)

    free_vertices = ~(
        body_anchor | wheel_anchor
    )

    degrees = np.asarray(
        graph.sum(axis=1)
    ).reshape(-1)

    degrees = np.maximum(degrees, 1.0)

    # Smooth only free transition vertices.
    for _ in range(smoothing_iterations):
        neighbour_average = (
            np.asarray(graph.dot(weights)).reshape(-1)
            / degrees
        )

        weights[free_vertices] = (
            (1.0 - smoothing_factor)
            * weights[free_vertices]
            + smoothing_factor
            * neighbour_average[free_vertices]
        )

        weights[wheel_anchor] = 0.0
        weights[body_anchor] = 1.0

    weights = np.clip(weights, 0.0, 1.0)

    # Local backtracking for inverted faces.
    reference_mesh = trimesh.Trimesh(
        vertices=vertices_before,
        faces=faces,
        process=False,
    )

    reference_normals = reference_mesh.face_normals
    repair_iterations = 0
    remaining_flipped = 0

    for iteration in range(max_repair_iterations + 1):
        trial_body_positions = body_transform(
            vertices_before,
            moment_center,
        )

        trial_vertices = (
            vertices_before
            + weights[:, None]
            * (trial_body_positions - vertices_before)
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

        neighbour_average = (
            np.asarray(graph.dot(weights)).reshape(-1)
            / degrees
        )

        old_weights = weights[adjustable].copy()

        reduced_weights = (
            0.5 * old_weights
            + 0.5 * neighbour_average[adjustable]
        )

        weights[adjustable] = np.minimum(
            reduced_weights,
            0.75 * old_weights,
        )

        weights[wheel_anchor] = 0.0
        weights[body_anchor] = 1.0
        weights = np.clip(weights, 0.0, 1.0)

    if remaining_flipped:
        raise SystemExit(
            f"Contact-aware morph quality failed for "
            f"{suspension_key}: "
            f"flippedFaces={remaining_flipped}, "
            f"repairIterations={repair_iterations}"
        )

    # Enforce exact contact constraints after smoothing.
    weights[wheel_anchor] = 0.0
    weights[body_anchor] = 1.0

    target_body_positions = body_transform(
        vertices_before,
        moment_center,
    )

    vertices_after = (
        vertices_before
        + weights[:, None]
        * (target_body_positions - vertices_before)
    )

    # Enforce exact coordinates again at shared anchors.
    vertices_after[wheel_anchor] = (
        vertices_before[wheel_anchor]
    )

    vertices_after[body_anchor] = (
        target_body_positions[body_anchor]
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
        "wheelAnchorVertices": int(
            np.count_nonzero(wheel_anchor)
        ),
        "connectedComponents": int(component_count),
        "componentModes": component_modes,
        "unanchoredVertices": int(unanchored_vertices),
        "bodyAnchorVertices": int(
            np.count_nonzero(body_anchor)
        ),
        "interpolatedVertices": int(
            len(vertices_before)
            - np.count_nonzero(wheel_anchor)
            - np.count_nonzero(body_anchor)
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
    }

    if zero_area_faces or flipped_faces:
        raise SystemExit(
            f"Contact-aware morph quality failed for "
            f"{suspension_key}: "
            f"zeroAreaFaces={zero_area_faces}, "
            f"flippedFaces={flipped_faces}"
        )

    suspension.vertices = vertices_after

    print(
        suspension_key,
        "wheelAnchors=",
        np.count_nonzero(wheel_anchor),
        "bodyAnchors=",
        np.count_nonzero(body_anchor),
        "flippedFaces=",
        flipped_faces,
        flush=True,
    )

# Export all transformed parts.
for key, mesh in meshes.items():
    target = tri_dir / parts[key]["file"]
    mesh.export(target)
    print("Exported:", target)

# Recalculate metrics with per-part bounds.
minimum = np.array(
    [float("inf")] * 3,
    dtype=float,
)

maximum = np.array(
    [float("-inf")] * 3,
    dtype=float,
)

for mesh in meshes.values():
    bounds = mesh.bounds
    minimum = np.minimum(minimum, bounds[0])
    maximum = np.maximum(maximum, bounds[1])

metrics_path = CASE / "constant/geometryMetrics.json"

metrics = {
    "profile": profile,
    "bbox_m": [
        minimum.tolist(),
        maximum.tolist(),
    ],
    "vehicleLength": float(maximum[0] - minimum[0]),
    "vehicleWidth": float(maximum[1] - minimum[1]),
    "vehicleHeight": float(maximum[2] - minimum[2]),
    "momentCenter": moment_center.tolist(),
    "patches": sorted(
        spec["patch"]
        for spec in parts.values()
        if spec.get("include", True)
    ),
    "contactAwareMorph": report,
}

metrics_path.write_text(
    json.dumps(metrics, indent=2),
    encoding="utf-8",
)

report_path = (
    ROOT / "results/contact_aware_morph_report.json"
)

report_path.write_text(
    json.dumps(report, indent=2),
    encoding="utf-8",
)

print("Contact-aware morph report:", report_path)
print("Updated geometry metrics:", metrics_path)
