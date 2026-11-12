"""Exact 3D support-plane and junction primitives for spatial roof construction.

This module is deliberately independent of the historical spatial solvers and
of height-field approximation. It only creates exact support planes, exact
pairwise intersections and planar junction patches. A topology builder may
compose these primitives, but may not move a point off its defining plane.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import hypot, isfinite, radians, sqrt, tan
from typing import Sequence

from .geometry import (
    GeometryInputError,
    PlaneZ,
    _bbox_scale,
    signed_area,
    triangulate_simple_polygon,
    validate_simple_polygon,
)

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
Face = tuple[int, ...]


@dataclass(frozen=True)
class SupportPlane:
    """A roof support plane z = ax + by + c tied to one source boundary edge."""

    source_index: int
    a: float
    b: float
    c: float

    def height(self, x: float, y: float) -> float:
        return self.a * x + self.b * y + self.c

    def residual(self, point: Point3) -> float:
        return point[2] - self.height(point[0], point[1])


@dataclass(frozen=True)
class PlaneIntersectionLine:
    """Exact intersection of two non-coincident z=f(x,y) planes."""

    source_indices: tuple[int, int]
    point: Point3
    direction: Point3

    def point_at(self, parameter: float) -> Point3:
        return tuple(
            self.point[axis] + float(parameter) * self.direction[axis]
            for axis in range(3)
        )


@dataclass(frozen=True)
class SpatialJunction:
    """A roof junction represented by one point or a planar transition patch.

    For a non-concurrent multi-plane event, boundary_points are the exact
    pairwise plane-intersection points in cyclic source order. Each boundary
    segment belongs to the corresponding source support plane. faces are
    triangles in the new transition patch; no interpolated height field is
    involved.
    """

    boundary_points: tuple[Point3, ...]
    faces: tuple[Face, ...]
    boundary_source_indices: tuple[int, ...]
    concurrent: bool


def build_support_planes(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    eps: float = 1e-9,
) -> tuple[SupportPlane, ...]:
    """Construct one exact pitched plane through each authored 3D eave edge.

    The horizontal gradient is assembled from the known gradient along the
    edge and the remaining inward-normal gradient. The requested pitch is the
    total inclination of that plane, not merely its inward component.
    """
    if len(points) < 3:
        raise GeometryInputError("POLY_TOO_SMALL", "Контур должен содержать минимум три вершины.")
    if len(points) != len(pitches_degrees):
        raise GeometryInputError("PITCH_COUNT", "Нужно задать один уклон на каждое ребро.")

    normalized = tuple(tuple(float(value) for value in point) for point in points)
    if any(
        len(point) != 3 or not all(isfinite(value) for value in point)
        for point in normalized
    ):
        raise GeometryInputError("NON_FINITE", "Координаты 3D-контура должны быть конечными числами.")
    pitches = tuple(float(value) for value in pitches_degrees)
    if any(not isfinite(value) or value < 0.0 or value >= 89.9 for value in pitches):
        raise GeometryInputError("PITCH_RANGE", "Уклоны должны быть конечными и находиться в диапазоне 0–89.9°.")

    polygon_xy = tuple((point[0], point[1]) for point in normalized)
    issues = validate_simple_polygon(polygon_xy, eps)
    if issues:
        raise GeometryInputError(issues[0].code, issues[0].message)

    winding = 1.0 if signed_area(polygon_xy) > 0.0 else -1.0
    scale = max(_bbox_scale(polygon_xy), 1.0)
    edge_tolerance = eps * scale
    output: list[SupportPlane] = []

    for index, start in enumerate(normalized):
        end = normalized[(index + 1) % len(normalized)]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        length = hypot(dx, dy)
        if length <= edge_tolerance:
            raise GeometryInputError(
                "VERTICAL_PROJECTED_EDGE",
                f"Ребро {index + 1} не имеет устойчивой XY-проекции.",
            )

        tx, ty = dx / length, dy / length
        inward_x, inward_y = -ty * winding, tx * winding
        along_gradient = dz / length
        total_gradient = tan(radians(pitches[index]))
        inward_gradient_sq = total_gradient * total_gradient - along_gradient * along_gradient
        gradient_tolerance = eps * max(1.0, total_gradient * total_gradient, along_gradient * along_gradient)
        if inward_gradient_sq < -gradient_tolerance:
            raise GeometryInputError(
                "PITCH_BELOW_EAVE_GRADE",
                f"Уклон ребра {index + 1} меньше перепада высоты вдоль карниза.",
            )

        inward_gradient = sqrt(max(0.0, inward_gradient_sq))
        a = along_gradient * tx + inward_gradient * inward_x
        b = along_gradient * ty + inward_gradient * inward_y
        c = start[2] - a * start[0] - b * start[1]
        plane = SupportPlane(index, a, b, c)

        endpoint_residual = max(
            abs(plane.residual(start)),
            abs(plane.residual(end)),
        )
        if endpoint_residual > edge_tolerance * max(1.0, abs(start[2]), abs(end[2])):
            raise GeometryInputError(
                "PLANE_ENDPOINT_ERROR",
                f"Опорная плоскость ребра {index + 1} не проходит через обе вершины.",
            )
        output.append(plane)

    return tuple(output)


def intersect_support_planes(
    first: SupportPlane,
    second: SupportPlane,
    eps: float = 1e-10,
) -> PlaneIntersectionLine | None:
    """Return the exact 3D line where two support planes meet.

    None means the planes are parallel and distinct. Coincident planes are
    rejected because they do not define a unique seam and must be coalesced by
    the topology builder before intersection.
    """
    a = first.a - second.a
    b = first.b - second.b
    c = first.c - second.c
    norm_sq = a * a + b * b
    coefficient_scale = max(
        1.0, abs(first.a), abs(first.b), abs(first.c),
        abs(second.a), abs(second.b), abs(second.c),
    )
    tolerance = eps * coefficient_scale
    if norm_sq <= tolerance * tolerance:
        if abs(c) <= tolerance:
            raise GeometryInputError(
                "COINCIDENT_SUPPORT_PLANES",
                f"Опорные плоскости {first.source_index + 1} и {second.source_index + 1} совпадают.",
            )
        return None

    x = -a * c / norm_sq
    y = -b * c / norm_sq
    z = first.height(x, y)
    xy_length = sqrt(norm_sq)
    dx, dy = -b / xy_length, a / xy_length
    dz = first.a * dx + first.b * dy
    return PlaneIntersectionLine(
        tuple(sorted((first.source_index, second.source_index))),
        (x, y, z),
        (dx, dy, dz),
    )


def project_to_plane_intersection(
    first: SupportPlane,
    second: SupportPlane,
    target_xy: Point2,
    eps: float = 1e-10,
) -> Point3:
    """Project a 2D event target onto the exact intersection of two planes.

    The returned point is not a height compromise: it lies on both planes.
    This operation is intended to place the boundary vertices of a multi-plane
    transition patch once its topological event and cyclic source order are
    already known.
    """
    a = first.a - second.a
    b = first.b - second.b
    c = first.c - second.c
    norm_sq = a * a + b * b
    coefficient_scale = max(
        1.0, abs(first.a), abs(first.b), abs(first.c),
        abs(second.a), abs(second.b), abs(second.c),
    )
    tolerance = eps * coefficient_scale
    if norm_sq <= tolerance * tolerance:
        if abs(c) <= tolerance:
            raise GeometryInputError(
                "COINCIDENT_SUPPORT_PLANES",
                "Нельзя определить единственную линию перехода между совпадающими плоскостями.",
            )
        raise GeometryInputError(
            "PARALLEL_SUPPORT_PLANES",
            "Параллельные опорные плоскости не имеют общей линии перехода.",
        )

    signed_distance_numerator = a * target_xy[0] + b * target_xy[1] + c
    x = target_xy[0] - a * signed_distance_numerator / norm_sq
    y = target_xy[1] - b * signed_distance_numerator / norm_sq
    z = first.height(x, y)
    point = (x, y, z)

    residual = abs(second.residual(point))
    if residual > tolerance * max(1.0, abs(z)):
        raise GeometryInputError(
            "PAIR_INTERSECTION_RESIDUAL",
            "Вычисленная точка не лежит одновременно на обеих опорных плоскостях.",
        )
    return point


def intersect_three_support_planes(
    first: SupportPlane,
    second: SupportPlane,
    third: SupportPlane,
    eps: float = 1e-10,
) -> Point3:
    """Find the unique common point of three non-degenerate support planes."""
    a1, b1 = first.a - second.a, first.b - second.b
    c1 = second.c - first.c
    a2, b2 = first.a - third.a, first.b - third.b
    c2 = third.c - first.c
    determinant = a1 * b2 - a2 * b1
    determinant_scale = max(1.0, hypot(a1, b1) * hypot(a2, b2))
    if abs(determinant) <= eps * determinant_scale:
        raise GeometryInputError(
            "NON_UNIQUE_THREE_PLANE_JUNCTION",
            "Три опорные плоскости не задают единственную пространственную точку пересечения.",
        )

    x = (c1 * b2 - c2 * b1) / determinant
    y = (a1 * c2 - a2 * c1) / determinant
    z = first.height(x, y)
    point = (x, y, z)
    residual = max(
        abs(first.residual(point)),
        abs(second.residual(point)),
        abs(third.residual(point)),
    )
    if residual > eps * max(1.0, abs(x), abs(y), abs(z)):
        raise GeometryInputError(
            "THREE_PLANE_INTERSECTION_RESIDUAL",
            "Тройное пересечение не удовлетворяет всем трём опорным плоскостям.",
        )
    return point


def build_spatial_junction_patch(
    ordered_source_indices: Sequence[int],
    planes: Sequence[SupportPlane],
    target_xy: Point2,
    eps: float = 1e-8,
) -> SpatialJunction:
    """Build an exact multi-plane junction from its cyclic incident sources.

    Each consecutive source pair contributes a vertex on its exact 3D plane
    intersection. If all vertices coincide, the event is a true common node.
    Otherwise, the boundary is triangulated in XY; every transition triangle
    is an exact planar face and each boundary edge remains on its owning
    support plane. Self-crossing or degenerate patches are rejected.
    """
    sources = tuple(int(value) for value in ordered_source_indices)
    if len(sources) < 3 or len(set(sources)) != len(sources):
        raise GeometryInputError(
            "JUNCTION_SOURCE_ORDER",
            "Для переходного узла нужны минимум три различных ската в циклическом порядке.",
        )
    if any(index < 0 or index >= len(planes) for index in sources):
        raise GeometryInputError("JUNCTION_SOURCE_INDEX", "Узел ссылается на отсутствующую опорную плоскость.")

    points = tuple(
        project_to_plane_intersection(
            planes[source],
            planes[sources[(index + 1) % len(sources)]],
            target_xy,
            eps,
        )
        for index, source in enumerate(sources)
    )
    scale = max(
        1.0,
        max(point[0] for point in points) - min(point[0] for point in points),
        max(point[1] for point in points) - min(point[1] for point in points),
        max(point[2] for point in points) - min(point[2] for point in points),
    )
    tolerance = eps * scale

    if all(
        sqrt(sum((points[0][axis] - point[axis]) ** 2 for axis in range(3))) <= tolerance
        for point in points[1:]
    ):
        return SpatialJunction(
            (points[0],), (), (), True
        )

    polygon_xy = tuple((point[0], point[1]) for point in points)
    issues = validate_simple_polygon(polygon_xy, eps)
    if issues:
        raise GeometryInputError(
            "INVALID_SPATIAL_TRANSITION_PATCH",
            "Точки пересечения опорных плоскостей не образуют простой XY-контур переходной грани: "
            + issues[0].message,
        )

    triangles_xy = triangulate_simple_polygon(polygon_xy, eps)
    index_by_xy = {xy: index for index, xy in enumerate(polygon_xy)}
    faces: list[Face] = []
    for triangle in triangles_xy:
        face = tuple(index_by_xy[point] for point in triangle)
        if len(set(face)) != 3:
            raise GeometryInputError(
                "DEGENERATE_TRANSITION_TRIANGLE",
                "Переходная грань содержит повторяющиеся вершины.",
            )
        faces.append(face)

    # Boundary edge Q_(i-1) -> Q_i belongs to source plane i.
    boundary_sources = tuple(sources)
    for index, source in enumerate(sources):
        previous_point = points[index - 1]
        current_point = points[index]
        residual = max(
            abs(planes[source].residual(previous_point)),
            abs(planes[source].residual(current_point)),
        )
        if residual > tolerance * max(1.0, abs(previous_point[2]), abs(current_point[2])):
            raise GeometryInputError(
                "TRANSITION_BOUNDARY_OFF_PLANE",
                f"Граница переходной грани не лежит на опорной плоскости ската {source + 1}.",
            )

    return SpatialJunction(points, tuple(faces), boundary_sources, False)



def _point_in_polygon(point: Point2, polygon: Sequence[Point2], tolerance: float) -> bool:
    """Boundary-inclusive point-in-polygon test used only for topology checks."""
    x, y = point
    inside = False
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        cross = (
            (end[0] - start[0]) * (y - start[1])
            - (end[1] - start[1]) * (x - start[0])
        )
        if (
            abs(cross) <= tolerance
            and min(start[0], end[0]) - tolerance <= x <= max(start[0], end[0]) + tolerance
            and min(start[1], end[1]) - tolerance <= y <= max(start[1], end[1]) + tolerance
        ):
            return True
        if (start[1] > y) != (end[1] > y):
            crossing_x = start[0] + (
                (y - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
            )
            if x < crossing_x:
                inside = not inside
    return inside


def _proper_segment_cross(
    first_a: Point2, first_b: Point2,
    second_a: Point2, second_b: Point2,
    tolerance: float,
) -> bool:
    def orient(a, b, c):
        return (
            (b[0] - a[0]) * (c[1] - a[1])
            - (b[1] - a[1]) * (c[0] - a[0])
        )

    o1 = orient(first_a, first_b, second_a)
    o2 = orient(first_a, first_b, second_b)
    o3 = orient(second_a, second_b, first_a)
    o4 = orient(second_a, second_b, first_b)
    return (
        ((o1 > tolerance and o2 < -tolerance) or (o1 < -tolerance and o2 > tolerance))
        and ((o3 > tolerance and o4 < -tolerance) or (o3 < -tolerance and o4 > tolerance))
    )


def _ray_segment_parameter(
    origin: Point2,
    direction: Point2,
    segment_start: Point2,
    segment_end: Point2,
    tolerance: float,
) -> float | None:
    edge_x = segment_end[0] - segment_start[0]
    edge_y = segment_end[1] - segment_start[1]
    relative_x = segment_start[0] - origin[0]
    relative_y = segment_start[1] - origin[1]
    denominator = direction[0] * (-edge_y) - direction[1] * (-edge_x)
    if abs(denominator) <= tolerance:
        return None
    parameter = (
        relative_x * (-edge_y) - relative_y * (-edge_x)
    ) / denominator
    edge_parameter = (
        direction[0] * relative_y - direction[1] * relative_x
    ) / denominator
    if parameter > tolerance and -tolerance <= edge_parameter <= 1.0 + tolerance:
        return parameter
    return None


def _polygon_area_centroid(polygon: Sequence[Point2]) -> Point2:
    area_twice = 2.0 * signed_area(polygon)
    if abs(area_twice) <= 1e-20:
        return (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
        )
    cx = cy = 0.0
    for first, second in zip(polygon, polygon[1:] + polygon[:1]):
        cross = first[0] * second[1] - second[0] * first[1]
        cx += (first[0] + second[0]) * cross
        cy += (first[1] + second[1]) * cross
    factor = 1.0 / (6.0 * signed_area(polygon))
    return cx * factor, cy * factor


def _corner_seam_event_options(
    vertex_index: int,
    polygon: Sequence[Point2],
    planes: Sequence[SupportPlane],
    scale: float,
    tolerance: float,
) -> tuple[tuple[Point3, float, tuple[int, ...]], ...]:
    """Find the first exact third-plane event on each inward corner seam ray.

    A seam begins at an authored boundary vertex and lies on the exact
    intersection of its two incident support planes. It ends at the first
    point where that line meets another support plane. That event is a true
    3-plane intersection, not a sampled or percentage-based point.
    """
    count = len(polygon)
    previous_index = (vertex_index - 1) % count
    previous = planes[previous_index]
    current = planes[vertex_index]
    intersection = intersect_support_planes(
        previous, current, max(1e-12, tolerance / scale)
    )
    if intersection is None:
        return ()

    dx, dy = intersection.direction[0], intersection.direction[1]
    direction_length = hypot(dx, dy)
    if direction_length <= tolerance:
        return ()
    base_direction = (dx / direction_length, dy / direction_length)
    origin = polygon[vertex_index]
    probe_distance = max(scale * 1e-7, tolerance * 20.0)
    options: list[tuple[Point3, float, tuple[int, ...]]] = []

    for sign in (1.0, -1.0):
        direction = (
            base_direction[0] * sign,
            base_direction[1] * sign,
        )
        probe = (
            origin[0] + direction[0] * probe_distance,
            origin[1] + direction[1] * probe_distance,
        )
        if not _point_in_polygon(probe, polygon, tolerance):
            continue

        # The first footprint-boundary hit bounds the valid part of this ray.
        exit_parameters = []
        for edge_index, (edge_start, edge_end) in enumerate(
            zip(polygon, polygon[1:] + polygon[:1])
        ):
            if edge_index in {previous_index, vertex_index}:
                continue
            parameter = _ray_segment_parameter(
                origin, direction, edge_start, edge_end, tolerance
            )
            if parameter is not None:
                exit_parameters.append(parameter)
        exit_parameter = min(exit_parameters) if exit_parameters else float("inf")

        events: list[tuple[float, int, Point3]] = []
        for third_index, third in enumerate(planes):
            if third_index in {previous_index, vertex_index}:
                continue
            a = current.a - third.a
            b = current.b - third.b
            c = current.c - third.c
            denominator = a * direction[0] + b * direction[1]
            coefficient_scale = max(
                1.0, abs(a), abs(b), abs(c),
                abs(current.a), abs(current.b), abs(third.a), abs(third.b),
            )
            if abs(denominator) <= 1e-12 * coefficient_scale:
                continue
            parameter = -(
                a * origin[0] + b * origin[1] + c
            ) / denominator
            if parameter <= tolerance or parameter > exit_parameter + tolerance:
                continue

            x = origin[0] + direction[0] * parameter
            y = origin[1] + direction[1] * parameter
            if not _point_in_polygon((x, y), polygon, tolerance):
                continue

            # Ensure the seam segment does not leave and later re-enter a
            # concave footprint before reaching the plane-intersection event.
            if not all(
                _point_in_polygon(
                    (
                        origin[0] + direction[0] * parameter * fraction,
                        origin[1] + direction[1] * parameter * fraction,
                    ),
                    polygon,
                    tolerance,
                )
                for fraction in (0.1, 0.25, 0.5, 0.75, 0.9)
            ):
                continue

            z = current.height(x, y)
            point = (x, y, z)
            residual = max(
                abs(previous.residual(point)),
                abs(current.residual(point)),
                abs(third.residual(point)),
            )
            if residual > tolerance * max(1.0, abs(z)):
                continue
            events.append((parameter, third_index, point))

        if not events:
            continue
        events.sort(key=lambda item: (item[0], item[1]))
        first_parameter = events[0][0]
        simultaneous = tuple(
            sorted(
                third_index
                for parameter, third_index, _point in events
                if abs(parameter - first_parameter) <= tolerance * 10.0
            )
        )
        point = events[0][2]
        if not any(
            sqrt(sum((point[axis] - other[0][axis]) ** 2 for axis in range(3)))
            <= tolerance
            for other in options
        ):
            options.append((point, first_parameter, simultaneous))

    options.sort(key=lambda item: (item[1], item[0][0], item[0][1]))
    return tuple(options)


def _build_event_ring_candidate(
    points: Sequence[Point3],
    polygon: Sequence[Point2],
    planes: Sequence[SupportPlane],
    inner: Sequence[Point3],
    scale: float,
    tolerance: float,
):
    """Validate and assemble a ring whose vertices are exact plane events."""
    count = len(points)
    if len(inner) != count:
        return None

    winding = 1.0 if signed_area(polygon) > 0.0 else -1.0
    quad_areas: list[float] = []

    for index, point in enumerate(inner):
        previous = planes[(index - 1) % count]
        current = planes[index]
        if max(
            abs(previous.residual(point)),
            abs(current.residual(point)),
        ) > tolerance * max(1.0, abs(point[2])):
            return None
        if not _point_in_polygon((point[0], point[1]), polygon, tolerance):
            return None
        origin = polygon[index]
        for fraction in (0.2, 0.4, 0.6, 0.8):
            sample = (
                origin[0] + (point[0] - origin[0]) * fraction,
                origin[1] + (point[1] - origin[1]) * fraction,
            )
            if not _point_in_polygon(sample, polygon, tolerance):
                return None

    source_polygons: list[list[Point2]] = []
    for index in range(count):
        next_index = (index + 1) % count
        raw_xy = [
            polygon[index],
            polygon[next_index],
            (inner[next_index][0], inner[next_index][1]),
            (inner[index][0], inner[index][1]),
        ]
        compact_xy: list[Point2] = []
        for point in raw_xy:
            if not compact_xy or hypot(
                point[0] - compact_xy[-1][0],
                point[1] - compact_xy[-1][1],
            ) > tolerance:
                compact_xy.append(point)
        if len(compact_xy) > 1 and hypot(
            compact_xy[0][0] - compact_xy[-1][0],
            compact_xy[0][1] - compact_xy[-1][1],
        ) <= tolerance:
            compact_xy.pop()
        if len(compact_xy) < 3:
            return None
        if validate_simple_polygon(
            compact_xy, max(1e-12, tolerance / scale)
        ):
            return None
        area = signed_area(compact_xy)
        if area * winding <= tolerance * tolerance:
            return None
        for edge_start, edge_end in zip(
            compact_xy, compact_xy[1:] + compact_xy[:1]
        ):
            for fraction in (0.25, 0.5, 0.75):
                sample = (
                    edge_start[0] + (edge_end[0] - edge_start[0]) * fraction,
                    edge_start[1] + (edge_end[1] - edge_start[1]) * fraction,
                )
                if not _point_in_polygon(sample, polygon, tolerance):
                    return None
        centroid = _polygon_area_centroid(compact_xy)
        if not _point_in_polygon(centroid, polygon, tolerance):
            return None
        source_polygons.append(compact_xy)
        quad_areas.append(area)

    # Corner seams may meet at their intended shared endpoints, but they may
    # not cross each other in the footprint.
    for first in range(count):
        for second in range(first + 1, count):
            if second == first + 1 or (first == 0 and second == count - 1):
                continue
            if _proper_segment_cross(
                polygon[first], (inner[first][0], inner[first][1]),
                polygon[second], (inner[second][0], inner[second][1]),
                tolerance * tolerance,
            ):
                return None

    compact_indices: list[int] = []
    for index, point in enumerate(inner):
        if not compact_indices or sqrt(sum(
            (point[axis] - inner[compact_indices[-1]][axis]) ** 2
            for axis in range(3)
        )) > tolerance:
            compact_indices.append(index)
    if len(compact_indices) > 1:
        first_point = inner[compact_indices[0]]
        last_point = inner[compact_indices[-1]]
        if sqrt(sum(
            (first_point[axis] - last_point[axis]) ** 2
            for axis in range(3)
        )) <= tolerance:
            compact_indices.pop()

    compact_inner = [inner[index] for index in compact_indices]
    compact_xy = [(point[0], point[1]) for point in compact_inner]
    ring_area = signed_area(compact_xy) if len(compact_inner) >= 3 else 0.0
    if ring_area * winding < -tolerance * tolerance:
        return None

    ring_kind = "empty"
    transition_faces: tuple[Face, ...] = ()
    ring_edge_sources: tuple[int, ...] = ()
    if len(compact_inner) == 1:
        ring_kind = "point"
    elif len(compact_inner) == 2:
        ring_kind = "line"
    elif abs(ring_area) <= tolerance * tolerance:
        first = compact_inner[0]
        last = compact_inner[-1]
        direction = tuple(last[axis] - first[axis] for axis in range(3))
        direction_sq = sum(value * value for value in direction)
        if direction_sq <= tolerance * tolerance:
            return None
        for point in compact_inner[1:-1]:
            relative = tuple(point[axis] - first[axis] for axis in range(3))
            projection = sum(
                relative[axis] * direction[axis] for axis in range(3)
            ) / direction_sq
            closest = tuple(
                first[axis] + projection * direction[axis] for axis in range(3)
            )
            if sqrt(sum(
                (point[axis] - closest[axis]) ** 2 for axis in range(3)
            )) > tolerance:
                return None
        ring_kind = "line"
    else:
        if validate_simple_polygon(
            compact_xy, max(1e-12, tolerance / scale)
        ):
            return None
        if ring_area * winding <= tolerance * tolerance:
            return None
        # Every central boundary edge T_i -> T_(i+1) must lie on the
        # corresponding source plane i. The cap may be non-planar as a whole,
        # but each generated transition triangle is planar by construction.
        for compact_index, original_index in enumerate(compact_indices):
            next_original = compact_indices[
                (compact_index + 1) % len(compact_indices)
            ]
            source = planes[(next_original - 1) % count]
            first_point = compact_inner[compact_index]
            second_point = compact_inner[(compact_index + 1) % len(compact_inner)]
            if max(
                abs(source.residual(first_point)),
                abs(source.residual(second_point)),
            ) > tolerance * max(1.0, abs(first_point[2]), abs(second_point[2])):
                return None
            for fraction in (0.25, 0.5, 0.75):
                sample = (
                    first_point[0] + (second_point[0] - first_point[0]) * fraction,
                    first_point[1] + (second_point[1] - first_point[1]) * fraction,
                )
                if not _point_in_polygon(sample, polygon, tolerance):
                    return None
        try:
            triangles = triangulate_simple_polygon(
                compact_xy, max(1e-12, tolerance / scale)
            )
        except GeometryInputError:
            return None
        index_by_xy = {point: index for index, point in enumerate(compact_xy)}
        transition_faces = tuple(
            tuple(index_by_xy[point] for point in triangle)
            for triangle in triangles
        )
        ring_kind = "polygon"
        ring_edge_sources = tuple(
            (compact_indices[(index + 1) % len(compact_indices)] - 1) % count
            for index in range(len(compact_indices))
        )

    total_area = sum(quad_areas) + abs(ring_area)
    domain_area = abs(signed_area(polygon))
    if abs(total_area - domain_area) > max(
        tolerance * scale * 10.0,
        domain_area * 1e-7,
    ):
        return None

    return {
        "inner": tuple(inner),
        "compact_indices": tuple(compact_indices),
        "compact_inner": tuple(compact_inner),
        "quad_areas": tuple(quad_areas),
        "ring_kind": ring_kind,
        "transition_faces": transition_faces,
        "ring_edge_sources": ring_edge_sources,
        "ring_area": abs(ring_area),
        "event_distance_sum": sum(
            sqrt(
                (inner[index][0] - points[index][0]) ** 2
                + (inner[index][1] - points[index][1]) ** 2
            )
            for index in range(count)
        ),
    }


def _select_exact_ring_candidate(
    points: Sequence[Point3],
    polygon: Sequence[Point2],
    planes: Sequence[SupportPlane],
    event_options: Sequence[Sequence[tuple[Point3, float, tuple[int, ...]]]],
    scale: float,
    tolerance: float,
):
    """Select a conforming ring from first exact 3-plane seam events.

    A reflex vertex may have more than one inward direction. Each direction
    contributes its first exact plane-intersection event. The selector tests
    the small set of resulting topologies and accepts only a complete simple
    partition. For large ambiguous sets it fails closed rather than guessing.
    """
    combination_count = 1
    for options in event_options:
        combination_count *= len(options)
        if combination_count > 50000:
            raise GeometryInputError(
                "SPATIAL_EVENT_AMBIGUITY",
                "Слишком много альтернативных пространственных событий для однозначного выбора топологии.",
            )

    valid_candidates = []
    for combination in product(*event_options):
        inner = tuple(option[0] for option in combination)
        candidate = _build_event_ring_candidate(
            points, polygon, planes, inner, scale, tolerance
        )
        if candidate is not None:
            valid_candidates.append(candidate)

    if not valid_candidates:
        raise GeometryInputError(
            "EXACT_SPATIAL_TOPOLOGY_UNRESOLVED",
            "Первые пересечения пространственных швов не образуют простой замкнутый набор плоских скатов. "
            "Поверхность не создана; сглаженная или приблизительная подмена не применяется.",
        )

    valid_candidates.sort(
        key=lambda candidate: (
            candidate["ring_area"],
            candidate["event_distance_sum"],
        )
    )
    return valid_candidates[0]

def build_exact_planar_ring_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    eps: float = 1e-9,
):
    """Build a piecewise-planar roof from exact edge planes and their seams.

    Each original eave edge receives one flat source-plane face. Adjacent
    source faces meet on the exact 3D intersection line of their support
    planes. Their inner seam endpoints form a compact central ring; if the
    seams converge to a line or point, no transition patch is needed. A
    remaining polygonal ring is filled with planar triangles. The builder
    searches only for a simple, non-overlapping partition of the footprint;
    it rejects the contour if such a partition cannot be formed.

    Unlike the historical distance-field route, this surface is never
    smoothed or approximated. Every source face is checked against its exact
    support plane, and every transition face is checked for planarity.
    """
    normalized = tuple(tuple(float(value) for value in point) for point in points)
    planes = build_support_planes(normalized, pitches_degrees, eps)
    polygon = tuple((point[0], point[1]) for point in normalized)
    scale = max(_bbox_scale(polygon), 1.0)
    tolerance = max(1e-12, eps * scale * 100.0)
    event_options = tuple(
        _corner_seam_event_options(
            index, polygon, planes, scale, tolerance
        )
        for index in range(len(normalized))
    )
    if any(not options for options in event_options):
        missing = [
            index + 1 for index, options in enumerate(event_options) if not options
        ]
        raise GeometryInputError(
            "SPATIAL_SEAM_WITHOUT_EVENT",
            "Для швов у вершин {} не найдено конечное пересечение с третьей опорной плоскостью внутри контура. "
            "Нельзя достраивать такие швы произвольной длиной.".format(missing),
        )

    candidate = _select_exact_ring_candidate(
        normalized, polygon, planes, event_options, scale, tolerance
    )

    # Weld only geometrically identical 3D points. The selected alpha and
    # support-plane intersections remain untouched.
    vertices: list[Point3] = []
    buckets: dict[tuple[int, int, int], list[int]] = {}

    def add_vertex(point: Point3) -> int:
        key = tuple(int(round(value / tolerance)) for value in point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    nearby = buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ())
                    for vertex_index in nearby:
                        existing = vertices[vertex_index]
                        distance_sq = sum(
                            (existing[axis] - point[axis]) ** 2
                            for axis in range(3)
                        )
                        if distance_sq <= tolerance * tolerance:
                            return vertex_index
        index = len(vertices)
        vertices.append(tuple(float(value) for value in point))
        buckets.setdefault(key, []).append(index)
        return index

    outer_ids = [add_vertex(point) for point in normalized]
    inner_ids = [add_vertex(point) for point in candidate["inner"]]
    faces: list[Face] = []
    face_sources: list[int] = []

    for index in range(len(normalized)):
        next_index = (index + 1) % len(normalized)
        raw_face = (
            outer_ids[index],
            outer_ids[next_index],
            inner_ids[next_index],
            inner_ids[index],
        )
        compact: list[int] = []
        for vertex_index in raw_face:
            if not compact or compact[-1] != vertex_index:
                compact.append(vertex_index)
        if len(compact) > 1 and compact[0] == compact[-1]:
            compact.pop()
        if len(set(compact)) < 3:
            raise GeometryInputError(
                "DEGENERATE_SOURCE_SLOPE_FACE",
                f"Плоский скат по ребру {index + 1} схлопнулся в линию.",
            )
        face_xy = [(vertices[v][0], vertices[v][1]) for v in compact]
        if signed_area(face_xy) < 0.0:
            compact.reverse()
        validate_planar_face(
            vertices, compact, support_plane=planes[index], eps=max(eps * 10.0, 1e-10)
        )

        # The shell validator and Blender's triangulators must never interpret
        # a concave source n-gon as a fan outside its true boundary. Split only
        # concave planar source faces into exact in-plane triangles. Blender's
        # coplanar dissolve stage can merge them back into one editable slope.
        turn_values = []
        for local_index in range(len(face_xy)):
            first = face_xy[local_index]
            second = face_xy[(local_index + 1) % len(face_xy)]
            third = face_xy[(local_index + 2) % len(face_xy)]
            turn_values.append(
                (second[0] - first[0]) * (third[1] - second[1])
                - (second[1] - first[1]) * (third[0] - second[0])
            )
        positive = any(value > tolerance * tolerance for value in turn_values)
        negative = any(value < -tolerance * tolerance for value in turn_values)
        if positive and negative:
            triangulated = triangulate_simple_polygon(
                face_xy, max(1e-12, tolerance / scale)
            )
            index_by_xy = {point: vertex_id for point, vertex_id in zip(face_xy, compact)}
            for triangle in triangulated:
                triangle_face = tuple(index_by_xy[point] for point in triangle)
                validate_planar_face(
                    vertices, triangle_face,
                    support_plane=planes[index],
                    eps=max(eps * 10.0, 1e-10),
                )
                faces.append(triangle_face)
                face_sources.append(index)
        else:
            faces.append(tuple(compact))
            face_sources.append(index)

    if candidate["ring_kind"] == "polygon":
        compact_inner_ids = [
            inner_ids[index] for index in candidate["compact_indices"]
        ]
        for triangle in candidate["transition_faces"]:
            face = tuple(compact_inner_ids[index] for index in triangle)
            face_xy = [(vertices[v][0], vertices[v][1]) for v in face]
            if signed_area(face_xy) < 0.0:
                face = tuple(reversed(face))
            validate_planar_face(
                vertices, face, support_plane=None, eps=max(eps * 10.0, 1e-10)
            )
            faces.append(face)
            face_sources.append(-1)

    # Every internal seam must be used twice. Single-use edges are permitted
    # only on the exact authored XYZ contour.
    edge_uses: dict[tuple[int, int], int] = {}
    for face in faces:
        for edge_index, first in enumerate(face):
            second = face[(edge_index + 1) % len(face)]
            edge = (min(first, second), max(first, second))
            edge_uses[edge] = edge_uses.get(edge, 0) + 1
    if any(count > 2 for count in edge_uses.values()):
        raise GeometryInputError(
            "EXACT_SPATIAL_NON_MANIFOLD",
            "Пространственная топология создала внутреннее ребро более чем с двумя гранями.",
        )

    from .mesh import RoofSurface, validate_surface_boundary_edges
    validate_surface_boundary_edges(
        vertices, faces, polygon, tolerance * 5.0
    )
    surface_area_xy = sum(
        abs(signed_area([(vertices[index][0], vertices[index][1]) for index in face]))
        for face in faces
    )
    source_area_xy = abs(signed_area(polygon))
    if abs(surface_area_xy - source_area_xy) > max(
        tolerance * scale * 10.0, source_area_xy * 1e-7
    ):
        raise GeometryInputError(
            "EXACT_SPATIAL_COVERAGE",
            "Плоские скаты и центральная переходная заплата не покрывают исходный контур без зазоров и перекрытий.",
        )

    return RoofSurface(
        vertices=tuple(vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(face_sources),
        planes=tuple(PlaneZ(plane.a, plane.b, plane.c) for plane in planes),
        source_area_xy=source_area_xy,
        surface_area_xy=surface_area_xy,
        boundary_xy=tuple(polygon),
        approximation_error=0.0,
        refinement_depth=0,
    )

def validate_planar_face(
    vertices: Sequence[Point3],
    face: Sequence[int],
    *,
    support_plane: SupportPlane | None = None,
    eps: float = 1e-8,
) -> None:
    """Reject a face that is not exactly planar within scale-aware tolerance."""
    if len(face) < 3 or len(set(face)) < 3:
        raise GeometryInputError("DEGENERATE_FACE", "Грань должна содержать минимум три различные вершины.")
    points = [vertices[index] for index in face]
    scale = max(
        1.0,
        *(
            max(point[axis] for point in points) - min(point[axis] for point in points)
            for axis in (0, 1, 2)
        ),
    )
    tolerance = eps * scale

    if support_plane is not None:
        residual = max(abs(support_plane.residual(point)) for point in points)
        if residual > tolerance:
            raise GeometryInputError(
                "NON_PLANAR_SUPPORT_FACE",
                f"Грань не лежит на точной опорной плоскости ската {support_plane.source_index + 1}.",
            )
        return

    origin = points[0]
    normal = None
    for index in range(1, len(points) - 1):
        u = tuple(points[index][axis] - origin[axis] for axis in range(3))
        v = tuple(points[index + 1][axis] - origin[axis] for axis in range(3))
        candidate = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        magnitude = sqrt(sum(value * value for value in candidate))
        if magnitude > tolerance * tolerance:
            normal = tuple(value / magnitude for value in candidate)
            break
    if normal is None:
        raise GeometryInputError("DEGENERATE_FACE", "Грань имеет нулевую площадь.")
    residual = max(
        abs(sum(normal[axis] * (point[axis] - origin[axis]) for axis in range(3)))
        for point in points
    )
    if residual > tolerance:
        raise GeometryInputError(
            "NON_PLANAR_TRANSITION_FACE",
            "Переходная грань не является плоской; её нельзя выдавать как готовую геометрию.",
        )


__all__ = [
    "SupportPlane",
    "PlaneIntersectionLine",
    "SpatialJunction",
    "build_support_planes",
    "intersect_support_planes",
    "intersect_three_support_planes",
    "project_to_plane_intersection",
    "build_spatial_junction_patch",
    "validate_planar_face",
]
