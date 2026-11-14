"""Topology validation helpers for generated closed meshes.

This module is pure Python and deliberately independent of bpy/bmesh.
"""
from __future__ import annotations

from collections import defaultdict, deque
from heapq import heappop, heappush
from math import isfinite, sqrt
from typing import Sequence

from .geometry import Diagnostic

Point3 = tuple[float, float, float]
Face = tuple[int, ...]



def _sub3(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot3(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross3(a: Point3, b: Point3) -> Point3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length3(value: Point3) -> float:
    return sqrt(_dot3(value, value))


def _triangle_normal(triangle: tuple[Point3, Point3, Point3]) -> Point3:
    return _cross3(_sub3(triangle[1], triangle[0]), _sub3(triangle[2], triangle[0]))


def _triangle_aabb(triangle: tuple[Point3, Point3, Point3]):
    return (
        tuple(min(point[axis] for point in triangle) for axis in range(3)),
        tuple(max(point[axis] for point in triangle) for axis in range(3)),
    )


def _aabbs_overlap(first, second, tolerance: float) -> bool:
    first_min, first_max = first
    second_min, second_max = second
    return all(
        first_min[axis] <= second_max[axis] + tolerance
        and second_min[axis] <= first_max[axis] + tolerance
        for axis in range(3)
    )


def _orient2(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_on_segment2(point, start, end, linear_tolerance: float, area_tolerance: float) -> bool:
    if abs(_orient2(start, end, point)) > area_tolerance:
        return False
    return (
        min(start[0], end[0]) - linear_tolerance <= point[0] <= max(start[0], end[0]) + linear_tolerance
        and min(start[1], end[1]) - linear_tolerance <= point[1] <= max(start[1], end[1]) + linear_tolerance
    )


def _segments_intersect2(a, b, c, d, linear_tolerance: float, area_tolerance: float) -> bool:
    o1 = _orient2(a, b, c)
    o2 = _orient2(a, b, d)
    o3 = _orient2(c, d, a)
    o4 = _orient2(c, d, b)
    if ((o1 > area_tolerance and o2 < -area_tolerance) or (o1 < -area_tolerance and o2 > area_tolerance)) and (
        (o3 > area_tolerance and o4 < -area_tolerance) or (o3 < -area_tolerance and o4 > area_tolerance)
    ):
        return True
    return (
        (abs(o1) <= area_tolerance and _point_on_segment2(c, a, b, linear_tolerance, area_tolerance))
        or (abs(o2) <= area_tolerance and _point_on_segment2(d, a, b, linear_tolerance, area_tolerance))
        or (abs(o3) <= area_tolerance and _point_on_segment2(a, c, d, linear_tolerance, area_tolerance))
        or (abs(o4) <= area_tolerance and _point_on_segment2(b, c, d, linear_tolerance, area_tolerance))
    )


def _point_in_triangle2(point, triangle, area_tolerance: float) -> bool:
    a, b, c = triangle
    values = (_orient2(a, b, point), _orient2(b, c, point), _orient2(c, a, point))
    return not (any(value > area_tolerance for value in values) and any(value < -area_tolerance for value in values))


def _coplanar_triangles_intersect(
    first: tuple[Point3, Point3, Point3],
    second: tuple[Point3, Point3, Point3],
    normal: Point3,
    tolerance: float,
) -> bool:
    drop_axis = max(range(3), key=lambda axis: abs(normal[axis]))
    keep_axes = tuple(axis for axis in range(3) if axis != drop_axis)
    first_2d = tuple((point[keep_axes[0]], point[keep_axes[1]]) for point in first)
    second_2d = tuple((point[keep_axes[0]], point[keep_axes[1]]) for point in second)
    longest_edge = max(
        sqrt((triangle[(index + 1) % 3][0] - triangle[index][0]) ** 2
             + (triangle[(index + 1) % 3][1] - triangle[index][1]) ** 2
             + (triangle[(index + 1) % 3][2] - triangle[index][2]) ** 2)
        for triangle in (first, second)
        for index in range(3)
    )
    area_tolerance = tolerance * max(1.0, longest_edge)
    for first_index in range(3):
        a = first_2d[first_index]
        b = first_2d[(first_index + 1) % 3]
        for second_index in range(3):
            c = second_2d[second_index]
            d = second_2d[(second_index + 1) % 3]
            if _segments_intersect2(a, b, c, d, tolerance, area_tolerance):
                return True
    return (
        _point_in_triangle2(first_2d[0], second_2d, area_tolerance)
        or _point_in_triangle2(second_2d[0], first_2d, area_tolerance)
    )


def _triangle_plane_interval(
    triangle: tuple[Point3, Point3, Point3],
    plane_origin: Point3,
    plane_normal: Point3,
    line_direction: Point3,
    tolerance: float,
):
    distances = tuple(_dot3(plane_normal, _sub3(point, plane_origin)) for point in triangle)
    if min(distances) > tolerance or max(distances) < -tolerance:
        return None
    points = []
    for index in range(3):
        first = triangle[index]
        second = triangle[(index + 1) % 3]
        first_distance = distances[index]
        second_distance = distances[(index + 1) % 3]
        if abs(first_distance) <= tolerance:
            points.append(first)
        if (first_distance < -tolerance and second_distance > tolerance) or (
            first_distance > tolerance and second_distance < -tolerance
        ):
            factor = first_distance / (first_distance - second_distance)
            points.append(tuple(
                first[axis] + (second[axis] - first[axis]) * factor
                for axis in range(3)
            ))
    if not points:
        return None
    coordinates = [_dot3(point, line_direction) for point in points]
    return min(coordinates), max(coordinates)


def _triangles_intersect(
    first: tuple[Point3, Point3, Point3],
    second: tuple[Point3, Point3, Point3],
    tolerance: float,
) -> bool:
    first_normal_raw = _triangle_normal(first)
    second_normal_raw = _triangle_normal(second)
    first_length = _length3(first_normal_raw)
    second_length = _length3(second_normal_raw)
    if first_length <= tolerance * tolerance or second_length <= tolerance * tolerance:
        return False
    first_normal = tuple(value / first_length for value in first_normal_raw)
    second_normal = tuple(value / second_length for value in second_normal_raw)
    line_raw = _cross3(first_normal, second_normal)
    line_length = _length3(line_raw)
    if line_length <= 1.0e-12:
        plane_distance = abs(_dot3(first_normal, _sub3(second[0], first[0])))
        if plane_distance > tolerance:
            return False
        return _coplanar_triangles_intersect(first, second, first_normal, tolerance)

    line_direction = tuple(value / line_length for value in line_raw)
    first_interval = _triangle_plane_interval(first, second[0], second_normal, line_direction, tolerance)
    if first_interval is None:
        return False
    second_interval = _triangle_plane_interval(second, first[0], first_normal, line_direction, tolerance)
    if second_interval is None:
        return False
    return max(first_interval[0], second_interval[0]) <= min(first_interval[1], second_interval[1]) + tolerance


def _self_intersection_diagnostics(
    vertices: Sequence[Point3],
    faces: Sequence[Face],
    tolerance: float,
) -> list[Diagnostic]:
    """Sweep non-adjacent face triangles through AABB and exact intersection tests."""
    triangles = []
    face_vertex_sets = [set(face) for face in faces]
    for face_index, face in enumerate(faces):
        if len(face) < 3 or any(index < 0 or index >= len(vertices) for index in face):
            continue
        # RoofForge-generated cells are convex planar polygons, so a fan
        # preserves their exact footprint for the intersection test.
        for local_index in range(1, len(face) - 1):
            indices = (face[0], face[local_index], face[local_index + 1])
            points = tuple(vertices[index] for index in indices)
            if _length3(_triangle_normal(points)) <= tolerance * tolerance:
                continue
            triangles.append((face_index, points, _triangle_aabb(points)))

    # Pick the sweep axis with the fewest one-dimensional AABB overlaps.
    # Roof faces are often much thinner in Z than in X/Y, so a fixed X sweep
    # can leave hundreds of needless candidates active for each triangle.
    candidate_counts = []
    for axis in range(3):
        ordered = sorted(triangles, key=lambda item: item[2][0][axis])
        maxima = []
        pair_count = 0
        for item in ordered:
            minimum = item[2][0][axis]
            while maxima and maxima[0] + tolerance < minimum:
                heappop(maxima)
            pair_count += len(maxima)
            heappush(maxima, item[2][1][axis])
        candidate_counts.append(pair_count)
    sweep_axis = min(range(3), key=lambda axis: candidate_counts[axis])
    triangles.sort(key=lambda item: item[2][0][sweep_axis])
    diagnostics = []
    reported_pairs: set[tuple[int, int]] = set()
    active = []
    for current in triangles:
        face_index, current_points, current_bounds = current
        current_min = current_bounds[0][sweep_axis]
        active = [item for item in active if item[2][1][sweep_axis] + tolerance >= current_min]
        for other in active:
            other_face_index, other_points, other_bounds = other
            if face_index == other_face_index:
                continue
            pair = (min(face_index, other_face_index), max(face_index, other_face_index))
            if pair in reported_pairs or face_vertex_sets[face_index] & face_vertex_sets[other_face_index]:
                continue
            if not _aabbs_overlap(current_bounds, other_bounds, tolerance):
                continue
            if _triangles_intersect(current_points, other_points, tolerance):
                reported_pairs.add(pair)
                diagnostics.append(Diagnostic(
                    "SELF_INTERSECTION",
                    f"Грани {pair[0] + 1} и {pair[1] + 1} геометрически пересекаются. "
                    "Проверьте сложные узлы и пересекающиеся участки крыши.",
                ))
        active.append(current)
    return diagnostics



def validate_closed_mesh(vertices: Sequence[Point3], faces: Sequence[Face],
                         eps: float = 1e-10) -> list[Diagnostic]:
    """Validate a closed, consistently wound, vertex-manifold surface mesh.

    Checks finite coordinates, valid/non-degenerate faces, duplicate faces,
    edge incidence and opposite edge winding, connected components, the
    cyclic link condition at every vertex, and geometric self-intersections
    between non-adjacent face triangles.
    """
    diagnostics: list[Diagnostic] = []
    if not vertices:
        return [Diagnostic("EMPTY_MESH", "Сетка не содержит вершин.")]
    if not faces:
        return [Diagnostic("EMPTY_MESH", "Сетка не содержит граней.")]

    if any(len(point) != 3 or not all(isfinite(value) for value in point) for point in vertices):
        return [Diagnostic("NON_FINITE_VERTEX", "Сетка содержит вершины с NaN или бесконечными координатами.")]

    min_values = [min(point[axis] for point in vertices) for axis in range(3)]
    max_values = [max(point[axis] for point in vertices) for axis in range(3)]
    scale = max(1.0, sqrt(sum((max_values[i] - min_values[i]) ** 2 for i in range(3))))
    length_eps = eps * scale

    edge_uses: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    vertex_neighbors: dict[int, set[int]] = defaultdict(set)
    vertex_link_edges: dict[int, set[tuple[int, int]]] = defaultdict(set)
    used_vertices: set[int] = set()
    face_keys: set[tuple[int, ...]] = set()

    for face_index, face in enumerate(faces):
        if len(face) < 3:
            diagnostics.append(Diagnostic(
                "DEGENERATE_FACE", f"Грань {face_index} содержит менее трёх вершин."
            ))
            continue
        if any(not isinstance(index, int) or index < 0 or index >= len(vertices) for index in face):
            diagnostics.append(Diagnostic(
                "INVALID_FACE_INDEX", f"Грань {face_index} содержит неверный индекс вершины."
            ))
            continue
        if len(set(face)) != len(face):
            diagnostics.append(Diagnostic(
                "DEGENERATE_FACE", f"Грань {face_index} повторно использует одну из вершин."
            ))
            continue

        face_key = tuple(sorted(face))
        if face_key in face_keys:
            diagnostics.append(Diagnostic(
                "DUPLICATE_FACE", f"Грань {face_index} дублирует другую грань."
            ))
        face_keys.add(face_key)

        # Newell's formula gives a stable area vector for planar n-gons.
        # Compare against the global linear-coordinate tolerance multiplied
        # by this face's own longest edge. A global scale^2 threshold rejects
        # small but well-shaped local facets on otherwise large meshes.
        nx = ny = nz = 0.0
        max_edge_length_sq = 0.0
        for local_index, current_index in enumerate(face):
            current = vertices[current_index]
            nxt = vertices[face[(local_index + 1) % len(face)]]
            nx += (current[1] - nxt[1]) * (current[2] + nxt[2])
            ny += (current[2] - nxt[2]) * (current[0] + nxt[0])
            nz += (current[0] - nxt[0]) * (current[1] + nxt[1])
            edge_length_sq = sum(
                (current[axis] - nxt[axis]) ** 2 for axis in range(3)
            )
            max_edge_length_sq = max(max_edge_length_sq, edge_length_sq)
        area = 0.5 * sqrt(nx * nx + ny * ny + nz * nz)
        area_eps = length_eps * sqrt(max_edge_length_sq)
        if area <= area_eps:
            diagnostics.append(Diagnostic(
                "ZERO_AREA_FACE", f"Грань {face_index} имеет нулевую или слишком малую площадь."
            ))

        for local_index, current_index in enumerate(face):
            previous_index = face[local_index - 1]
            next_index = face[(local_index + 1) % len(face)]
            used_vertices.add(current_index)
            vertex_neighbors[current_index].update((previous_index, next_index))
            link_edge = (min(previous_index, next_index), max(previous_index, next_index))
            vertex_link_edges[current_index].add(link_edge)

            edge_key = (min(current_index, next_index), max(current_index, next_index))
            edge_uses[edge_key].append((face_index, current_index, next_index))

    if len(used_vertices) != len(vertices):
        diagnostics.append(Diagnostic(
            "UNUSED_VERTEX",
            f"Сетка содержит неиспользуемых вершин: {len(vertices) - len(used_vertices)}."
        ))

    for edge, uses in edge_uses.items():
        if len(uses) == 1:
            diagnostics.append(Diagnostic(
                "BOUNDARY_EDGE", f"Ребро {edge} принадлежит только одной грани."
            ))
        elif len(uses) > 2:
            diagnostics.append(Diagnostic(
                "NON_MANIFOLD_EDGE", f"Ребро {edge} принадлежит {len(uses)} граням."
            ))
        elif len(uses) == 2:
            first, second = uses
            if first[1] != second[2] or first[2] != second[1]:
                diagnostics.append(Diagnostic(
                    "INCONSISTENT_WINDING",
                    f"Соседние грани используют ребро {edge} в одном направлении."
                ))

    # The link of every vertex in a closed 2-manifold must be one connected
    # cycle. Two disjoint cycles detect shells that touch at a single vertex.
    for vertex_index in used_vertices:
        link_edges = vertex_link_edges[vertex_index]
        adjacency: dict[int, set[int]] = defaultdict(set)
        for first, second in link_edges:
            adjacency[first].add(second)
            adjacency[second].add(first)
        if not adjacency or any(len(neighbors) != 2 for neighbors in adjacency.values()):
            diagnostics.append(Diagnostic(
                "NON_MANIFOLD_VERTEX",
                f"Вершина {vertex_index} не имеет кольцевого manifold-окружения."
            ))
            continue
        start = next(iter(adjacency))
        visited = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        if len(visited) != len(adjacency):
            diagnostics.append(Diagnostic(
                "NON_MANIFOLD_VERTEX",
                f"У вершины {vertex_index} несколько несвязанных циклов соседства."
            ))

    # A generated roof shell is expected to be one connected object.
    if used_vertices:
        start = next(iter(used_vertices))
        visited = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in vertex_neighbors[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        if len(visited) != len(used_vertices):
            diagnostics.append(Diagnostic(
                "DISCONNECTED_COMPONENTS",
                "Сетка состоит из нескольких несвязанных компонентов."
            ))

    diagnostics.extend(_self_intersection_diagnostics(vertices, faces, length_eps))
    return diagnostics
