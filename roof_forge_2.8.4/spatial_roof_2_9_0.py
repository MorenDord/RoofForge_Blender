"""Spatial roof topology lifting for RoofForge 2.9.

The established 2D straight-skeleton engine supplies the combinatorial
wavefront topology (including reflex-vertex split events). Each topological
roof vertex is then embedded by intersecting the actual 3D support planes
defined by the non-planar eave edges.

The resulting mesh is accepted only when its projected cells remain a valid
partition of the original footprint, every face lies on its source support
plane, and the complete 3D eave boundary is preserved. Incompatible geometry
is rejected rather than silently patched.
"""
import itertools
import math
from collections import defaultdict

try:
    from .straight_skeleton_2_6_0 import build_roof_mesh, build_weighted_roof_mesh, SkeletonError
except ImportError:
    from straight_skeleton_2_6_0 import build_roof_mesh, build_weighted_roof_mesh, SkeletonError


class SpatialRoofError(ValueError):
    """The requested 3D eave/pitch combination has no valid lifted topology."""


def _cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _area(poly):
    return 0.5 * sum(
        _cross2(poly[i], poly[(i + 1) % len(poly)])
        for i in range(len(poly))
    )


def _distance2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _distance3(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _dot3(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _cross3(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _inside_or_on(point, polygon, eps):
    x, y = point
    inside = False
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        ab = (b[0] - a[0], b[1] - a[1])
        ap = (x - a[0], y - a[1])
        if abs(_cross2(ab, ap)) <= eps and (
            ap[0] * (x - b[0]) + ap[1] * (y - b[1]) <= eps
        ):
            return True
        if (a[1] > y) != (b[1] > y):
            at_x = a[0] + (y - a[1]) * ab[0] / ab[1]
            if x < at_x:
                inside = not inside
    return inside


def _point_on_segment(point, a, b, eps):
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= eps * eps:
        return False, 0.0, float("inf")
    t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq
    nearest = (a[0] + dx * t, a[1] + dy * t)
    distance = _distance2(point, nearest)
    return (-eps <= t <= 1.0 + eps and distance <= eps), t, distance


def _edge_plane(p, q, pitch, eave_lift):
    """Return z=a*x+b*y+c for a plane containing one 3D eave edge."""
    dx = q[0] - p[0]
    dy = q[1] - p[1]
    dz = q[2] - p[2]
    horizontal_length = math.hypot(dx, dy)
    if horizontal_length <= 1.0e-10:
        raise SpatialRoofError(
            "Обнаружено почти вертикальное ребро карниза: его XY-проекция имеет нулевую длину."
        )
    tangent = (dx / horizontal_length, dy / horizontal_length)
    inward = (-tangent[1], tangent[0])
    along_grade = dz / horizontal_length
    slope = math.tan(float(pitch))
    if not math.isfinite(slope) or slope <= 1.0e-10:
        raise SpatialRoofError("Угол пространственного ската должен быть больше нуля и меньше 90°.")
    if slope + 1.0e-9 < abs(along_grade):
        minimum = math.degrees(math.atan(abs(along_grade)))
        raise SpatialRoofError(
            "Угол ската {:.2f}° меньше продольного уклона карнизного ребра {:.2f}°.".format(
                math.degrees(pitch), minimum
            )
        )
    inward_grade = math.sqrt(max(0.0, slope * slope - along_grade * along_grade))
    gx = along_grade * tangent[0] + inward_grade * inward[0]
    gy = along_grade * tangent[1] + inward_grade * inward[1]
    c = p[2] + float(eave_lift) - gx * p[0] - gy * p[1]
    return (gx, gy, c)


def _plane_value(plane, x, y):
    return plane[0] * x + plane[1] * y + plane[2]


def _plane_residual(plane, point):
    return abs(float(point[2]) - _plane_value(plane, point[0], point[1]))


def _solve_linear3(rows, rhs, eps):
    """Solve a 3x3 system with partial pivoting; return None if singular."""
    matrix = [
        [float(rows[i][0]), float(rows[i][1]), float(rows[i][2]), float(rhs[i])]
        for i in range(3)
    ]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) <= eps:
            return None
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        for j in range(column, 4):
            matrix[column][j] /= divisor
        for row in range(3):
            if row == column:
                continue
            factor = matrix[row][column]
            if factor == 0.0:
                continue
            for j in range(column, 4):
                matrix[row][j] -= factor * matrix[column][j]
    result = tuple(matrix[i][3] for i in range(3))
    return result if all(math.isfinite(v) for v in result) else None


def _three_plane_intersection(planes, ids, eps):
    selected = [planes[i] for i in ids]
    rows = [(-p[0], -p[1], 1.0) for p in selected]
    rhs = [p[2] for p in selected]
    return _solve_linear3(rows, rhs, eps)


def _two_plane_projection(plane_a, plane_b, target, eps):
    """Project target XY to the line where two z=f(x,y) planes intersect."""
    a = plane_a[0] - plane_b[0]
    b = plane_a[1] - plane_b[1]
    c = plane_b[2] - plane_a[2]
    denominator = a * a + b * b
    if denominator <= eps * eps:
        if abs(c) <= eps:
            x, y = target[0], target[1]
            return (x, y, _plane_value(plane_a, x, y))
        raise SpatialRoofError("Две соседние плоскости скатов параллельны и не пересекаются.")
    error = (a * target[0] + b * target[1] - c) / denominator
    x = target[0] - a * error
    y = target[1] - b * error
    return (x, y, _plane_value(plane_a, x, y))


def _best_concurrent_point(planes, source_ids, determinant_eps, residual_eps):
    """Find a stable triple intersection and check every incident support plane."""
    best = None
    best_det = 0.0
    for triple in itertools.combinations(source_ids, 3):
        p0, p1, p2 = (planes[i] for i in triple)
        n0 = (-p0[0], -p0[1], 1.0)
        n1 = (-p1[0], -p1[1], 1.0)
        n2 = (-p2[0], -p2[1], 1.0)
        determinant = abs(_dot3(n0, _cross3(n1, n2)))
        if determinant <= determinant_eps or determinant <= best_det:
            continue
        candidate = _three_plane_intersection(planes, triple, determinant_eps)
        if candidate is not None:
            best = candidate
            best_det = determinant
    if best is None:
        return None
    residual = max(_plane_residual(planes[i], best) for i in source_ids)
    return best if residual <= residual_eps else None


def _face_corner_direction(vertices, face, vertex_id):
    position = face.index(vertex_id)
    centre = vertices[vertex_id]
    previous = vertices[face[(position - 1) % len(face)]]
    following = vertices[face[(position + 1) % len(face)]]
    u = (previous[0] - centre[0], previous[1] - centre[1])
    v = (following[0] - centre[0], following[1] - centre[1])
    ul = math.hypot(*u)
    vl = math.hypot(*v)
    if ul > 1.0e-12:
        u = (u[0] / ul, u[1] / ul)
    if vl > 1.0e-12:
        v = (v[0] / vl, v[1] / vl)
    direction = (u[0] + v[0], u[1] + v[1])
    if math.hypot(*direction) <= 1.0e-10:
        cx = sum(vertices[i][0] for i in face) / len(face)
        cy = sum(vertices[i][1] for i in face) / len(face)
        direction = (cx - centre[0], cy - centre[1])
    return math.atan2(direction[1], direction[0])


def _proper_segment_cross(a, b, c, d, eps):
    """True for a proper XY crossing; shared endpoints are allowed."""
    o1 = _cross2((b[0] - a[0], b[1] - a[1]), (c[0] - a[0], c[1] - a[1]))
    o2 = _cross2((b[0] - a[0], b[1] - a[1]), (d[0] - a[0], d[1] - a[1]))
    o3 = _cross2((d[0] - c[0], d[1] - c[1]), (a[0] - c[0], a[1] - c[1]))
    o4 = _cross2((d[0] - c[0], d[1] - c[1]), (b[0] - c[0], b[1] - c[1]))
    return (
        ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps))
        and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps))
    )


def _embed_topology(template_vertices, template_faces, template_sources,
                    outline, planes, eps, scale):
    """Lift 2D skeleton vertices into exact support-plane intersections."""
    vertex_faces = defaultdict(list)
    for face_index, face in enumerate(template_faces):
        for vertex_id in face:
            vertex_faces[vertex_id].append(face_index)

    boundary_tolerance = max(eps * 50.0, scale * 1.0e-7)
    node_tolerance = max(eps * 100.0, scale * 1.0e-6)
    determinant_tolerance = 1.0e-11
    vertices = []
    vertex_map = {}
    replacements = {}

    def append_vertex(point):
        if not all(math.isfinite(float(v)) for v in point):
            raise SpatialRoofError("Пространственный узел содержит неконечные координаты.")
        index = len(vertices)
        vertices.append(tuple(float(v) for v in point))
        return index

    def boundary_point(template_point):
        best = None
        best_distance = float("inf")
        for edge_id, p in enumerate(outline):
            q = outline[(edge_id + 1) % len(outline)]
            on_segment, t, distance = _point_on_segment(
                template_point[:2], p[:2], q[:2], boundary_tolerance
            )
            if on_segment and distance < best_distance:
                t = max(0.0, min(1.0, t))
                best = tuple(
                    float(p[k]) + (float(q[k]) - float(p[k])) * t
                    for k in range(3)
                )
                best_distance = distance
        return best

    for vertex_id, template_point in enumerate(template_vertices):
        on_boundary = boundary_point(template_point)
        if on_boundary is not None:
            vertex_map[vertex_id] = append_vertex(on_boundary)
            continue

        incident_faces = list(dict.fromkeys(vertex_faces.get(vertex_id, ())))
        incident_sources = sorted({int(template_sources[i]) for i in incident_faces})
        if not incident_sources:
            raise SpatialRoofError("У внутренней вершины skeleton отсутствуют соседние скаты.")

        target = tuple(float(v) for v in template_point)
        if len(incident_sources) == 1:
            source_id = incident_sources[0]
            point = (target[0], target[1],
                     _plane_value(planes[source_id], target[0], target[1]))
            vertex_map[vertex_id] = append_vertex(point)
            continue

        if len(incident_sources) == 2:
            point = _two_plane_projection(
                planes[incident_sources[0]], planes[incident_sources[1]],
                target, determinant_tolerance
            )
            vertex_map[vertex_id] = append_vertex(point)
            continue

        common = _best_concurrent_point(
            planes, incident_sources, determinant_tolerance, node_tolerance
        )
        if common is not None:
            vertex_map[vertex_id] = append_vertex(common)
            continue

        # A symmetric 2D event can have four or more incident roof facets.
        # Arbitrary 3D support planes are not necessarily concurrent. Resolve
        # that degenerate node into a deterministic fan of 3-plane junctions.
        if len(incident_sources) < 4:
            raise SpatialRoofError(
                "Три соседних пространственных ската не имеют общей точки пересечения."
            )
        if len(incident_faces) != len(incident_sources):
            raise SpatialRoofError(
                "В многолучевом узле один исходный скат подходит несколькими отдельными участками; "
                "топология неоднозначна."
            )

        fan = sorted(
            incident_faces,
            key=lambda face_index: (
                _face_corner_direction(
                    template_vertices, template_faces[face_index], vertex_id
                ),
                int(template_sources[face_index]),
            )
        )
        fan_sources = [int(template_sources[i]) for i in fan]
        if len(set(fan_sources)) != len(fan_sources):
            raise SpatialRoofError("В многолучевом узле повторяется одна и та же плоскость ската.")

        junction_ids = []
        for i in range(1, len(fan_sources) - 1):
            triple = (fan_sources[0], fan_sources[i], fan_sources[i + 1])
            point = _three_plane_intersection(planes, triple, determinant_tolerance)
            if point is None:
                raise SpatialRoofError(
                    "Не удалось разрешить многолучевой узел: вырожденное пересечение плоскостей."
                )
            if max(_plane_residual(planes[s], point) for s in triple) > node_tolerance:
                raise SpatialRoofError("Многолучевой узел не лежит на общих плоскостях скатов.")
            junction_ids.append(append_vertex(point))

        for i, face_index in enumerate(fan):
            if i == 0:
                chain = list(junction_ids)
            elif i == 1:
                chain = [junction_ids[0]]
            elif i == len(fan) - 1:
                chain = [junction_ids[-1]]
            else:
                chain = [junction_ids[i - 1], junction_ids[i - 2]]
            replacements[(face_index, vertex_id)] = chain
        vertex_map[vertex_id] = None

    output_faces = []
    output_sources = []
    for face_index, face in enumerate(template_faces):
        expanded = []
        for vertex_id in face:
            replacement = replacements.get((face_index, vertex_id))
            if replacement is not None:
                expanded.extend(replacement)
            else:
                mapped = vertex_map.get(vertex_id)
                if mapped is None:
                    raise SpatialRoofError("Не удалось назначить пространственный узел одной из граней.")
                expanded.append(mapped)
        clean = []
        for index in expanded:
            if not clean or clean[-1] != index:
                clean.append(index)
        if len(clean) > 1 and clean[0] == clean[-1]:
            clean.pop()
        if len(set(clean)) >= 3:
            output_faces.append(tuple(clean))
            output_sources.append(int(template_sources[face_index]))

    return vertices, output_faces, output_sources


def _validate_lifted_mesh(vertices, faces, sources, outline, planes, eps, scale):
    if not vertices or not faces or len(faces) != len(sources):
        raise SpatialRoofError("Пространственный skeleton не создал полную поверхность крыши.")

    for vertex in vertices:
        if not _inside_or_on(vertex[:2], outline, eps * 20.0):
            raise SpatialRoofError(
                "После пространственного совмещения узел ската вышел за исходный контур карниза."
            )

    edge_uses = defaultdict(list)
    cross_eps = eps * max(scale, 1.0)
    plane_eps = max(eps * 100.0, scale * 1.0e-6)
    for face_index, face in enumerate(faces):
        if len(face) < 3:
            raise SpatialRoofError("В пространственной сетке обнаружена грань менее чем из трёх вершин.")
        points = [vertices[i] for i in face]
        plane = planes[sources[face_index]]
        for point in points:
            if _plane_residual(plane, point) > plane_eps:
                raise SpatialRoofError(
                    "Один из скатов не лежит на своей опорной плоскости после совмещения узлов."
                )
        area = _area([(p[0], p[1]) for p in points])
        if area <= eps * eps:
            raise SpatialRoofError(
                "Пространственное совмещение перевернуло или выродило один из скатов."
            )
        count = len(face)
        for i in range(count):
            a, b = face[i], face[(i + 1) % count]
            if a == b or _distance3(vertices[a], vertices[b]) <= eps:
                raise SpatialRoofError("В скате появилось ребро нулевой длины.")
            for j in range(i + 1, count):
                if j == i or j == (i + 1) % count or (j + 1) % count == i:
                    continue
                c, d = face[j], face[(j + 1) % count]
                if _proper_segment_cross(vertices[a], vertices[b], vertices[c], vertices[d], cross_eps):
                    raise SpatialRoofError("Граница одного пространственного ската самопересекается.")
            key = tuple(sorted((a, b)))
            edge_uses[key].append((face_index, a, b))
            if len(edge_uses[key]) > 2:
                raise SpatialRoofError("У внутреннего ребра ската оказалось более двух соседних граней.")

    # Reject crossing projected boundaries. A height-field roof cannot have
    # overlapping projected cells without creating a geometric self-intersection.
    face_edges = []
    for face_index, face in enumerate(faces):
        for i, a in enumerate(face):
            b = face[(i + 1) % len(face)]
            face_edges.append((face_index, a, b))
    for i, (face_a, a, b) in enumerate(face_edges):
        for face_b, c, d in face_edges[i + 1:]:
            if face_a == face_b or len({a, b, c, d}) < 4:
                continue
            if _proper_segment_cross(vertices[a], vertices[b], vertices[c], vertices[d], cross_eps):
                raise SpatialRoofError(
                    "Проекции соседних скатов пересекаются после 3D-совмещения; "
                    "для этих высот и углов нужна другая последовательность событий."
                )

    boundary_intervals = [[] for _ in range(len(outline))]
    for (a_id, b_id), uses in edge_uses.items():
        if len(uses) == 2:
            continue
        if len(uses) != 1:
            raise SpatialRoofError("Неманифолдная граница пространственной крыши.")
        a = vertices[a_id]
        b = vertices[b_id]
        matched = False
        for edge_id, p in enumerate(outline):
            q = outline[(edge_id + 1) % len(outline)]
            on_a, ta, _da = _point_on_segment(a[:2], p[:2], q[:2], eps * 20.0)
            on_b, tb, _db = _point_on_segment(b[:2], p[:2], q[:2], eps * 20.0)
            if not (on_a and on_b):
                continue
            za = p[2] + max(0.0, min(1.0, ta)) * (q[2] - p[2])
            zb = p[2] + max(0.0, min(1.0, tb)) * (q[2] - p[2])
            if abs(a[2] - za) <= plane_eps and abs(b[2] - zb) <= plane_eps:
                boundary_intervals[edge_id].append((min(ta, tb), max(ta, tb)))
                matched = True
                break
        if not matched:
            raise SpatialRoofError(
                "После совмещения найдено внутреннее открытое ребро, не принадлежащее карнизу."
            )

    for edge_id, intervals in enumerate(boundary_intervals):
        intervals.sort()
        covered = 0.0
        for low, high in intervals:
            if low > covered + eps * 100.0:
                raise SpatialRoofError(
                    "Пространственная поверхность не покрывает всю кромку карниза {}.".format(
                        edge_id + 1
                    )
                )
            covered = max(covered, high)
        if covered < 1.0 - eps * 100.0:
            raise SpatialRoofError(
                "Скат у ребра карниза {} не доходит до всей кромки.".format(edge_id + 1)
            )

    # A face centroid contained in another non-neighbouring cell indicates an
    # overlap even when their polygon edges do not cross.
    for face_index, face in enumerate(faces):
        centroid = (
            sum(vertices[i][0] for i in face) / len(face),
            sum(vertices[i][1] for i in face) / len(face),
        )
        for other_index, other in enumerate(faces):
            if other_index == face_index:
                continue
            shared = set(face) & set(other)
            if len(shared) >= 2:
                continue
            other_poly = [(vertices[i][0], vertices[i][1]) for i in other]
            if _inside_or_on(centroid, other_poly, eps):
                raise SpatialRoofError(
                    "Два пространственных ската перекрывают одну область плана."
                )


def build_spatial_roof_mesh(outline_xyz, pitch_angles, eave_lift=0.0, tolerance=None):
    """Build a non-planar concave or convex roof from a 3D eave loop.

    pitch_angles contains one radian value per ordered eave edge. The
    established 2D straight-skeleton engine supplies the face-adjacency
    topology; each vertex is embedded at the intersection of its incident
    3D edge-support planes. High-valence symmetric events are split into a
    deterministic fan when their support planes are not concurrent.

    Returns (vertices, faces, source_edge_ids). Unsupported or
    self-intersecting 3D combinations raise SpatialRoofError.
    """
    points = [tuple(float(v) for v in point) for point in outline_xyz]
    count = len(points)
    if count < 3 or len(pitch_angles) != count:
        raise SpatialRoofError(
            "Нужно минимум три вершины и ровно один угол на каждое ребро контура."
        )
    if any(len(point) != 3 or not all(math.isfinite(v) for v in point) for point in points):
        raise SpatialRoofError("Координаты карниза должны быть конечными XYZ.")
    if any(not math.isfinite(float(value)) for value in pitch_angles):
        raise SpatialRoofError("Углы скатов должны быть конечными числами.")

    xy = [(point[0], point[1]) for point in points]
    span = max(
        max(p[0] for p in xy) - min(p[0] for p in xy),
        max(p[1] for p in xy) - min(p[1] for p in xy),
        1.0,
    )
    eps = max(float(tolerance) if tolerance is not None else span * 1.0e-9, 1.0e-9)
    signed_area = _area(xy)
    if abs(signed_area) <= eps * eps:
        raise SpatialRoofError("XY-проекция контура имеет нулевую площадь.")

    if signed_area < 0.0:
        old_points = list(points)
        old_angles = list(pitch_angles)
        points = list(reversed(old_points))
        pitch_angles = [old_angles[(count - 2 - i) % count] for i in range(count)]
        xy = [(point[0], point[1]) for point in points]

    for i in range(count):
        if _distance2(xy[i], xy[(i + 1) % count]) <= eps:
            raise SpatialRoofError("Ребро {} имеет нулевую длину в XY.".format(i + 1))

    planes = [
        _edge_plane(points[i], points[(i + 1) % count],
                    float(pitch_angles[i]), float(eave_lift))
        for i in range(count)
    ]
    # Use the proven reflex-aware straight-skeleton topology as a candidate
    # partition, then lift every facet onto its own 3D eave support plane.
    # The strict geometric validator below rejects cases where independent
    # pitches change the event order enough to invalidate that partition.
    try:
        template_vertices, template_faces, template_sources = build_roof_mesh(
            xy, 1.0, 0.0, allow_oblique=True
        )
    except SkeletonError as exc:
        raise SpatialRoofError("Не удалось построить топологию wavefront: " + str(exc)) from exc

    vertices, faces, sources = _embed_topology(
        template_vertices, template_faces, template_sources,
        points, planes, eps, span
    )
    _validate_lifted_mesh(vertices, faces, sources, points, planes, eps, span)
    return vertices, faces, sources
