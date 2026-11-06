"""Blender mesh input adapter."""


def read_selected_boundary(obj):
    """Read exactly one selected closed edge loop in object-local XYZ space."""
    import bmesh

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        edges = [edge for edge in bm.edges if edge.select]
        if len(edges) < 3:
            raise ValueError("Выбери замкнутую петлю минимум из трёх рёбер.")

        degree = {}
        for edge in edges:
            for vert in edge.verts:
                degree[vert] = degree.get(vert, 0) + 1
        if any(value != 2 for value in degree.values()):
            raise ValueError("Выделенные рёбра не образуют одну замкнутую петлю.")

        edge_set = set(edges)
        start = edges[0].verts[0]
        ordered = [start]
        current = start
        previous_edge = None
        while True:
            candidates = [
                edge for edge in current.link_edges
                if edge in edge_set and edge is not previous_edge
            ]
            if not candidates:
                raise ValueError("Не удалось упорядочить замкнутую петлю.")
            edge = candidates[0]
            next_vert = edge.other_vert(current)
            if next_vert is start:
                break
            if next_vert in ordered:
                raise ValueError("Выделение содержит несколько петель или некорректный обход.")
            ordered.append(next_vert)
            previous_edge, current = edge, next_vert

        if len(ordered) != len(edges):
            raise ValueError("Выделение должно содержать ровно одну замкнутую петлю.")

        return [tuple(float(value) for value in vert.co) for vert in ordered]
    finally:
        bm.free()
