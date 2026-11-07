"""Offset eaves using a restricted lower envelope of the original roof planes."""
from __future__ import annotations

from math import hypot, isfinite

from .geometry import GeometryInputError, signed_area, validate_simple_polygon
from .mesh import RoofSurface, build_roof_surface_from_planes

Point2 = tuple[float, float]


def _cross2(first: Point2, second: Point2) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _miter_offset_point(
    previous: Point2,
    corner: Point2,
    following: Point2,
    distance: float,
    winding: float,
    tolerance: float,
    corner_index: int,
) -> Point2:
    """Intersect adjacent outward-offset boundary lines at any simple turn."""
    previous_dx = corner[0] - previous[0]
    previous_dy = corner[1] - previous[1]
    next_dx = following[0] - corner[0]
    next_dy = following[1] - corner[1]
    previous_length = hypot(previous_dx, previous_dy)
    next_length = hypot(next_dx, next_dy)
    if previous_length <= tolerance or next_length <= tolerance:
        raise GeometryInputError(
            "OVERHANG_ZERO_LENGTH_EDGE",
            f"Ребро рядом с углом {corner_index + 1} имеет нулевую длину.",
        )

    previous_tangent = (
        previous_dx / previous_length,
        previous_dy / previous_length,
    )
    next_tangent = (next_dx / next_length, next_dy / next_length)
    previous_normal = (
        winding * previous_tangent[1],
        -winding * previous_tangent[0],
    )
    next_normal = (
        winding * next_tangent[1],
        -winding * next_tangent[0],
    )
    previous_origin = (
        corner[0] + previous_normal[0] * distance,
        corner[1] + previous_normal[1] * distance,
    )
    next_origin = (
        corner[0] + next_normal[0] * distance,
        corner[1] + next_normal[1] * distance,
    )

    denominator = _cross2(previous_tangent, next_tangent)
    if abs(denominator) <= 1e-12:
        alignment = (
            previous_tangent[0] * next_tangent[0]
            + previous_tangent[1] * next_tangent[1]
        )
        if alignment < 0.0:
            raise GeometryInputError(
                "OVERHANG_PARALLEL_BACKTRACK",
                f"В углу {corner_index + 1} контур разворачивается назад; "
                "невозможно построить miter-свес.",
            )
        return previous_origin

    delta = (
        next_origin[0] - previous_origin[0],
        next_origin[1] - previous_origin[1],
    )
    parameter = _cross2(delta, next_tangent) / denominator
    result = (
        previous_origin[0] + previous_tangent[0] * parameter,
        previous_origin[1] + previous_tangent[1] * parameter,
    )
    miter_length = hypot(
        result[0] - corner[0],
        result[1] - corner[1],
    )
    if miter_length > max(distance * 50.0, distance + tolerance * 10.0):
        raise GeometryInputError(
            "OVERHANG_MITER_TOO_LONG",
            f"Угол {corner_index + 1} слишком острый для безопасного свеса: "
            "miter превышает 50 ширин свеса.",
        )
    return result


def extend_convex_roof_surface(
    surface: RoofSurface,
    distance: float,
    eps: float = 1e-9,
) -> RoofSurface:
    """Extend simple convex or concave contours with a continuous plane envelope.

    Every source boundary edge is offset outward by the requested horizontal
    distance. The original support planes are retained and remain active in
    their own exterior edge bands. Adjacent planes compete by lower envelope
    and join along their exact 3D intersection, avoiding manually stitched
    corner strips and protruding ridge tails. A concave offset is accepted
    whenever its expanded polygon remains simple and the envelope is manifold.
    """
    if not isfinite(distance) or distance < 0.0:
        raise GeometryInputError(
            "INVALID_OVERHANG",
            "Свес должен быть конечным неотрицательным расстоянием.",
        )
    if distance <= eps:
        return surface
    if len(surface.planes) != len(surface.boundary_xy):
        raise GeometryInputError(
            "OVERHANG_PLANE_BOUNDARY_MISMATCH",
            "Число исходных плоскостей скатов не совпадает с количеством рёбер контура.",
        )

    source_boundary = list(surface.boundary_xy)
    source_area = signed_area(source_boundary)
    if abs(source_area) <= eps:
        raise GeometryInputError(
            "OVERHANG_SOURCE_DEGENERATE",
            "Исходный контур имеет нулевую площадь.",
        )
    winding = 1.0 if source_area > 0.0 else -1.0

    scale = max(
        1.0,
        max(point[0] for point in source_boundary)
        - min(point[0] for point in source_boundary),
        max(point[1] for point in source_boundary)
        - min(point[1] for point in source_boundary),
        distance,
    )
    tolerance = max(1e-12, eps * scale * 100.0)

    offset_boundary: list[Point2] = []
    for index, corner in enumerate(source_boundary):
        offset_boundary.append(
            _miter_offset_point(
                source_boundary[index - 1],
                corner,
                source_boundary[(index + 1) % len(source_boundary)],
                distance,
                winding,
                tolerance,
                index,
            )
        )

    issues = validate_simple_polygon(offset_boundary, eps)
    if issues:
        raise GeometryInputError(
            "OVERHANG_OFFSET_INVALID",
            "Miter-свес создал самопересекающийся или вырожденный контур: "
            + issues[0].message
            + " Уменьши свес или проверь узкие вогнутые участки.",
        )

    offset_area = signed_area(offset_boundary)
    if offset_area * winding <= abs(source_area) * 1e-12:
        raise GeometryInputError(
            "OVERHANG_OFFSET_WINDING",
            "Внешний offset-контур схлопнулся или изменил ориентацию.",
        )
    if abs(offset_area) <= abs(source_area) + tolerance * tolerance:
        raise GeometryInputError(
            "OVERHANG_NOT_EXPANDED",
            "Построенный внешний контур не увеличил площадь крыши.",
        )

    # Confirm every offset edge is parallel to its source edge and exactly
    # distance units outside that source line. This catches wrong winding and
    # accidental inward offsets at reflex corners.
    for index, source_start in enumerate(source_boundary):
        source_end = source_boundary[(index + 1) % len(source_boundary)]
        offset_start = offset_boundary[index]
        offset_end = offset_boundary[(index + 1) % len(offset_boundary)]
        dx = source_end[0] - source_start[0]
        dy = source_end[1] - source_start[1]
        length = hypot(dx, dy)
        offset_dx = offset_end[0] - offset_start[0]
        offset_dy = offset_end[1] - offset_start[1]
        parallel_error = abs(_cross2((dx, dy), (offset_dx, offset_dy))) / max(length, tolerance)
        dot = dx * offset_dx + dy * offset_dy
        signed_distance = winding * _cross2(
            (dx, dy),
            (
                offset_start[0] - source_start[0],
                offset_start[1] - source_start[1],
            ),
        ) / length
        if (
            parallel_error > tolerance * 20.0
            or dot <= 0.0
            or abs(signed_distance + distance) > max(tolerance * 20.0, distance * 1e-7)
        ):
            raise GeometryInputError(
                "OVERHANG_OFFSET_EDGE_INVALID",
                f"Внешнее ребро {index + 1} не является параллельным смещением "
                f"исходного на {distance:.6g}. Проверь острые углы и свес.",
            )

    return build_roof_surface_from_planes(
        offset_boundary,
        surface.planes,
        source_area_xy=surface.source_area_xy,
        eps=eps,
    )
