"""Topology validation helpers for generated closed meshes.

This module is pure Python and deliberately independent of bpy/bmesh.
"""
from __future__ import annotations

from collections import defaultdict, deque
from math import isfinite, sqrt
from typing import Sequence

from .geometry import Diagnostic

Point3 = tuple[float, float, float]
Face = tuple[int, ...]


def validate_closed_mesh(vertices: Sequence[Point3], faces: Sequence[Face],
                         eps: float = 1e-10) -> list[Diagnostic]:
    """Validate a closed, consistently wound, vertex-manifold surface mesh.

    Checks finite coordinates, valid/non-degenerate faces, duplicate faces,
    edge incidence and opposite edge winding, connected components, and the
    cyclic link condition at every vertex (which catches bow-tie vertices).
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
    area_eps = eps * scale * scale

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
        nx = ny = nz = 0.0
        for local_index, current_index in enumerate(face):
            current = vertices[current_index]
            nxt = vertices[face[(local_index + 1) % len(face)]]
            nx += (current[1] - nxt[1]) * (current[2] + nxt[2])
            ny += (current[2] - nxt[2]) * (current[0] + nxt[0])
            nz += (current[0] - nxt[0]) * (current[1] + nxt[1])
        area = 0.5 * sqrt(nx * nx + ny * ny + nz * nz)
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

    return diagnostics
