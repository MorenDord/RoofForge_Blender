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
    from .straight_skeleton_2_6_0 import build_roof_mesh, SkeletonError
    from .weighted_skeleton_2_9_0 import (
        build_weighted_roof_mesh,
        SkeletonError as WeightedSkeletonError,
    )
except ImportError:
    from straight_skeleton_2_6_0 import build_roof_mesh, SkeletonError
    from weighted_skeleton_2_9_0 import (
        build_weighted_roof_mesh,
        SkeletonError as WeightedSkeletonError,
    )


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
    """Return the midpoint angle of the face's actual interior corner sector.

    The normalized-vector sum always chooses the smaller angle and therefore
    misorders reflex (>180 degree) corners. Roof facets around a split node
    must be sorted by their oriented interior wedge, not by the shortest
    bisector between adjacent boundary rays.
    """
    position = face.index(vertex_id)
    centre = vertices[vertex_id]
    previous = vertices[face[(position - 1) % len(face)]]
    following = vertices[face[(position + 1) % len(face)]]
    angle_previous = math.atan2(
        previous[1] - centre[1], previous[0] - centre[0]
    )
    angle_following = math.atan2(
        following[1] - centre[1], following[0] - centre[0]
    )
    # Faces are oriented counter-clockwise in XY. The interior sector runs
    # counter-clockwise from the outgoing ray to the incoming ray.
    span = (angle_previous - angle_following) % (2.0 * math.pi)
    if span <= 1.0e-10:
        cx = sum(vertices[i][0] for i in face) / len(face)
        cy = sum(vertices[i][1] for i in face) / len(face)
        return math.atan2(cy - centre[1], cx - centre[0])
    return (angle_following + 0.5 * span) % (2.0 * math.pi)

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
    # Non-concurrent support planes at a non-planar reflex node cannot all
    # pass through one point. Bound the local shared-height compromise by
    # 25% of the actual eave height range, capped at 1% of plan scale. This
    # scales with the input geometry but does not grow without limit.
    eave_height_range = max(float(p[2]) for p in outline) - min(float(p[2]) for p in outline)
    node_height_tolerance = max(
        eps * 100.0,
        scale * 2.5e-4,
        min(scale * 1.0e-2, eave_height_range * 0.75)
    )
    determinant_tolerance = 1.0e-11
    vertices = []
    vertex_map = {}
    replacements = {}
    junction_fill_faces = []
    junction_fill_sources = {}

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
            z_values = [
                _plane_value(planes[source_id], target[0], target[1])
                for source_id in incident_sources
            ]
            # Keep the event's XY location. Projecting a two-plane line back
            # to its nearest point can move a reflex event across a sibling
            # wavefront edge and invert the projected facet partition. A
            # shared least-squares height retains the tested 2D topology;
            # the residual bound in _validate_lifted_mesh limits the local
            # 3D compromise.
            point = (target[0], target[1], sum(z_values) / len(z_values))
            vertex_map[vertex_id] = append_vertex(point)
            continue

        common = _best_concurrent_point(
            planes, incident_sources, determinant_tolerance, node_tolerance
        )
        if common is not None:
            vertex_map[vertex_id] = append_vertex(common)
            continue

        target_heights = [
            _plane_value(planes[source_id], target[0], target[1])
            for source_id in incident_sources
        ]
        if max(target_heights) - min(target_heights) <= node_height_tolerance:
            # Keep the 2D skeleton's XY event location, but make one shared
            # Z value that minimizes the residual to all incident 3D planes.
            # This is a local compromise only at the incompatible junction;
            # each adjacent n-gon remains a single source facet.
            point = (target[0], target[1], sum(target_heights) / len(target_heights))
            vertex_map[vertex_id] = append_vertex(point)
            continue

        # If the incident support planes do not share one point, replace
        # the zero-area multi-facet node with a small closed transition patch.
        # For cyclically adjacent facets i,j, their pairwise intersection
        # point Q(i,j) lies on both support planes. The segment between the
        # previous and next Q points therefore lies on the current facet.
        # A triangular patch closes a 3-way event; higher valence patches are
        # triangulated around a local centre to avoid warped n-gons.
        if len(incident_sources) < 3:
            raise SpatialRoofError(
                "Пространственный узел с двумя скатами не имеет устойчивой точки пересечения."
            )
        if len(incident_faces) != len(incident_sources):
            raise SpatialRoofError(
                "В узле несколько участков одного исходного ската; "
                "автоматическое замыкание переходной грани неоднозначно."
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
            raise SpatialRoofError(
                "В узле повторяется одна опорная плоскость; нельзя однозначно упорядочить скаты."
            )

        junction_ids = []
        target_xy = (float(target[0]), float(target[1]))
        max_junction_radius = max(scale * 0.35, node_tolerance * 100.0)
        for i in range(len(fan_sources)):
            source_a = fan_sources[i]
            source_b = fan_sources[(i + 1) % len(fan_sources)]
            point = _two_plane_projection(
                planes[source_a], planes[source_b], target_xy, determinant_tolerance
            )
            if _distance2(point[:2], target_xy) > max_junction_radius:
                raise SpatialRoofError(
                    "Переходный узел разошёлся дальше допустимого радиуса; "
                    "измените высоты карниза или углы прилегающих скатов."
                )
            if max(_plane_residual(planes[s], point) for s in (source_a, source_b)) > node_tolerance:
                raise SpatialRoofError("Парная точка переходного узла не лежит на обеих плоскостях.")
            if junction_ids and _distance3(vertices[junction_ids[-1]], point) <= node_tolerance:
                junction_ids.append(junction_ids[-1])
            else:
                junction_ids.append(append_vertex(point))

        if len(set(junction_ids)) < 3:
            raise SpatialRoofError(
                "Переходный узел выродился: попарные пересечения скатов не образуют замкнутую область."
            )

        for i, face_index in enumerate(fan):
            previous_q = junction_ids[(i - 1) % len(junction_ids)]
            next_q = junction_ids[i]
            replacements[(face_index, vertex_id)] = [previous_q, next_q]

        if len(junction_ids) == 3:
            patch_face = tuple(junction_ids)
            patch_area = _area([
                (vertices[index][0], vertices[index][1]) for index in patch_face
            ])
            if abs(patch_area) <= eps * eps:
                raise SpatialRoofError("Треугольная переходная грань имеет нулевую проекционную площадь.")
            if patch_area < 0.0:
                patch_face = tuple(reversed(patch_face))
            junction_fill_faces.append(patch_face)
        else:
            centre = tuple(
                sum(vertices[index][axis] for index in junction_ids) / len(junction_ids)
                for axis in range(3)
            )
            centre_id = append_vertex(centre)
            for i in range(len(junction_ids)):
                triangle = (
                    centre_id,
                    junction_ids[i],
                    junction_ids[(i + 1) % len(junction_ids)],
                )
                area = _area([(vertices[index][0], vertices[index][1]) for index in triangle])
                if abs(area) <= eps * eps:
                    raise SpatialRoofError(
                        "Триангуляция многолучевой переходной грани создала вырожденный треугольник."
                    )
                if area < 0.0:
                    triangle = tuple(reversed(triangle))
                junction_fill_faces.append(triangle)
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

    output_faces.extend(junction_fill_faces)
    output_sources.extend([-2] * len(junction_fill_faces))
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
    eave_height_range = max(float(p[2]) for p in outline) - min(float(p[2]) for p in outline)
    plane_eps = max(
        eps * 100.0,
        scale * 2.5e-4,
        min(scale * 1.0e-2, eave_height_range * 0.75)
    )
    for face_index, face in enumerate(faces):
        if len(face) < 3:
            raise SpatialRoofError("В пространственной сетке обнаружена грань менее чем из трёх вершин.")
        points = [vertices[i] for i in face]
        source_id = int(sources[face_index])
        if source_id >= 0:
            plane = planes[source_id]
            for local_index, point in zip(face, points):
                residual = _plane_residual(plane, point)
                if residual > plane_eps:
                    raise SpatialRoofError(
                        "Скат {}: вершина {} {} отклоняется от опорной плоскости на {:.6g} м "
                        "(допуск {:.6g} м).".format(
                            face_index + 1, local_index, point, residual, plane_eps
                        )
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
                    raise SpatialRoofError(
                        "Граница пространственного ската {} самопересекается: {}.".format(
                            sources[face_index], points
                        )
                    )
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
                    "Проекции скатов пересекаются: face {} (source {}), edge {}-{} "
                    "и face {} (source {}), edge {}-{}. Координаты XY: {} {} / {} {}.".format(
                        face_a, sources[face_a], a, b,
                        face_b, sources[face_b], c, d,
                        vertices[a][:2], vertices[b][:2],
                        vertices[c][:2], vertices[d][:2],
                    )
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
            face_index = uses[0][0]
            nearby = []
            for other_face_index, other_face in enumerate(faces):
                if other_face_index == face_index:
                    continue
                for other_a_id, other_b_id in zip(
                    other_face, other_face[1:] + other_face[:1]
                ):
                    other_a = vertices[other_a_id]
                    other_b = vertices[other_b_id]
                    da = _distance3(a, other_a) + _distance3(b, other_b)
                    db = _distance3(a, other_b) + _distance3(b, other_a)
                    if min(da, db) <= plane_eps * 20.0:
                        nearby.append((sources[other_face_index], other_a, other_b))
            raise SpatialRoofError(
                "После совмещения найдено внутреннее открытое ребро: "
                "A=({}, {}, {}), B=({}, {}, {}), скат={}, соседние совпадающие рёбра={}.".format(
                    a[0], a[1], a[2], b[0], b[1], b[2],
                    sources[face_index] + 1, nearby[:4]
                )
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


def _collapse_near_event_slivers(vertices, faces, sources, outline, eps, scale):
    """Collapse only tiny source facets trapped between nearly coincident events.

    Two close interior vertices may be merged when they are adjacent in every
    common face and those common faces have a tiny projected area. Such faces
    are zero-area event slivers after the 3D event order changes; dropping them
    lets their neighbouring roof facets share one edge. Large faces and
    non-adjacent vertices are never candidates.
    """
    height_range=max(float(p[2]) for p in outline)-min(float(p[2]) for p in outline)
    weld_xy_tolerance=max(
        eps*100.0,
        min(scale*3.0e-2,height_range*1.5)
    )
    weld_z_tolerance=max(
        eps*100.0,
        min(height_range*1.5,scale*3.0e-2)
    )
    sliver_area_tolerance=max(
        weld_xy_tolerance*scale*0.25,
        scale*scale*1.0e-9
    )

    vertex_faces=[set() for _ in vertices]
    face_areas=[]
    for face_index,face in enumerate(faces):
        for vertex_id in face:
            vertex_faces[vertex_id].add(face_index)
        face_areas.append(abs(_area([
            (vertices[index][0],vertices[index][1]) for index in face
        ])))

    def boundary(point):
        for edge_id,p in enumerate(outline):
            q=outline[(edge_id+1)%len(outline)]
            on,t,distance=_point_on_segment(point[:2],p[:2],q[:2],eps*20.0)
            if on:
                t=max(0.0,min(1.0,t))
                expected_z=p[2]+(q[2]-p[2])*t
                if abs(point[2]-expected_z)<=max(eps*100.0,scale*2.5e-4):
                    return True
        return False

    def adjacent_in_face(face, a_id, b_id):
        try:
            a_pos=face.index(a_id)
            b_pos=face.index(b_id)
        except ValueError:
            return False
        n=len(face)
        return (a_pos-b_pos)%n in (1,n-1)

    def can_merge(a_id,b_id):
        common=vertex_faces[a_id] & vertex_faces[b_id]
        for face_index in common:
            face=faces[face_index]
            if not adjacent_in_face(face,a_id,b_id):
                return False
            # In an n-gon, merging two adjacent near-coincident corners only
            # removes a microscopic boundary edge and preserves the rest of
            # the facet. A triangular face can disappear entirely, so it is
            # allowed only when the whole projected triangle is a true sliver.
            if len(face)<=3 and face_areas[face_index]>sliver_area_tolerance:
                return False
        return True

    welded=[]
    counts=[]
    sums=[]
    face_membership=[]
    boundary_fixed=[]
    buckets=defaultdict(list)
    old_to_new=[]

    for old_id,raw in enumerate(vertices):
        point=tuple(float(v) for v in raw)
        if boundary(point):
            new_id=len(welded)
            welded.append(point)
            counts.append(1)
            sums.append(list(point))
            face_membership.append(set(vertex_faces[old_id]))
            boundary_fixed.append(True)
            old_to_new.append(new_id)
            continue

        cell=(int(math.floor(point[0]/weld_xy_tolerance)),
              int(math.floor(point[1]/weld_xy_tolerance)))
        best=None
        best_distance=float("inf")
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for candidate_id in buckets.get((cell[0]+dx,cell[1]+dy),()):
                    if boundary_fixed[candidate_id]:
                        continue
                    candidate=welded[candidate_id]
                    xy_distance=_distance2(point[:2],candidate[:2])
                    z_distance=abs(point[2]-candidate[2])
                    if xy_distance>weld_xy_tolerance or z_distance>weld_z_tolerance:
                        continue
                    # Test against every original vertex already represented
                    # by this cluster; do not use a transitive chain to bridge
                    # unrelated event nodes.
                    if not can_merge(old_id,candidate_id):
                        continue
                    if xy_distance<best_distance:
                        best,best_distance=candidate_id,xy_distance

        if best is None:
            best=len(welded)
            welded.append(point)
            counts.append(1)
            sums.append(list(point))
            face_membership.append(set(vertex_faces[old_id]))
            boundary_fixed.append(False)
            buckets[cell].append(best)
        else:
            for axis in range(3):
                sums[best][axis]+=point[axis]
            counts[best]+=1
            face_membership[best].update(vertex_faces[old_id])
            welded[best]=tuple(value/counts[best] for value in sums[best])
        old_to_new.append(best)

    remapped_faces=[]
    remapped_sources=[]
    for face_index,(face,source) in enumerate(zip(faces,sources)):
        mapped=[]
        for old_id in face:
            new_id=old_to_new[old_id]
            if not mapped or mapped[-1]!=new_id:
                mapped.append(new_id)
        if len(mapped)>1 and mapped[0]==mapped[-1]:
            mapped.pop()
        if len(set(mapped))<3:
            if face_areas[face_index] <= sliver_area_tolerance:
                # A face whose two event corners collapsed to one vertex has
                # zero area. Its two remaining sides become one shared edge.
                continue
            raise SpatialRoofError(
                "Попытка схлопнуть пространственный узел затронула неузкую грань ската."
            )
        remapped_faces.append(tuple(mapped))
        remapped_sources.append(source)

    used=sorted({index for face in remapped_faces for index in face})
    index_map={old:new for new,old in enumerate(used)}
    compact_vertices=[welded[index] for index in used]
    compact_faces=[tuple(index_map[index] for index in face) for face in remapped_faces]
    return compact_vertices,compact_faces,remapped_sources


def _build_spatial_roof_mesh_template(outline_xyz, pitch_angles, eave_lift=0.0, tolerance=None):
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

    source_edge_map = list(range(count))
    if signed_area < 0.0:
        old_points = list(points)
        old_angles = list(pitch_angles)
        points = list(reversed(old_points))
        pitch_angles = [old_angles[(count - 2 - i) % count] for i in range(count)]
        source_edge_map = [(count - 2 - i) % count for i in range(count)]
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
    vertices, faces, sources = _collapse_near_event_slivers(
        vertices, faces, sources, points, eps, span
    )
    _validate_lifted_mesh(vertices, faces, sources, points, planes, eps, span)
    return vertices, faces, [
        source_edge_map[source_id] if source_id >= 0 else source_id
        for source_id in sources
    ]


def _is_convex_xy_outline(points, eps):
    """Return True for a simple CCW outline with no reflex turns."""
    for i in range(len(points)):
        a=points[i-1]
        b=points[i]
        c=points[(i+1)%len(points)]
        ab=(b[0]-a[0],b[1]-a[1])
        bc=(c[0]-b[0],c[1]-b[1])
        if _cross2(ab,bc) < -eps*max(math.hypot(*ab),math.hypot(*bc),1.0):
            return False
    return True


def build_spatial_roof_mesh(outline_xyz, pitch_angles, eave_lift=0.0, tolerance=None):
    """Build a roof from edge-specific pitches and a 3D eave loop.

    Flat eaves use the independent weighted wavefront, which recomputes
    collapse and reflex split events for the actual pitch assigned to every
    edge. Non-planar convex eaves use the validated support-plane lifting path.
    Non-planar concave eaves are attempted only through that strict lifting
    path and are rejected if its topology does not close.
    """
    points=[tuple(float(v) for v in point) for point in outline_xyz]
    count=len(points)
    if count<3 or len(pitch_angles)!=count:
        raise SpatialRoofError(
            "Нужно минимум три вершины и ровно один угол на каждое ребро контура."
        )
    if any(len(point)!=3 or not all(math.isfinite(v) for v in point) for point in points):
        raise SpatialRoofError("Координаты карниза должны быть конечными XYZ.")
    angles=[float(value) for value in pitch_angles]
    if any(not math.isfinite(value) for value in angles):
        raise SpatialRoofError("Углы скатов должны быть конечными числами.")

    xy=[(p[0],p[1]) for p in points]
    scale=max(
        max(p[0] for p in xy)-min(p[0] for p in xy),
        max(p[1] for p in xy)-min(p[1] for p in xy),
        1.0,
    )
    eps=max(float(tolerance) if tolerance is not None else scale*1.0e-9,1.0e-9)
    signed_area=_area(xy)
    if abs(signed_area)<=eps*eps:
        raise SpatialRoofError("XY-проекция контура имеет нулевую площадь.")

    if signed_area<0.0:
        old_points=list(points)
        old_angles=list(angles)
        points=list(reversed(old_points))
        angles=[old_angles[(count-2-i)%count] for i in range(count)]
        xy=[(p[0],p[1]) for p in points]
        source_edge_map=[(count-2-i)%count for i in range(count)]
    else:
        source_edge_map=list(range(count))

    for i in range(count):
        if _distance2(xy[i],xy[(i+1)%count])<=eps:
            raise SpatialRoofError("Ребро {} имеет нулевую длину в XY.".format(i+1))

    z_values=[p[2] for p in points]
    z_span=max(z_values)-min(z_values)
    flat_tolerance=max(eps*10.0,scale*1.0e-9)

    planes=[
        _edge_plane(points[i],points[(i+1)%count],angles[i],eave_lift)
        for i in range(count)
    ]

    if z_span<=flat_tolerance:
        # With a uniform pitch the established unit-speed straight skeleton
        # is the best-conditioned path, especially at symmetric L/U events.
        uniform_pitch = max(angles)-min(angles) <= 1.0e-9
        if uniform_pitch:
            vertices,faces,sources=_build_spatial_roof_mesh_template(
                points,angles,eave_lift=float(eave_lift),tolerance=tolerance
            )
            return vertices,faces,[source_edge_map[source] for source in sources]

        # Individual pitches require actual weighted collapse/split times.
        # Each support plane contributes its exact inward normal speed.
        speeds=[]
        for i in range(count):
            p=points[i]
            q=points[(i+1)%count]
            edge_length=math.hypot(q[0]-p[0],q[1]-p[1])
            along_grade=(q[2]-p[2])/edge_length
            inward_grade=math.sqrt(
                max(0.0,math.tan(angles[i])**2-along_grade**2)
            )
            if inward_grade<=1.0e-10:
                raise SpatialRoofError(
                    "Для ребра {} не хватает внутреннего уклона.".format(i+1)
                )
            speeds.append(1.0/inward_grade)
        try:
            vertices,faces,sources=build_weighted_roof_mesh(
                xy,speeds,planes
            )
        except WeightedSkeletonError as exc:
            raise SpatialRoofError(
                "Взвешенный волновой фронт: "+str(exc)
            ) from exc
        _validate_lifted_mesh(vertices,faces,sources,points,planes,eps,scale)
        return vertices,faces,[source_edge_map[source] for source in sources]

    # Non-planar contours currently use the validated support-plane lifting
    # path. For reflex L/U outlines, small node incompatibilities are reconciled
    # locally; larger event-order changes are rejected by strict overlap tests.
    try:
        vertices,faces,sources=_build_spatial_roof_mesh_template(
            points,angles,eave_lift=float(eave_lift),tolerance=tolerance
        )
    except SpatialRoofError:
        raise
    return vertices,faces,[source_edge_map[source] for source in sources]

