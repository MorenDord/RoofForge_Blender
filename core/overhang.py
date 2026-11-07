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



def build_source_anchored_overhang_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    distance: float,
):
    """Extend a roof beyond the original eaves without moving support lines.

    Pitch planes are built through the original 3D contour first. The outward
    offset is used only as the roof's XY domain, so the same planes continue
    beyond the source contour and remain exact along every authored eave edge.
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
    if not _is_convex_xy(source):
        raise GeometryInputError(
            "OVERHANG_CONCAVE_UNSUPPORTED",
            "Свес с сохранением исходной опорной поверхности пока поддерживается "
            "только для выпуклого контура. Для вогнутой крыши отключи свес; "
            "обычная генерация контура остаётся доступна.",
        )
    expanded = offset_contour_outward(source, distance)
    planes = build_boundary_planes(source, pitches_degrees)
    conflicts = boundary_envelope_conflicts(
        source, planes, active_contour=source
    )
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
    "build_source_anchored_overhang_surface",
]

