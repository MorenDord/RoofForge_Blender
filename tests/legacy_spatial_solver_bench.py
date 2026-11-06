"""Benchmark the historical Python 2.9 spatial solver in isolation.

This code is retained for comparison only and is not part of the extension.
"""
from __future__ import annotations

import math
import statistics
import sys
import time
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "legacy_spatial_solver"))

import spatial_roof_2_9_0 as spatial_module
from spatial_roof_2_9_0 import build_spatial_roof_mesh, SpatialRoofError


def radial_polygon(count: int, concave: bool):
    result = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        if concave:
            angle += 0.045 * math.sin(0.7 * index)
            radius = 8.6 + 1.05 * math.sin(1.73 * index + 0.2) + 0.55 * math.cos(2.41 * index)
        else:
            radius = 10.0 * (1.0 + 0.0015 * math.sin(7.0 * angle) + 0.0008 * math.cos(11.0 * angle))
        result.append((radius * math.cos(angle), radius * math.sin(angle), 0.0))
    return result


def check_shell(vertices, faces):
    surface_uses = Counter()
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            surface_uses[tuple(sorted((int(a), int(b))))] += 1
    if not surface_uses or any(value not in (1, 2) for value in surface_uses.values()):
        raise ValueError("surface contains non-manifold edges")
    count = len(vertices)
    shell_uses = Counter()
    def add(face):
        for a, b in zip(face, face[1:] + face[:1]):
            shell_uses[tuple(sorted((int(a), int(b))))] += 1
    for face in faces:
        add(face)
        add(tuple(reversed([int(index) + count for index in face])))
    for (a, b), uses in surface_uses.items():
        if uses == 1:
            add((a, b, b + count, a + count))
    bad = [edge for edge, uses in shell_uses.items() if uses != 2]
    if bad:
        raise ValueError(f"closed shell has {len(bad)} non-manifold edges")
    return count * 2, len(faces) * 2 + sum(value == 1 for value in surface_uses.values())


def run_case(label, points, pitch_degrees, repeats=2):
    pitches = [math.radians(value) for value in pitch_degrees]
    durations = []
    stats = None
    try:
        for _ in range(repeats):
            start = time.perf_counter()
            vertices, faces, sources = build_spatial_roof_mesh(points, pitches)
            shell_vertices, shell_faces = check_shell(vertices, faces)
            durations.append((time.perf_counter() - start) * 1000.0)
            stats = (len(vertices), len(faces), len(set(sources)), shell_vertices, shell_faces)
        ordered = sorted(durations)
        median = statistics.median(ordered)
        p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
        print(f"{label},{len(points)},ok,{median:.3f},{p95:.3f},{stats[0]},{stats[1]},{stats[2]},{stats[3]},{stats[4]},")
    except Exception as exc:
        message = str(exc).replace(",", ";").replace("\n", " ")[:220]
        print(f"{label},{len(points)},error,,,,,,,," + repr(message))


def run_all_pairs_nonplanar(label, points, pitch_degrees):
    """Exercise the unconstrained all-pairs lower-envelope alternative."""
    started = time.perf_counter()
    try:
        count = len(points)
        scale = max(
            max(point[0] for point in points) - min(point[0] for point in points),
            max(point[1] for point in points) - min(point[1] for point in points),
            1.0,
        )
        eps = max(scale * 1.0e-9, 1.0e-9)
        pitches = [math.radians(value) for value in pitch_degrees]
        planes = [
            spatial_module._edge_plane(
                points[index], points[(index + 1) % count], pitches[index], 0.0
            )
            for index in range(count)
        ]
        vertices, faces, sources = spatial_module._build_nonplanar_lower_envelope(
            points, planes, eps
        )
        spatial_module._validate_lifted_mesh(
            vertices, faces, sources, points, planes, eps, scale
        )
        shell_vertices, shell_faces = check_shell(vertices, faces)
        elapsed = (time.perf_counter() - started) * 1000.0
        print(
            f"{label},{count},ok,{elapsed:.3f},{elapsed:.3f},"
            f"{len(vertices)},{len(faces)},{len(set(sources))},"
            f"{shell_vertices},{shell_faces},"
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        message = str(exc).replace(",", ";").replace("\\n", " ")[:220]
        print(f"{label},{len(points)},error,{elapsed:.3f},{elapsed:.3f},,,,,," + repr(message))


def run_all_pairs_arrangement(label, points, pitch_degrees):
    """Try the DCEL planar support arrangement with no topology adjacency mask."""
    started = time.perf_counter()
    try:
        count = len(points)
        scale = max(
            max(point[0] for point in points) - min(point[0] for point in points),
            max(point[1] for point in points) - min(point[1] for point in points),
            1.0,
        )
        eps = max(scale * 1.0e-9, 1.0e-9)
        pitches = [math.radians(value) for value in pitch_degrees]
        planes = [
            spatial_module._edge_plane(
                points[index], points[(index + 1) % count], pitches[index], 0.0
            )
            for index in range(count)
        ]
        vertices, faces, sources = spatial_module._build_planar_support_arrangement(
            points, planes, eps, allowed_pairs=None, label_by_minimum=True
        )
        spatial_module._validate_lifted_mesh(
            vertices, faces, sources, points, planes, eps, scale
        )
        shell_vertices, shell_faces = check_shell(vertices, faces)
        elapsed = (time.perf_counter() - started) * 1000.0
        print(
            f"{label},{count},ok,{elapsed:.3f},{elapsed:.3f},"
            f"{len(vertices)},{len(faces)},{len(set(sources))},"
            f"{shell_vertices},{shell_faces},"
        )
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        message = str(exc).replace(",", ";").replace("\\n", " ")[:220]
        print(f"{label},{len(points)},error,{elapsed:.3f},{elapsed:.3f},,,,,," + repr(message))


def main():
    print("case,n,status,median_ms,p95_ms,top_vertices,top_faces,source_ids,shell_vertices,shell_faces,error")
    for n in (8, 16, 32, 64, 128):
        for concave in (False, True):
            points = radial_polygon(n, concave)
            pitch = [35.0 + ((i * 17 % 19) if (i % 2 == 1) else 0.0) for i in range(n)]
            label = "radial_concave" if concave else "radial_convex"
            run_case(label + "_equal_pitch", points, [35.0] * n)
            run_case(label + "_variable_pitch", points, pitch)

    l_xy = [(0,0),(8,0),(8,4),(4,4),(4,8),(0,8)]
    run_case("L_equal_pitch", [(x,y,0.0) for x,y in l_xy], [35.0]*6)
    run_case("L_variable_pitch", [(x,y,0.0) for x,y in l_xy], [30,36,42,34,39,32])
    u_xy = [(0,0),(10,0),(10,8),(7,8),(7,3),(3,3),(3,8),(0,8)]
    run_case("U_equal_pitch", [(x,y,0.0) for x,y in u_xy], [35.0]*8)
    run_case("U_variable_pitch", [(x,y,0.0) for x,y in u_xy], [32,35,38,40,34,37,31,36])

    multi_xy = [(0,0),(12,0),(12,8),(10,8),(9,4),(8,4),(7,7),(5,7),(4,4),(3,4),(2,8),(0,8)]
    run_case("multi_notch_equal_pitch", [(x,y,0.0) for x,y in multi_xy], [35.0]*12)
    run_case("multi_notch_variable_pitch", [(x,y,0.0) for x,y in multi_xy], [34,35,36,37,34,38,33,36,35,37,34,36])

    nonplanar_l = [(0,0,0.0),(8,0,0.08),(8,4,0.12),(4,4,0.16),(4,8,0.20),(0,8,0.10)]
    run_case("nonplanar_L_equal_pitch", nonplanar_l, [35.0]*6)
    run_case("nonplanar_L_variable_pitch", nonplanar_l, [33,35,37,36,38,34])
    nonplanar_u = [(0,0,0.0),(10,0,0.08),(10,8,0.14),(7,8,0.20),(7,3,0.12),(3,3,0.18),(3,8,0.24),(0,8,0.10)]
    run_case("nonplanar_U_equal_pitch", nonplanar_u, [35.0]*8)
    run_case("nonplanar_U_variable_pitch", nonplanar_u, [33,35,37,38,34,36,32,37])

    run_all_pairs_nonplanar("all_pairs_nonplanar_L_equal_pitch", nonplanar_l, [35.0]*6)
    run_all_pairs_nonplanar("all_pairs_nonplanar_L_variable_pitch", nonplanar_l, [33,35,37,36,38,34])
    run_all_pairs_nonplanar("all_pairs_nonplanar_U_equal_pitch", nonplanar_u, [35.0]*8)
    run_all_pairs_nonplanar("all_pairs_nonplanar_U_variable_pitch", nonplanar_u, [33,35,37,38,34,36,32,37])

    run_all_pairs_arrangement("all_pairs_arrangement_L_equal_pitch", nonplanar_l, [35.0]*6)
    run_all_pairs_arrangement("all_pairs_arrangement_L_variable_pitch", nonplanar_l, [33,35,37,36,38,34])
    run_all_pairs_arrangement("all_pairs_arrangement_U_equal_pitch", nonplanar_u, [35.0]*8)
    run_all_pairs_arrangement("all_pairs_arrangement_U_variable_pitch", nonplanar_u, [33,35,37,38,34,36,32,37])


if __name__ == "__main__":
    main()
