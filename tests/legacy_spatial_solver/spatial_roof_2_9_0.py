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
    from .straight_skeleton_2_6_0 import build_roof_mesh, SkeletonError, _merge_coplanar_roof_faces
    from .weighted_skeleton_2_9_0 import (
        build_weighted_roof_mesh,
        _merge_face_patches,
        _split_global_t_junctions,
        SkeletonError as WeightedSkeletonError,
    )
except ImportError:
    from straight_skeleton_2_6_0 import build_roof_mesh, SkeletonError, _merge_coplanar_roof_faces
    from weighted_skeleton_2_9_0 import (
        build_weighted_roof_mesh,
        _merge_face_patches,
        _split_global_t_junctions,
        SkeletonError as WeightedSkeletonError,
    )


class SpatialRoofError(ValueError):
    """The requested 3D eave/pitch combination has no valid lifted topology."""


def _source_id_values(source_id):
    """Normalize one source ID or a merged tuple of IDs without int(tuple)."""
    if isinstance(source_id, (tuple, list, set)):
        return tuple(int(value) for value in source_id)
    return (int(source_id),)


def _representative_source_id(source_id):
    """Choose a stable scalar label for Blender's integer face attributes."""
    values = _source_id_values(source_id)
    if -2 in values:
        return -2
    positive = [value for value in values if value >= 0]
    return min(positive) if positive else (values[0] if values else -1)


def _remap_source_id(source_id, source_edge_map):
    values = _source_id_values(source_id)
    mapped = tuple(
        source_edge_map[value] if value >= 0 else value
        for value in values
    )
    return mapped[0] if len(mapped) == 1 else mapped


def _unique_support_sources(source_ids, planes, tolerance):
    """Collapse source IDs that describe the same coplanar support plane."""
    result = []
    plane_tolerance = max(1.0e-9, float(tolerance) * 10.0)
    for source_id in sorted(set(int(value) for value in source_ids if int(value) >= 0)):
        plane = planes[source_id]
        if any(
            max(abs(plane[i] - planes[existing][i]) for i in range(3))
            <= plane_tolerance
            for existing in result
        ):
            continue
        result.append(source_id)
    return result


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
        min(scale * 1.25e-2, eave_height_range * 0.75)
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
        raw_incident_sources = (
            source_id
            for face_index in incident_faces
            for source_id in _source_id_values(template_sources[face_index])
        )
        incident_sources = _unique_support_sources(
            raw_incident_sources, planes, eps
        )
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
                _representative_source_id(template_sources[face_index]),
            )
        )
        fan_sources = [
            _representative_source_id(template_sources[i]) for i in fan
        ]
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
            # A coplanar template face can retain several original eave-edge IDs.
            # Keep the full set for overhang extension and support-plane validation.
            output_sources.append(template_sources[face_index])

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
        min(scale * 1.25e-2, eave_height_range * 0.75)
    )
    for face_index, face in enumerate(faces):
        if len(face) < 3:
            raise SpatialRoofError("В пространственной сетке обнаружена грань менее чем из трёх вершин.")
        points = [vertices[i] for i in face]
        source_ids = [
            source_id for source_id in _source_id_values(sources[face_index])
            if source_id >= 0
        ]
        for source_id in source_ids:
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
    # Sweep by the minimum X coordinate first: most edge pairs are far apart in
    # the plan and can be discarded using their bounding boxes before the exact
    # orientation test. The previous all-pairs loop did quadratic work even for
    # roofs whose facets occupy disjoint regions of the plan.
    bbox_eps = eps * 20.0
    face_edges = []
    for face_index, face in enumerate(faces):
        for i, a in enumerate(face):
            b = face[(i + 1) % len(face)]
            pa, pb = vertices[a], vertices[b]
            face_edges.append((
                face_index, a, b,
                min(pa[0], pb[0]), max(pa[0], pb[0]),
                min(pa[1], pb[1]), max(pa[1], pb[1]),
            ))
    face_edges.sort(key=lambda item: item[3])
    active_edges = []
    for current in face_edges:
        face_b, c, d, min_x, max_x, min_y, max_y = current
        active_edges = [
            item for item in active_edges
            if item[4] >= min_x - bbox_eps
        ]
        for item in active_edges:
            face_a, a, b, _min_ax, max_ax, min_ay, max_ay = item
            if face_a == face_b or len({a, b, c, d}) < 4:
                continue
            if max_ay < min_y - bbox_eps or max_y < min_ay - bbox_eps:
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
        active_edges.append(current)

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
    # overlap even when their polygon edges do not cross. Use the same X-sweep
    # broad phase to avoid testing every facet against every other facet.
    face_records = []
    for face_index, face in enumerate(faces):
        points_xy = [(vertices[i][0], vertices[i][1]) for i in face]
        centroid = (
            sum(point[0] for point in points_xy) / len(points_xy),
            sum(point[1] for point in points_xy) / len(points_xy),
        )
        face_records.append((
            face_index,
            min(point[0] for point in points_xy),
            max(point[0] for point in points_xy),
            min(point[1] for point in points_xy),
            max(point[1] for point in points_xy),
            centroid,
            set(face),
            points_xy,
        ))
    face_records.sort(key=lambda item: item[1])
    active_faces = []
    for current in face_records:
        (face_index, min_x, max_x, min_y, max_y,
         centroid, vertex_set, face_polygon) = current
        active_faces = [
            item for item in active_faces
            if item[2] >= min_x - eps
        ]
        for other in active_faces:
            (other_index, _other_min_x, _other_max_x,
             other_min_y, other_max_y, other_centroid,
             other_vertex_set, other_polygon) = other
            if min(max_y, other_max_y) < max(min_y, other_min_y) - eps:
                continue
            if len(vertex_set & other_vertex_set) >= 2:
                continue
            if (_inside_or_on(centroid, other_polygon, eps)
                    or _inside_or_on(other_centroid, face_polygon, eps)):
                raise SpatialRoofError(
                    "Два пространственных ската перекрывают одну область плана."
                )
        active_faces.append(current)


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
    # Weighted wavefront supplies the actual edge-to-edge topology.
    speeds = []
    for edge_id in range(count):
        p = points[edge_id]
        q = points[(edge_id + 1) % count]
        edge_length = math.hypot(q[0] - p[0], q[1] - p[1])
        along_grade = (q[2] - p[2]) / edge_length
        inward_grade = math.sqrt(
            max(0.0, math.tan(float(pitch_angles[edge_id])) ** 2 - along_grade ** 2)
        )
        if inward_grade <= 1.0e-10:
            raise SpatialRoofError(
                "Для ребра карниза {} недостаточен угол ската после учёта перепада высот.".format(
                    edge_id + 1
                )
            )
        speeds.append(1.0 / inward_grade)

    try:
        topology_vertices, topology_faces, topology_sources = build_weighted_roof_mesh(
            xy, speeds, planes
        )
    except WeightedSkeletonError:
        # A modest non-planar eave can alter 3D heights without altering the
        # underlying XY event topology. Fall back to the proven unit-speed
        # skeleton for adjacency instead of rejecting the roof here.
        try:
            topology_vertices, topology_faces, topology_sources = build_roof_mesh(
                xy, 1.0, 0.0, allow_oblique=True
            )
        except SkeletonError as exc:
            raise SpatialRoofError("Не удалось получить топологию скатов: " + str(exc)) from exc

    adjacency = _derive_source_adjacency(
        topology_vertices,
        topology_faces,
        topology_sources,
        max(eps * 10.0, 1.0e-8),
    )
    triangles = _triangulate_xy(xy, eps)
    vertices, faces, sources = _build_boundary_aware_spatial_envelope(
        points, pitch_angles, planes, adjacency, triangles, eps, eave_lift
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



def _triangulate_xy(poly, eps):
    points = [tuple(p) for p in poly]
    if _area(points) < 0.0:
        points.reverse()
    indices = list(range(len(points)))
    triangles = []

    def triangle_contains(point, a, b, c):
        return (
            _cross2((b[0] - a[0], b[1] - a[1]), (point[0] - a[0], point[1] - a[1])) >= -eps
            and _cross2((c[0] - b[0], c[1] - b[1]), (point[0] - b[0], point[1] - b[1])) >= -eps
            and _cross2((a[0] - c[0], a[1] - c[1]), (point[0] - c[0], point[1] - c[1])) >= -eps
        )

    guard = 0
    while len(indices) > 3:
        guard += 1
        if guard > len(points) * len(points) * 2:
            raise SpatialRoofError("Не удалось триангулировать XY-контур крыши.")
        found = False
        for position in range(len(indices)):
            ia = indices[position - 1]
            ib = indices[position]
            ic = indices[(position + 1) % len(indices)]
            a, b, c = points[ia], points[ib], points[ic]
            if _cross2((b[0] - a[0], b[1] - a[1]),
                       (c[0] - b[0], c[1] - b[1])) <= eps:
                continue
            if any(
                triangle_contains(points[index], a, b, c)
                for index in indices
                if index not in (ia, ib, ic)
            ):
                continue
            triangles.append((a, b, c))
            indices.pop(position)
            found = True
            break
        if not found:
            raise SpatialRoofError(
                "XY-контур самопересекается или содержит вырожденный угол."
            )
    if len(indices) == 3:
        triangles.append(tuple(points[index] for index in indices))
    return triangles


def _clip_halfplane(poly, a, b, c, eps):
    if not poly:
        return []
    result = []
    for p, q in zip(poly, poly[1:] + poly[:1]):
        fp = a * p[0] + b * p[1] + c
        fq = a * q[0] + b * q[1] + c
        p_inside = fp <= eps
        q_inside = fq <= eps
        if p_inside:
            result.append(p)
        if p_inside != q_inside:
            denominator = fp - fq
            if abs(denominator) > 1.0e-20:
                t = fp / denominator
                result.append((
                    p[0] + (q[0] - p[0]) * t,
                    p[1] + (q[1] - p[1]) * t,
                ))
    cleaned = []
    for point in result:
        if not cleaned or _distance2(point, cleaned[-1]) > eps:
            cleaned.append(tuple(point))
    if len(cleaned) > 1 and _distance2(cleaned[0], cleaned[-1]) <= eps:
        cleaned.pop()
    return cleaned


def _derive_source_adjacency(vertices, faces, sources, tolerance):
    """Return source-edge adjacency from the weighted skeleton mesh."""
    edge_sources = defaultdict(set)

    canonical = []
    buckets = defaultdict(list)
    point_ids = {}

    def point_id(point):
        key = tuple(int(round(float(v) / tolerance)) for v in point)
        for index in buckets[key]:
            if _distance2(canonical[index], point) <= tolerance * 2.0:
                return index
        index = len(canonical)
        canonical.append((float(point[0]), float(point[1])))
        buckets[key].append(index)
        return index

    for face_index, face in enumerate(faces):
        source = int(sources[face_index])
        ids = [point_id(vertices[index]) for index in face]
        for a, b in zip(ids, ids[1:] + ids[:1]):
            if a != b:
                edge_sources[tuple(sorted((a, b)))].add(source)

    adjacency = defaultdict(set)
    for source_ids in edge_sources.values():
        clean = sorted(source_ids)
        if len(clean) == 2 and clean[0] != clean[1]:
            adjacency[clean[0]].add(clean[1])
            adjacency[clean[1]].add(clean[0])
    return adjacency


def _split_polygon_by_line(poly, a, b, c, eps):
    positive = _clip_halfplane(poly, -a, -b, -c, eps)
    negative = _clip_halfplane(poly, a, b, c, eps)
    result = []
    if len(positive) >= 3 and abs(_area(positive)) > eps * eps:
        result.append(positive)
    if len(negative) >= 3 and abs(_area(negative)) > eps * eps:
        result.append(negative)
    return result


def _polygon_centroid_xy(poly):
    area = _area(poly)
    if abs(area) <= 1.0e-20:
        return (
            sum(point[0] for point in poly) / len(poly),
            sum(point[1] for point in poly) / len(poly),
        )
    cx = cy = 0.0
    for a, b in zip(poly, poly[1:] + poly[:1]):
        cross = a[0] * b[1] - b[0] * a[1]
        cx += (a[0] + b[0]) * cross
        cy += (a[1] + b[1]) * cross
    factor = 1.0 / (6.0 * area)
    return cx * factor, cy * factor


def _build_boundary_aware_spatial_envelope(
    topology_vertices, topology_faces, topology_sources,
    points, planes, eps
):
    """Build a locally constrained lower envelope inside each XY topology cell."""
    merge_scale=max(eps*10.0,1.0e-8)
    xy=[(float(p[0]),float(p[1])) for p in points]
    patches_by_source=defaultdict(list)

    def boundary_owner(poly):
        owners=set()
        for edge_id,(p,q) in enumerate(zip(xy,xy[1:]+xy[:1])):
            for a,b in zip(poly,poly[1:]+poly[:1]):
                oa,_,_=_point_on_segment(a,p,q,eps*10.0)
                ob,_,_=_point_on_segment(b,p,q,eps*10.0)
                if oa and ob and _distance2(a,b)>eps:
                    owners.add(edge_id)
        return next(iter(owners)) if len(owners)==1 else None

    def split_winner_cell(poly,winner,challenger):
        forced_parent=boundary_owner(poly)
        effective_winner=(
            forced_parent if forced_parent is not None else winner
        )
        pa=planes[effective_winner]
        pb=planes[challenger]
        a=pa[0]-pb[0]
        b=pa[1]-pb[1]
        cc=pa[2]-pb[2]
        if math.hypot(a,b)<=eps:
            return [(poly,effective_winner)]
        pieces=[]
        low=_clip_halfplane(poly,a,b,cc,eps*5.0)
        high=_clip_halfplane(poly,-a,-b,-cc,eps*5.0)
        if len(low)>=3 and abs(_area(low))>eps*eps:
            forced=boundary_owner(low)
            source=(
                forced
                if forced is not None
                else effective_winner
            )
            pieces.append((low,source))
        if len(high)>=3 and abs(_area(high))>eps*eps:
            forced=boundary_owner(high)
            source=(
                forced
                if forced is not None
                else challenger
            )
            pieces.append((high,source))
        return pieces

    for face_index,face in enumerate(topology_faces):
        base_source=int(topology_sources[face_index])
        mask=[
            (float(topology_vertices[index][0]),float(topology_vertices[index][1]))
            for index in face
        ]
        if len(mask)<3 or abs(_area(mask))<=eps*eps:
            continue

        cells=[(list(triangle),base_source)
               for triangle in _triangulate_xy(mask,eps)]
        for challenger in range(len(planes)):
            new_cells=[]
            for cell,winner in cells:
                if challenger==winner:
                    new_cells.append((cell,winner))
                    continue
                # A boundary-owned piece must keep its eave source even when
                # a remote support plane is lower just inside the footprint.
                split_winner_cell_result=split_winner_cell(
                    cell,winner,challenger
                )
                new_cells.extend(split_winner_cell_result)
            cells=new_cells
            if not cells:
                break

        for cell,source_id in cells:
            if len(cell)<3 or abs(_area(cell))<=eps*eps:
                continue
            plane=planes[source_id]
            patch=[
                (
                    float(x),float(y),
                    _plane_value(plane,float(x),float(y))
                )
                for x,y in cell
            ]
            if _area(cell)<0.0:
                patch.reverse()
            patches_by_source[int(source_id)].append(patch)

    if not patches_by_source:
        raise SpatialRoofError(
            "Не удалось получить области пространственной крыши."
        )

    grouped=[]
    for source_id,patches in sorted(patches_by_source.items()):
        for loop in _merge_face_patches(patches,merge_scale):
            if len(loop)>=3:
                grouped.append((source_id,loop))

    if not grouped:
        raise SpatialRoofError(
            "После объединения локальных пространственных фрагментов "
            "не осталось скатов."
        )

    # Same-source union is exact; common seam vertices are then canonicalized.
    vertices=[]
    faces=[]
    sources=[]
    buckets=defaultdict(list)

    def add_point(point):
        key=tuple(int(round(float(v)/merge_scale)) for v in point)
        for index in buckets[key]:
            if _distance3(vertices[index],point)<=merge_scale*2.0:
                return index
        index=len(vertices)
        vertices.append(tuple(float(v) for v in point))
        buckets[key].append(index)
        return index

    for source_id,loop in grouped:
        face=[add_point(point) for point in loop]
        clean=[]
        for index in face:
            if not clean or clean[-1]!=index:
                clean.append(index)
        if len(clean)>1 and clean[0]==clean[-1]:
            clean.pop()
        if len(clean)<3:
            continue
        if _area([(vertices[i][0],vertices[i][1]) for i in clean])<0.0:
            clean.reverse()
        faces.append(tuple(clean))
        sources.append(int(source_id))

    vertices,faces,sources=_merge_coplanar_roof_faces(
        vertices,faces,sources,scale=max(merge_scale,eps*10.0)
    )

    # The topology-cell boundaries may not coincide with the exact 3D seam
    # after the local winner changes. Repair only near-coincident internal
    # edges by the exact intersection of the two owning support planes.
    face_loops=[]
    for face,source_id in zip(faces,sources):
        face_loops.append((
            int(source_id),
            [vertices[index] for index in face]
        ))
    plan_scale=max(
        max(p[0] for p in xy)-min(p[0] for p in xy),
        max(p[1] for p in xy)-min(p[1] for p in xy),
        1.0
    )
    face_loops=_repair_internal_seam_loops(
        face_loops,planes,topology_vertices,eps,plan_scale
    )

    vertices=[]
    faces=[]
    sources=[]
    buckets=defaultdict(list)

    def add_final(point):
        key=tuple(int(round(float(v)/merge_scale)) for v in point)
        for index in buckets[key]:
            if _distance3(vertices[index],point)<=merge_scale*2.0:
                return index
        index=len(vertices)
        vertices.append(tuple(float(v) for v in point))
        buckets[key].append(index)
        return index

    for source_id,loop in face_loops:
        face=[add_final(point) for point in loop]
        clean=[]
        for index in face:
            if not clean or clean[-1]!=index:
                clean.append(index)
        if len(clean)>1 and clean[0]==clean[-1]:
            clean.pop()
        if len(clean)>=3:
            faces.append(tuple(clean))
            sources.append(source_id)

    return vertices,faces,sources



def _point_to_line_parameter(point, line_point, direction):
    denominator = direction[0] * direction[0] + direction[1] * direction[1]
    if denominator <= 1.0e-20:
        return 0.0
    return (
        (point[0] - line_point[0]) * direction[0]
        + (point[1] - line_point[1]) * direction[1]
    ) / denominator


def _plane_intersection_xy(plane_a, plane_b, eps):
    a = float(plane_a[0]) - float(plane_b[0])
    b = float(plane_a[1]) - float(plane_b[1])
    c = float(plane_a[2]) - float(plane_b[2])
    length = math.hypot(a, b)
    if length <= eps:
        return None
    if abs(a) >= abs(b):
        line_point = (-c / a, 0.0)
    else:
        line_point = (0.0, -c / b)
    direction = (b / length, -a / length)
    return line_point, direction


def _segment_projection_interval_xy(segment, line_point, direction):
    t0 = _point_to_line_parameter(segment[0], line_point, direction)
    t1 = _point_to_line_parameter(segment[1], line_point, direction)
    return min(t0, t1), max(t0, t1)


def _segments_are_near_parallel(a, b, c, d, tolerance):
    ab = (b[0] - a[0], b[1] - a[1])
    cd = (d[0] - c[0], d[1] - c[1])
    la = math.hypot(*ab)
    lc = math.hypot(*cd)
    if la <= tolerance or lc <= tolerance:
        return False
    cross = abs(ab[0] * cd[1] - ab[1] * cd[0]) / (la * lc)
    return cross <= 0.05


def _repair_internal_seam_loops(face_loops, planes, outline_vertices, eps, scale):
    """Snap every candidate internal seam to the exact intersection of its two planes."""
    if len(face_loops)<2:
        return face_loops

    outline=[(float(v[0]),float(v[1])) for v in outline_vertices]
    seam_tolerance=max(eps*100.0,scale*2.0e-2)

    def on_outline(a,b):
        for i,p in enumerate(outline):
            q=outline[(i+1)%len(outline)]
            oa,_,_= _point_on_segment(a[:2],p,q,seam_tolerance)
            ob,_,_= _point_on_segment(b[:2],p,q,seam_tolerance)
            if oa and ob:
                return True
        return False

    def line_distance(point,line_point,direction):
        return abs(
            direction[0]*(point[1]-line_point[1])
            - direction[1]*(point[0]-line_point[0])
        )

    for _pass in range(8):
        changed=False
        records=[]
        for face_index,(source_id,loop) in enumerate(face_loops):
            for local_index,a in enumerate(loop):
                b=loop[(local_index+1)%len(loop)]
                if _distance2(a[:2],b[:2])<=eps or on_outline(a,b):
                    continue
                records.append((face_index,source_id,local_index,a,b))

        used=set()
        for i,first in enumerate(records):
            face_a,source_a,index_a,a,b=first
            len_a=_distance2(a[:2],b[:2])
            for j in range(i+1,len(records)):
                face_b,source_b,index_b,c,d=records[j]
                if face_a==face_b or source_a==source_b:
                    continue
                if (face_a,index_a) in used or (face_b,index_b) in used:
                    continue

                line=_plane_intersection_xy(
                    planes[source_a],planes[source_b],max(eps,1.0e-12)
                )
                if line is None:
                    continue
                line_point,direction=line
                if max(
                    line_distance(a[:2],line_point,direction),
                    line_distance(b[:2],line_point,direction),
                    line_distance(c[:2],line_point,direction),
                    line_distance(d[:2],line_point,direction),
                )>seam_tolerance:
                    continue

                ia=_segment_projection_interval_xy((a[:2],b[:2]),line_point,direction)
                ib=_segment_projection_interval_xy((c[:2],d[:2]),line_point,direction)
                low=max(ia[0],ib[0])
                high=min(ia[1],ib[1])
                overlap=high-low
                min_length=min(len_a,_distance2(c[:2],d[:2]))
                if overlap<=max(eps*10.0,min_length*0.20):
                    continue

                p0xy=(
                    line_point[0]+direction[0]*low,
                    line_point[1]+direction[1]*low,
                )
                p1xy=(
                    line_point[0]+direction[0]*high,
                    line_point[1]+direction[1]*high,
                )
                plane=planes[source_a]
                p0=(p0xy[0],p0xy[1],_plane_value(plane,*p0xy))
                p1=(p1xy[0],p1xy[1],_plane_value(plane,*p1xy))

                loop_a=list(face_loops[face_a][1])
                loop_b=list(face_loops[face_b][1])
                oa0=loop_a[index_a]; oa1=loop_a[(index_a+1)%len(loop_a)]
                ob0=loop_b[index_b]; ob1=loop_b[(index_b+1)%len(loop_b)]

                a_forward=(
                    _distance2(oa0[:2],p0xy)+_distance2(oa1[:2],p1xy)
                    <=
                    _distance2(oa0[:2],p1xy)+_distance2(oa1[:2],p0xy)
                )
                b_forward=(
                    _distance2(ob0[:2],p0xy)+_distance2(ob1[:2],p1xy)
                    <=
                    _distance2(ob0[:2],p1xy)+_distance2(ob1[:2],p0xy)
                )
                if a_forward:
                    loop_a[index_a]=p0
                    loop_a[(index_a+1)%len(loop_a)]=p1
                else:
                    loop_a[index_a]=p1
                    loop_a[(index_a+1)%len(loop_a)]=p0
                if b_forward:
                    loop_b[index_b]=p0
                    loop_b[(index_b+1)%len(loop_b)]=p1
                else:
                    loop_b[index_b]=p1
                    loop_b[(index_b+1)%len(loop_b)]=p0

                face_loops[face_a]=(source_a,loop_a)
                face_loops[face_b]=(source_b,loop_b)
                used.add((face_a,index_a))
                used.add((face_b,index_b))
                changed=True
                break
            if changed:
                break
        if not changed:
            break
    return face_loops


def _build_nonplanar_lower_envelope(points, planes, eps):
    xy = [(float(point[0]), float(point[1])) for point in points]
    triangles = _triangulate_xy(xy, eps)
    patches_by_source = defaultdict(list)

    def boundary_source(cell):
        found = set()
        for edge_index, p in enumerate(xy):
            q = xy[(edge_index + 1) % len(xy)]
            for a, b in zip(cell, cell[1:] + cell[:1]):
                on_a, _, _ = _point_on_segment(a, p, q, eps * 10.0)
                on_b, _, _ = _point_on_segment(b, p, q, eps * 10.0)
                if on_a and on_b and _distance2(a, b) > eps:
                    found.add(edge_index)
        return next(iter(found)) if len(found) == 1 else None

    for triangle in triangles:
        cells = [list(triangle)]
        for source_a in range(len(planes)):
            for source_b in range(source_a + 1, len(planes)):
                pa, pb = planes[source_a], planes[source_b]
                a = float(pa[0]) - float(pb[0])
                b = float(pa[1]) - float(pb[1])
                cc = float(pa[2]) - float(pb[2])
                if math.hypot(a, b) <= eps:
                    continue
                split = []
                for cell in cells:
                    split.extend(_split_polygon_by_line(cell, a, b, cc, eps * 5.0))
                cells = split
                if not cells:
                    break
            if not cells:
                break

        for cell in cells:
            if len(cell) < 3 or abs(_area(cell)) <= eps * eps:
                continue
            forced = boundary_source(cell)
            centroid = _polygon_centroid_xy(cell)
            source_id = (
                forced
                if forced is not None
                else min(
                    range(len(planes)),
                    key=lambda index: _plane_value(
                        planes[index], centroid[0], centroid[1]
                    ),
                )
            )
            plane = planes[source_id]
            patch = [
                (
                    float(x),
                    float(y),
                    float(plane[0]) * x + float(plane[1]) * y + float(plane[2]),
                )
                for x, y in cell
            ]
            if _area(cell) < 0.0:
                patch.reverse()
            patches_by_source[source_id].append(patch)

    if not patches_by_source:
        raise SpatialRoofError("Не удалось построить нижнюю огибающую опорных плоскостей.")

    merge_scale = max(eps * 10.0, 1.0e-8)
    face_loops = []
    for source_id, patches in sorted(patches_by_source.items()):
        for loop in _merge_face_patches(patches, merge_scale):
            if len(loop) >= 3:
                face_loops.append((source_id, loop))

    if not face_loops:
        raise SpatialRoofError("Нижняя огибающая не сформировала ни одного ската.")

    face_loops = _split_global_t_junctions(face_loops, merge_scale)
    vertices = []
    faces = []
    sources = []
    buckets = defaultdict(list)

    def add_vertex(point):
        key = tuple(int(round(float(v) / merge_scale)) for v in point)
        for index in buckets[key]:
            if _distance3(vertices[index], point) <= merge_scale * 2.0:
                return index
        index = len(vertices)
        vertices.append(tuple(float(v) for v in point))
        buckets[key].append(index)
        return index

    for source_id, loop in face_loops:
        face = [add_vertex(point) for point in loop]
        clean = []
        for index in face:
            if not clean or clean[-1] != index:
                clean.append(index)
        if len(clean) > 1 and clean[0] == clean[-1]:
            clean.pop()
        if len(clean) < 3:
            continue
        if _area([(vertices[index][0], vertices[index][1]) for index in clean]) < 0.0:
            clean.reverse()
        faces.append(tuple(clean))
        sources.append(source_id)
    return vertices, faces, sources


def _build_mask_clipped_spatial_roof(
    topology_vertices, topology_faces, topology_sources,
    planes, adjacency, eps
):
    """Clip each 2D skeleton facet by exact intersections with its neighbours."""
    merge_scale=max(eps*10.0,1.0e-8)
    patches_by_source=defaultdict(list)

    for face_index, face in enumerate(topology_faces):
        source_id=int(topology_sources[face_index])
        mask=[
            (float(topology_vertices[index][0]),float(topology_vertices[index][1]))
            for index in face
        ]
        if len(mask)<3 or abs(_area(mask))<=eps*eps:
            continue
        cell=list(mask)
        for neighbour_id in sorted(adjacency.get(source_id,())):
            plane=planes[source_id]
            other=planes[neighbour_id]
            cell=_clip_halfplane(
                cell,
                plane[0]-other[0],
                plane[1]-other[1],
                plane[2]-other[2],
                eps*5.0,
            )
            if len(cell)<3:
                break
        if len(cell)<3 or abs(_area(cell))<=eps*eps:
            continue
        plane=planes[source_id]
        lifted=[
            (
                float(x),float(y),
                float(plane[0])*x+float(plane[1])*y+float(plane[2])
            )
            for x,y in cell
        ]
        if _area(cell)<0.0:
            lifted.reverse()
        patches_by_source[source_id].append(lifted)

    face_loops=[]
    for source_id,patches in sorted(patches_by_source.items()):
        for loop in _merge_face_patches(patches,merge_scale):
            if len(loop)>=3:
                face_loops.append((source_id,loop))
    if not face_loops:
        raise SpatialRoofError("Не удалось сформировать пространственные скаты из topology masks.")

    face_loops=_split_global_t_junctions(face_loops,merge_scale)

    vertices=[]
    faces=[]
    sources=[]
    buckets=defaultdict(list)

    def add_vertex(point):
        key=tuple(int(round(float(v)/merge_scale)) for v in point)
        for index in buckets[key]:
            if _distance3(vertices[index],point)<=merge_scale*2.0:
                return index
        index=len(vertices)
        vertices.append(tuple(float(v) for v in point))
        buckets[key].append(index)
        return index

    for source_id,loop in face_loops:
        face=[add_vertex(point) for point in loop]
        clean=[]
        for index in face:
            if not clean or clean[-1]!=index:
                clean.append(index)
        if len(clean)>1 and clean[0]==clean[-1]:
            clean.pop()
        if len(clean)<3:
            continue
        if _area([(vertices[index][0],vertices[index][1]) for index in clean])<0.0:
            clean.reverse()
        faces.append(tuple(clean))
        sources.append(int(source_id))
    return vertices,faces,sources


def _line_segment_intersections(a,b,c,points,eps):
    """Clip a*x+b*y+c=0 to a simple polygon, returning disjoint segments."""
    length=math.hypot(a,b)
    if length<=eps:
        return []
    # Point on the infinite line.
    if abs(a)>=abs(b):
        origin=(-c/a,0.0)
    else:
        origin=(0.0,-c/b)
    direction=(b/length,-a/length)

    values=[]
    for p,q in zip(points,points[1:]+points[:1]):
        fp=a*p[0]+b*p[1]+c
        fq=a*q[0]+b*q[1]+c
        if abs(fp)<=eps:
            values.append(_point_to_line_parameter(p,origin,direction))
        if fp*fq<-(eps*eps):
            t=fp/(fp-fq)
            hit=(p[0]+(q[0]-p[0])*t,p[1]+(q[1]-p[1])*t)
            values.append(_point_to_line_parameter(hit,origin,direction))
    values=sorted(values)
    unique=[]
    for value in values:
        if not unique or abs(value-unique[-1])>eps:
            unique.append(value)
    segments=[]
    for t0,t1 in zip(unique,unique[1:]):
        if t1-t0<=eps:
            continue
        tm=(t0+t1)*0.5
        midpoint=(origin[0]+direction[0]*tm,origin[1]+direction[1]*tm)
        if _inside_or_on(midpoint,points,eps*20.0):
            p0=(origin[0]+direction[0]*t0,origin[1]+direction[1]*t0)
            p1=(origin[0]+direction[0]*t1,origin[1]+direction[1]*t1)
            segments.append((p0,p1))
    return segments


def _segment_pair_parameters(a,b,c,d,eps):
    r=(b[0]-a[0],b[1]-a[1])
    s=(d[0]-c[0],d[1]-c[1])
    den=_cross2(r,s)
    q=(c[0]-a[0],c[1]-a[1])
    if abs(den)>eps:
        t=_cross2(q,s)/den
        u=_cross2(q,r)/den
        if -eps<=t<=1.0+eps and -eps<=u<=1.0+eps:
            return [(max(0.0,min(1.0,t)),max(0.0,min(1.0,u)))]
        return []
    if abs(_cross2(q,r))>eps:
        return []
    rr=r[0]*r[0]+r[1]*r[1]
    ss=s[0]*s[0]+s[1]*s[1]
    result=[]
    if rr>eps*eps:
        for p in (c,d):
            result.append((
                ((p[0]-a[0])*r[0]+(p[1]-a[1])*r[1])/rr,
                0.0,
            ))
    if ss>eps*eps:
        for p in (a,b):
            result.append((
                0.0,
                ((p[0]-c[0])*s[0]+(p[1]-c[1])*s[1])/ss,
            ))
    return [
        (max(0.0,min(1.0,t)),max(0.0,min(1.0,u)))
        for t,u in result
        if -eps<=t<=1.0+eps and -eps<=u<=1.0+eps
    ]


def _build_planar_support_arrangement(\n    points, planes, eps, allowed_pairs=None, label_by_minimum=False\n):
    """Exact planar arrangement with boundary-owned roof cells."""
    xy=[(float(p[0]),float(p[1])) for p in points]
    raw_segments=[]

    # Ordered boundary segments carry their eave source id.
    for edge_id,(p,q) in enumerate(zip(xy,xy[1:]+xy[:1])):
        raw_segments.append({
            "a":p,"b":q,"kind":"boundary","label":edge_id,"params":[0.0,1.0]
        })

    # Only topologically adjacent plane pairs are allowed to become roof
    # seams. Without this restriction, every mathematical plane crossing would
    # create spurious cells unrelated to the roof wavefront.
    if allowed_pairs is None:
        pair_list=[
            (source_a,source_b)
            for source_a in range(len(planes))
            for source_b in range(source_a+1,len(planes))
        ]
    else:
        pair_list=sorted({
            tuple(sorted((int(pair[0]),int(pair[1]))))
            for pair in allowed_pairs
            if pair[0]!=pair[1]
        })

    for source_a,source_b in pair_list:
        pa=planes[source_a]; pb=planes[source_b]
        a=pa[0]-pb[0]; b=pa[1]-pb[1]; cc=pa[2]-pb[2]
        for p0,p1 in _line_segment_intersections(a,b,cc,xy,eps*5.0):
            raw_segments.append({
                "a":p0,"b":p1,"kind":"pair",
                "label":(source_a,source_b),"params":[0.0,1.0]
            })

    for i,first in enumerate(raw_segments):
        a,b=first["a"],first["b"]
        for j in range(i+1,len(raw_segments)):
            second=raw_segments[j]
            for t,u in _segment_pair_parameters(a,b,second["a"],second["b"],eps*5.0):
                first["params"].append(t)
                second["params"].append(u)

    vertices=[]
    buckets=defaultdict(list)
    merge_tol=max(eps*5.0,1.0e-9)

    def add_point(point):
        key=(int(round(point[0]/merge_tol)),int(round(point[1]/merge_tol)))
        for index in buckets[key]:
            if _distance2(vertices[index],point)<=merge_tol*2.0:
                return index
        index=len(vertices)
        vertices.append((float(point[0]),float(point[1])))
        buckets[key].append(index)
        return index

    edges={}
    boundary_directed=defaultdict(set)
    for data in raw_segments:
        a,b=data["a"],data["b"]
        params=sorted(set(max(0.0,min(1.0,float(v))) for v in data["params"]))
        for t0,t1 in zip(params,params[1:]):
            if t1-t0<=eps:
                continue
            p0=(a[0]+(b[0]-a[0])*t0,a[1]+(b[1]-a[1])*t0)
            p1=(a[0]+(b[0]-a[0])*t1,a[1]+(b[1]-a[1])*t1)
            u=add_point(p0); v=add_point(p1)
            if u==v:
                continue
            key=(min(u,v),max(u,v))
            meta=edges.setdefault(key,{"pairs":set(),"boundaries":set()})
            if data["kind"]=="boundary":
                meta["boundaries"].add(int(data["label"]))
                boundary_directed[(u,v)].add(int(data["label"]))
            else:
                meta["pairs"].add(tuple(sorted(data["label"])))

    adjacency=defaultdict(list)
    for u,v in edges:
        adjacency[u].append(v)
        adjacency[v].append(u)
    for u in adjacency:
        adjacency[u].sort(key=lambda v:math.atan2(
            vertices[v][1]-vertices[u][1],vertices[v][0]-vertices[u][0]
        ))

    # Standard DCEL traversal. Every directed edge belongs to exactly one
    # face; the next edge is the outgoing half-edge immediately clockwise
    # from the reverse incoming half-edge.
    halfedges=[]
    outgoing=defaultdict(list)
    for u,v in edges:
        halfedges.append((u,v))
        halfedges.append((v,u))
        outgoing[u].append((u,v))
        outgoing[v].append((v,u))

    outgoing_order={}
    angle_index={}
    for vertex_id,items in outgoing.items():
        ordered=sorted(
            items,
            key=lambda edge:math.atan2(
                vertices[edge[1]][1]-vertices[vertex_id][1],
                vertices[edge[1]][0]-vertices[vertex_id][0]
            )
        )
        outgoing_order[vertex_id]=ordered
        for index,edge in enumerate(ordered):
            angle_index[edge]=index

    next_halfedge={}
    for u,v in halfedges:
        ordered=outgoing_order.get(v,())
        if not ordered:
            continue
        reverse=(v,u)
        reverse_index=angle_index.get(reverse)
        if reverse_index is None:
            continue
        next_halfedge[(u,v)]=ordered[
            (reverse_index-1)%len(ordered)
        ]

    halfedge_face={}
    faces=[]
    visited=set()
    for start_edge in halfedges:
        if start_edge in visited:
            continue
        current=start_edge
        loop=[]
        local=set()
        guard=0
        while current not in local and current not in visited:
            guard+=1
            if guard>len(halfedges)+4:
                raise SpatialRoofError("Не удалось замкнуть half-edge planar arrangement.")
            local.add(current)
            visited.add(current)
            loop.append(current[0])
            current=next_halfedge.get(current)
            if current is None:
                break

        if current!=start_edge or len(loop)<3:
            continue

        polygon=[vertices[index] for index in loop]
        area=_area(polygon)
        if area<=eps*eps:
            continue

        # The left-face traversal yields positive orientation for bounded
        # cells and negative orientation for the unbounded exterior face.
        face_id=len(faces)
        faces.append(loop)
        for a,b in zip(loop,loop[1:]+loop[:1]):
            halfedge_face[(a,b)]=face_id

    if not faces:
        raise SpatialRoofError("Planar arrangement не создал ячеек крыши.")

    edge_faces=defaultdict(set)
    for (a,b),face_id in halfedge_face.items():
        edge_faces[(min(a,b),max(a,b))].add(face_id)

    face_source=[None]*len(faces)

    # Seed source labels from the original eave boundary. Every interior roof
    # facet ultimately has to be connected to one of these boundary sources.
    for directed,source_ids in boundary_directed.items():
        face_id=halfedge_face.get(directed)
        if face_id is None:
            continue
        for source_id in sorted(source_ids):
            if face_source[face_id] is None:
                face_source[face_id]=int(source_id)
                break

    edge_faces=defaultdict(set)
    for (a,b),face_id in halfedge_face.items():
        edge_faces[(min(a,b),max(a,b))].add(face_id)

    if label_by_minimum:
        # The all-pairs arrangement partitions the footprint by every
        # pairwise plane equality line. Thus the ordering of plane heights is
        # constant inside each cell; choose its exact lower support at the
        # centroid instead of propagating labels across coincident DCEL seams.
        # Boundary-seeded cells retain their source edge by construction.
        for face_id, loop in enumerate(faces):
            if face_source[face_id] is not None:
                continue
            polygon = [vertices[index] for index in loop]
            centroid = _polygon_centroid_xy(polygon)
            face_source[face_id] = min(
                range(len(planes)),
                key=lambda source_id: _plane_value(
                    planes[source_id], centroid[0], centroid[1]
                )
            )
    else:
        # Propagate source labels across exact support-plane intersections.
        # Crossing an (i,j) arrangement edge switches from source i to source j.
        changed = True
        while changed:
            changed = False
            for edge_key, face_ids in edge_faces.items():
                if len(face_ids) != 2:
                    continue
                meta = edges.get(edge_key)
                if not meta or not meta["pairs"]:
                    continue
                a_face, b_face = tuple(face_ids)
                sa, sb = face_source[a_face], face_source[b_face]
                for pair in sorted(meta["pairs"]):
                    p, q = pair
                    if sa == p and sb is None:
                        face_source[b_face] = q
                        changed = True
                        break
                    if sa == q and sb is None:
                        face_source[b_face] = p
                        changed = True
                        break
                    if sb == p and sa is None:
                        face_source[a_face] = q
                        changed = True
                        break
                    if sb == q and sa is None:
                        face_source[a_face] = p
                        changed = True
                        break

        # Disconnected arrangement components are rare but possible at
        # coincident events. Choose the lowest plane only for such a component;
        # never overwrite a boundary-propagated source.
        for face_id, loop in enumerate(faces):
            if face_source[face_id] is not None:
                continue
            polygon = [vertices[index] for index in loop]
            centroid = _polygon_centroid_xy(polygon)
            face_source[face_id] = min(
                range(len(planes)),
                key=lambda source_id: _plane_value(
                    planes[source_id], centroid[0], centroid[1]
                )
            )

    # Every internal edge between different source cells must be the exact
    # pair of support planes carried by that arrangement edge.
    for edge_key,face_ids in edge_faces.items():
        if len(face_ids)!=2:
            continue
        sa,sb=[face_source[index] for index in face_ids]
        if sa==sb:
            continue
        meta=edges.get(edge_key)
        if not meta or not any(
            sa in pair and sb in pair for pair in meta["pairs"]
        ):
            a_vertex,b_vertex=edge_key
            raise SpatialRoofError(
                "Arrangement-ячейки получили несовместимые источники: "
                "edge {}-{} XY=({:.6f},{:.6f})->({:.6f},{:.6f}), "
                "sources=({},{}), allowed_pairs={}.".format(
                    a_vertex,b_vertex,
                    vertices[a_vertex][0],vertices[a_vertex][1],
                    vertices[b_vertex][0],vertices[b_vertex][1],
                    sa,sb,sorted(meta["pairs"]) if meta else []
                )
            )

    # Lift arrangement cells to their own support planes. Shared XY points
    # at a real seam become identical 3D points because both support planes
    # intersect there; same-source cells therefore share exact edges.
    out_vertices=[]
    out_faces=[]
    out_sources=[]
    out_buckets=defaultdict(list)
    merge_scale=max(eps*10.0,1.0e-8)

    def add_out(point):
        key=tuple(int(round(float(v)/merge_scale)) for v in point)
        for index in out_buckets[key]:
            if _distance3(out_vertices[index],point)<=merge_scale*2.0:
                return index
        index=len(out_vertices)
        out_vertices.append(tuple(float(v) for v in point))
        out_buckets[key].append(index)
        return index

    for face_id,loop in enumerate(faces):
        source_id=int(face_source[face_id])
        plane=planes[source_id]
        face=[]
        for vertex_index in loop:
            x,y=vertices[vertex_index]
            point=(x,y,_plane_value(plane,x,y))
            face.append(add_out(point))
        clean=[]
        for index in face:
            if not clean or clean[-1]!=index:
                clean.append(index)
        if len(clean)>1 and clean[0]==clean[-1]:
            clean.pop()
        if len(clean)<3:
            continue
        if _area([(out_vertices[index][0],out_vertices[index][1]) for index in clean])<0.0:
            clean.reverse()
        out_faces.append(tuple(clean))
        out_sources.append(source_id)

    if not out_faces:
        raise SpatialRoofError("Planar arrangement не сформировал скатов.")

    out_vertices,out_faces,out_sources=_merge_coplanar_roof_faces(
        out_vertices,out_faces,out_sources,scale=max(merge_scale,eps*10.0)
    )
    return out_vertices,out_faces,out_sources



def _build_triangulated_lower_envelope(points, planes, eps):
    """Exact lower support-plane envelope inside a triangulated footprint."""
    xy=[(float(p[0]),float(p[1])) for p in points]
    triangles=_triangulate_xy(xy,eps)
    patches=[]
    split_eps=eps*5.0

    def boundary_owner(poly):
        owners=set()
        for edge_id,(p,q) in enumerate(zip(xy,xy[1:]+xy[:1])):
            for a,b in zip(poly,poly[1:]+poly[:1]):
                oa,_,_=_point_on_segment(a,p,q,eps*10.0)
                ob,_,_=_point_on_segment(b,p,q,eps*10.0)
                if oa and ob and _distance2(a,b)>eps:
                    owners.add(edge_id)
        return next(iter(owners)) if len(owners)==1 else None

    for triangle in triangles:
        cells=[list(triangle)]
        for i in range(len(planes)):
            for j in range(i+1,len(planes)):
                pa,pb=planes[i],planes[j]
                a=pa[0]-pb[0]
                b=pa[1]-pb[1]
                cc=pa[2]-pb[2]
                if math.hypot(a,b)<=eps:
                    continue
                split=[]
                for cell in cells:
                    split.extend(
                        _split_polygon_by_line(cell,a,b,cc,split_eps)
                    )
                cells=split
                if not cells:
                    break
            if not cells:
                break

        for cell in cells:
            if len(cell)<3 or abs(_area(cell))<=eps*eps:
                continue
            forced=boundary_owner(cell)
            centroid=_polygon_centroid_xy(cell)
            source_id=(
                forced
                if forced is not None
                else min(
                    range(len(planes)),
                    key=lambda source:_plane_value(
                        planes[source],centroid[0],centroid[1]
                    )
                )
            )
            plane=planes[source_id]
            lifted=[
                (
                    float(x),float(y),
                    _plane_value(plane,float(x),float(y))
                )
                for x,y in cell
            ]
            if _area(cell)<0.0:
                lifted.reverse()
            patches.append((source_id,lifted))

    if not patches:
        raise SpatialRoofError(
            "Не удалось построить патчи нижней огибающей внутри триангуляции."
        )

    # Use the established exact same-source boundary union, then canonicalize
    # the shared 3D edges once globally.
    grouped=defaultdict(list)
    for source_id,patch in patches:
        grouped[int(source_id)].append(patch)

    face_loops=[]
    merge_scale=max(eps*10.0,1.0e-8)
    for source_id,group in sorted(grouped.items()):
        for loop in _merge_face_patches(group,merge_scale):
            if len(loop)>=3:
                face_loops.append((source_id,loop))

    if not face_loops:
        raise SpatialRoofError(
            "После объединения патчей нижней огибающей не осталось граней."
        )

    vertices=[]
    faces=[]
    sources=[]
    buckets=defaultdict(list)

    def add_vertex(point):
        key=tuple(int(round(float(v)/merge_scale)) for v in point)
        for index in buckets[key]:
            if _distance3(vertices[index],point)<=merge_scale*2.0:
                return index
        index=len(vertices)
        vertices.append(tuple(float(v) for v in point))
        buckets[key].append(index)
        return index

    for source_id,loop in face_loops:
        face=[add_vertex(point) for point in loop]
        clean=[]
        for index in face:
            if not clean or clean[-1]!=index:
                clean.append(index)
        if len(clean)>1 and clean[0]==clean[-1]:
            clean.pop()
        if len(clean)<3:
            continue
        if _area([(vertices[i][0],vertices[i][1]) for i in clean])<0.0:
            clean.reverse()
        faces.append(tuple(clean))
        sources.append(int(source_id))

    vertices,faces,sources=_merge_coplanar_roof_faces(
        vertices,faces,sources,scale=max(merge_scale,eps*10.0)
    )
    return vertices,faces,sources


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
        # With a uniform pitch use the established reflex-aware 2D topology
        # and lift its facets onto the identical support planes.
        uniform_pitch = max(angles)-min(angles) <= 1.0e-9
        if uniform_pitch:
            try:
                template_vertices,template_faces,template_sources=build_roof_mesh(
                    xy,1.0,0.0,allow_oblique=True
                )
            except SkeletonError as exc:
                raise SpatialRoofError(
                    "Не удалось построить XY-топологию крыши: "+str(exc)
                ) from exc
            vertices,faces,sources=_embed_topology(
                template_vertices,template_faces,template_sources,
                points,planes,eps,scale
            )
            _validate_lifted_mesh(vertices,faces,sources,points,planes,eps,scale)
            return vertices,faces,[_remap_source_id(source,source_edge_map) for source in sources]

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
                xy,speeds,planes,merge_coplanar=False
            )
        except WeightedSkeletonError as exc:
            raise SpatialRoofError(
                "Взвешенный волновой фронт: "+str(exc)
            ) from exc
        _validate_lifted_mesh(vertices,faces,sources,points,planes,eps,scale)
        return vertices,faces,[_remap_source_id(source, source_edge_map) for source in sources]

    # For a non-planar eave, the combinatorial neighbourhood is taken
    # from the proven stable 2D skeleton. Individual angles define the 3D
    # support planes, but do not silently renumber source edges.
    try:
        topology_vertices,topology_faces,topology_sources=build_roof_mesh(
            xy,1.0,0.0,allow_oblique=True
        )
    except SkeletonError as exc:
        raise SpatialRoofError(
            "Не удалось получить устойчивую XY-топологию: "+str(exc)
        ) from exc

    adjacency=_derive_source_adjacency(
        topology_vertices,topology_faces,topology_sources,
        max(eps*10.0,1.0e-8)
    )
    allowed_pairs=set()
    for source_id,neighbors in adjacency.items():
        for neighbor_id in neighbors:
            a,b=sorted((int(source_id),int(neighbor_id)))
            if a!=b:
                allowed_pairs.add((a,b))

    vertices,faces,sources=_build_planar_support_arrangement(
        points,planes,eps,allowed_pairs
    )
    _validate_lifted_mesh(vertices,faces,sources,points,planes,eps,scale)
    return vertices,faces,[
        _remap_source_id(source,source_edge_map) for source in sources
    ]

