"""Blender mesh input adapter: discover the object's single outer contour."""

import bmesh

MAX_BOUNDARY_EDGES = 64
MAX_CONVEX_FLAT_BOUNDARY_EDGES = 256


def _boundary_edges_for_object_bmesh(bm):
    if bm.faces:
        edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    else:
        edges = [edge for edge in bm.edges if len(edge.link_faces) == 0]
    if not edges:
        raise ValueError(
            "Не найдена открытая граница объекта. Нужен один контур из рёбер или край плоской сетки."
        )
    return edges


def _ordered_cycle_topology(bm, edges, *, max_edges=MAX_BOUNDARY_EDGES):
    """Return boundary vertices and edges in the same deterministic order."""
    edges = list(edges)
    if len(edges) < 3:
        raise ValueError("На объекте не найдена замкнутая граница минимум из трёх рёбер.")
    if len(edges) > max_edges:
        raise ValueError(
            f"Эта alpha-версия RoofForge поддерживает максимум {max_edges} "
            "граничных рёбер. Упрости контур или уменьши число сегментов."
        )

    edge_set = set(edges)
    degree = {}
    for edge in edges:
        for vertex in edge.verts:
            degree[vertex] = degree.get(vertex, 0) + 1

    if any(value != 2 for value in degree.values()):
        raise ValueError(
            "Граница объекта должна быть одной простой замкнутой петлёй без ветвлений."
        )

    bm.verts.index_update()
    bm.edges.index_update()
    start = min(degree, key=lambda vertex: vertex.index)
    ordered_vertices = [start]
    ordered_edges = []
    current = start
    previous_edge = None

    while True:
        candidates = [
            edge for edge in current.link_edges
            if edge in edge_set and edge is not previous_edge
        ]
        if previous_edge is None and current is start:
            edge = min(candidates, key=lambda item: item.index)
        elif len(candidates) == 1:
            edge = candidates[0]
        else:
            raise ValueError("Не удалось однозначно обойти границу объекта.")
        next_vertex = edge.other_vert(current)
        ordered_edges.append(edge)
        if next_vertex is start:
            break
        if next_vertex in ordered_vertices:
            raise ValueError("Граница содержит самопересечение или несколько петель.")
        ordered_vertices.append(next_vertex)
        previous_edge, current = edge, next_vertex

    if len(ordered_vertices) != len(edges) or len(ordered_edges) != len(edges):
        raise ValueError(
            "Объект содержит несколько граничных контуров; сейчас поддерживается один."
        )
    return ordered_vertices, ordered_edges


def ordered_boundary_edge_vertex_indices(bm):
    """Return directed vertex-index pairs matching RoofForge's contour order."""
    edges = _boundary_edges_for_object_bmesh(bm)
    vertices, _ordered_edges = _ordered_cycle_topology(bm, edges)
    return [
        (vertices[index].index, vertices[(index + 1) % len(vertices)].index)
        for index in range(len(vertices))
    ]


def _ordered_cycle_points(bm, edges, *, max_edges=MAX_BOUNDARY_EDGES):
    vertices, _ordered_edges = _ordered_cycle_topology(bm, edges, max_edges=max_edges)
    return [tuple(float(value) for value in vertex.co) for vertex in vertices]


def read_object_boundary(obj):
    """Read the object's outer boundary without relying on mesh selection.

    For a surface mesh, use its one-face boundary edges. For a wire contour
    without faces, use its loose edges. The returned coordinates are local XYZ.
    """
    owns_bmesh = obj.mode != "EDIT"
    bm = bmesh.new() if owns_bmesh else bmesh.from_edit_mesh(obj.data)
    if owns_bmesh:
        bm.from_mesh(obj.data)

    try:
        boundary_edges = _boundary_edges_for_object_bmesh(bm)
        points = _ordered_cycle_points(
            bm,
            boundary_edges,
            max_edges=MAX_CONVEX_FLAT_BOUNDARY_EDGES,
        )
        if len(points) > MAX_BOUNDARY_EDGES:
            # The higher limit is deliberately restricted to flat convex
            # footprints. Concave and mixed-height contours retain the
            # conservative 64-edge limit until their large-loop solvers are
            # profiled and validated independently.
            from ...core.overhang import is_convex_contour_xy
            from ...core.wavefront import is_flat_eave_contour

            if not (
                is_flat_eave_contour(points)
                and is_convex_contour_xy(points)
            ):
                raise ValueError(
                    f"Эта alpha-версия RoofForge поддерживает максимум {MAX_BOUNDARY_EDGES} "
                    "граничных рёбер для вогнутых и неплоских контуров. "
                    f"Плоские выпуклые контуры поддерживают до {MAX_CONVEX_FLAT_BOUNDARY_EDGES} рёбер."
                )
        return points
    finally:
        if owns_bmesh:
            bm.free()


def read_selected_boundary(obj):
    """Backward-compatible helper for explicitly selected edge loops."""
    owns_bmesh = obj.mode != "EDIT"
    bm = bmesh.new() if owns_bmesh else bmesh.from_edit_mesh(obj.data)
    if owns_bmesh:
        bm.from_mesh(obj.data)
    try:
        selected_edges = [edge for edge in bm.edges if edge.select]
        if not selected_edges:
            raise ValueError("Не выбраны рёбра границы.")
        return _ordered_cycle_points(bm, selected_edges)
    finally:
        if owns_bmesh:
            bm.free()
