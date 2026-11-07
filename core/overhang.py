"""3D mitered eave extension for convex roof surfaces."""
from __future__ import annotations

from math import hypot, isfinite
from typing import Sequence

from .geometry import (
    GeometryInputError,
    PlaneZ,
    signed_area,
    validate_simple_polygon,
)
from .mesh import RoofSurface, _VertexRegistry, validate_surface_boundary_edges

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
BoundaryRecord = tuple[int, int, int, int]


def _cross2(first: Point2, second: Point2) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _distance_xy(first: Point3, second: Point3) -> float:
    return hypot(first[0] - second[0], first[1] - second[1])


def _plane_pair_is_coincident(
    first: PlaneZ,
    second: PlaneZ,
    corner: Point3,
    tolerance: float,
) -> bool:
    gradient_scale = max(
        1.0, abs(first.a), abs(first.b), abs(second.a), abs(second.b)
    )
    if (
        abs(first.a - second.a) > tolerance * gradient_scale
        or abs(first.b - second.b) > tolerance * gradient_scale
    ):
        return False
    return abs(
        first.height(corner[0], corner[1])
        - second.height(corner[0], corner[1])
    ) <= tolerance


def _planar_miter_xy(
    previous: Point3,
    corner: Point3,
    following: Point3,
    distance: float,
    tolerance: float,
) -> Point2:
    """Intersect adjacent parallel offset lines for one shared roof plane."""
    previous_dx = corner[0] - previous[0]
    previous_dy = corner[1] - previous[1]
    next_dx = following[0] - corner[0]
    next_dy = following[1] - corner[1]
    previous_length = hypot(previous_dx, previous_dy)
    next_length = hypot(next_dx, next_dy)
    if previous_length <= tolerance or next_length <= tolerance:
        raise GeometryInputError(
            "OVERHANG_ZERO_LENGTH_EDGE",
            "Внешняя граница содержит ребро нулевой длины.",
        )

    previous_tangent = (
        previous_dx / previous_length,
        previous_dy / previous_length,
    )
    next_tangent = (next_dx / next_length, next_dy / next_length)
    previous_normal = (previous_tangent[1], -previous_tangent[0])
    next_normal = (next_tangent[1], -next_tangent[0])
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
                "Нельзя построить свес на развёрнутом или обратном угле контура.",
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
    miter_length = hypot(result[0] - corner[0], result[1] - corner[1])
    if miter_length > max(distance * 50.0, distance + tolerance * 10.0):
        raise GeometryInputError(
            "OVERHANG_MITER_TOO_LONG",
            "Угол контура слишком острый для безопасного свеса: длина miter "
            "превышает 50 ширин свеса.",
        )
    return result


def _edge_offset_ridge_intersection(
    edge_start: Point3,
    edge_end: Point3,
    corner: Point3,
    edge_plane: PlaneZ,
    other_plane: PlaneZ,
    distance: float,
    winding: float,
    tolerance: float,
) -> Point3:
    """Intersect an edge-parallel offset line with the adjacent planes' ridge.

    The two roof planes meet at the source corner. Their 3D intersection is
    therefore a ridge line through that corner. Each boundary edge is extended
    in its own support plane until its offset line reaches this ridge. The two
    adjacent strips may reach different points on the ridge; their collinear
    overlap is welded and the remaining ridge segment becomes one outer edge.
    """
    dx = edge_end[0] - edge_start[0]
    dy = edge_end[1] - edge_start[1]
    edge_length = hypot(dx, dy)
    if edge_length <= tolerance:
        raise GeometryInputError(
            "OVERHANG_ZERO_LENGTH_EDGE",
            "Внешняя граница содержит ребро нулевой длины.",
        )
    tangent = (dx / edge_length, dy / edge_length)
    outward = (winding * tangent[1], -winding * tangent[0])

    ridge_direction = (
        edge_plane.b - other_plane.b,
        other_plane.a - edge_plane.a,
    )
    ridge_length = hypot(*ridge_direction)
    if ridge_length <= tolerance:
        raise GeometryInputError(
            "OVERHANG_UNRESOLVED_RIDGE",
            "Соседние плоскости не образуют устойчивую линию пересечения для свеса.",
        )
    ridge_direction = (
        ridge_direction[0] / ridge_length,
        ridge_direction[1] / ridge_length,
    )

    offset_origin = (
        corner[0] + outward[0] * distance,
        corner[1] + outward[1] * distance,
    )
    denominator = _cross2(tangent, ridge_direction)
    if abs(denominator) <= 1e-12:
        raise GeometryInputError(
            "OVERHANG_PARALLEL_RIDGE",
            "Линия свеса параллельна линии пересечения соседних скатов; "
            "в этой вершине нельзя получить конечный miter.",
        )
    to_corner = (corner[0] - offset_origin[0], corner[1] - offset_origin[1])
    parameter = _cross2(to_corner, ridge_direction) / denominator
    x = offset_origin[0] + tangent[0] * parameter
    y = offset_origin[1] + tangent[1] * parameter
    z = edge_plane.height(x, y)

    other_z = other_plane.height(x, y)
    if abs(z - other_z) > tolerance * 20.0:
        raise GeometryInputError(
            "OVERHANG_RIDGE_RESIDUAL",
            "Не удалось точно пересечь соседние плоскости скатов при построении свеса.",
        )

    miter_length = hypot(x - corner[0], y - corner[1])
    if miter_length > max(distance * 50.0, distance + tolerance * 10.0):
        raise GeometryInputError(
            "OVERHANG_MITER_TOO_LONG",
            "Угол контура слишком острый для безопасного 3D-свеса: длина miter "
            "превышает 50 ширин свеса.",
        )
    return (x, y, z)


def _validate_corner_ridge(
    corner: Point3,
    incoming: Point3,
    outgoing: Point3,
    tolerance: float,
    corner_index: int,
) -> None:
    """Ensure both edge extensions meet along one outward ridge ray."""
    first = (incoming[0] - corner[0], incoming[1] - corner[1])
    second = (outgoing[0] - corner[0], outgoing[1] - corner[1])
    first_length = hypot(*first)
    second_length = hypot(*second)
    if first_length <= tolerance or second_length <= tolerance:
        raise GeometryInputError(
            "OVERHANG_COLLAPSED_MITER",
            f"В углу {corner_index + 1} свес схлопнулся в исходную вершину.",
        )
    cross_error = abs(_cross2(first, second))
    allowed_cross = tolerance * max(first_length, second_length) * 20.0
    dot = first[0] * second[0] + first[1] * second[1]
    if cross_error > allowed_cross or dot < -tolerance * tolerance:
        raise GeometryInputError(
            "OVERHANG_RIDGE_MISMATCH",
            f"В углу {corner_index + 1} смещения соседних скатов не лежат "
            "на одном внешнем гребне. Попробуй меньший свес или проверь контур.",
        )


def extend_convex_roof_surface(
    surface: RoofSurface,
    distance: float,
    eps: float = 1e-9,
) -> RoofSurface:
    """Extend convex flat- or mixed-height eaves using 3D ridge miters.

    Each boundary segment gets one strip on its own support plane. At every
    corner, the incoming and outgoing offset lines terminate on the actual
    intersection line of their adjacent support planes. Their shared segment
    is welded and the remaining ridge segment becomes one outer boundary edge.
    This supports individual pitches and XYZ eaves without adding a corner fan.
    """
    if not isfinite(distance) or distance < 0.0:
        raise GeometryInputError(
            "INVALID_OVERHANG",
            "Свес должен быть конечным неотрицательным расстоянием.",
        )
    if distance <= eps:
        return surface
    if len(surface.face_slope_indices) != len(surface.faces):
        raise GeometryInputError(
            "FACE_METADATA_MISMATCH",
            "Количество идентификаторов скатов не совпадает с количеством граней.",
        )

    scale = max(
        1.0,
        max(point[0] for point in surface.vertices) - min(point[0] for point in surface.vertices),
        max(point[1] for point in surface.vertices) - min(point[1] for point in surface.vertices),
        max(point[2] for point in surface.vertices) - min(point[2] for point in surface.vertices),
        distance,
    )
    tolerance = max(1e-12, eps * scale * 100.0)
    area_tolerance = tolerance * scale * 10.0
    plane_tolerance = max(1e-10, eps * scale * 100.0)

    edge_uses: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for face_index, face in enumerate(surface.faces):
        for local_index, first in enumerate(face):
            second = face[(local_index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            edge_uses.setdefault(key, []).append((face_index, first, second))

    records: list[BoundaryRecord] = []
    outgoing: dict[int, BoundaryRecord] = {}
    for uses in edge_uses.values():
        if len(uses) > 2:
            raise GeometryInputError(
                "NON_MANIFOLD_SURFACE",
                "Верхняя поверхность содержит ребро с более чем двумя гранями.",
            )
        if len(uses) != 1:
            continue
        face_index, first, second = uses[0]
        slope_index = surface.face_slope_indices[face_index]
        if not (0 <= slope_index < len(surface.planes)):
            raise GeometryInputError(
                "OVERHANG_SOURCE_SLOPE_MISSING",
                "Не удалось определить исходную плоскость для граничного ребра свеса.",
            )
        record = (first, second, slope_index, face_index)
        if first in outgoing:
            raise GeometryInputError(
                "OVERHANG_BOUNDARY_BRANCH",
                "Граница крыши разветвляется; свес требует одной замкнутой петли.",
            )
        outgoing[first] = record
        records.append(record)

    if len(records) < 3 or not outgoing:
        raise GeometryInputError(
            "OVERHANG_BOUNDARY_MISSING",
            "Не удалось найти внешнюю границу верхней поверхности для построения свеса.",
        )

    start_record = min(
        records,
        key=lambda item: (
            surface.vertices[item[0]][0],
            surface.vertices[item[0]][1],
            surface.vertices[item[0]][2],
            item[0],
        ),
    )
    ordered: list[BoundaryRecord] = []
    current = start_record
    seen: set[tuple[int, int]] = set()
    while (current[0], current[1]) not in seen:
        seen.add((current[0], current[1]))
        ordered.append(current)
        next_record = outgoing.get(current[1])
        if next_record is None:
            raise GeometryInputError(
                "OVERHANG_OPEN_BOUNDARY",
                "Граничные рёбра крыши не образуют единую замкнутую петлю.",
            )
        current = next_record
    if current != start_record or len(ordered) != len(records):
        raise GeometryInputError(
            "OVERHANG_MULTIPLE_BOUNDARIES",
            "Свес поддерживает только одну непрерывную внешнюю границу крыши.",
        )

    contour_xy = [
        (surface.vertices[record[0]][0], surface.vertices[record[0]][1])
        for record in ordered
    ]
    contour_area = signed_area(contour_xy)
    if abs(contour_area) <= area_tolerance:
        raise GeometryInputError(
            "OVERHANG_BOUNDARY_WINDING",
            "Не удалось подтвердить ненулевую площадь внешней границы крыши.",
        )
    winding = 1.0 if contour_area > 0.0 else -1.0

    # Reflex corners are not handled by this convex miter construction.
    for index, point in enumerate(contour_xy):
        previous = contour_xy[index - 1]
        following = contour_xy[(index + 1) % len(contour_xy)]
        turn = _cross2(
            (point[0] - previous[0], point[1] - previous[1]),
            (following[0] - point[0], following[1] - point[1]),
        ) * winding
        if turn < -area_tolerance:
            raise GeometryInputError(
                "OVERHANG_REFLEX_UNSUPPORTED",
                "Свес с miter-соединением пока поддерживается только для выпуклых контуров. "
                "Для вогнутого L/U-контура установи Свес = 0.",
            )

    incoming_points: list[Point3] = []
    outgoing_points: list[Point3] = []
    incoming_distances: list[float] = []
    outgoing_distances: list[float] = []

    for index, record in enumerate(ordered):
        previous_record = ordered[index - 1]
        corner = surface.vertices[record[0]]
        if previous_record[1] != record[0]:
            raise GeometryInputError(
                "OVERHANG_BOUNDARY_DISCONTINUITY",
                "Соседние граничные рёбра не имеют общей исходной вершины.",
            )
        previous_corner = surface.vertices[previous_record[0]]
        following_corner = surface.vertices[record[1]]
        incoming_plane = surface.planes[previous_record[2]]
        outgoing_plane = surface.planes[record[2]]

        incoming_at_corner = incoming_plane.height(corner[0], corner[1])
        outgoing_at_corner = outgoing_plane.height(corner[0], corner[1])
        if abs(incoming_at_corner - outgoing_at_corner) > plane_tolerance:
            raise GeometryInputError(
                "OVERHANG_SOURCE_PLANE_DISCONTINUITY",
                f"Соседние скаты не сходятся в исходной вершине {index + 1}; "
                "свес нельзя продолжить без разрыва.",
            )

        if _plane_pair_is_coincident(
            incoming_plane, outgoing_plane, corner, plane_tolerance
        ):
            miter_xy = _planar_miter_xy(
                previous_corner, corner, following_corner, distance, tolerance
            )
            point = (
                miter_xy[0],
                miter_xy[1],
                outgoing_plane.height(*miter_xy),
            )
            incoming_point = point
            outgoing_point = point
        else:
            incoming_point = _edge_offset_ridge_intersection(
                previous_corner,
                corner,
                corner,
                incoming_plane,
                outgoing_plane,
                distance,
                winding,
                tolerance,
            )
            outgoing_point = _edge_offset_ridge_intersection(
                corner,
                following_corner,
                corner,
                outgoing_plane,
                incoming_plane,
                distance,
                winding,
                tolerance,
            )
            _validate_corner_ridge(
                corner, incoming_point, outgoing_point, tolerance, index
            )

        incoming_points.append(incoming_point)
        outgoing_points.append(outgoing_point)
        incoming_distances.append(_distance_xy(corner, incoming_point))
        outgoing_distances.append(_distance_xy(corner, outgoing_point))

    registry = _VertexRegistry(tolerance)
    remap = [registry.add(point) for point in surface.vertices]
    if any(new_index != old_index for old_index, new_index in enumerate(remap)):
        raise GeometryInputError(
            "OVERHANG_DUPLICATE_SOURCE_VERTEX",
            "Исходная поверхность содержит совпадающие вершины; свес нельзя надёжно привязать.",
        )

    incoming_ids = [
        registry.add(point) for point in incoming_points
    ]
    outgoing_ids = [
        registry.add(point) for point in outgoing_points
    ]

    faces = [tuple(remap[index] for index in face) for face in surface.faces]
    slope_ids = list(surface.face_slope_indices)

    for index, record in enumerate(ordered):
        next_index = (index + 1) % len(ordered)
        first, second, slope_index, _face_index = record

        # If the incoming strip reaches the corner ridge closer than this
        # strip, split this strip's side edge at that shared point. Do the
        # symmetric operation at the far end. The overlapping edge is then
        # literally the same pair of mesh indices in both faces.
        start_split = None
        if (
            incoming_distances[index] + tolerance
            < outgoing_distances[index]
            and incoming_ids[index] != outgoing_ids[index]
        ):
            start_split = incoming_ids[index]

        end_split = None
        if (
            outgoing_distances[next_index] + tolerance
            < incoming_distances[next_index]
            and outgoing_ids[next_index] != incoming_ids[next_index]
        ):
            end_split = outgoing_ids[next_index]

        strip = [remap[second], remap[first]]
        if start_split is not None:
            strip.append(start_split)
        strip.append(outgoing_ids[index])
        strip.append(incoming_ids[next_index])
        if end_split is not None:
            strip.append(end_split)

        compact: list[int] = []
        for vertex_id in strip:
            if not compact or compact[-1] != vertex_id:
                compact.append(vertex_id)
        if len(compact) > 1 and compact[0] == compact[-1]:
            compact.pop()
        if len(set(compact)) < 3:
            raise GeometryInputError(
                "OVERHANG_DEGENERATE_STRIP",
                f"Свес создал вырожденную полосу ребра {index + 1}.",
            )

        strip_area = signed_area([
            (registry.vertices[vertex_id][0], registry.vertices[vertex_id][1])
            for vertex_id in compact
        ])
        if strip_area * winding <= area_tolerance:
            raise GeometryInputError(
                "OVERHANG_DEGENERATE_STRIP",
                f"Свес создал вырожденную или перевёрнутую полосу ребра {index + 1}.",
            )
        faces.append(tuple(compact))
        slope_ids.append(slope_index)

    # The outer boundary alternates between one strip's outer edge and the
    # connector along the shared 3D ridge at the next source corner.
    boundary_xy: list[Point2] = []

    def append_boundary_point(point: Point3) -> None:
        xy = (point[0], point[1])
        if not boundary_xy or hypot(
            boundary_xy[-1][0] - xy[0],
            boundary_xy[-1][1] - xy[1],
        ) > tolerance:
            boundary_xy.append(xy)

    for index in range(len(ordered)):
        append_boundary_point(outgoing_points[index])
        append_boundary_point(incoming_points[(index + 1) % len(ordered)])

    if len(boundary_xy) > 1 and hypot(
        boundary_xy[0][0] - boundary_xy[-1][0],
        boundary_xy[0][1] - boundary_xy[-1][1],
    ) <= tolerance:
        boundary_xy.pop()

    issues = validate_simple_polygon(boundary_xy, eps)
    if issues:
        raise GeometryInputError(
            "OVERHANG_OFFSET_INVALID",
            "3D miter-свес создал самопересекающийся или вырожденный внешний контур: "
            + issues[0].message,
        )

    try:
        validate_surface_boundary_edges(
            registry.vertices, faces, boundary_xy, tolerance * 5.0
        )
    except GeometryInputError as exc:
        raise GeometryInputError(
            "OVERHANG_SURFACE_INVALID",
            "Не удалось собрать непрерывную поверхность 3D miter-свеса: " + exc.message,
        ) from exc

    surface_area = sum(
        abs(signed_area([
            (registry.vertices[index][0], registry.vertices[index][1])
            for index in face
        ]))
        for face in faces
    )
    expanded_area = abs(signed_area(boundary_xy))
    if abs(surface_area - expanded_area) > max(
        area_tolerance * 10.0,
        expanded_area * 1e-7,
    ):
        raise GeometryInputError(
            "OVERHANG_COVERAGE_MISMATCH",
            f"Свес покрывает {surface_area:.9g} из {expanded_area:.9g} квадратных единиц внешнего контура.",
        )

    return RoofSurface(
        vertices=tuple(registry.vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(slope_ids),
        planes=surface.planes,
        source_area_xy=surface.source_area_xy,
        surface_area_xy=surface_area,
        boundary_xy=tuple(boundary_xy),
        approximation_error=surface.approximation_error,
        refinement_depth=surface.refinement_depth,
    )
