"""Blender mesh input adapter: discover the object's single outer contour."""

import bmesh


def _ordered_cycle_points(bm, edges):
    edges = list(edges)
    if len(edges) < 3:
        raise ValueError("На объекте не найдена замкнутая граница минимум из трёх рёбер.")

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
    ordered = [start]
    current = start
    previous_edge = None

    while True:
        candidates = [
            edge for edge in current.link_edges
            if edge in edge_set and edge is not previous_edge
        ]
        if len(candidates) != 1:
            raise ValueError("Не удалось однозначно обойти границу объекта.")
        edge = candidates[0]
        next_vertex = edge.other_vert(current)
        if next_vertex is start:
            break
        if next_vertex in ordered:
            raise ValueError("Граница содержит самопересечение или несколько петель.")
        ordered.append(next_vertex)
        previous_edge, current = edge, next_vertex

    if len(ordered) != len(edges):
        raise ValueError(
            "Объект содержит несколько граничных контуров; сейчас поддерживается один."
        )

    return [tuple(float(value) for value in vertex.co) for vertex in ordered]


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
        if bm.faces:
            boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
        else:
            boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 0]
        if not boundary_edges:
            raise ValueError(
                "Не найдена открытая граница объекта. Нужен один контур из рёбер или край плоской сетки."
            )
        return _ordered_cycle_points(bm, boundary_edges)
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
