"""Geometric outward offset for the roof source boundary contour."""
from __future__ import annotations

from math import hypot, isfinite
from typing import Sequence

from .geometry import GeometryInputError, signed_area, validate_simple_polygon
from .mesh import build_roof_surface_from_planes
from .planes import build_boundary_planes, boundary_envelope_conflicts

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]


def _cross2(first: Point2, second: Point2) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _is_convex_xy(points: Sequence[Point3], eps: float = 1e-9) -> bool:
    """Return whether a simple XY contour has one consistent turn direction."""
    sign = 0
    scale = max(
        1.0,
        max(point[0] for point in points) - min(point[0] for point in points),
        max(point[1] for point in points) - min(point[1] for point in points),
    )
    tolerance = eps * scale * scale
    for index, current in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % len(points)]
        first = (current[0] - previous[0], current[1] - previous[1])
        second = (following[0] - current[0], following[1] - current[1])
        turn = _cross2(first, second)
        if abs(turn) <= tolerance:
            continue
        current_sign = 1 if turn > 0.0 else -1
        if sign and current_sign != sign:
            return False
        sign = current_sign
    return sign != 0


def is_convex_contour_xy(points: Sequence[Point3], eps: float = 1e-9) -> bool:
    """Public contour predicate shared by the Blender build-path diagnostics."""
    return _is_convex_xy(points, eps)


def offset_contour_outward(
    points: Sequence[Point3],
    distance: float,
    eps: float = 1e-9,
) -> tuple[Point3, ...]:
    """Create one parallel/miter-offset 3D contour from the source footprint.

    Every XY edge is translated outward by distance. Each new vertex is the
    intersection of its two adjacent translated edge lines. This produces
    one new closed contour, rather than appending separate eave strips to an
    already-built roof.

    The source vertex Z value is preserved at the corresponding offset corner.
    Consequently edge order and one-pitch-per-edge indexing stay unchanged.
    The final roof must be rebuilt from this returned contour.
    """
    distance = float(distance)
    if not isfinite(distance) or distance < 0.0:
        raise GeometryInputError(
            "INVALID_OVERHANG",
            "Свес должен быть конечным неотрицательным расстоянием.",
        )
    if len(points) < 3:
        raise GeometryInputError(
            "POLY_TOO_SMALL",
            "Для смещения контура нужны минимум три вершины.",
        )
    source: list[Point3] = []
    for index, point in enumerate(points):
        if len(point) != 3 or not all(isfinite(float(value)) for value in point):
            raise GeometryInputError(
                "NON_FINITE",
                f"Исходная вершина {index + 1} содержит неверные координаты.",
            )
        source.append((float(point[0]), float(point[1]), float(point[2])))

    source_xy = [(point[0], point[1]) for point in source]
    issues = validate_simple_polygon(source_xy, eps)
    if issues:
        raise GeometryInputError(issues[0].code, issues[0].message)
    if distance == 0.0:
        return tuple(source)

    signed_source_area = signed_area(source_xy)
    if abs(signed_source_area) <= eps:
        raise GeometryInputError(
            "OVERHANG_SOURCE_DEGENERATE",
            "Исходный контур имеет нулевую площадь.",
        )
    winding = 1.0 if signed_source_area > 0.0 else -1.0
    scale = max(
        1.0,
        max(point[0] for point in source) - min(point[0] for point in source),
        max(point[1] for point in source) - min(point[1] for point in source),
        distance,
    )
    linear_tolerance = max(1e-12, eps * scale * 100.0)
    angular_tolerance = max(1e-12, eps * 10.0)

    # Each translated edge is represented by an origin and a unit direction.
    offset_lines: list[tuple[Point2, Point2]] = []
    for index, start in enumerate(source_xy):
        end = source_xy[(index + 1) % len(source_xy)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = hypot(dx, dy)
        if length <= linear_tolerance:
            raise GeometryInputError(
                "OVERHANG_ZERO_LENGTH_EDGE",
                f"Исходное ребро {index + 1} имеет нулевую длину.",
            )
        tangent = (dx / length, dy / length)
        # For CCW polygons the outward normal is to the right; for CW it is
        # to the left. The winding multiplier makes both cases equivalent.
        outward = (winding * tangent[1], -winding * tangent[0])
        origin = (
            start[0] + outward[0] * distance,
            start[1] + outward[1] * distance,
        )
        offset_lines.append((origin, tangent))

    result: list[Point3] = []
    for index, source_corner in enumerate(source):
        previous_origin, previous_tangent = offset_lines[index - 1]
        current_origin, current_tangent = offset_lines[index]
        denominator = _cross2(previous_tangent, current_tangent)

        if abs(denominator) <= angular_tolerance:
            alignment = (
                previous_tangent[0] * current_tangent[0]
                + previous_tangent[1] * current_tangent[1]
            )
            if alignment <= 0.0:
                raise GeometryInputError(
                    "OVERHANG_PARALLEL_BACKTRACK",
                    f"В углу {index + 1} контур разворачивается назад; "
                    "невозможно построить однозначный внешний offset.",
                )
            # Collinear forward edges share the same translated line.
            offset_xy = current_origin
        else:
            delta = (
                current_origin[0] - previous_origin[0],
                current_origin[1] - previous_origin[1],
            )
            parameter = _cross2(delta, current_tangent) / denominator
            offset_xy = (
                previous_origin[0] + previous_tangent[0] * parameter,
                previous_origin[1] + previous_tangent[1] * parameter,
            )

        miter_length = hypot(
            offset_xy[0] - source_corner[0],
            offset_xy[1] - source_corner[1],
        )
        if miter_length > max(
            distance * 50.0,
            distance + linear_tolerance * 10.0,
        ):
            raise GeometryInputError(
                "OVERHANG_MITER_TOO_LONG",
                f"Угол {index + 1} слишком острый: внешний miter длиннее "
                "50 ширин свеса. Уменьши свес.",
            )

        # Keep the corresponding eave elevation. Pitch planes are rebuilt
        # from the new 3D contour instead of extending old roof facets.
        result.append((offset_xy[0], offset_xy[1], source_corner[2]))

    result_xy = [(point[0], point[1]) for point in result]
    offset_issues = validate_simple_polygon(result_xy, eps)
    if offset_issues:
        raise GeometryInputError(
            "OVERHANG_OFFSET_INVALID",
            "Внешний контур свеса самопересекается или схлопнулся: "
            + offset_issues[0].message
            + " Уменьши свес или измени узкие вогнутые участки.",
        )

    result_area = signed_area(result_xy)
    if result_area * winding <= 0.0:
        raise GeometryInputError(
            "OVERHANG_OFFSET_WINDING",
            "Внешний контур свеса изменил ориентацию или схлопнулся.",
        )
    if abs(result_area) <= abs(signed_source_area) + linear_tolerance**2:
        raise GeometryInputError(
            "OVERHANG_NOT_EXPANDED",
            "Смещённый контур не увеличил площадь крыши.",
        )

    # Assert that each new edge is parallel to and exactly the requested
    # distance outside its source edge.
    for index, source_start in enumerate(source_xy):
        source_end = source_xy[(index + 1) % len(source_xy)]
        offset_start = result_xy[index]
        offset_end = result_xy[(index + 1) % len(result_xy)]
        dx = source_end[0] - source_start[0]
        dy = source_end[1] - source_start[1]
        length = hypot(dx, dy)
        offset_dx = offset_end[0] - offset_start[0]
        offset_dy = offset_end[1] - offset_start[1]
        parallel_error = abs(_cross2((dx, dy), (offset_dx, offset_dy))) / length
        signed_distance = winding * _cross2(
            (dx, dy),
            (
                offset_start[0] - source_start[0],
                offset_start[1] - source_start[1],
            ),
        ) / length
        if (
            parallel_error > linear_tolerance * 30.0
            or abs(signed_distance + distance)
            > max(linear_tolerance * 30.0, distance * 1e-7)
        ):
            raise GeometryInputError(
                "OVERHANG_OFFSET_EDGE_INVALID",
                f"Смещённое ребро {index + 1} не параллельно исходному "
                "или находится не на заданном расстоянии.",
            )

    return tuple(result)



def corner_converged_overhang_contour(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    distance: float,
    eps: float = 1e-9,
) -> tuple[Point3, ...]:
    """Build one outer corner per source vertex where neighbouring pitches meet.

    Each miter-offset corner is projected to the XY line where its two adjacent
    source-edge roof planes have equal height. This keeps the outer boundary
    vertex on both slope planes, so adjacent roof facets converge at one 3D
    point. The requested distance is a target, not a hard constraint: the
    resulting eave extension may vary around the perimeter.
    """
    if len(points) < 3 or len(points) != len(pitches_degrees):
        raise GeometryInputError(
            "INPUT_COUNT",
            "Нужно минимум три вершины и по одному уклону на каждое ребро."
        )
    distance = float(distance)
    if not isfinite(distance) or distance <= 0.0:
        raise GeometryInputError(
            "INVALID_OVERHANG",
            "Для построения свеса нужно положительное конечное расстояние."
        )
    source = tuple(
        tuple(float(value) for value in point) for point in points
    )
    reference = offset_contour_outward(source, distance, eps)
    planes = build_boundary_planes(source, pitches_degrees, eps)
    winding = 1.0 if signed_area([(p[0], p[1]) for p in source]) > 0.0 else -1.0
    scale = max(
        1.0,
        max(p[0] for p in source) - min(p[0] for p in source),
        max(p[1] for p in source) - min(p[1] for p in source),
        distance,
    )
    linear_tolerance = max(1e-10, eps * scale * 100.0)
    result: list[Point3] = []

    for index, target in enumerate(reference):
        previous = planes[index - 1]
        current = planes[index]
        a = previous.a - current.a
        b = previous.b - current.b
        c = previous.c - current.c
        norm_sq = a * a + b * b

        x, y = target[0], target[1]
        if norm_sq <= eps * eps:
            if abs(c) > linear_tolerance:
                raise GeometryInputError(
                    "OVERHANG_CORNER_PARALLEL_PLANES",
                    f"Скаты по сторонам угла {index + 1} параллельны и не пересекаются; "
                    "нельзя свести их в одну вершину. Отключи схождение углов "
                    "или измени один из уклонов.",
                )
        else:
            residual = a * x + b * y + c
            x -= residual * a / norm_sq
            y -= residual * b / norm_sq

        z_previous = previous.height(x, y)
        z_current = current.height(x, y)
        if abs(z_previous - z_current) > linear_tolerance:
            raise GeometryInputError(
                "OVERHANG_CORNER_INTERSECTION",
                f"Не удалось свести соседние скаты в вершине {index + 1}.",
            )
        z = 0.5 * (z_previous + z_current)

        # The projected corner must remain outside both adjacent source edges.
        for edge_index in ((index - 1) % len(source), index):
            start = source[edge_index]
            end = source[(edge_index + 1) % len(source)]
            dx, dy = end[0] - start[0], end[1] - start[1]
            edge_length = hypot(dx, dy)
            inward = winding * (
                -dy * x + dx * y + dy * start[0] - dx * start[1]
            ) / edge_length
            if inward >= -linear_tolerance:
                raise GeometryInputError(
                    "OVERHANG_CORNER_NOT_OUTSIDE",
                    f"Схождение скатов у вершины {index + 1} уводит край свеса "
                    "внутрь исходного контура. Уменьши свес или отключи схождение углов.",
                )

        extension = hypot(x - source[index][0], y - source[index][1])
        if extension > max(distance * 50.0, distance + linear_tolerance * 10.0):
            raise GeometryInputError(
                "OVERHANG_CORNER_TOO_FAR",
                f"Схождение скатов у вершины {index + 1} требует слишком большого выноса.",
            )
        result.append((x, y, z))

    result_xy = [(point[0], point[1]) for point in result]
    issues = validate_simple_polygon(result_xy, eps)
    if issues:
        raise GeometryInputError(
            "OVERHANG_CORNER_CONTOUR_INVALID",
            "Контур углового свеса самопересекается или схлопнулся: "
            + issues[0].message,
        )
    if signed_area(result_xy) * winding <= 0.0:
        raise GeometryInputError(
            "OVERHANG_CORNER_WINDING",
            "Контур углового свеса изменил ориентацию.",
        )
    source_area = abs(signed_area([(p[0], p[1]) for p in source]))
    if abs(signed_area(result_xy)) <= source_area + linear_tolerance * linear_tolerance:
        raise GeometryInputError(
            "OVERHANG_CORNER_NO_EXTENSION",
            "Схождение скатов не создало внешний свес.",
        )

    # Every outer edge is required to lie on its corresponding source plane.
    for index, plane in enumerate(planes):
        for point_index in (index, (index + 1) % len(result)):
            point = result[point_index]
            if abs(point[2] - plane.height(point[0], point[1])) > linear_tolerance:
                raise GeometryInputError(
                    "OVERHANG_CORNER_EDGE_MISMATCH",
                    f"Внешнее ребро {index + 1} не лежит на плоскости своего ската.",
                )
    return tuple(result)


def _point_parameter_on_segment(point: Point2, start: Point2, end: Point2, tolerance: float) -> float | None:
    """Return the point's segment parameter when it lies on the segment."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= tolerance * tolerance:
        return None
    parameter = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    length = length_sq ** 0.5
    if parameter < -tolerance / length or parameter > 1.0 + tolerance / length:
        return None
    closest = (start[0] + parameter * dx, start[1] + parameter * dy)
    if hypot(point[0] - closest[0], point[1] - closest[1]) > tolerance:
        return None
    return max(0.0, min(1.0, parameter))


def _point_in_polygon(point: Point2, polygon: Sequence[Point2], tolerance: float) -> bool:
    """Inclusive ray-cast test used to prove that the offset contains its source."""
    x, y = point
    inside = False
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _point_parameter_on_segment(point, start, end, tolerance) is not None:
            return True
        if (start[1] > y) != (end[1] > y):
            crossing_x = start[0] + (y - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
            if x < crossing_x:
                inside = not inside
    return inside


def _build_concave_wavefront_overhang_surface(points: Sequence[Point3], pitches_degrees: Sequence[float], distance: float, *, eps: float):
    """Extend a concave wavefront roof with exact planar eave strips."""
    from .mesh import RoofSurface, _VertexRegistry, validate_surface_boundary_edges
    from .wavefront import build_wavefront_roof_surface, is_flat_eave_contour

    if not is_flat_eave_contour(points, eps):
        raise GeometryInputError(
            "OVERHANG_CONCAVE_NON_FLAT_EAVES",
            "Для свеса невыпуклого контура пока нужна одна общая высота всех карнизов. Выровняй исходные вершины по Z.",
        )

    source = tuple(tuple(float(value) for value in point) for point in points)
    expanded = corner_converged_overhang_contour(source, pitches_degrees, distance, eps)
    source_xy = tuple((point[0], point[1]) for point in source)
    expanded_xy = tuple((point[0], point[1]) for point in expanded)
    scale = max(
        1.0,
        max(point[0] for point in source) - min(point[0] for point in source),
        max(point[1] for point in source) - min(point[1] for point in source),
        distance,
    )
    linear_tolerance = max(1e-10, eps * scale * 100.0)
    area_tolerance = max(eps * scale * scale * 100.0, 1e-12)
    source_area = abs(signed_area(source_xy))
    expanded_area = abs(signed_area(expanded_xy))
    if expanded_area <= source_area + area_tolerance:
        raise GeometryInputError("OVERHANG_OFFSET_NOT_EXPANDED", "Смещённый внешний контур не увеличил площадь крыши.")

    # A valid miter offset must contain the complete source boundary. This rejects offsets that close a narrow notch.
    for edge_index, start in enumerate(source_xy):
        end = source_xy[(edge_index + 1) % len(source_xy)]
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            sample = (start[0] + (end[0] - start[0]) * fraction, start[1] + (end[1] - start[1]) * fraction)
            if not _point_in_polygon(sample, expanded_xy, linear_tolerance * 5.0):
                raise GeometryInputError(
                    "OVERHANG_OFFSET_NOT_NESTED",
                    f"Свес {distance:.6g} схлопывает или пересекает вогнутый участок у ребра {edge_index + 1}. Уменьши ширину свеса.",
                )

    # Validate offset geometry before invoking wavefront events.
    base_surface = build_wavefront_roof_surface(source, pitches_degrees, eps=eps)
    source_boundary_edges = validate_surface_boundary_edges(
        base_surface.vertices, base_surface.faces, source_xy, linear_tolerance * 5.0
    )
    planes = build_boundary_planes(source, pitches_degrees, eps)
    registry = _VertexRegistry(linear_tolerance)
    source_index_map = [registry.add(point) for point in base_surface.vertices]
    faces = [tuple(source_index_map[index] for index in face) for face in base_surface.faces]
    slope_indices = list(base_surface.face_slope_indices)
    strip_area = 0.0

    for first_source_index, second_source_index in source_boundary_edges:
        first_source = base_surface.vertices[first_source_index]
        second_source = base_surface.vertices[second_source_index]
        matches = []
        for edge_index, edge_start in enumerate(source_xy):
            edge_end = source_xy[(edge_index + 1) % len(source_xy)]
            first_parameter = _point_parameter_on_segment(
                (first_source[0], first_source[1]), edge_start, edge_end, linear_tolerance * 5.0
            )
            second_parameter = _point_parameter_on_segment(
                (second_source[0], second_source[1]), edge_start, edge_end, linear_tolerance * 5.0
            )
            if first_parameter is not None and second_parameter is not None:
                matches.append((edge_index, first_parameter, second_parameter))
        if len(matches) != 1:
            raise GeometryInputError(
                "OVERHANG_BOUNDARY_EDGE_MAPPING",
                "Не удалось однозначно сопоставить сегмент карниза с исходным ребром. Проверь контур на дублирующиеся или нулевые рёбра.",
            )

        edge_index, first_parameter, second_parameter = matches[0]
        outer_start = expanded[edge_index]
        outer_end = expanded[(edge_index + 1) % len(expanded)]

        def outer_point(parameter: float) -> Point3:
            return tuple(outer_start[axis] + (outer_end[axis] - outer_start[axis]) * parameter for axis in range(3))

        first_outer = outer_point(first_parameter)
        second_outer = outer_point(second_parameter)
        plane = planes[edge_index]
        for point in (first_outer, second_outer):
            if abs(point[2] - plane.height(point[0], point[1])) > linear_tolerance * 20.0:
                raise GeometryInputError(
                    "OVERHANG_STRIP_PLANE_MISMATCH",
                    f"Полоса свеса у ребра {edge_index + 1} отклоняется от плоскости ската.",
                )

        first_outer_index = registry.add(first_outer)
        second_outer_index = registry.add(second_outer)
        strip_face = (
            source_index_map[second_source_index],
            source_index_map[first_source_index],
            first_outer_index,
            second_outer_index,
        )
        strip_xy = [(registry.vertices[i][0], registry.vertices[i][1]) for i in strip_face]
        strip_signed_area = signed_area(strip_xy)
        if strip_signed_area <= area_tolerance:
            raise GeometryInputError(
                "OVERHANG_STRIP_DEGENERATE",
                f"Полоса свеса у ребра {edge_index + 1} выродилась или пересекает соседнюю полосу. Уменьши ширину свеса.",
            )
        strip_area += strip_signed_area
        faces.append(strip_face)
        slope_indices.append(edge_index)

    expected_strip_area = expanded_area - source_area
    if abs(strip_area - expected_strip_area) > max(area_tolerance * 100.0, expected_strip_area * 1e-7):
        raise GeometryInputError(
            "OVERHANG_STRIP_COVERAGE",
            "Полосы свеса не покрывают ровно область между исходным и внешним контурами. Уменьши ширину свеса.",
        )

    edge_usage: dict[tuple[int, int], int] = {}
    for face in faces:
        for local_index, first in enumerate(face):
            second = face[(local_index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            edge_usage[key] = edge_usage.get(key, 0) + 1
    if any(count > 2 for count in edge_usage.values()):
        raise GeometryInputError("OVERHANG_NON_MANIFOLD_SURFACE", "Сборка полос свеса создала неманифольное ребро.")

    vertices = tuple(registry.vertices)
    validate_surface_boundary_edges(vertices, faces, expanded_xy, linear_tolerance * 5.0)
    return RoofSurface(
        vertices=vertices,
        faces=tuple(faces),
        face_slope_indices=tuple(slope_indices),
        planes=tuple(planes),
        source_area_xy=source_area,
        surface_area_xy=base_surface.surface_area_xy + strip_area,
        boundary_xy=expanded_xy,
        approximation_error=base_surface.approximation_error,
        refinement_depth=base_surface.refinement_depth,
    )


def build_source_anchored_overhang_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    distance: float,
    *,
    corner_convergence: bool = True,
):
    """Extend a roof beyond its original eaves while retaining source planes."""
    if len(points) < 3 or len(points) != len(pitches_degrees):
        raise GeometryInputError("INPUT_COUNT", "Нужно минимум три вершины и по одному уклону на каждое ребро.")
    distance = float(distance)
    if not isfinite(distance) or distance <= 0.0:
        raise GeometryInputError("INVALID_OVERHANG", "Для построения свеса нужно положительное конечное расстояние.")
    source = tuple(tuple(float(value) for value in point) for point in points)
    if not _is_convex_xy(source):
        if not corner_convergence:
            raise GeometryInputError(
                "OVERHANG_CONCAVE_NEEDS_CORNER_CONVERGENCE",
                "Для свеса невыпуклого контура включи «Сводить углы»: соседние полосы свеса должны сходиться в общей точке.",
            )
        return _build_concave_wavefront_overhang_surface(source, pitches_degrees, distance, eps=1e-9)

    planes = build_boundary_planes(source, pitches_degrees)
    expanded = (
        corner_converged_overhang_contour(source, pitches_degrees, distance)
        if corner_convergence
        else offset_contour_outward(source, distance)
    )
    conflicts = boundary_envelope_conflicts(source, planes, active_contour=source)
    if conflicts:
        first = conflicts[0]
        raise GeometryInputError(first.code, first.message)
    domain = [(point[0], point[1]) for point in expanded]
    source_area = abs(signed_area([(point[0], point[1]) for point in source]))
    return build_roof_surface_from_planes(
        domain, planes, source_area_xy=source_area,
        active_contour=[(point[0], point[1]) for point in source],
    )


__all__ = [
    "offset_contour_outward",
    "corner_converged_overhang_contour",
    "build_source_anchored_overhang_surface",
    "is_convex_contour_xy",
]

