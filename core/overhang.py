"""Geometric eave overhang extension for validated convex roof surfaces."""
from __future__ import annotations

from math import hypot
from typing import Sequence

from .geometry import GeometryInputError, signed_area, validate_simple_polygon
from .mesh import (
    RoofSurface,
    _VertexRegistry,
    validate_surface_boundary_edges,
)


def extend_convex_roof_surface(
    surface: RoofSurface,
    distance: float,
    eps: float = 1e-9,
) -> RoofSurface:
    """Extend each boundary facet outward by a horizontal distance.

    The edge strips remain on their authored support planes. Convex corners
    receive a triangular miter patch between adjacent strips. Reflex corners
    are intentionally rejected until a non-overlapping concave join strategy
    is available.
    """
    from math import isfinite

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
    corner_area_tolerance = tolerance * tolerance * 10.0

    # Record the unique face adjacent to every mesh edge. An open edge also
    # carries its source slope ID, which determines the exact extension plane.
    edge_uses: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for face_index, face in enumerate(surface.faces):
        for local_index, first in enumerate(face):
            second = face[(local_index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            edge_uses.setdefault(key, []).append((face_index, first, second))

    records: list[tuple[int, int, int, int]] = []
    outgoing: dict[int, tuple[int, int, int, int]] = {}
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

    # Order the directed boundary edges into exactly one loop.
    start_record = min(
        records,
        key=lambda item: (
            surface.vertices[item[0]][0],
            surface.vertices[item[0]][1],
            surface.vertices[item[0]][2],
            item[0],
        ),
    )
    ordered: list[tuple[int, int, int, int]] = []
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
    if contour_area <= area_tolerance:
        raise GeometryInputError(
            "OVERHANG_BOUNDARY_WINDING",
            "Не удалось подтвердить положительную ориентацию внешней границы крыши.",
        )

    # The initial alpha join is exact for convex corners. At a reflex corner,
    # adjacent outward strips overlap; adding a simple triangle would invert
    # its top-face winding, so reject it instead of generating a folded roof.
    for index, point in enumerate(contour_xy):
        previous = contour_xy[index - 1]
        following = contour_xy[(index + 1) % len(contour_xy)]
        turn = (
            (point[0] - previous[0]) * (following[1] - point[1])
            - (point[1] - previous[1]) * (following[0] - point[0])
        )
        if turn < -area_tolerance:
            raise GeometryInputError(
                "OVERHANG_REFLEX_UNSUPPORTED",
                "Свес в этой alpha пока поддерживается только для выпуклых контуров. "
                "Для вогнутого L/U-контура установи Свес = 0.",
            )

    # Rebuild a deterministic registry while preserving every original index.
    registry = _VertexRegistry(tolerance)
    remap = [registry.add(point) for point in surface.vertices]
    if any(new_index != old_index for old_index, new_index in enumerate(remap)):
        raise GeometryInputError(
            "OVERHANG_DUPLICATE_SOURCE_VERTEX",
            "Исходная поверхность содержит совпадающие вершины; свес нельзя надёжно привязать.",
        )

    faces = [tuple(remap[index] for index in face) for face in surface.faces]
    slope_ids = list(surface.face_slope_indices)
    outer_records: list[tuple[int, int]] = []

    for first, second, slope_index, _face_index in ordered:
        p = surface.vertices[first]
        q = surface.vertices[second]
        dx, dy = q[0] - p[0], q[1] - p[1]
        edge_length = hypot(dx, dy)
        if edge_length <= tolerance:
            raise GeometryInputError(
                "OVERHANG_ZERO_LENGTH_EDGE",
                "Внешняя граница содержит ребро нулевой длины.",
            )

        # The face boundary is CCW, so its outward normal is the right normal.
        nx, ny = dy / edge_length, -dx / edge_length
        plane = surface.planes[slope_index]
        outer_first_point = (
            p[0] + nx * distance,
            p[1] + ny * distance,
            plane.height(p[0] + nx * distance, p[1] + ny * distance),
        )
        outer_second_point = (
            q[0] + nx * distance,
            q[1] + ny * distance,
            plane.height(q[0] + nx * distance, q[1] + ny * distance),
        )
        outer_first = registry.add(outer_first_point)
        outer_second = registry.add(outer_second_point)

        # Reverse the inner edge so the strip shares it with the existing roof
        # top using opposite winding.
        strip = (remap[second], remap[first], outer_first, outer_second)
        strip_area = signed_area([
            (registry.vertices[index][0], registry.vertices[index][1])
            for index in strip
        ])
        if strip_area <= area_tolerance:
            raise GeometryInputError(
                "OVERHANG_DEGENERATE_STRIP",
                "Свес создал вырожденную или перевёрнутую полосу ската.",
            )
        faces.append(strip)
        slope_ids.append(slope_index)
        outer_records.append((outer_first, outer_second))

    # Bridge the two offset endpoints at every convex source corner. These
    # triangles connect both support-plane strips without altering either.
    for index, record in enumerate(ordered):
        next_index = (index + 1) % len(ordered)
        next_record = ordered[next_index]
        inner_corner = record[1]
        if inner_corner != next_record[0]:
            raise GeometryInputError(
                "OVERHANG_BOUNDARY_DISCONTINUITY",
                "Соседние граничные полосы не имеют общей исходной вершины.",
            )
        previous_outer = outer_records[index][1]
        next_outer = outer_records[next_index][0]
        if previous_outer == next_outer:
            continue

        corner = surface.vertices[inner_corner]
        previous_point = registry.vertices[previous_outer]
        next_point = registry.vertices[next_outer]
        corner_area = signed_area([
            (corner[0], corner[1]),
            (previous_point[0], previous_point[1]),
            (next_point[0], next_point[1]),
        ])
        if corner_area < -corner_area_tolerance:
            raise GeometryInputError(
                "OVERHANG_REFLEX_UNSUPPORTED",
                "Свес в этой alpha пока поддерживается только для выпуклых контуров. "
                "Для вогнутого L/U-контура установи Свес = 0.",
            )
        if abs(corner_area) <= corner_area_tolerance:
            dx = previous_point[0] - next_point[0]
            dy = previous_point[1] - next_point[1]
            dz = previous_point[2] - next_point[2]
            if dx * dx + dy * dy + dz * dz > tolerance * tolerance:
                raise GeometryInputError(
                    "OVERHANG_COLLINEAR_PITCH_BREAK",
                    "На прямом участке с разными углами скатов свес пока не может "
                    "сформировать вертикальный переход без потери manifold-топологии.",
                )
            continue

        faces.append((remap[inner_corner], previous_outer, next_outer))
        slope_ids.append(-1)  # Convex corner transition, not one authored slope.

    # The outer boundary consists of each offset edge and each convex-corner
    # connector. Intermediate points are retained for exact boundary coverage.
    boundary_xy: list[tuple[float, float]] = []
    for index, (outer_first, outer_second) in enumerate(outer_records):
        first_point = registry.vertices[outer_first]
        second_point = registry.vertices[outer_second]
        first_xy = (first_point[0], first_point[1])
        second_xy = (second_point[0], second_point[1])
        if not boundary_xy:
            boundary_xy.append(first_xy)
        elif hypot(
            boundary_xy[-1][0] - first_xy[0],
            boundary_xy[-1][1] - first_xy[1],
        ) > tolerance:
            boundary_xy.append(first_xy)
        boundary_xy.append(second_xy)

    issues = validate_simple_polygon(boundary_xy, eps)
    if issues:
        raise GeometryInputError(
            "OVERHANG_OFFSET_INVALID",
            "Свес создал самопересекающийся или вырожденный внешний контур: "
            + issues[0].message,
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
