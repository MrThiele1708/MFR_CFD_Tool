#!/usr/bin/env python3
"""Global assembly morph for FormulaStudentCFD_v0_8.

The mapped assembly is kept as one indexed surface while the displacement
field is calculated. Component patch STLs are exported only after all global
vertices have received one common target coordinate. This prevents separate
STL exports from drifting apart at shared interfaces.

Geometry-only operation: no OpenFOAM mesh or solver is started.
"""

from __future__ import annotations

import csv
import gc
import json
import math
import os
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import trimesh
import yaml
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[1]
CASE = Path(os.environ.get("CFD_CASE", str(ROOT / "case")))
CONFIG_PATH = Path(
    os.environ.get(
        "CFD_CONFIG",
        str(ROOT / "config/parameters.yaml"),
    )
)
MANIFEST_PATH = Path(
    os.environ.get(
        "CFD_MANIFEST",
        str(ROOT / "config/geometryManifest.yaml"),
    )
)
RESULTS = Path(
    os.environ.get(
        "CFD_RESULTS",
        str(ROOT / "results"),
    )
)

config = yaml.safe_load(
    CONFIG_PATH.read_text(encoding="utf-8")
)
manifest = yaml.safe_load(
    MANIFEST_PATH.read_text(encoding="utf-8")
)

geometry = config.get("geometry", {}) or {}
morph = geometry.get("contactAwareMorph", {}) or {}
parts = manifest["parts"]

if not bool(morph.get("enabled", False)):
    print("Global assembly morphing disabled.")
    raise SystemExit(0)

profile = geometry["profile"]
source_dir = ROOT / "geometry" / profile
tri_dir = CASE / "constant/triSurface"
tri_dir.mkdir(parents=True, exist_ok=True)
RESULTS.mkdir(parents=True, exist_ok=True)

units = str(geometry.get("inputUnits", "m")).lower()
scale = (
    0.001
    if units in ("mm", "millimeter", "millimetre")
    else 1.0
)

shared_tolerance = float(
    morph.get("sharedVertexTolerance", 1.0e-6)
)
shared_digits = int(
    morph.get("sharedVertexDigits", 9)
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
body_rigid_layers = int(
    morph.get("bodyRigidLayers", 2)
)
wheel_rigid_layers = int(
    morph.get("wheelRigidLayers", 1)
)
if body_rigid_layers < 0 or wheel_rigid_layers < 0:
    raise SystemExit(
        "bodyRigidLayers and wheelRigidLayers must be non-negative"
    )


ignore_flipped_faces = bool(
    morph.get("ignoreFlippedFaces", False)
)


body_reference_keys = list(
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

suspension_keys = set(wheel_map.keys())
wheel_keys = set(wheel_map.values())
radiator_enabled = bool(
    config.get("radiator", {})
    .get("enabled", False)
)
radiator_keys = {
    "radiatorLeft",
    "radiatorRight",
} if radiator_enabled else set()

ride_height = float(geometry.get("rideHeight", 0.0))
pitch_angle = float(geometry.get("pitchAngle", 0.0))
roll_angle = float(geometry.get("rollAngle", 0.0))
steering_angle = float(geometry.get("steeringAngle", 0.0))

assembly_name = str(
    morph.get("assemblyFile", "assembly.stl")
)
assembly_path = source_dir / assembly_name

if not assembly_path.exists():
    raise SystemExit(f"Missing source assembly STL: {assembly_path}")


def load_mesh(path, process=False):
    return trimesh.load(
        path,
        force="mesh",
        process=process,
    )


def triangle_key(triangle, digits=6):
    rounded = np.round(
        np.asarray(triangle, dtype=float),
        decimals=digits,
    )
    vertices = sorted(
        tuple(float(value) for value in row)
        for row in rounded
    )
    return tuple(vertices)


def build_face_assignment(assembly, assembly_path):
    """Recover component face labels from mapped component STLs.

    map_assembly_regions_fast.py writes each component as a face subset of
    assembly.stl. Matching canonical triangle coordinates reconstructs that
    face assignment without relying on stale reports.
    """
    face_queues = defaultdict(deque)

    for face_index, triangle in enumerate(assembly.triangles):
        face_queues[triangle_key(triangle)].append(face_index)

    assignment = {
        key: []
        for key, spec in parts.items()
        if spec.get("include", True)
        and key not in radiator_keys
    }
    assigned = np.full(
        len(assembly.faces),
        -1,
        dtype=np.int32,
    )
    missing = []
    duplicates = []

    for part_key in assignment:
        path = source_dir / parts[part_key]["file"]
        if not path.exists():
            raise SystemExit(f"Missing mapped component STL: {path}")

        component = load_mesh(path, process=False)

        for triangle in component.triangles:
            key = triangle_key(triangle)
            queue = face_queues.get(key)
            if not queue:
                missing.append(
                    {
                        "part": part_key,
                        "triangle": triangle.tolist(),
                    }
                )
                continue

            face_index = queue.popleft()
            if assigned[face_index] != -1:
                duplicates.append(
                    {
                        "face": int(face_index),
                        "oldPart": int(assigned[face_index]),
                        "newPart": part_key,
                    }
                )
            assigned[face_index] = 0
            assignment[part_key].append(face_index)

        del component
        gc.collect()

    unassigned = np.flatnonzero(assigned < 0)

    if missing:
        raise SystemExit(
            "Could not match mapped component triangles to the "
            f"assembly. Missing triangles: {len(missing)}"
        )

    if duplicates:
        raise SystemExit(
            "Duplicate assembly face assignments detected: "
            f"{len(duplicates)}"
        )

    if len(unassigned):
        raise SystemExit(
            "Assembly faces were not assigned to a component: "
            f"{len(unassigned)}"
        )

    assigned_count = sum(
        len(indices)
        for indices in assignment.values()
    )

    if assigned_count != len(assembly.faces):
        raise SystemExit(
            "Assigned component face count does not equal assembly face count: "
            f"{assigned_count} != {len(assembly.faces)}"
        )

    return assignment


def vertex_adjacency(faces, vertex_count):
    if len(faces) == 0:
        return coo_matrix(
            (vertex_count, vertex_count),
            dtype=np.float32,
        ).tocsr()

    edges = np.vstack(
        [
            faces[:, [0, 1]],
            faces[:, [1, 2]],
            faces[:, [2, 0]],
        ]
    )

    rows = np.concatenate(
        [edges[:, 0], edges[:, 1]]
    )
    cols = np.concatenate(
        [edges[:, 1], edges[:, 0]]
    )

    graph = coo_matrix(
        (
            np.ones(len(rows), dtype=np.float32),
            (rows, cols),
        ),
        shape=(vertex_count, vertex_count),
    ).tocsr()
    graph.sum_duplicates()
    graph.data[:] = 1.0
    graph.setdiag(0.0)
    graph.eliminate_zeros()
    return graph


def apply_transform_points(points, transform):
    homogeneous = np.column_stack(
        [
            points,
            np.ones(len(points)),
        ]
    )
    return (homogeneous @ transform.T)[:, :3]


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
    return apply_transform_points(
        points,
        pitch @ roll,
    ) + np.array([0.0, 0.0, ride_height])


def steering_transform(points, wheel_key, wheel_centers):
    if (
        wheel_key not in ("wheelFL", "wheelFR")
        or abs(steering_angle) <= 1.0e-12
    ):
        return np.asarray(points, dtype=float).copy()

    transform = trimesh.transformations.rotation_matrix(
        math.radians(steering_angle),
        [0.0, 0.0, 1.0],
        wheel_centers[wheel_key],
    )
    return apply_transform_points(points, transform)


def face_quality(reference_vertices, trial_vertices, faces):
    reference = trimesh.Trimesh(
        vertices=reference_vertices,
        faces=faces,
        process=False,
    )
    trial = trimesh.Trimesh(
        vertices=trial_vertices,
        faces=faces,
        process=False,
    )
    dots = np.einsum(
        "ij,ij->i",
        reference.face_normals,
        trial.face_normals,
    )
    bad_faces = np.flatnonzero(dots <0.0)
    zero_area = int(
        np.count_nonzero(trial.area_faces <=1.0e-14)
    )
    return bad_faces, zero_area


print("Loading source assembly:", assembly_path, flush=True)
assembly = load_mesh(assembly_path, process=True)
assembly_vertices_m = (
    np.asarray(assembly.vertices, dtype=float) * scale
)
assembly_faces = np.asarray(assembly.faces, dtype=np.int64)

print("Assembly triangles:", len(assembly_faces), flush=True)
assignment = build_face_assignment(
    assembly,
    assembly_path,
)

part_face_arrays = {
    key: np.asarray(indices, dtype=np.int64)
    for key, indices in assignment.items()
}

# Compute wheel centers from the globally indexed assembly.
wheel_centers = {}
for wheel_key in wheel_keys:
    face_indices = part_face_arrays[wheel_key]
    vertex_ids = np.unique(
        assembly_faces[face_indices].reshape(-1)
    )
    wheel_centers[wheel_key] = (
        assembly_vertices_m[vertex_ids].mean(axis=0)
    )

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

moment_center = np.zeros(3, dtype=float)
if front_centers and rear_centers:
    moment_center[0] = 0.5 * (
        np.mean([point[0] for point in front_centers])
        + np.mean([point[0] for point in rear_centers])
    )

# Part ownership of globally indexed vertices.
vertex_members = [set() for _ in range(len(assembly_vertices_m))]
for part_key, face_indices in part_face_arrays.items():
    vertex_ids = np.unique(
        assembly_faces[face_indices].reshape(-1)
    )
    for vertex_id in vertex_ids:
        vertex_members[int(vertex_id)].add(part_key)

sprung_keys = {
    key
    for key, spec in parts.items()
    if spec.get("include", True)
    and key not in radiator_keys
    and spec.get("group", "unsprung") == "sprung"
}

sprung_vertex_ids = {
    vertex_id
    for vertex_id, members in enumerate(vertex_members)
    if members.intersection(sprung_keys)
}

wheel_vertex_ids = {
    wheel_key: {
        int(vertex_id)
        for vertex_id, members in enumerate(vertex_members)
        if wheel_key in members
    }
    for wheel_key in wheel_keys
}

wheel_vertex_union = set().union(
    *wheel_vertex_ids.values()
) if wheel_vertex_ids else set()

conflicting_vertices = sorted(
    vertex_id
    for vertex_id in sprung_vertex_ids
    if vertex_id in wheel_vertex_union
)

if conflicting_vertices:
    raise SystemExit(
        "Global vertices belong to both sprung and wheel surfaces: "
        f"{len(conflicting_vertices)}"
    )

# Initial global targets for rigidly transformed sprung and wheel parts.
body_targets = body_transform(
    assembly_vertices_m,
    moment_center,
)

target_vertices = np.full_like(
    assembly_vertices_m,
    np.nan,
)

target_vertices[list(sprung_vertex_ids)] = (
    body_targets[list(sprung_vertex_ids)]
)

for wheel_key, vertex_ids in wheel_vertex_ids.items():
    if not vertex_ids:
        continue
    ids = np.asarray(sorted(vertex_ids), dtype=np.int64)
    target_vertices[ids] = steering_transform(
        assembly_vertices_m[ids],
        wheel_key,
        wheel_centers,
    )

report = {
    "enabled": True,
    "method": "global-indexed-assembly-rigid-transition-v1",
    "profile": profile,
    "assemblyFile": str(assembly_path),
    "assemblyTriangles": int(len(assembly_faces)),
    "assignedPartTriangles": {
        key: int(len(indices))
        for key, indices in part_face_arrays.items()
    },
    "sharedVertexDigits": shared_digits,
    "sharedVertexTolerance": shared_tolerance,
    "rideHeight": ride_height,
    "pitchAngle": pitch_angle,
    "rollAngle": roll_angle,
    "steeringAngle": steering_angle,
    "momentCenter": moment_center.tolist(),
    "parts": {},
}

# Morph each suspension on the global assembly vertex IDs.
for suspension_key, wheel_key in wheel_map.items():
    print("Processing:", suspension_key, flush=True)

    face_indices = part_face_arrays[suspension_key]
    suspension_vertex_ids = np.unique(
        assembly_faces[face_indices].reshape(-1)
    )
    local_index = {
        int(global_id): index
        for index, global_id in enumerate(suspension_vertex_ids)
    }
    local_faces = np.asarray(
        [
            [
                local_index[int(vertex)]
                for vertex in face
            ]
            for face in assembly_faces[face_indices]
        ],
        dtype=np.int64,
    )
    before = assembly_vertices_m[suspension_vertex_ids].copy()

    body_tree = cKDTree(
        assembly_vertices_m[
            np.asarray(sorted(sprung_vertex_ids), dtype=np.int64)
        ]
    ) if sprung_vertex_ids else None
    wheel_tree = cKDTree(
        assembly_vertices_m[
            np.asarray(
                sorted(wheel_vertex_ids[wheel_key]),
                dtype=np.int64,
            )
        ]
    ) if wheel_vertex_ids.get(wheel_key) else None

    if body_tree is None or wheel_tree is None:
        raise SystemExit(
            f"Missing global body/wheel reference for {suspension_key}"
        )

    body_distance = body_tree.query(before, k=1)[0]
    wheel_distance = wheel_tree.query(before, k=1)[0]

    body_anchor = (
        body_distance <= shared_tolerance
    )
    wheel_anchor = (
        wheel_distance <= shared_tolerance
    )

    body_anchor |= np.fromiter(
        (
            int(global_id) in sprung_vertex_ids
            for global_id in suspension_vertex_ids
        ),
        dtype=bool,
        count=len(suspension_vertex_ids),
    )
    wheel_anchor |= np.fromiter(
        (
            int(global_id) in wheel_vertex_ids[wheel_key]
            for global_id in suspension_vertex_ids
        ),
        dtype=bool,
        count=len(suspension_vertex_ids),
    )

    if np.any(body_anchor & wheel_anchor):
        raise SystemExit(
            f"Conflicting body/wheel anchors in {suspension_key}: "
            f"{np.count_nonzero(body_anchor & wheel_anchor)}"
        )

    graph = vertex_adjacency(
        local_faces,
        len(suspension_vertex_ids),
    )
    component_count, component_labels = connected_components(
        graph,
        directed=False,
    )

    weights = np.full(
        len(suspension_vertex_ids),
        np.nan,
        dtype=float,
    )
    body_graph_distance = np.full(
        len(suspension_vertex_ids),
        np.inf,
        dtype=float,
    )
    wheel_graph_distance = np.full(
        len(suspension_vertex_ids),
        np.inf,
        dtype=float,
    )
    component_modes = []
    unanchored = 0

    degrees = np.asarray(graph.sum(axis=1)).reshape(-1)
    degrees = np.maximum(degrees, 1.0)

    for component_id in range(component_count):
        local_vertices = np.flatnonzero(
            component_labels == component_id
        )
        local_body = body_anchor[local_vertices]
        local_wheel = wheel_anchor[local_vertices]
        body_count = int(np.count_nonzero(local_body))
        wheel_count = int(np.count_nonzero(local_wheel))

        if body_count and wheel_count:
            component_graph = graph[
                local_vertices
            ][:, local_vertices]
            wheel_indices = np.flatnonzero(local_wheel)
            body_indices = np.flatnonzero(local_body)
            from_wheel = dijkstra(
                component_graph,
                directed=False,
                indices=wheel_indices,
                min_only=True,
            )
            from_body = dijkstra(
                component_graph,
                directed=False,
                indices=body_indices,
                min_only=True,
            )
            body_graph_distance[local_vertices] = from_body
            wheel_graph_distance[local_vertices] = from_wheel
            denominator = from_wheel + from_body
            local_weights = np.divide(
                from_wheel,
                denominator,
                out=np.full(len(local_vertices), 0.5),
                where=denominator > 1.0e-12,
            )
            weights[local_vertices] = local_weights
            component_modes.append("graph")
        elif body_count:
            weights[local_vertices] = 1.0
            component_modes.append("body-fixed")
        elif wheel_count:
            weights[local_vertices] = 0.0
            component_modes.append("wheel-fixed")
        else:
            local_points = before[local_vertices]
            denominator = (
                body_tree.query(local_points, k=1)[0]
                + wheel_tree.query(local_points, k=1)[0]
            )
            local_weights = np.divide(
                wheel_tree.query(local_points, k=1)[0],
                denominator,
                out=np.full(len(local_vertices), 0.5),
                where=denominator > 1.0e-12,
            )
            weights[local_vertices] = local_weights
            unanchored += len(local_vertices)
            component_modes.append("euclidean-fallback")

    if np.any(~np.isfinite(weights)):
        raise SystemExit(
            f"Could not determine global morph weights for {suspension_key}"
        )

    weights = np.clip(weights, 0.0, 1.0)

    body_locked = body_anchor.copy()
    wheel_locked = wheel_anchor.copy()

    body_layer = (
        body_graph_distance <= float(body_rigid_layers)
    ) if body_rigid_layers > 0 else np.zeros(
        len(suspension_vertex_ids), dtype=bool
    )
    wheel_layer = (
        wheel_graph_distance <= float(wheel_rigid_layers)
    ) if wheel_rigid_layers > 0 else np.zeros(
        len(suspension_vertex_ids), dtype=bool
    )

    layer_overlap = body_layer & wheel_layer
    body_locked |= body_layer & ~layer_overlap
    wheel_locked |= wheel_layer & ~layer_overlap

    body_wins = layer_overlap & (
        body_graph_distance <= wheel_graph_distance
    )
    wheel_wins = layer_overlap & (
        wheel_graph_distance < body_graph_distance
    )
    body_locked |= body_wins
    wheel_locked |= wheel_wins

    if np.any(body_locked & wheel_locked):
        raise SystemExit(
            f"Body/wheel rigid transition overlap in {suspension_key}: "
            f"{np.count_nonzero(body_locked & wheel_locked)}"
        )

    # A smoothstep blend gives a rigid-like transition near each contact
    # instead of a direct linear pointwise displacement.
    body_blend = weights.copy()
    finite_distances = (
        np.isfinite(body_graph_distance)
        & np.isfinite(wheel_graph_distance)
    )
    ratio = np.divide(
        wheel_graph_distance,
        body_graph_distance + wheel_graph_distance,
        out=body_blend,
        where=finite_distances,
    )
    body_blend = np.clip(ratio, 0.0, 1.0)
    body_blend[body_locked] = 1.0
    body_blend[wheel_locked] = 0.0
    free = ~(body_locked | wheel_locked)

    target_body = body_targets[suspension_vertex_ids].copy()
    target_wheel = steering_transform(
        before,
        wheel_key,
        wheel_centers,
    )

    # Apply canonical global target coordinates at exact shared contacts.
    for local, global_id in enumerate(suspension_vertex_ids):
        global_target = target_vertices[int(global_id)]
        if np.all(np.isfinite(global_target)):
            if body_anchor[local]:
                target_body[local] = global_target
            if wheel_anchor[local]:
                target_wheel[local] = global_target

    degrees = np.asarray(
        graph.sum(axis=1)
    ).reshape(-1)
    degrees = np.maximum(degrees, 1.0)

    repair_iterations = 0
    remaining_flipped = 0
    remaining_zero_area = 0
    vertices_after = None
    bad_faces = np.array([], dtype=np.int64)

    for repair_iteration in range(max_repair_iterations + 1):
        smooth_blend = (
            body_blend * body_blend
            * (3.0 - 2.0 * body_blend)
        )

        vertices_after = (
            before
            + smooth_blend[:, None]
            * (target_body - before)
            + (1.0 - smooth_blend)[:, None]
            * (target_wheel - before)
        )

        for local, global_id in enumerate(suspension_vertex_ids):
            global_target = target_vertices[int(global_id)]
            if np.all(np.isfinite(global_target)) and (
                body_anchor[local] or wheel_anchor[local]
            ):
                vertices_after[local] = global_target

        bad_faces, zero_area = face_quality(
            before,
            vertices_after,
            local_faces,
        )
        remaining_flipped = int(len(bad_faces))
        remaining_zero_area = int(zero_area)
        repair_iterations = repair_iteration

        if remaining_flipped == 0 and remaining_zero_area == 0:
            break
        if repair_iteration >= max_repair_iterations:
            break

        bad_vertices = (
            np.unique(local_faces[bad_faces].reshape(-1))
            if remaining_flipped
            else np.array([], dtype=np.int64)
        )

        if remaining_zero_area:
            zero_mesh = trimesh.Trimesh(
                vertices=vertices_after,
                faces=local_faces,
                process=False,
            )
            zero_faces = np.flatnonzero(
                zero_mesh.area_faces <= 1.0e-14
            )
            if len(zero_faces):
                bad_vertices = np.unique(
                    np.concatenate(
                        [
                            bad_vertices,
                            local_faces[zero_faces].reshape(-1),
                        ]
                    )
                )

        if len(bad_vertices) == 0:
            break

        adjustable = bad_vertices[
            ~(
                body_locked[bad_vertices]
                | wheel_locked[bad_vertices]
            )
        ]

        if len(adjustable) == 0:
            break

        neighbour_average = (
            np.asarray(
                graph.dot(body_blend)
            ).reshape(-1)
            / degrees
        )

        old_blend = (
            body_blend[adjustable].copy()
        )

        reduced_blend = (
            0.5 * old_blend
            + 0.5 * neighbour_average[adjustable]
        )

        body_blend[adjustable] = np.minimum(
            reduced_blend,
            0.75 * old_blend,
        )

        body_blend[body_locked] = 1.0
        body_blend[wheel_locked] = 0.0

        body_blend = np.clip(
            body_blend,
            0.0,
            1.0,
        )

    report["parts"][suspension_key] = {
        "wheelReference": wheel_key,
        "deformationMethod": "rigid-transition-smoothstep",
        "bodyRigidLayers": int(body_rigid_layers),
        "wheelRigidLayers": int(wheel_rigid_layers),
        "vertexCount": int(len(suspension_vertex_ids)),
        "bodyAnchorVertices": int(
            np.count_nonzero(body_anchor)
        ),
        "wheelAnchorVertices": int(
            np.count_nonzero(wheel_anchor)
        ),
        "bodyLockedVertices": int(
            np.count_nonzero(body_locked)
        ),
        "wheelLockedVertices": int(
            np.count_nonzero(wheel_locked)
        ),
        "interpolatedVertices": int(
            np.count_nonzero(free)
        ),
        "connectedComponents": int(component_count),
        "repairIterations": int(repair_iterations),
        "maxDisplacement": float(
            np.linalg.norm(
                vertices_after - before,
                axis=1,
            ).max()
        ) if vertices_after is not None else 0.0,
        "flippedFaces": int(remaining_flipped),
        "zeroAreaFaces": int(remaining_zero_area),
    }

    if remaining_flipped or remaining_zero_area:
        bad_local_vertices = (
            np.unique(
                local_faces[bad_faces].reshape(-1)
            )
            if len(bad_faces)
            else np.array([], dtype=np.int64)
        )

        bad_global_vertices = (
            suspension_vertex_ids[bad_local_vertices]
            if len(bad_local_vertices)
            else np.array([], dtype=np.int64)
        )

        failure_info = {
            "suspension": suspension_key,
            "wheelReference": wheel_key,
            "flippedFaces": int(remaining_flipped),
            "zeroAreaFaces": int(remaining_zero_area),
            "repairIterations": int(repair_iterations),
            "badFaceIndices": (
                bad_faces[:500].tolist()
                if len(bad_faces)
                else []
            ),
            "badLocalVertexIndices": (
                bad_local_vertices[:1000].tolist()
            ),
            "badGlobalAssemblyVertexIndices": (
                bad_global_vertices[:1000].tolist()
            ),
            "badBodyAnchorVertices": int(
                np.count_nonzero(
                    body_anchor[bad_local_vertices]
                )
            ) if len(bad_local_vertices) else 0,
            "badWheelAnchorVertices": int(
                np.count_nonzero(
                    wheel_anchor[bad_local_vertices]
                )
            ) if len(bad_local_vertices) else 0,
            "badBodyLockedVertices": int(
                np.count_nonzero(
                    body_locked[bad_local_vertices]
                )
            ) if len(bad_local_vertices) else 0,
            "badWheelLockedVertices": int(
                np.count_nonzero(
                    wheel_locked[bad_local_vertices]
                )
            ) if len(bad_local_vertices) else 0,
        }

        report["parts"][suspension_key][
            "failureDiagnostics"
        ] = failure_info

        failure_report_path = (
            RESULTS / "rigid_transition_failure_report.json"
        )

        failure_report_path.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        if len(bad_faces):
            bad_before = trimesh.Trimesh(
                vertices=before.copy(),
                faces=local_faces[bad_faces],
                process=False,
            )
            bad_after = trimesh.Trimesh(
                vertices=vertices_after.copy(),
                faces=local_faces[bad_faces],
                process=False,
            )

            bad_before.export(
                RESULTS
                / f"{suspension_key}_bad_faces_before.stl"
            )
            bad_after.export(
                RESULTS
                / f"{suspension_key}_bad_faces_after.stl"
            )

        print(
            "Rigid-transition failure report:",
            failure_report_path,
        )

        if (
            (not ignore_flipped_faces)
            or remaining_zero_area
        ):
            raise SystemExit(
                f"Rigid-transition morph quality failed for "
                f"{suspension_key}: flippedFaces={remaining_flipped}, "
                f"zeroAreaFaces={remaining_zero_area}, "
                f"repairIterations={repair_iterations}"
            )
        else:
            print(
                "WARNING: flipped faces ignored in "
                "diagnostic mode:",
                suspension_key,
                "flippedFaces=",
                remaining_flipped,
            )

    target_vertices[suspension_vertex_ids] = vertices_after
    target_vertices[suspension_vertex_ids[body_anchor]] = (
        target_body[body_anchor]
    )
    target_vertices[suspension_vertex_ids[wheel_anchor]] = (
        target_wheel[wheel_anchor]
    )

# Any remaining global vertex must be assigned. Parts that are not suspension
# or wheels are sprung in the active manifest and were assigned body targets.
if np.any(~np.isfinite(target_vertices)):
    missing = int(np.count_nonzero(~np.isfinite(target_vertices).any(axis=1)))
    raise SystemExit(
        f"Global target field contains unassigned vertices: {missing}"
    )

reference_global = trimesh.Trimesh(
    vertices=assembly_vertices_m,
    faces=assembly_faces,
    process=False,
)
after_global = trimesh.Trimesh(
    vertices=target_vertices,
    faces=assembly_faces,
    process=False,
)
global_bad_faces, global_zero = face_quality(
    assembly_vertices_m,
    target_vertices,
    assembly_faces,
)
global_flipped = int(len(global_bad_faces))


report["globalQuality"] = {
    "watertight": bool(after_global.is_watertight),
    "windingConsistent": bool(after_global.is_winding_consistent),
    "flippedFaces": global_flipped,
    "zeroAreaFaces": global_zero,
}

if global_flipped or global_zero:
    if (
        global_zero
        or (
            global_flipped
            and not ignore_flipped_faces
        )
    ):
        raise SystemExit(
            "Global assembly quality failed: "
            f"flippedFaces={global_flipped}, "
            f"zeroAreaFaces={global_zero}"
        )

    print(
        "WARNING: global flipped faces ignored "
        "in diagnostic mode:",
        global_flipped,
    )


# Export each patch from the same globally transformed indexed vertices.
for part_key, face_indices in part_face_arrays.items():
    output = trimesh.Trimesh(
        vertices=target_vertices.copy(),
        faces=assembly_faces[face_indices],
        process=False,
    )
    output.remove_unreferenced_vertices()
    target_path = tri_dir / parts[part_key]["file"]
    output.export(target_path)
    print("Exported:", target_path, flush=True)

# Transform and export radiator volume sources separately.
if radiator_enabled:
    radiator_config = config.get("radiator", {}) or {}
    radiator_parts = radiator_config.get(
        "parts",
        {
            "radiatorLeft": "radiator_left_volume.stl",
            "radiatorRight": "radiator_right_volume.stl",
        },
    )
    for key, filename in radiator_parts.items():
        source = source_dir / filename
        if not source.exists():
            raise SystemExit(f"Missing radiator source STL: {source}")
        radiator_mesh = load_mesh(source, process=False)
        radiator_mesh.apply_scale(scale)
        radiator_mesh.vertices = body_transform(
            radiator_mesh.vertices,
            moment_center,
        )
        radiator_mesh.export(tri_dir / filename)
        del radiator_mesh
        gc.collect()

minimum = np.array([np.inf, np.inf, np.inf])
maximum = np.array([-np.inf, -np.inf, -np.inf])
minimum = np.minimum(minimum, after_global.bounds[0])
maximum = np.maximum(maximum, after_global.bounds[1])

if radiator_enabled:
    for key, filename in radiator_parts.items():
        radiator_mesh = load_mesh(
            tri_dir / filename,
            process=False,
        )
        minimum = np.minimum(minimum, radiator_mesh.bounds[0])
        maximum = np.maximum(maximum, radiator_mesh.bounds[1])
        del radiator_mesh

metrics = {
    "profile": profile,
    "bbox_m": [minimum.tolist(), maximum.tolist()],
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

metrics_path = CASE / "constant/geometryMetrics.json"
metrics_path.write_text(
    json.dumps(metrics, indent=2),
    encoding="utf-8",
)

report_path = RESULTS / "global_assembly_morph_report.json"
report_path.write_text(
    json.dumps(report, indent=2),
    encoding="utf-8",
)

print("Global assembly morph report:", report_path)
print("Updated geometry metrics:", metrics_path)
