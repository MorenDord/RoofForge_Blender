"""Roof ridge/valley topology and inset profile geometry.

Ported from RoofForge 2.9.2 weighted-endpoint-fix. The geometry functions are
pure Python and operate on a shared top-surface vertex/face table.
"""
from collections import defaultdict
import math


class RoofDetailsError(RuntimeError):
    """Invalid ridge/valley detail geometry."""


SkeletonError = RoofDetailsError


def _key3(point, tolerance):
    return tuple(int(round(float(value) / tolerance)) for value in point)


def _sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length3(value):
    return math.sqrt(_dot3(value, value))


def _cross3(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _newell_normal(points):
    normal = [0.0, 0.0, 0.0]
    for i, point in enumerate(points):
        nxt = points[(i + 1) % len(points)]
        normal[0] += (point[1] - nxt[1]) * (point[2] + nxt[2])
        normal[1] += (point[2] - nxt[2]) * (point[0] + nxt[0])
        normal[2] += (point[0] - nxt[0]) * (point[1] + nxt[1])
    return tuple(normal)


def _unit_face_normal(vertices, face):
    points = [vertices[index] for index in face]
    normal = _newell_normal(points)
    length = _length3(normal)
    if length <= 1.0e-12:
        raise SkeletonError("Straight skeleton: вырожденная грань при расчёте нормали.")
    result = tuple(component / length for component in normal)
    if result[2] < 0.0:
        result = tuple(-component for component in result)
    return result


def _validate_face_planarity(vertices, faces, tolerance):
    for face_index, face in enumerate(faces):
        if len(face) < 3:
            raise SkeletonError("Straight skeleton: найден скат менее чем с тремя вершинами.")
        origin = vertices[face[0]]
        normal = None
        for i in range(1, len(face) - 1):
            a = _sub3(vertices[face[i]], origin)
            b = _sub3(vertices[face[i + 1]], origin)
            candidate = _cross3(a, b)
            if _length3(candidate) > tolerance * tolerance:
                normal = candidate
                break
        if normal is None:
            raise SkeletonError("Straight skeleton: вырожденный скат.")
        normal_length = _length3(normal)
        for index in face:
            distance = abs(_dot3(normal, _sub3(vertices[index], origin))) / normal_length
            if distance > tolerance * 20.0:
                raise SkeletonError(
                    "Straight skeleton: получен неплоский скат. Проверьте почти вырожденные углы контура."
                )


def _orient_closed_mesh_faces(vertices, faces):
    """Orient a closed polygon mesh consistently, component by component."""
    edge_uses = defaultdict(list)
    for face_index, face in enumerate(faces):
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((face_index, a, b))
    if any(len(uses) != 2 for uses in edge_uses.values()):
        raise SkeletonError("Нельзя согласовать нормали: профильная оболочка не замкнута.")

    face_edges = [[] for _ in faces]
    for uses in edge_uses.values():
        first, second = uses
        face_edges[first[0]].append((first[1], first[2], second[0], second[1], second[2]))
        face_edges[second[0]].append((second[1], second[2], first[0], first[1], first[2]))

    flip = {}
    components = []
    for start in range(len(faces)):
        if start in flip:
            continue
        flip[start] = False
        stack = [start]
        component = []
        while stack:
            current = stack.pop()
            component.append(current)
            for a, b, neighbour, na, nb in face_edges[current]:
                effective_a, effective_b = (b, a) if flip[current] else (a, b)
                # Neighbour must traverse the shared edge in the opposite direction.
                required_flip = (na == effective_a and nb == effective_b)
                if neighbour not in flip:
                    flip[neighbour] = required_flip
                    stack.append(neighbour)
                elif flip[neighbour] != required_flip:
                    raise SkeletonError("В профильной оболочке обнаружена неориентируемая связность.")
        components.append(component)

    result = [tuple(reversed(face)) if flip[i] else tuple(face)
              for i, face in enumerate(faces)]
    # Choose the outward orientation from the signed volume of each closed shell.
    for component in components:
        volume6 = 0.0
        for face_index in component:
            face = result[face_index]
            if len(face) < 3:
                continue
            origin = vertices[face[0]]
            for i in range(1, len(face) - 1):
                b = vertices[face[i]]
                c = vertices[face[i + 1]]
                volume6 += (
                    origin[0] * (b[1] * c[2] - b[2] * c[1])
                    + origin[1] * (b[2] * c[0] - b[0] * c[2])
                    + origin[2] * (b[0] * c[1] - b[1] * c[0])
                )
        if volume6 < 0.0:
            for face_index in component:
                result[face_index] = tuple(reversed(result[face_index]))
    return result


def extract_roof_seams(vertices, faces, face_source_ids, polygon_ccw):
    """Extract only real dihedral breaks between roof facets.

    Coplanar adjacent faces (180-degree continuation) are not seams and never
    create a ridge/valley profile. For all other shared edges, the signed
    dihedral orientation determines whether the edge is a convex ridge or a
    concave valley. This remains valid after coplanar face dissolution has
    combined several original source facets into one n-gon.
    """
    edge_uses = defaultdict(list)
    for face_index, face in enumerate(faces):
        for i, a in enumerate(face):
            b = face[(i + 1) % len(face)]
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((face_index, a, b))

    normals = [_unit_face_normal(vertices, face) for face in faces]
    records = []
    angle_tolerance = 1.0e-7

    for _key, uses in edge_uses.items():
        if len(uses) != 2:
            continue
        (face_a, a0, a1), (face_b, b0, b1) = uses
        if a0 == b0 and a1 == b1:
            continue
        # -2 marks a small transition patch used only to close a non-concurrent
        # 3D multi-facet junction. Its perimeter is not a physical ridge/valley
        # and must not generate a separate profile.
        if face_source_ids and (
            face_source_ids[face_a] == -2
            or face_source_ids[face_b] == -2
        ):
            continue

        normal_a = normals[face_a]
        normal_b = normals[face_b]
        cosine = max(-1.0, min(1.0, _dot3(normal_a, normal_b)))
        if cosine >= math.cos(angle_tolerance):
            # A 180-degree surface continuation: no seam, no cap.
            continue

        edge_vector = _sub3(vertices[a1], vertices[a0])
        edge_length = _length3(edge_vector)
        if edge_length <= 1.0e-12:
            continue
        edge_direction = tuple(value / edge_length for value in edge_vector)
        signed_dihedral = _dot3(_cross3(normal_a, normal_b), edge_direction)
        if abs(signed_dihedral) <= math.sin(angle_tolerance):
            continue
        kind = "RIDGE" if signed_dihedral > 0.0 else "VALLEY"
        records.append((vertices[a0], vertices[a1], face_a, face_b, kind))

    return records


def roof_face_plane(vertices, face):
    """Return a least-squares roof plane z = a*x + b*y + c.

    Planar faces are recovered exactly up to floating-point error. Slightly
    warped imported n-gons are approximated by their best-fit height plane;
    callers that need a strict bound should validate the residual separately.
    """
    points = [tuple(float(v) for v in vertices[i][:3]) for i in face]
    if len(points) < 3:
        raise SkeletonError("Для вычисления плоскости ската нужно минимум три вершины.")

    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sz = sum(p[2] for p in points)
    sxx = sum(p[0]*p[0] for p in points)
    syy = sum(p[1]*p[1] for p in points)
    sxy = sum(p[0]*p[1] for p in points)
    sxz = sum(p[0]*p[2] for p in points)
    syz = sum(p[1]*p[2] for p in points)
    count = float(len(points))
    matrix = [
        [sxx, sxy, sx, sxz],
        [sxy, syy, sy, syz],
        [sx, sy, count, sz],
    ]
    matrix_scale = max(
        1.0, abs(sxx), abs(syy), abs(sx), abs(sy), count
    )
    pivot_eps = matrix_scale * 1.0e-13

    # Gaussian elimination with partial pivoting.
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) <= pivot_eps:
            # A nearly vertical/degenerate XY projection: fall back to the
            # first non-collinear triangle, as in the original implementation.
            origin = points[0]
            normal = None
            for i in range(1, len(points)-1):
                candidate = _cross3(
                    _sub3(points[i], origin),
                    _sub3(points[i+1], origin),
                )
                if _length3(candidate) > 1.0e-10:
                    normal = candidate
                    break
            if normal is None or abs(normal[2]) < 1.0e-10:
                raise SkeletonError("Невозможно вычислить плоскость одного из скатов.")
            nx, ny, nz = normal
            a = -nx/nz
            b = -ny/nz
            return (a, b, origin[2]-a*origin[0]-b*origin[1])

        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        for j in range(column, 4):
            matrix[column][j] /= divisor
        for row in range(3):
            if row == column:
                continue
            factor = matrix[row][column]
            for j in range(column, 4):
                matrix[row][j] -= factor*matrix[column][j]

    a, b, c = (matrix[i][3] for i in range(3))
    if not all(math.isfinite(v) for v in (a, b, c)):
        raise SkeletonError("Плоскость одного из скатов содержит неконечные коэффициенты.")
    return (a, b, c)


def build_inset_seam_profile_mesh(
    surface_vertices,
    faces,
    seams,
    profile_kind,
    width,
    extrusion_offset,
    end_setback=0.0,
    end_overhang=0.0,
    seat_sink_offset=(0.0, 0.0, 0.0),
    outline=None,
    end_offset=None,
    boundary_edges=None,
):
    """Create one continuous roof-following band network from face insets.

    Each selected seam edge is inset into its adjacent roof facets by ``width``
    measured on the actual sloping plane. Adjacent selected edges on the same
    facet share their miter corner; adjacent facets share the original seam
    edge. The resulting strip network is therefore welded before extrusion,
    including at connected branch nodes. Only exposed perimeter edges receive
    side walls. A single upper copy is translated by the requested global-Z
    vector to form the profile crown.

    ``end_offset`` moves degree-one seam ends along their tangent only when
    they lie on the supplied polygon outline or extracted mesh boundary:
    positive values extend outward and negative values retract inward. The
    older end_overhang/end_setback keyword pair is
    still accepted for compatibility when end_offset is not supplied.
    """
    if not surface_vertices or not faces or not seams:
        return [], []

    kind = str(profile_kind).upper()
    if kind not in {"RIDGE", "VALLEY"}:
        raise SkeletonError("Тип профиля должен быть RIDGE или VALLEY.")

    band_width = max(1.0e-6, float(width))
    extrusion = tuple(float(v) for v in extrusion_offset)
    sink = tuple(float(v) for v in seat_sink_offset)
    # One signed parameter replaces the old pair: positive extends outward,
    # negative retracts the end inward. The legacy arguments remain accepted
    # for backward compatibility with older test scripts and callers.
    net_end_shift = (float(end_offset) if end_offset is not None
                     else float(end_overhang) - float(end_setback))
    outline_points = [(float(p[0]), float(p[1])) for p in outline] if outline and len(outline) >= 3 else None

    def cross2(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def sub2(a, b):
        return (a[0] - b[0], a[1] - b[1])

    def dot2(a, b):
        return a[0] * b[0] + a[1] * b[1]

    def length3(v):
        return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    def norm3(v):
        length = length3(v)
        if length <= 1.0e-12:
            return (0.0, 0.0, 0.0)
        return (v[0] / length, v[1] / length, v[2] / length)

    def cross3(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def line_intersection(p, r, q, s, eps):
        denominator = cross2(r, s)
        if abs(denominator) <= eps:
            return None
        t = cross2(sub2(q, p), s) / denominator
        return (p[0] + t * r[0], p[1] + t * r[1])

    def project_to_segment(point, a, b):
        ab = sub2(b, a)
        length_sq = dot2(ab, ab)
        if length_sq <= 1.0e-20:
            return a
        t = max(0.0, min(1.0, dot2(sub2(point, a), ab) / length_sq))
        return (a[0] + ab[0] * t, a[1] + ab[1] * t)

    def point_in_polygon(point, polygon, eps):
        x, y = point
        inside = False
        for i, a in enumerate(polygon):
            b = polygon[(i + 1) % len(polygon)]
            ab = sub2(b, a)
            ap = sub2((x, y), a)
            if abs(cross2(ab, ap)) <= eps and dot2(ap, sub2((x, y), b)) <= eps:
                return True
            if (a[1] > y) != (b[1] > y):
                at_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                if x < at_x:
                    inside = not inside
        return inside

    scale = max(1.0, max(length3(tuple(surface_vertices[a][k] - surface_vertices[b][k] for k in range(3)))
                         for face in faces for a, b in zip(face, face[1:] + face[:1])))
    tolerance = max(1.0e-8, scale * 1.0e-8)
    xy_epsilon = max(1.0e-10, scale * 1.0e-10)
    weld_tolerance = max(1.0e-8, scale * 1.0e-8)
    input_face_planarity_tolerance = max(1.0e-5, scale * 5.0e-3)
    output_quad_planarity_tolerance = max(1.0e-10, scale * 1.0e-10)

    def point_key3(point):
        return _key3(point, weld_tolerance)

    boundary_segments = []
    for edge in boundary_edges or ():
        if len(edge) == 2 and len(edge[0]) >= 2 and len(edge[1]) >= 2:
            boundary_segments.append((
                (float(edge[0][0]), float(edge[0][1])),
                (float(edge[1][0]), float(edge[1][1])),
            ))

    def point_on_outline(point):
        x, y = point[0], point[1]
        segments = list(boundary_segments)
        if outline_points is not None:
            segments.extend(
                (outline_points[i], outline_points[(i + 1) % len(outline_points)])
                for i in range(len(outline_points))
            )
        for a, b in segments:
            ab = sub2(b, a)
            length_sq = dot2(ab, ab)
            if length_sq <= tolerance * tolerance:
                continue
            t = max(0.0, min(1.0, dot2(sub2((x, y), a), ab) / length_sq))
            q = (a[0] + ab[0] * t, a[1] + ab[1] * t)
            if math.hypot(x - q[0], y - q[1]) <= tolerance * 20.0:
                return True
        return False

    vertex_lookup = {point_key3(v): i for i, v in enumerate(surface_vertices)}
    selected_edges = set()
    selected_adjacency = defaultdict(list)
    for seam in seams:
        a, b, face_a, face_b, seam_kind = seam
        if str(seam_kind).upper() != kind:
            continue
        ia = vertex_lookup.get(point_key3(a))
        ib = vertex_lookup.get(point_key3(b))
        if ia is None or ib is None or ia == ib:
            continue
        edge_key = (ia, ib) if ia < ib else (ib, ia)
        selected_edges.add(edge_key)
        selected_adjacency[ia].append((ib, face_a, face_b))
        selected_adjacency[ib].append((ia, face_a, face_b))
    if not selected_edges:
        return [], []

    # A degree-one node gets an extension only when it really touches the eave.
    endpoint_shift = {}
    if abs(net_end_shift) > tolerance:
        for vertex_id, incident in selected_adjacency.items():
            if len(incident) != 1:
                continue
            point = surface_vertices[vertex_id]
            # A degree-one seam node can also be an internal termination
            # (for example, a junction left open by the source mesh). Only
            # nodes verified against the real exterior boundary may move.
            if not point_on_outline(point):
                continue
            other = surface_vertices[incident[0][0]]
            direction = norm3((point[0] - other[0], point[1] - other[1], 0.0))
            if length3(direction) > 1.0e-12:
                endpoint_shift[vertex_id] = (direction[0] * net_end_shift,
                                             direction[1] * net_end_shift)

    base_vertices = []
    base_faces = []
    base_face_meta = []
    # For each selected source seam edge and its endpoint, retain the inset
    # corner on both adjacent roof facets. These points define a true miter
    # cross-section when two ridge branches meet at a non-manifold point.
    endpoint_corner_map = {}
    base_vertex_map = {}

    def add_base_vertex(point):
        key = point_key3(point)
        index = base_vertex_map.get(key)
        if index is None:
            index = len(base_vertices)
            base_vertex_map[key] = index
            base_vertices.append(tuple(float(v) for v in point))
        return index

    for face_index, face in enumerate(faces):
        count_face = len(face)
        if count_face < 3:
            continue
        edge_keys = []
        selected = []
        for i, vertex_id in enumerate(face):
            next_id = face[(i + 1) % count_face]
            key = (vertex_id, next_id) if vertex_id < next_id else (next_id, vertex_id)
            edge_keys.append(key)
            selected.append(key in selected_edges)
        if not any(selected):
            continue

        plane = roof_face_plane(surface_vertices, face)
        pa, pb, pc = plane
        max_face_residual = max(
            abs(surface_vertices[index][2] - (pa*surface_vertices[index][0]
                + pb*surface_vertices[index][1] + pc))
            for index in face
        )
        if max_face_residual > input_face_planarity_tolerance:
            raise SkeletonError(
                "Грань крыши слишком сильно отклоняется от собственной опорной плоскости "
                "({:.6g} м > {:.6g} м). Разбейте её на более мелкие плоские грани.".format(
                    max_face_residual, input_face_planarity_tolerance
                )
            )
        plane_normal = norm3((-pa, -pb, 1.0))
        polygon_xy = [(surface_vertices[i][0], surface_vertices[i][1]) for i in face]
        edge_data = []
        for i, vertex_id in enumerate(face):
            next_id = face[(i + 1) % count_face]
            p = surface_vertices[vertex_id]
            q = surface_vertices[next_id]
            direction3 = norm3((q[0] - p[0], q[1] - p[1], q[2] - p[2]))
            inward3 = norm3(cross3(plane_normal, direction3))
            if length3(inward3) <= 1.0e-12:
                edge_data.append(None)
                continue
            edge_data.append({
                "p": (p[0], p[1]),
                "q": (q[0], q[1]),
                "d": (q[0] - p[0], q[1] - p[1]),
                "shifted": (p[0] + inward3[0] * band_width,
                            p[1] + inward3[1] * band_width),
                "inward": inward3,
            })

        def z_on_plane(x, y):
            return pa * x + pb * y + pc

        # At each original face corner, compute the common inner point of the
        # two adjacent selected bands. If only one band touches the corner,
        # intersect its offset rail with the unselected facet boundary.
        corner_points = [None] * count_face
        for i in range(count_face):
            previous = (i - 1) % count_face
            prev_selected = selected[previous]
            curr_selected = selected[i]
            if not (prev_selected or curr_selected):
                continue
            original = surface_vertices[face[i]]
            if edge_data[previous] is None or edge_data[i] is None:
                continue

            if prev_selected and curr_selected:
                prev_edge = edge_data[previous]
                curr_edge = edge_data[i]
                xy = line_intersection(
                    prev_edge["shifted"], prev_edge["d"],
                    curr_edge["shifted"], curr_edge["d"], xy_epsilon,
                )
                if xy is None:
                    n1, n2 = prev_edge["inward"], curr_edge["inward"]
                    bisector = norm3((n1[0] + n2[0], n1[1] + n2[1], n1[2] + n2[2]))
                    xy = (original[0] + bisector[0] * band_width,
                          original[1] + bisector[1] * band_width)
                candidate = (xy[0], xy[1], z_on_plane(xy[0], xy[1]))
                displacement = length3((candidate[0] - original[0],
                                        candidate[1] - original[1],
                                        candidate[2] - original[2]))
                # Limit pathological miter spikes at near-parallel corners.
                if displacement > band_width * 8.0:
                    direction = norm3((candidate[0] - original[0],
                                       candidate[1] - original[1],
                                       candidate[2] - original[2]))
                    candidate = (original[0] + direction[0] * band_width * 8.0,
                                 original[1] + direction[1] * band_width * 8.0,
                                 original[2] + direction[2] * band_width * 8.0)
                if not point_in_polygon((candidate[0], candidate[1]), polygon_xy, tolerance):
                    n1, n2 = prev_edge["inward"], curr_edge["inward"]
                    bisector = norm3((n1[0] + n2[0], n1[1] + n2[1], n1[2] + n2[2]))
                    candidate = (original[0] + bisector[0] * band_width,
                                 original[1] + bisector[1] * band_width,
                                 original[2] + bisector[2] * band_width)
                    if not point_in_polygon((candidate[0], candidate[1]), polygon_xy, tolerance):
                        candidate = (original[0] + curr_edge["inward"][0] * band_width * 0.5,
                                     original[1] + curr_edge["inward"][1] * band_width * 0.5,
                                     original[2] + curr_edge["inward"][2] * band_width * 0.5)
                corner_points[i] = candidate
            else:
                selected_edge_index = i if curr_selected else previous
                boundary_edge_index = previous if curr_selected else i
                selected_edge = edge_data[selected_edge_index]
                boundary_edge = edge_data[boundary_edge_index]
                xy = line_intersection(
                    selected_edge["shifted"], selected_edge["d"],
                    boundary_edge["p"], boundary_edge["d"], xy_epsilon,
                )
                if xy is None:
                    inward = selected_edge["inward"]
                    xy = (original[0] + inward[0] * band_width,
                          original[1] + inward[1] * band_width)
                else:
                    # Keep the cut point on the finite neighbouring facet edge.
                    projected = project_to_segment(
                        xy, boundary_edge["p"], boundary_edge["q"]
                    )
                    if math.hypot(xy[0] - projected[0], xy[1] - projected[1]) > tolerance * 10.0:
                        xy = projected
                corner_points[i] = (xy[0], xy[1], z_on_plane(xy[0], xy[1]))

            # Eave extension/setback shifts only the cap's copy of this corner.
            shift = endpoint_shift.get(face[i])
            if shift is not None:
                point = corner_points[i]
                corner_points[i] = (point[0] + shift[0], point[1] + shift[1],
                                    z_on_plane(point[0] + shift[0], point[1] + shift[1]))

        # Create one inset quad per selected seam edge. Adjacent quads share
        # the same miter corner and radial edge on this roof facet.
        for i in range(count_face):
            if not selected[i] or corner_points[i] is None:
                continue
            j = (i + 1) % count_face
            if corner_points[j] is None:
                continue
            original_a = surface_vertices[face[i]]
            original_b = surface_vertices[face[j]]
            shift_a = endpoint_shift.get(face[i])
            shift_b = endpoint_shift.get(face[j])
            if shift_a is not None:
                original_a = (original_a[0] + shift_a[0], original_a[1] + shift_a[1],
                              z_on_plane(original_a[0] + shift_a[0], original_a[1] + shift_a[1]))
            if shift_b is not None:
                original_b = (original_b[0] + shift_b[0], original_b[1] + shift_b[1],
                              z_on_plane(original_b[0] + shift_b[0], original_b[1] + shift_b[1]))
            ids = (
                add_base_vertex(original_a),
                add_base_vertex(original_b),
                add_base_vertex(corner_points[j]),
                add_base_vertex(corner_points[i]),
            )
            # Miter collapses can turn a nominal quad into a triangle. Remove
            # duplicate indices while preserving the polygon's cyclic order.
            clean_ids = []
            for vertex_id in ids:
                if not clean_ids or clean_ids[-1] != vertex_id:
                    clean_ids.append(vertex_id)
            if len(clean_ids) > 1 and clean_ids[0] == clean_ids[-1]:
                clean_ids.pop()
            if len(set(clean_ids)) >= 3:
                unique_ids = []
                for vertex_id in clean_ids:
                    if vertex_id not in unique_ids:
                        unique_ids.append(vertex_id)
                if len(unique_ids) >= 3:
                    faces_to_add = [tuple(unique_ids)]
                    if len(unique_ids) == 4:
                        p0, p1, p2, p3 = [base_vertices[index] for index in unique_ids]
                        normal = cross3(
                            (p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]),
                            (p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]),
                        )
                        normal_length = length3(normal)
                        warp = (
                            abs(normal[0]*(p3[0]-p0[0])
                                + normal[1]*(p3[1]-p0[1])
                                + normal[2]*(p3[2]-p0[2])) / normal_length
                            if normal_length > 1.0e-14 else float("inf")
                        )
                        if warp > output_quad_planarity_tolerance:
                            diagonal_02 = length3((
                                p0[0]-p2[0], p0[1]-p2[1], p0[2]-p2[2]
                            ))
                            diagonal_13 = length3((
                                p1[0]-p3[0], p1[1]-p3[1], p1[2]-p3[2]
                            ))
                            if diagonal_02 <= diagonal_13:
                                faces_to_add = [
                                    (unique_ids[0], unique_ids[1], unique_ids[2]),
                                    (unique_ids[0], unique_ids[2], unique_ids[3]),
                                ]
                            else:
                                faces_to_add = [
                                    (unique_ids[0], unique_ids[1], unique_ids[3]),
                                    (unique_ids[1], unique_ids[2], unique_ids[3]),
                                ]
                    seam_vertex_a, seam_vertex_b = face[i], face[j]
                    seam_edge_key = (
                        (seam_vertex_a, seam_vertex_b)
                        if seam_vertex_a < seam_vertex_b
                        else (seam_vertex_b, seam_vertex_a)
                    )
                    for profile_face in faces_to_add:
                        base_faces.append(profile_face)
                        base_face_meta.append((seam_edge_key, face_index))
                    # ids are (original_a, original_b, inset_b, inset_a).
                    endpoint_corner_map[(seam_edge_key, seam_vertex_a, face_index)] = ids[3]
                    endpoint_corner_map[(seam_edge_key, seam_vertex_b, face_index)] = ids[2]

    if not base_faces:
        return [], []

    def triangulate_junction_loop(vertex_ids):
        """Ear-clip a simple XY junction rim while preserving every rim edge."""
        ids = list(vertex_ids)
        if len(ids) < 3 or len(set(ids)) != len(ids):
            raise SkeletonError("Переходный контур узла профиля вырожден.")

        points = [(base_vertices[index][0], base_vertices[index][1]) for index in ids]
        area = 0.5 * sum(
            a[0] * b[1] - b[0] * a[1]
            for a, b in zip(points, points[1:] + points[:1])
        )
        area_eps = xy_epsilon * max(scale, 1.0)
        if abs(area) <= area_eps:
            raise SkeletonError("Переходный контур узла профиля имеет нулевую площадь.")
        orientation = 1.0 if area > 0.0 else -1.0

        def orient2(a, b, c):
            return cross2(sub2(b, a), sub2(c, a))

        def proper_cross(a, b, c, d):
            o1, o2 = orient2(a, b, c), orient2(a, b, d)
            o3, o4 = orient2(c, d, a), orient2(c, d, b)
            return o1 * o2 < -area_eps * area_eps and o3 * o4 < -area_eps * area_eps

        for i in range(len(points)):
            a, b = points[i], points[(i + 1) % len(points)]
            for j in range(i + 1, len(points)):
                if j == i or j == (i + 1) % len(points) or (j + 1) % len(points) == i:
                    continue
                if proper_cross(a, b, points[j], points[(j + 1) % len(points)]):
                    raise SkeletonError("Переходный контур многоветвевого узла профиля самопересекается.")

        remaining = list(range(len(ids)))
        triangles = []
        while len(remaining) > 3:
            ear = None
            for position, current in enumerate(remaining):
                previous = remaining[position - 1]
                following = remaining[(position + 1) % len(remaining)]
                a, b, c = points[previous], points[current], points[following]
                if orientation * orient2(a, b, c) <= area_eps:
                    continue
                contains = False
                for other in remaining:
                    if other in (previous, current, following):
                        continue
                    p = points[other]
                    s1 = orientation * orient2(a, b, p)
                    s2 = orientation * orient2(b, c, p)
                    s3 = orientation * orient2(c, a, p)
                    if min(s1, s2, s3) >= -area_eps:
                        contains = True
                        break
                if not contains:
                    ear = (position, (ids[previous], ids[current], ids[following]))
                    break
            if ear is None:
                raise SkeletonError("Не удалось триангулировать переходный контур узла профиля.")
            triangles.append(ear[1])
            remaining.pop(ear[0])

        final = (ids[remaining[0]], ids[remaining[1]], ids[remaining[2]])
        if abs(orient2(
            points[remaining[0]], points[remaining[1]], points[remaining[2]]
        )) <= area_eps:
            raise SkeletonError("Последний треугольник переходного узла профиля вырожден.")
        triangles.append(final)
        return triangles

    # Three-or-more ridge branches must not share one extrusion vertex. Split
    # their local strips at the node, close each branch cross-section, then
    # connect those sections with one triangulated patch ordered by the actual
    # angular sectors of the adjacent roof faces.
    for vertex_id, incident in selected_adjacency.items():
        if len(incident) < 3:
            continue

        centre = surface_vertices[vertex_id]
        centre_key = point_key3(centre)
        original_centre_id = base_vertex_map.get(centre_key)
        if original_centre_id is None:
            continue

        local_edge_uses = defaultdict(int)
        for face in base_faces:
            for a_id, b_id in zip(face, face[1:] + face[:1]):
                key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
                local_edge_uses[key] += 1
        local_boundary_degree = sum(
            1 for (a_id, b_id), uses in local_edge_uses.items()
            if uses == 1 and (a_id == original_centre_id or b_id == original_centre_id)
        )
        # Most high-valence graph nodes are already locally manifold because
        # adjacent selected strips share their face-corner rails. Only split
        # the genuinely pinched nodes that would otherwise extrude a multi-use
        # vertical edge.
        if local_boundary_degree <= 2:
            continue

        branch_records = []
        face_corner_ids = {}
        face_corner_angles = defaultdict(list)
        for other_id, face_a, face_b in incident:
            edge_key = (
                (vertex_id, other_id)
                if vertex_id < other_id else (other_id, vertex_id)
            )
            corner_a = endpoint_corner_map.get((edge_key, vertex_id, face_a))
            corner_b = endpoint_corner_map.get((edge_key, vertex_id, face_b))
            if corner_a is None or corner_b is None or corner_a == corner_b:
                raise SkeletonError(
                    "Не удалось определить угловые вершины граней многоветвевого узла профиля."
                )
            branch_records.append((edge_key, face_a, face_b, corner_a, corner_b))

            for face_index, corner_id in ((face_a, corner_a), (face_b, corner_b)):
                previous_corner = face_corner_ids.get(face_index)
                if previous_corner is not None and previous_corner != corner_id:
                    raise SkeletonError(
                        "Одна грань получила две разные угловые вершины в узле профиля."
                    )
                face_corner_ids[face_index] = corner_id

                roof_face = faces[face_index]
                try:
                    corner_position = list(roof_face).index(vertex_id)
                except ValueError:
                    raise SkeletonError(
                        "Смежная грань не содержит вершину своего узла профиля."
                    )
                previous_point = surface_vertices[roof_face[corner_position - 1]]
                next_point = surface_vertices[roof_face[(corner_position + 1) % len(roof_face)]]
                origin = centre
                face_area = 0.5 * sum(
                    surface_vertices[roof_face[i]][0] * surface_vertices[roof_face[(i + 1) % len(roof_face)]][1]
                    - surface_vertices[roof_face[(i + 1) % len(roof_face)]][0] * surface_vertices[roof_face[i]][1]
                    for i in range(len(roof_face))
                )
                if face_area >= 0.0:
                    start_vector = (next_point[0] - origin[0], next_point[1] - origin[1])
                    end_vector = (previous_point[0] - origin[0], previous_point[1] - origin[1])
                else:
                    start_vector = (previous_point[0] - origin[0], previous_point[1] - origin[1])
                    end_vector = (next_point[0] - origin[0], next_point[1] - origin[1])
                start_angle = math.atan2(start_vector[1], start_vector[0])
                end_angle = math.atan2(end_vector[1], end_vector[0])
                span_angle = (end_angle - start_angle) % (2.0 * math.pi)
                face_corner_angles[corner_id].append(
                    (start_angle + 0.5 * span_angle) % (2.0 * math.pi)
                )

        unique_corner_ids = list(face_corner_angles)
        if len(unique_corner_ids) < 3:
            raise SkeletonError("У многоветвевого узла профиля менее трёх различных угловых точек.")

        def circular_mean(angles):
            sx = sum(math.cos(angle) for angle in angles)
            sy = sum(math.sin(angle) for angle in angles)
            if math.hypot(sx, sy) <= 1.0e-10:
                return angles[0] % (2.0 * math.pi)
            return math.atan2(sy, sx) % (2.0 * math.pi)

        unique_corner_ids.sort(key=lambda corner_id: (
            circular_mean(face_corner_angles[corner_id]), corner_id
        ))
        ring_edges = {
            frozenset((
                unique_corner_ids[i],
                unique_corner_ids[(i + 1) % len(unique_corner_ids)],
            ))
            for i in range(len(unique_corner_ids))
        }
        missing_sections = [
            (corner_a, corner_b)
            for _edge_key, _face_a, _face_b, corner_a, corner_b in branch_records
            if frozenset((corner_a, corner_b)) not in ring_edges
        ]
        if missing_sections:
            raise SkeletonError(
                "Угловые секции многоветвевого профиля не являются соседними в порядке граней: {}."
                .format(missing_sections[:4])
            )

        # Reassign each strip pair to its own centre copy and close its section.
        for edge_key, face_a, face_b, corner_a, corner_b in branch_records:
            centre_copy = len(base_vertices)
            base_vertices.append(tuple(float(v) for v in centre))
            for face_index, meta in enumerate(base_face_meta):
                meta_edge, meta_face = meta
                if meta_edge == edge_key and meta_face in (face_a, face_b):
                    base_faces[face_index] = tuple(
                        centre_copy if item == original_centre_id else item
                        for item in base_faces[face_index]
                    )
            base_faces.append((centre_copy, corner_a, corner_b))
            base_face_meta.append((None, -1))

        # The polygon rim contains every branch cross-section edge. Its other
        # edges form the exposed perimeter of the common junction patch.
        for triangle in triangulate_junction_loop(unique_corner_ids):
            base_faces.append(tuple(triangle))
            base_face_meta.append((None, -1))

    # At some roof nodes two ridge seams meet while their four adjacent
    # facets are separated by valley seams. Per-facet inset strips then touch
    # only at the original node, producing four boundary spokes and a 4-use
    # vertical edge after extrusion. Split that point into two miter sections
    # and bridge the sections with one shared transition patch.
    for vertex_id, incident in selected_adjacency.items():
        if len(incident) != 2:
            continue
        branch_records = []
        face_sets = []
        valid = True
        for other_id, face_a, face_b in incident:
            edge_key = (vertex_id, other_id) if vertex_id < other_id else (other_id, vertex_id)
            corner_a = endpoint_corner_map.get((edge_key, vertex_id, face_a))
            corner_b = endpoint_corner_map.get((edge_key, vertex_id, face_b))
            if corner_a is None or corner_b is None:
                valid = False
                break
            branch_records.append((edge_key, face_a, face_b, corner_a, corner_b))
            face_sets.append({face_a, face_b})
        # Only handle the genuinely pinched case: each ridge branch has its
        # own pair of adjacent roof facets, with no common facet between runs.
        if not valid or face_sets[0] & face_sets[1]:
            continue
        center_key = point_key3(surface_vertices[vertex_id])
        original_center = base_vertex_map.get(center_key)
        if original_center is None:
            continue
        # A local base boundary degree check prevents perturbing ordinary
        # degree-two miter corners, which are already watertight.
        local_boundary_degree = 0
        local_edge_uses = defaultdict(int)
        for face in base_faces:
            for a_id, b_id in zip(face, face[1:] + face[:1]):
                key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
                local_edge_uses[key] += 1
        for (a_id, b_id), uses in local_edge_uses.items():
            if uses == 1 and (a_id == original_center or b_id == original_center):
                local_boundary_degree += 1
        if local_boundary_degree <= 2:
            continue

        branch_sections = []
        for edge_key, face_a, face_b, corner_a, corner_b in branch_records:
            center_copy = len(base_vertices)
            base_vertices.append(tuple(float(v) for v in surface_vertices[vertex_id]))
            # Reassign only the two inset strips belonging to this seam.
            for face_index, meta in enumerate(base_face_meta):
                meta_edge, meta_face = meta
                if meta_edge == edge_key and meta_face in (face_a, face_b):
                    base_faces[face_index] = tuple(
                        center_copy if item == original_center else item
                        for item in base_faces[face_index]
                    )
            # The cross-section triangle closes the two boundary spokes on
            # the opposite facets of this one ridge segment.
            base_faces.append((center_copy, corner_a, corner_b))
            base_face_meta.append((None, -1))
            branch_sections.append((corner_a, corner_b))

        # Bridge the two cross-sections. The side edges of this miter patch
        # become the only exposed boundary around the junction; the profile
        # remains one connected shell rather than two prisms touching at a point.
        a0, a1 = branch_sections[0]
        b0, b1 = branch_sections[1]
        bridge = (a0, a1, b1, b0)
        if len(set(bridge)) == 4:
            # Triangulate the transition patch explicitly. Its four points
            # belong to different roof planes, so retaining a warped quad
            # would leave Blender free to choose an arbitrary diagonal.
            diagonal_02 = _length3(_sub3(base_vertices[a0], base_vertices[b1]))
            diagonal_13 = _length3(_sub3(base_vertices[a1], base_vertices[b0]))
            if diagonal_02 <= diagonal_13:
                base_faces.append((a0, a1, b1))
                base_faces.append((a0, b1, b0))
            else:
                base_faces.append((a0, a1, b0))
                base_faces.append((a1, b1, b0))
            base_face_meta.extend(((None, -1), (None, -1)))

    # Remove centre copies and any vertices made obsolete by the split branch
    # miter. Keeping unused vertices would make the exported object contain
    # detached points even though the polygon shell itself is closed.
    used_base_vertices = sorted({index for face in base_faces for index in face})
    compact_map = {old: new for new, old in enumerate(used_base_vertices)}
    base_vertices = [base_vertices[index] for index in used_base_vertices]
    base_faces = [tuple(compact_map[index] for index in face) for face in base_faces]

    # Welded strip topology must be a manifold surface before extrusion.
    edge_uses = defaultdict(list)
    for face_index, face in enumerate(base_faces):
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((face_index, a, b))
    if any(len(uses) > 2 for uses in edge_uses.values()):
        raise SkeletonError(
            "Inset-полосы профиля образовали неманифолдальный узел. "
            "Проверьте пересечение ветвей конька в узле крыши."
        )

    bottom_vertices = [
        (p[0] + sink[0], p[1] + sink[1], p[2] + sink[2])
        for p in base_vertices
    ]
    top_vertices = [
        (p[0] + extrusion[0], p[1] + extrusion[1], p[2] + extrusion[2])
        for p in bottom_vertices
    ]
    count = len(base_vertices)
    out_vertices = bottom_vertices + top_vertices
    out_faces = []
    out_faces.extend(tuple(reversed(face)) for face in base_faces)
    out_faces.extend(tuple(index + count for index in face) for face in base_faces)
    for uses in edge_uses.values():
        if len(uses) != 1:
            continue
        _face_index, a, b = uses[0]
        out_faces.append((a, b, b + count, a + count))

    # Refuse to output an open/non-manifold shell. This catches pathological
    # branch junctions instead of leaving overlapping end walls in Blender.
    final_edge_counts = defaultdict(int)
    for face in out_faces:
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            final_edge_counts[key] += 1
    if any(use_count != 2 for use_count in final_edge_counts.values()):
        bad_edges = [
            (
                tuple(round(float(v), 6) for v in out_vertices[a]),
                tuple(round(float(v), 6) for v in out_vertices[b]),
                int(use_count),
            )
            for (a, b), use_count in final_edge_counts.items()
            if use_count != 2
        ][:8]
        branch_nodes = [
            (
                tuple(round(float(v), 6) for v in surface_vertices[vertex_id]),
                len(incident),
            )
            for vertex_id, incident in selected_adjacency.items()
            if len(incident) >= 3
        ][:8]
        raise SkeletonError(
            "В узле профиля не удалось собрать замкнутую manifold-оболочку. "
            "Многоветвевые узлы (XYZ, valence): {}; граничные рёбра (A, B, uses): {}. "
            "Проверьте соединение ветвей конька в узле крыши.".format(
                branch_nodes, bad_edges
            )
        )

    out_faces = _orient_closed_mesh_faces(out_vertices, out_faces)
    _validate_face_planarity(out_vertices, out_faces, max(scale * 2.0e-7, 1.0e-8))
    return out_vertices, out_faces

