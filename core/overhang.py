"""Mitered horizontal eave extension for convex roof surfaces."""
from __future__ import annotations

from math import hypot, isfinite
from typing import Sequence

from .geometry import GeometryInputError, signed_area, validate_simple_polygon
from .mesh import RoofSurface, _VertexRegistry, validate_surface_boundary_edges

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
BoundaryRecord = tuple[int, int, int, int]


def _cross2(first: Point2, second: Point2) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _miter_offset_point(
    previous: Point3,
    corner: Point3,
    following: Point3,
    distance: float,
    tolerance: float,
) -> Point2:
    """Intersect the two adjacent outward-offset boundary lines in XY."""
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

    previous_tangent = (previous_dx / previous_length, previous_dy / previous_length)
    next_tangent = (next_dx / next_length, next_dy / next_length)
    # The source boundary is counter-clockwise, so the right normal points out.
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
    parallel_tolerance = 1e-12
    if abs(denominator) <= parallel_tolerance:
        alignment = (
            previous_tangent[0] * next_tangent[0]
            + previous_tangent[1] * next_tangent[1]
        )
        if alignment < 0.0:
            raise GeometryInputError(
                "OVERHANG_PARALLEL_BACKTRACK",
                "Нельзя построить свес на развёрнутом или обратном угле контура.",
            )
        # Consecutive collinear edges share one common offset line.
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
    if miter_length > max(distance * 25.0, distance + tolerance * 10.0):
        raise GeometryInputError(
            "OVERHANG_MITER_TOO_LONG",
            "Угол контура слишком острый для безопасного свеса: длина углового "
            "соединения превышает 25 ширин свеса.",
        )
    return result


def extend_convex_roof_surface(
    surface: RoofSurface,
    distance: float,
    eps: float = 1e-9,
) -> RoofSurface:
    """Extend the roof using one miter vertex at every convex eave corner.

    Every source boundary segment gets exactly one parallel outer edge. Adjacent
    strips share the same miter vertex, so no triangular fan or pair of extra
    corner edges is emitted. If two neighbouring support planes disagree at
    that shared miter point (for example, because adjacent pitches differ), the
    requested overhang is rejected rather than introducing a broken seam.
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
    z_tolerance = max(tolerance * 20.0, eps * scale * 1000.0)

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
    if signed_area(contour_xy) <= area_tolerance:
        raise GeometryInputError(
            "OVERHANG_BOUNDARY_WINDING",
            "Не удалось подтвердить положительную ориентацию внешней границы крыши.",
        )

    # Reflex turns are not valid for this offset implementation.
    for index, point in enumerate(contour_xy):
        previous = contour_xy[index - 1]
        following = contour_xy[(index + 1) % len(contour_xy)]
        turn = _cross2(
            (point[0] - previous[0], point[1] - previous[1]),
            (following[0] - point[0], following[1] - point[1]),
        )
        if turn < -area_tolerance:
            raise GeometryInputError(
                "OVERHANG_REFLEX_UNSUPPORTED",
                "Свес с miter-соединением пока поддерживается только для выпуклых контуров. "
                "Для вогнутого L/U-контура установи Свес = 0.",
            )

    # The roof boundary may contain intermediate collinear split vertices.
    # Each one receives the same shared offset point if its adjacent segments
    # are on one straight line.
    offset_xy: list[Point2] = []
    for index, point in enumerate(contour_xy):
        previous = contour_xy[index - 1]
        following = contour_xy[(index + 1) % len(contour_xy)]
        source_vertex = surface.vertices[ordered[index][0]]
        previous_vertex = surface.vertices[ordered[index - 1][0]]
        next_vertex = surface.vertices[ordered[index][1]]
        # Use the actual ordered 3D endpoints so support-plane height checks
        # remain tied to the existing mesh boundary vertices.
        offset_xy.append(
            _miter_offset_point(
                previous_vertex,
                source_vertex,
                next_vertex,
                distance,
                tolerance,
            )
        )

    issues = validate_simple_polygon(offset_xy, eps)
    if issues:
        raise GeometryInputError(
            "OVERHANG_OFFSET_INVALID",
            "Miter-свес создал самопересекающийся или вырожденный внешний контур: "
            + issues[0].message,
        )
    if signed_area(offset_xy) <= area_tolerance:
        raise GeometryInputError(
            "OVERHANG_OFFSET_WINDING",
            "Внешний miter-контур имеет неверную ориентацию.",
        )

    # At a corner the incoming and outgoing strips must share one 3D vertex.
    # If their roof planes disagree in height there, refuse to build a fan.
    for index, point_xy in enumerate(offset_xy):
        previous_slope = ordered[index - 1][2]
        next_slope = ordered[index][2]
        previous_z = surface.planes[previous_slope].height(*point_xy)
        next_z = surface.planes[next_slope].height(*point_xy)
        if abs(previous_z - next_z) > z_tolerance:
            raise GeometryInputError(
                "OVERHANG_PITCH_DISCONTINUITY",
                f"На углу {index + 1} соседние плоскости скатов расходятся по высоте "
                f"на {abs(previous_z - next_z):.6g}. Для свеса здесь нужны совместимые "
                "уклоны соседних скатов; измени pitch или установи Свес = 0.",
            )

    registry = _VertexRegistry(tolerance)
    remap = [registry.add(point) for point in surface.vertices]
    if any(new_index != old_index for old_index, new_index in enumerate(remap)):
        raise GeometryInputError(
            "OVERHANG_DUPLICATE_SOURCE_VERTEX",
            "Исходная поверхность содержит совпадающие вершины; свес нельзя надёжно привязать.",
        )

    faces = [tuple(remap[index] for index in face) for face in surface.faces]
    slope_ids = list(surface.face_slope_indices)

    # One miter point belongs to the two adjacent strips. No corner triangle
    # is necessary and no duplicate spokes leave the original source vertex.
    offset_vertex_ids: list[int] = []
    for index, (x, y) in enumerate(offset_xy):
        plane = surface.planes[ordered[index][2]]
        z = plane.height(x, y)
        offset_vertex_ids.append(registry.add((x, y, z)))

    for index, (first, second, slope_index, _face_index) in enumerate(ordered):
        next_index = (index + 1) % len(ordered)
        outer_first = offset_vertex_ids[index]
        outer_second = offset_vertex_ids[next_index]
        if outer_first == outer_second:
            raise GeometryInputError(
                "OVERHANG_COLLAPSED_EDGE",
                f"После offset схлопнулось внешнее ребро {index + 1}.",
            )

        strip = (
            remap[second],
            remap[first],
            outer_first,
            outer_second,
        )
        strip_area = signed_area([
            (registry.vertices[vertex_id][0], registry.vertices[vertex_id][1])
            for vertex_id in strip
        ])
        if strip_area <= area_tolerance:
            raise GeometryInputError(
                "OVERHANG_DEGENERATE_STRIP",
                f"Свес создал вырожденную или перевёрнутую полосу ребра {index + 1}.",
            )
        faces.append(strip)
        slope_ids.append(slope_index)

    try:
        validate_surface_boundary_edges(
            registry.vertices, faces, offset_xy, tolerance * 5.0
        )
    except GeometryInputError as exc:
        raise GeometryInputError(
            "OVERHANG_SURFACE_INVALID",
            "Не удалось собрать непрерывную поверхность miter-свеса: " + exc.message,
        ) from exc

    surface_area = sum(
        abs(signed_area([
            (registry.vertices[index][0], registry.vertices[index][1])
            for index in face
        ]))
        for face in faces
    )
    expanded_area = abs(signed_area(offset_xy))
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
        boundary_xy=tuple(offset_xy),
        approximation_error=surface.approximation_error,
        refinement_depth=surface.refinement_depth,
    )
