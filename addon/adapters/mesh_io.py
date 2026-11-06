"""Blender mesh input adapter."""
def read_selected_boundary(obj):
    import bmesh
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        edges = [e for e in bm.edges if e.select]
        if len(edges) < 3:
            raise ValueError("Выбери замкнутую петлю минимум из трёх рёбер.")
        degree = {}
        for edge in edges:
            for vert in edge.verts:
                degree[vert] = degree.get(vert, 0) + 1
        if any(value != 2 for value in degree.values()):
            raise ValueError("Выделенные рёбра не образуют одну замкнутую петлю.")
        start = edges[0].verts[0]
        ordered = [start]
        current = start
        previous_edge = None
        while True:
            candidates = [e for e in current.link_edges if e in edges and e is not previous_edge]
            if not candidates:
                raise ValueError("Не удалось упорядочить петлю.")
            edge = candidates[0]
            nxt = edge.other_vert(current)
            if nxt is start:
                break
            if nxt in ordered:
                raise ValueError("Выделение содержит несколько петель или самопересечение топологии.")
            ordered.append(nxt)
            previous_edge, current = edge, nxt
        if len(ordered) != len(edges):
            raise ValueError("Выделение должно содержать ровно одну замкнутую петлю.")
        return [(float(v.co.x), float(v.co.y)) for v in ordered]
    finally:
        bm.free()
