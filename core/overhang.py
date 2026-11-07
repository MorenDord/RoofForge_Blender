"""Plane-preserving eave strips with a single miter cap at each corner."""
from __future__ import annotations

from math import hypot, isfinite

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


def _plane_pair_is_coincident(
    first: PlaneZ,
    second: PlaneZ,
    corner: Point3,
    tolerance: float,
) -> bool:
    scale = max(
        1.0, abs(first.a), abs(first.b), abs(second.a), abs(second.b)
    )
    return (
        abs(first.a - second.a) <= tolerance * scale
        and abs(first.b - second.b) <= tolerance * scale
        and abs(
            first.height(corner[0], corner[1])
            - second.height(corner[0], corner[1])
        ) <= tolerance
    )


def _miter_offset_point(
    previous: Point3,
    corner: Point3,
    following: Point3,
    distance: float,
    winding: float,
    tolerance: float,
    corner_index: int,
) -> Point2:
    """Intersect the adjacent outward-offset XY lines, including reflex turns."""
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
        result[0] - corner[0], result[1] - corner[1]
    )
    if miter_length > max(distance * 50.0, distance + tolerance * 10.0):
        raise GeometryInputError(
            "OVERHANG_MITER_TOO_LONG",
            f"Угол {corner_index + 1} слишком острый для безопасного свеса: "
            "miter превышает 50 ширин свеса.",
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
    """Intersect an edge-parallel offset line with its adjacent planes' ridge."""
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
            "Соседние плоскости не образуют устойчивую линию пересечения свесов.",
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
            "Смещение ребра параллельно линии пересечения соседних скатов. "
            "Для такого набора уклонов конечный miter не существует.",
        )
    to_corner = (
        corner[0] - offset_origin[0],
        corner[1] - offset_origin[1],
    )
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
            "Угол контура слишком острый: 3D-пересечение скатов слишком далеко.",
        )
    return (x, y, z)


def _validate_corner_ridge(
    corner: Point3,
    incoming: Point3,
    outgoing: Point3,
    tolerance: float,
    corner_index: int,
) -> None:
    """Both edge extensions must lie on the same 3D ridge through the corner."""
    first = (incoming[0] - corner[0], incoming[1] - corner[1])
    second = (outgoing[0] - corner[0], outgoing[1] - corner[1])
    first_length = hypot(*first)
    second_length = hypot(*second)
    if first_length <= tolerance or second_length <= tolerance:
        raise GeometryInputError(
            "OVERHANG_COLLAPSED_MITER",
            f"В углу {corner_index + 1} смещение схлопнулось в исходную вершину.",
        )
    first_3d = (
        incoming[0] - corner[0],
        incoming[1] - corner[1],
        incoming[2] - corner[2],
    )
    second_3d = (
        outgoing[0] - corner[0],
        outgoing[1] - corner[1],
        outgoing[2] - corner[2],
    )
    cross_3d = (
        first_3d[1] * second_3d[2] - first_3d[2] * second_3d[1],
        first_3d[2] * second_3d[0] - first_3d[0] * second_3d[2],
        first_3d[0] * second_3d[1] - first_3d[1] * second_3d[0],
    )
    cross_length = hypot(hypot(cross_3d[0], cross_3d[1]), cross_3d[2])
    allowed_cross = tolerance * max(first_length, second_length, 1.0) * 20.0
    if cross_length > allowed_cross:
        raise GeometryInputError(
            "OVERHANG_RIDGE_MISMATCH",
            f"В углу {corner_index + 1} смещения соседних скатов не лежат "
            "на одной 3D-линии пересечения.",
        )


def extend_convex_roof_surface(
    surface: RoofSurface,
    distance: float,
    eps: float = 1e-9,
) -> RoofSurface:
    """Extend convex or concave eaves while preserving every edge's support plane.

    One strip is created for each original boundary segment on that segment's
    exact support plane. Where neighbouring planes meet at different offset
    points, a single planar miter-cap joins the two strip ends and the standard
    XY offset corner. The cap shares its two inner edges with the strips, so
    the outer boundary has one continuous corner path and no loose spokes.
    Reflex corners are accepted when the resulting offset remains simple.
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
                "Не удалось определить плоскость исходного ребра свеса.",
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
            "Не удалось найти внешнюю границу верхней поверхности.",
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
            "Свес поддерживает только одну непрерывную внешнюю границу.",
        )

    contour_xy = [
        (surface.vertices[record[0]][0], surface.vertices[record[0]][1])
        for record in ordered
    ]
    contour_area = signed_area(contour_xy)
    if abs(contour_area) <= area_tolerance:
        raise GeometryInputError(
            "OVERHANG_BOUNDARY_DEGENERATE",
            "Граница крыши имеет нулевую площадь.",
        )
    winding = 1.0 if contour_area > 0.0 else -1.0

    incoming_points: list[Point3] = []
    outgoing_points: list[Point3] = []
    cap_points: list[Point3] = []

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

        incoming_z = incoming_plane.height(corner[0], corner[1])
        outgoing_z = outgoing_plane.height(corner[0], corner[1])
        if abs(incoming_z - outgoing_z) > plane_tolerance:
            raise GeometryInputError(
                "OVERHANG_SOURCE_PLANE_DISCONTINUITY",
                f"Скаты не сходятся в исходной вершине {index + 1}; свес нельзя продолжить.",
            )

        miter_xy = _miter_offset_point(
            previous_corner,
            corner,
            following_corner,
            distance,
            winding,
            tolerance,
            index,
        )

        if _plane_pair_is_coincident(
            incoming_plane, outgoing_plane, corner, plane_tolerance
        ):
            point = (
                miter_xy[0],
                miter_xy[1],
                outgoing_plane.height(*miter_xy),
            )
            incoming_point = point
            outgoing_point = point
            cap_point = point
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
            cap_z = 0.5 * (
                incoming_plane.height(*miter_xy)
                + outgoing_plane.height(*miter_xy)
            )
            cap_point = (miter_xy[0], miter_xy[1], cap_z)

        incoming_points.append(incoming_point)
        outgoing_points.append(outgoing_point)
        cap_points.append(cap_point)

    registry = _VertexRegistry(tolerance)
    remap = [registry.add(point) for point in surface.vertices]
    if any(new_index != old_index for old_index, new_index in enumerate(remap)):
        raise GeometryInputError(
            "OVERHANG_DUPLICATE_SOURCE_VERTEX",
            "Исходная поверхность содержит совпадающие вершины; свес нельзя надёжно привязать.",
        )

    incoming_ids = [registry.add(point) for point in incoming_points]
    outgoing_ids = [registry.add(point) for point in outgoing_points]
    cap_ids = [registry.add(point) for point in cap_points]

    faces = [tuple(remap[index] for index in face) for face in surface.faces]
    slope_ids = list(surface.face_slope_indices)

    # Edge strips: their four vertices are on the originating support plane.
    for index, (first, second, slope_index, _face_index) in enumerate(ordered):
        next_index = (index + 1) % len(ordered)
        strip = (
            remap[second],
            remap[first],
            outgoing_ids[index],
            incoming_ids[next_index],
        )
        if len(set(strip)) < 3:
            raise GeometryInputError(
                "OVERHANG_DEGENERATE_STRIP",
                f"Свес создал вырожденную полосу ребра {index + 1}.",
            )
        strip_area = signed_area([
            (registry.vertices[vertex_id][0], registry.vertices[vertex_id][1])
            for vertex_id in strip
        ])
        if strip_area * winding <= area_tolerance:
            raise GeometryInputError(
                "OVERHANG_DEGENERATE_STRIP",
                f"Свес создал вырожденную или перевёрнутую полосу ребра {index + 1}.",
            )
        faces.append(strip)
        slope_ids.append(slope_index)

    # A single corner cap closes the incoming/outgoing strip sides. The source
    # vertex is one point on the cap's inner ridge edge; the cap does not emit
    # two separate spokes as independent topological boundary edges.
    for index, corner_record in enumerate(ordered):
        previous_index = index - 1
        if incoming_ids[index] == outgoing_ids[index] == cap_ids[index]:
            continue
        cap = (
            remap[corner_record[0]],
            incoming_ids[index],
            cap_ids[index],
            outgoing_ids[index],
        )
        cap_area = signed_area([
            (registry.vertices[vertex_id][0], registry.vertices[vertex_id][1])
            for vertex_id in cap
        ])
        if abs(cap_area) <= area_tolerance:
            raise GeometryInputError(
                "OVERHANG_CORNER_CAP_DEGENERATE",
                f"В углу {index + 1} соединительная фаска свеса выродилась. "
                "Уменьши свес или измени соседние Pitch.",
            )
        if cap_area * winding < 0.0:
            cap = tuple(reversed(cap))
        faces.append(cap)
        slope_ids.append(-1)

    boundary_xy: list[Point2] = []

    def append_boundary_point(point: Point3) -> None:
        xy = (point[0], point[1])
        if not boundary_xy or hypot(
            boundary_xy[-1][0] - xy[0],
            boundary_xy[-1][1] - xy[1],
        ) > tolerance:
            boundary_xy.append(xy)

    for index in range(len(ordered)):
        next_index = (index + 1) % len(ordered)
        append_boundary_point(outgoing_points[index])
        append_boundary_point(incoming_points[next_index])
        append_boundary_point(cap_points[next_index])
        append_boundary_point(outgoing_points[next_index])

    if len(boundary_xy) > 1 and hypot(
        boundary_xy[0][0] - boundary_xy[-1][0],
        boundary_xy[0][1] - boundary_xy[-1][1],
    ) <= tolerance:
        boundary_xy.pop()

    issues = validate_simple_polygon(boundary_xy, eps)
    if issues:
        raise GeometryInputError(
            "OVERHANG_OFFSET_INVALID",
            "Свес создал самопересекающийся или вырожденный внешний контур: "
            + issues[0].message
            + " Уменьши свес или проверь вогнутые участки.",
        )

    try:
        validate_surface_boundary_edges(
            registry.vertices, faces, boundary_xy, tolerance * 5.0
        )
    except GeometryInputError as exc:
        raise GeometryInputError(
            "OVERHANG_SURFACE_INVALID",
            "Не удалось собрать непрерывную поверхность свеса: " + exc.message,
        ) from exc

    edge_usage: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for face in faces:
        for local_index, first in enumerate(face):
            second = face[(local_index + 1) % len(face)]
            edge_usage.setdefault(
                (min(first, second), max(first, second)), []
            ).append((first, second))
    if any(len(uses) > 2 for uses in edge_usage.values()):
        raise GeometryInputError(
            "OVERHANG_NON_MANIFOLD",
            "Угловое соединение свеса создало неманифолдное ребро.",
        )

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
            f"Свес покрывает {surface_area:.9g} из {expanded_area:.9g} "
            "квадратных единиц внешнего контура.",
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
