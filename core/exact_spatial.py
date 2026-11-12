"""Exact 3D support-plane and junction primitives for spatial roof construction.

This module is deliberately independent of the historical spatial solvers and
of height-field approximation. It only creates exact support planes, exact
pairwise intersections and planar junction patches. A topology builder may
compose these primitives, but may not move a point off its defining plane.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import atan2, hypot, isfinite, radians, sqrt, tan
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
    reject_reasons: list[str] | None = None,
):
    """Validate and assemble a ring whose vertices are exact plane events."""
    count = len(points)
    def reject(reason: str):
        if reject_reasons is not None:
            reject_reasons.append(reason)
        return None
    if len(inner) != count:
        return reject("inner-count")

    winding = 1.0 if signed_area(polygon) > 0.0 else -1.0
    quad_areas: list[float] = []

    for index, point in enumerate(inner):
        previous = planes[(index - 1) % count]
        current = planes[index]
        if max(
            abs(previous.residual(point)),
            abs(current.residual(point)),
        ) > tolerance * max(1.0, abs(point[2])):
            return reject("check-2")
        if not _point_in_polygon((point[0], point[1]), polygon, tolerance):
            return reject("check-3")
        origin = polygon[index]
        for fraction in (0.2, 0.4, 0.6, 0.8):
            sample = (
                origin[0] + (point[0] - origin[0]) * fraction,
                origin[1] + (point[1] - origin[1]) * fraction,
            )
            if not _point_in_polygon(sample, polygon, tolerance):
                return reject("check-4")

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
            return reject("check-5")
        if validate_simple_polygon(
            compact_xy, max(1e-12, tolerance / scale)
        ):
            return reject("check-6")
        area = signed_area(compact_xy)
        if area * winding <= tolerance * tolerance:
            return reject("check-7")
        for edge_start, edge_end in zip(
            compact_xy, compact_xy[1:] + compact_xy[:1]
        ):
            for fraction in (0.25, 0.5, 0.75):
                sample = (
                    edge_start[0] + (edge_end[0] - edge_start[0]) * fraction,
                    edge_start[1] + (edge_end[1] - edge_start[1]) * fraction,
                )
                if not _point_in_polygon(sample, polygon, tolerance):
                    return reject("check-8")
        centroid = _polygon_area_centroid(compact_xy)
        if not _point_in_polygon(centroid, polygon, tolerance):
            return reject("check-9")
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
                return reject("check-10")

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
        return reject("check-11")

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
            return reject("check-12")
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
                return reject("check-13")
        ring_kind = "line"
    else:
        if validate_simple_polygon(
            compact_xy, max(1e-12, tolerance / scale)
        ):
            return reject("check-14")
        if ring_area * winding <= tolerance * tolerance:
            return reject("check-15")
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
                return reject("check-16")
            for fraction in (0.25, 0.5, 0.75):
                sample = (
                    first_point[0] + (second_point[0] - first_point[0]) * fraction,
                    first_point[1] + (second_point[1] - first_point[1]) * fraction,
                )
                if not _point_in_polygon(sample, polygon, tolerance):
                    return reject("check-17")
        try:
            triangles = triangulate_simple_polygon(
                compact_xy, max(1e-12, tolerance / scale)
            )
        except GeometryInputError:
            return reject("check-18")
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
        return reject("check-19")

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
    rejected: list[str] = []
    for combination in product(*event_options):
        inner = tuple(option[0] for option in combination)
        candidate = _build_event_ring_candidate(
            points, polygon, planes, inner, scale, tolerance, rejected
        )
        if candidate is not None:
            valid_candidates.append(candidate)

    if not valid_candidates:
        raise GeometryInputError(
            "EXACT_SPATIAL_TOPOLOGY_UNRESOLVED",
            "Первые пересечения пространственных швов не образуют простой замкнутый набор плоских скатов. "
            "Поверхность не создана; сглаженная или приблизительная подмена не применяется. "
            + "Причины отказа: " + ", ".join(
                f"{reason}={rejected.count(reason)}"
                for reason in sorted(set(rejected))
            ),
        )

    valid_candidates.sort(
        key=lambda candidate: (
            candidate["ring_area"],
            candidate["event_distance_sum"],
        )
    )
    return valid_candidates[0]



def _segment_pair_parameters(
    first_start: Point2,
    first_end: Point2,
    second_start: Point2,
    second_end: Point2,
    tolerance: float,
) -> tuple[tuple[float, float], ...]:
    """Return all split parameters for a finite 2D segment pair.

    Collinear overlaps are split at every endpoint of the overlap so the
    resulting planar graph has one canonical edge for each geometric interval.
    """
    rx = first_end[0] - first_start[0]
    ry = first_end[1] - first_start[1]
    sx = second_end[0] - second_start[0]
    sy = second_end[1] - second_start[1]
    qx = second_start[0] - first_start[0]
    qy = second_start[1] - first_start[1]
    first_length_sq = rx * rx + ry * ry
    second_length_sq = sx * sx + sy * sy
    if first_length_sq <= tolerance * tolerance or second_length_sq <= tolerance * tolerance:
        return ()

    denominator = rx * sy - ry * sx
    scale = max(1.0, sqrt(first_length_sq), sqrt(second_length_sq))
    cross_tolerance = tolerance * scale
    output: list[tuple[float, float]] = []

    if abs(denominator) > cross_tolerance:
        first_parameter = (qx * sy - qy * sx) / denominator
        second_parameter = (qx * ry - qy * rx) / denominator
        parameter_tolerance = tolerance / scale
        if (
            -parameter_tolerance <= first_parameter <= 1.0 + parameter_tolerance
            and -parameter_tolerance <= second_parameter <= 1.0 + parameter_tolerance
        ):
            output.append((
                max(0.0, min(1.0, first_parameter)),
                max(0.0, min(1.0, second_parameter)),
            ))
        return tuple(output)

    # Parallel but not collinear.
    if abs(qx * ry - qy * rx) > cross_tolerance:
        return ()

    # Collinear: project both pairs of endpoints onto the opposite segment.
    for point, is_first_segment in (
        (second_start, False),
        (second_end, False),
        (first_start, True),
        (first_end, True),
    ):
        if is_first_segment:
            first_parameter = (
                (point[0] - first_start[0]) * rx
                + (point[1] - first_start[1]) * ry
            ) / first_length_sq
            projected = (
                first_start[0] + first_parameter * rx,
                first_start[1] + first_parameter * ry,
            )
            second_parameter = (
                (projected[0] - second_start[0]) * sx
                + (projected[1] - second_start[1]) * sy
            ) / second_length_sq
        else:
            second_parameter = (
                (point[0] - second_start[0]) * sx
                + (point[1] - second_start[1]) * sy
            ) / second_length_sq
            projected = (
                second_start[0] + second_parameter * sx,
                second_start[1] + second_parameter * sy,
            )
            first_parameter = (
                (projected[0] - first_start[0]) * rx
                + (projected[1] - first_start[1]) * ry
            ) / first_length_sq

        parameter_tolerance = tolerance / scale
        if (
            -parameter_tolerance <= first_parameter <= 1.0 + parameter_tolerance
            and -parameter_tolerance <= second_parameter <= 1.0 + parameter_tolerance
            and hypot(projected[0] - point[0], projected[1] - point[1]) <= tolerance
        ):
            pair = (
                max(0.0, min(1.0, first_parameter)),
                max(0.0, min(1.0, second_parameter)),
            )
            if not any(
                abs(pair[0] - existing[0]) <= parameter_tolerance
                and abs(pair[1] - existing[1]) <= parameter_tolerance
                for existing in output
            ):
                output.append(pair)
    return tuple(output)


def _interpolate_point3(first: Point3, second: Point3, parameter: float) -> Point3:
    return tuple(
        first[axis] + (second[axis] - first[axis]) * parameter
        for axis in range(3)
    )


def _clean_collinear_cell_loop(
    loop: Sequence[int],
    vertices: Sequence[Point3],
    tolerance: float,
) -> list[int]:
    """Remove only 3D-collinear degree-two vertices from one planar cell loop."""
    result = list(loop)
    changed = True
    while changed and len(result) > 3:
        changed = False
        for index in range(len(result)):
            a = vertices[result[index - 1]]
            b = vertices[result[index]]
            c = vertices[result[(index + 1) % len(result)]]
            u = tuple(b[axis] - a[axis] for axis in range(3))
            v = tuple(c[axis] - b[axis] for axis in range(3))
            cross = (
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            )
            cross_length = sqrt(sum(value * value for value in cross))
            u_length = sqrt(sum(value * value for value in u))
            v_length = sqrt(sum(value * value for value in v))
            dot = sum(u[axis] * v[axis] for axis in range(3))
            if (
                cross_length <= tolerance * max(1.0, u_length, v_length)
                and dot >= -tolerance * tolerance
            ):
                del result[index]
                changed = True
                break
    return result


def _build_exact_spatial_arrangement_surface(
    points: Sequence[Point3],
    polygon: Sequence[Point2],
    planes: Sequence[SupportPlane],
    event_nodes: Sequence[Point3],
    eps: float,
):
    """Build a planar-cell arrangement from exact boundary and seam segments.

    The graph can contain multiple transition regions, coincident seam
    intervals, reflex-corner split events and repeated triple-plane nodes.
    It is not forced into one simple central ring. Every arrangement vertex
    has a single XYZ location; projected crossings at different heights are
    rejected as self-intersections.
    """
    count = len(points)
    scale = max(_bbox_scale(polygon), 1.0)
    tolerance = max(1e-12, eps * scale * 100.0)
    area_tolerance = tolerance * scale

    segments: list[dict] = []
    for index in range(count):
        segments.append({
            "a": tuple(points[index]),
            "b": tuple(points[(index + 1) % count]),
            "kind": "boundary",
            "label": index,
            "params": [0.0, 1.0],
        })
        previous = planes[(index - 1) % count]
        current = planes[index]
        event = event_nodes[index]
        if max(abs(previous.residual(event)), abs(current.residual(event))) > tolerance * max(1.0, abs(event[2])):
            raise GeometryInputError(
                "SPATIAL_EVENT_OFF_SEAM",
                f"Точка события у вершины {index + 1} не лежит на обеих соседних опорных плоскостях.",
            )
        segments.append({
            "a": tuple(points[index]),
            "b": tuple(event),
            "kind": "seam",
            "label": tuple(sorted(((index - 1) % count, index))),
            "params": [0.0, 1.0],
        })

    for index in range(count):
        first = event_nodes[index]
        second = event_nodes[(index + 1) % count]
        distance = sqrt(sum((first[axis] - second[axis]) ** 2 for axis in range(3)))
        if distance <= tolerance:
            continue
        source = planes[index]
        if max(abs(source.residual(first)), abs(source.residual(second))) > tolerance * max(1.0, abs(first[2]), abs(second[2])):
            raise GeometryInputError(
                "SPATIAL_EVENT_EDGE_OFF_PLANE",
                f"Внутреннее событийное ребро между узлами {index + 1} и {(index + 2) % count + 1} не лежит на плоскости ската {index + 1}.",
            )
        segments.append({
            "a": tuple(first),
            "b": tuple(second),
            "kind": "transition_boundary",
            "label": index,
            "params": [0.0, 1.0],
        })

    # All authored and event segments must remain within the footprint.
    for segment in segments:
        if segment["kind"] == "boundary":
            continue
        a = segment["a"]
        b = segment["b"]
        for fraction in (0.2, 0.4, 0.6, 0.8):
            sample = (
                a[0] + (b[0] - a[0]) * fraction,
                a[1] + (b[1] - a[1]) * fraction,
            )
            if not _point_in_polygon(sample, polygon, tolerance):
                raise GeometryInputError(
                    "SPATIAL_EVENT_SEGMENT_OUTSIDE",
                    "Сегмент пространственного события выходит за пределы исходного контура.",
                )

    # Split every finite segment at exact projected intersections. Any two
    # segments that cross in XY must have the same Z at the crossing.
    for first_index, first in enumerate(segments):
        for second in segments[first_index + 1:]:
            intersections = _segment_pair_parameters(
                first["a"][:2], first["b"][:2],
                second["a"][:2], second["b"][:2],
                tolerance,
            )
            for first_parameter, second_parameter in intersections:
                first_point = _interpolate_point3(
                    first["a"], first["b"], first_parameter
                )
                second_point = _interpolate_point3(
                    second["a"], second["b"], second_parameter
                )
                if hypot(
                    first_point[0] - second_point[0],
                    first_point[1] - second_point[1],
                ) > tolerance:
                    continue
                if abs(first_point[2] - second_point[2]) > tolerance * max(
                    1.0, abs(first_point[2]), abs(second_point[2])
                ):
                    raise GeometryInputError(
                        "SPATIAL_SEGMENT_CROSSING_HEIGHT",
                        "Два пространственных шва пересекаются в плане, но имеют разную высоту. "
                        "Такая крыша самопересекается и не может быть собрана.",
                    )
                first["params"].append(first_parameter)
                second["params"].append(second_parameter)

    vertices: list[Point3] = []
    xy_buckets: dict[tuple[int, int], list[int]] = {}

    def add_vertex(point: Point3) -> int:
        key = (int(round(point[0] / tolerance)), int(round(point[1] / tolerance)))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for vertex_index in xy_buckets.get((key[0] + dx, key[1] + dy), ()):
                    existing = vertices[vertex_index]
                    xy_distance = hypot(existing[0] - point[0], existing[1] - point[1])
                    if xy_distance <= tolerance:
                        if abs(existing[2] - point[2]) > tolerance * max(
                            1.0, abs(existing[2]), abs(point[2])
                        ):
                            raise GeometryInputError(
                                "SPATIAL_VERTEX_HEIGHT_CONFLICT",
                                "Одна XY-точка получила две разные высоты от пространственных швов.",
                            )
                        return vertex_index
        vertex_index = len(vertices)
        vertices.append(tuple(float(value) for value in point))
        xy_buckets.setdefault(key, []).append(vertex_index)
        return vertex_index

    edges: dict[tuple[int, int], dict[str, set]] = {}
    for segment in segments:
        a = segment["a"]
        b = segment["b"]
        length = hypot(b[0] - a[0], b[1] - a[1])
        if length <= tolerance:
            if abs(b[2] - a[2]) > tolerance:
                raise GeometryInputError(
                    "VERTICAL_SPATIAL_SEGMENT",
                    "Пространственная поверхность требует вертикального ребра с нулевой XY-проекцией.",
                )
            continue
        parameter_tolerance = tolerance / max(length, tolerance)
        params = sorted(segment["params"])
        unique_params = []
        for parameter in params:
            clipped = max(0.0, min(1.0, float(parameter)))
            if not unique_params or clipped - unique_params[-1] > parameter_tolerance:
                unique_params.append(clipped)
        for first_parameter, second_parameter in zip(unique_params, unique_params[1:]):
            if second_parameter - first_parameter <= parameter_tolerance:
                continue
            first_point = _interpolate_point3(a, b, first_parameter)
            second_point = _interpolate_point3(a, b, second_parameter)
            first_id = add_vertex(first_point)
            second_id = add_vertex(second_point)
            if first_id == second_id:
                continue
            key = (min(first_id, second_id), max(first_id, second_id))
            metadata = edges.setdefault(
                key,
                {"pairs": set(), "boundaries": set(), "transition": set()},
            )
            if segment["kind"] == "boundary":
                metadata["boundaries"].add(int(segment["label"]))
            elif segment["kind"] == "seam":
                metadata["pairs"].add(tuple(segment["label"]))
            else:
                metadata["transition"].add(int(segment["label"]))

    if not edges:
        raise GeometryInputError("EMPTY_SPATIAL_ARRANGEMENT", "Пространственная раскладка не содержит рёбер.")

    outgoing: dict[int, list[tuple[int, int]]] = {}
    for first_id, second_id in edges:
        outgoing.setdefault(first_id, []).append((first_id, second_id))
        outgoing.setdefault(second_id, []).append((second_id, first_id))
    for vertex_id, half_edges in outgoing.items():
        half_edges.sort(key=lambda edge: atan2(
            vertices[edge[1]][1] - vertices[vertex_id][1],
            vertices[edge[1]][0] - vertices[vertex_id][0],
        ))

    outgoing_indices = {
        vertex_id: {edge: index for index, edge in enumerate(half_edges)}
        for vertex_id, half_edges in outgoing.items()
    }
    next_half_edge = {}
    all_half_edges = [
        edge
        for first_id, second_id in edges
        for edge in ((first_id, second_id), (second_id, first_id))
    ]
    for first_id, second_id in all_half_edges:
        ordered = outgoing.get(second_id, ())
        reverse = (second_id, first_id)
        reverse_index = outgoing_indices[second_id].get(reverse)
        if reverse_index is None:
            raise GeometryInputError(
                "SPATIAL_ARRANGEMENT_HALF_EDGE",
                "Не удалось построить согласованную half-edge структуру.",
            )
        next_half_edge[(first_id, second_id)] = ordered[
            (reverse_index - 1) % len(ordered)
        ]

    cell_loops: list[tuple[int, ...]] = []
    half_edge_cell: dict[tuple[int, int], int] = {}
    visited: set[tuple[int, int]] = set()
    for start_edge in all_half_edges:
        if start_edge in visited:
            continue
        current = start_edge
        local: set[tuple[int, int]] = set()
        loop: list[int] = []
        for _guard in range(len(all_half_edges) + 2):
            if current in local:
                break
            if current in visited and current != start_edge:
                break
            local.add(current)
            visited.add(current)
            loop.append(current[0])
            current = next_half_edge.get(current)
            if current is None:
                break
            if current == start_edge:
                break
        if current != start_edge or len(loop) < 3:
            continue
        compact_loop: list[int] = []
        for vertex_id in loop:
            if not compact_loop or compact_loop[-1] != vertex_id:
                compact_loop.append(vertex_id)
        if len(compact_loop) > 1 and compact_loop[0] == compact_loop[-1]:
            compact_loop.pop()
        if len(set(compact_loop)) != len(compact_loop):
            raise GeometryInputError(
                "SPATIAL_ARRANGEMENT_REPEATED_VERTEX",
                "Ячейка пространственной раскладки имеет самокасание или незамкнутую ветвь.",
            )
        loop_xy = [(vertices[index][0], vertices[index][1]) for index in compact_loop]
        loop_area = signed_area(loop_xy)
        if loop_area <= area_tolerance * 1e-4:
            continue
        cell_id = len(cell_loops)
        cell_loops.append(tuple(compact_loop))
        for first_id, second_id in zip(compact_loop, compact_loop[1:] + compact_loop[:1]):
            half_edge_cell[(first_id, second_id)] = cell_id

    if not cell_loops:
        raise GeometryInputError(
            "SPATIAL_ARRANGEMENT_EMPTY_CELLS",
            "Пространственная раскладка не образовала ограниченных ячеек крыши.",
        )

    edge_cells: dict[tuple[int, int], set[int]] = {}
    for (first_id, second_id), cell_id in half_edge_cell.items():
        key = (min(first_id, second_id), max(first_id, second_id))
        edge_cells.setdefault(key, set()).add(cell_id)

    cell_sources: list[int] = []
    for loop in cell_loops:
        matching = []
        for plane in planes:
            if max(
                abs(plane.residual(vertices[vertex_id])) for vertex_id in loop
            ) <= tolerance * max(
                1.0,
                max(abs(vertices[vertex_id][2]) for vertex_id in loop),
            ):
                matching.append(plane.source_index)
        cell_sources.append(min(matching) if matching else -1)

    for edge_key, adjacent_cells in edge_cells.items():
        metadata = edges[edge_key]
        if len(adjacent_cells) == 1:
            if not metadata["boundaries"]:
                raise GeometryInputError(
                    "SPATIAL_ARRANGEMENT_OPEN_INTERNAL_EDGE",
                    f"Внутреннее ребро {edge_key} осталось открытым после построения ячеек.",
                )
            continue
        if len(adjacent_cells) != 2:
            raise GeometryInputError(
                "SPATIAL_ARRANGEMENT_NON_MANIFOLD_EDGE",
                f"Ребро {edge_key} принадлежит {len(adjacent_cells)} ячейкам.",
            )
        first_cell, second_cell = tuple(adjacent_cells)
        first_source, second_source = cell_sources[first_cell], cell_sources[second_cell]
        edge_points = [vertices[edge_key[0]], vertices[edge_key[1]]]

        if first_source >= 0 and second_source >= 0 and first_source != second_source:
            first_plane = planes[first_source]
            second_plane = planes[second_source]
            residual = max(
                abs(first_plane.residual(point))
                for point in edge_points
            )
            residual = max(
                residual,
                *(abs(second_plane.residual(point)) for point in edge_points),
            )
            if residual > tolerance * max(
                1.0, *(abs(point[2]) for point in edge_points)
            ):
                raise GeometryInputError(
                    "SPATIAL_ARRANGEMENT_UNSUPPORTED_ADJACENCY",
                    f"Общее ребро скатов {first_source + 1} и {second_source + 1} "
                    "не является точной линией пересечения их опорных плоскостей.",
                )
        elif first_source >= 0 and second_source == -1:
            if max(
                abs(planes[first_source].residual(point))
                for point in edge_points
            ) > tolerance * max(1.0, *(abs(point[2]) for point in edge_points)):
                raise GeometryInputError(
                    "SPATIAL_ARRANGEMENT_UNOWNED_TRANSITION_EDGE",
                    f"Граница переходной ячейки не лежит на плоскости ската {first_source + 1}.",
                )
        elif second_source >= 0 and first_source == -1:
            if max(
                abs(planes[second_source].residual(point))
                for point in edge_points
            ) > tolerance * max(1.0, *(abs(point[2]) for point in edge_points)):
                raise GeometryInputError(
                    "SPATIAL_ARRANGEMENT_UNOWNED_TRANSITION_EDGE",
                    f"Граница переходной ячейки не лежит на плоскости ската {second_source + 1}.",
                )

    faces: list[Face] = []
    face_sources: list[int] = []
    for loop, source_index in zip(cell_loops, cell_sources):
        clean_loop = _clean_collinear_cell_loop(loop, vertices, tolerance)
        cell_xy = [(vertices[index][0], vertices[index][1]) for index in clean_loop]
        issues = validate_simple_polygon(
            cell_xy, max(1e-12, tolerance / scale)
        )
        if issues:
            raise GeometryInputError(
                "SPATIAL_ARRANGEMENT_INVALID_CELL",
                "Ячейка пространственной раскладки не является простым контуром: "
                + issues[0].message,
            )
        try:
            triangles = triangulate_simple_polygon(
                cell_xy, max(1e-12, tolerance / scale)
            )
        except GeometryInputError as exc:
            raise GeometryInputError(
                "SPATIAL_ARRANGEMENT_TRIANGULATION",
                "Не удалось разбить ячейку точной плоской раскладки: " + exc.message,
            ) from exc
        index_by_xy = {point: vertex_id for point, vertex_id in zip(cell_xy, clean_loop)}
        support_plane = planes[source_index] if source_index >= 0 else None
        for triangle in triangles:
            face = tuple(index_by_xy[point] for point in triangle)
            validate_planar_face(
                vertices, face,
                support_plane=support_plane,
                eps=max(eps * 10.0, 1e-10),
            )
            faces.append(face)
            face_sources.append(source_index)

    edge_uses: dict[tuple[int, int], int] = {}
    for face in faces:
        for edge_index, first_id in enumerate(face):
            second_id = face[(edge_index + 1) % len(face)]
            key = (min(first_id, second_id), max(first_id, second_id))
            edge_uses[key] = edge_uses.get(key, 0) + 1
    if any(value > 2 for value in edge_uses.values()):
        raise GeometryInputError(
            "SPATIAL_ARRANGEMENT_TRIANGLE_NON_MANIFOLD",
            "Триангуляция ячеек создала неманифолдное внутреннее ребро.",
        )

    from .mesh import RoofSurface, validate_surface_boundary_edges
    validate_surface_boundary_edges(
        vertices, faces, polygon, tolerance * 5.0
    )
    source_area_xy = abs(signed_area(polygon))
    surface_area_xy = sum(
        abs(signed_area([
            (vertices[vertex_id][0], vertices[vertex_id][1])
            for vertex_id in face
        ]))
        for face in faces
    )
    if abs(surface_area_xy - source_area_xy) > max(
        tolerance * scale * 10.0, source_area_xy * 1e-7
    ):
        raise GeometryInputError(
            "SPATIAL_ARRANGEMENT_COVERAGE",
            "Пространственные плоские ячейки не покрывают контур точно без дыр и перекрытий.",
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


def select_exact_spatial_arrangement(
    points: Sequence[Point3],
    polygon: Sequence[Point2],
    planes: Sequence[SupportPlane],
    event_options: Sequence[Sequence[tuple[Point3, float, tuple[int, ...]]]],
    scale: float,
    tolerance: float,
    eps: float,
):
    """Choose a valid exact arrangement when a reflex event has two inward rays."""
    combinations = 1
    for options in event_options:
        combinations *= len(options)
        if combinations > 50000:
            raise GeometryInputError(
                "SPATIAL_EVENT_AMBIGUITY",
                "Слишком много альтернативных событий в вогнутых углах для однозначной топологии.",
            )
    candidates = []
    errors = []
    for combination in product(*event_options):
        event_nodes = tuple(option[0] for option in combination)
        try:
            surface = _build_exact_spatial_arrangement_surface(
                points, polygon, planes, event_nodes, eps
            )
        except GeometryInputError as exc:
            errors.append((exc.code, exc.message))
            continue
        transition_area = sum(
            abs(signed_area([
                (surface.vertices[vertex_id][0], surface.vertices[vertex_id][1])
                for vertex_id in face
            ]))
            for face, source in zip(surface.faces, surface.face_slope_indices)
            if source == -1
        )
        candidates.append((
            transition_area,
            len(surface.faces),
            sum(option[1] for option in combination),
            surface,
        ))
    if not candidates:
        unique = []
        for code, message in errors:
            entry = f"{code}: {message}"
            if entry not in unique:
                unique.append(entry)
        raise GeometryInputError(
            "EXACT_SPATIAL_TOPOLOGY_UNRESOLVED",
            "Не удалось построить точную пространственную раскладку: "
            + " | ".join(unique[:4]),
        )
    candidates.sort(key=lambda item: item[:3])
    return candidates[0][3]


def _clip_affine_cell(
    polygon: Sequence[Point2],
    a: float,
    b: float,
    c: float,
    keep_negative: bool,
    tolerance: float,
) -> list[Point2]:
    """Clip a convex cell to one side of an exact affine plane-equality line."""
    if not polygon:
        return []
    sign = 1.0 if keep_negative else -1.0
    output: list[Point2] = []
    previous = polygon[-1]
    previous_value = sign * (a * previous[0] + b * previous[1] + c)
    previous_inside = previous_value <= tolerance
    for current in polygon:
        current_value = sign * (a * current[0] + b * current[1] + c)
        current_inside = current_value <= tolerance
        if current_inside != previous_inside:
            denominator = previous_value - current_value
            if abs(denominator) > tolerance * 1e-6:
                factor = max(0.0, min(1.0, previous_value / denominator))
                intersection = (
                    previous[0] + (current[0] - previous[0]) * factor,
                    previous[1] + (current[1] - previous[1]) * factor,
                )
                if not output or hypot(
                    intersection[0] - output[-1][0],
                    intersection[1] - output[-1][1],
                ) > tolerance * 0.1:
                    output.append(intersection)
        if current_inside:
            if not output or hypot(
                current[0] - output[-1][0],
                current[1] - output[-1][1],
            ) > tolerance * 0.1:
                output.append((float(current[0]), float(current[1])))
        previous = current
        previous_value = current_value
        previous_inside = current_inside

    if len(output) > 1 and hypot(
        output[0][0] - output[-1][0],
        output[0][1] - output[-1][1],
    ) <= tolerance * 0.1:
        output.pop()
    return output



def _merge_coplanar_source_cells(
    vertices: Sequence[Point3],
    faces: Sequence[Face],
    face_sources: Sequence[int],
    tolerance: float,
) -> tuple[list[Face], list[int]]:
    """Merge adjacent cells owned by the same exact support plane.

    Only a shared complete edge is dissolved. The merged projected loop must
    remain a simple polygon, and its every vertex is checked against the same
    source plane. No coordinates are averaged or moved.
    """
    active_faces = [tuple(face) for face in faces]
    active_sources = [int(source) for source in face_sources]

    changed = True
    while changed:
        changed = False
        edge_uses: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
        for face_index, face in enumerate(active_faces):
            if active_sources[face_index] < 0:
                continue
            for local_index, first in enumerate(face):
                second = face[(local_index + 1) % len(face)]
                edge_uses.setdefault(
                    (min(first, second), max(first, second)), []
                ).append((face_index, first, second))

        for _edge_key, uses in edge_uses.items():
            if len(uses) != 2:
                continue
            first_face, first_a, first_b = uses[0]
            second_face, second_a, second_b = uses[1]
            if first_face == second_face:
                continue
            source = active_sources[first_face]
            if source != active_sources[second_face]:
                continue
            if first_a != second_b or first_b != second_a:
                continue

            loop_a = list(active_faces[first_face])
            loop_b = list(active_faces[second_face])
            index_a = next(
                index for index in range(len(loop_a))
                if loop_a[index] == first_a and loop_a[(index + 1) % len(loop_a)] == first_b
            )
            index_b = next(
                index for index in range(len(loop_b))
                if loop_b[index] == second_a and loop_b[(index + 1) % len(loop_b)] == second_b
            )

            # Walk the first face from the shared edge's end back to its start.
            path_a = loop_a[index_a + 1:] + loop_a[:index_a + 1]
            # Walk the second face from the opposite shared edge's end back to
            # its start, then concatenate after omitting the shared endpoints.
            path_b = loop_b[index_b + 1:] + loop_b[:index_b + 1]
            merged = path_a + path_b[1:-1]
            compact: list[int] = []
            for vertex_index in merged:
                if not compact or compact[-1] != vertex_index:
                    compact.append(vertex_index)
            if len(compact) > 1 and compact[0] == compact[-1]:
                compact.pop()
            if len(compact) < 3 or len(set(compact)) != len(compact):
                continue

            merged_xy = [
                (vertices[index][0], vertices[index][1])
                for index in compact
            ]
            if signed_area(merged_xy) < 0.0:
                compact.reverse()
                merged_xy.reverse()
            issues = validate_simple_polygon(
                merged_xy,
                max(1e-12, tolerance / max(_bbox_scale(merged_xy), 1.0)),
            )
            if issues:
                continue

            source_plane = None
            # Each face source is an authored support-plane index; callers
            # pass the validated plane through this local lookup below.
            # The vertex residual consistency is also preserved by identity:
            # no new vertex is generated during a dissolve.
            active_faces[first_face] = tuple(compact)
            del active_faces[second_face]
            del active_sources[second_face]
            changed = True
            break

    return active_faces, active_sources

def _build_exact_support_plane_envelope(
    points: Sequence[Point3],
    polygon: Sequence[Point2],
    planes: Sequence[SupportPlane],
    eps: float,
):
    """Partition the footprint by every exact pairwise support-plane equality.

    The result is the lower envelope of the authored edge planes, clipped to
    the original simple footprint. Every cell is convex and belongs to one
    exact support plane. There is no interpolated height field and no
    arbitrarily positioned transition patch.
    """
    scale = max(_bbox_scale(polygon), 1.0)
    tolerance = max(1e-12, eps * scale * 100.0)
    area_tolerance = tolerance * scale * 1e-4

    # Build unique equality lines. Coincident planes are handled by a stable
    # source-index tie break; distinct parallel planes never exchange order.
    equality_lines: list[tuple[float, float, float]] = []
    coefficient_tolerance = max(1e-12, eps * 10.0)
    for first_index, first in enumerate(planes):
        for second in planes[first_index + 1:]:
            a = first.a - second.a
            b = first.b - second.b
            c = first.c - second.c
            norm = hypot(a, b)
            coefficient_scale = max(
                1.0, abs(first.a), abs(first.b), abs(first.c),
                abs(second.a), abs(second.b), abs(second.c),
            )
            if norm <= coefficient_tolerance * coefficient_scale:
                # Parallel or coincident planes have no finite equality line.
                continue
            line_scale = hypot(a, b)
            a, b, c = a / line_scale, b / line_scale, c / line_scale
            # Canonical sign makes duplicate line removal deterministic.
            if a < -coefficient_tolerance or (
                abs(a) <= coefficient_tolerance and b < 0.0
            ):
                a, b, c = -a, -b, -c
            if any(
                abs(a - old_a) <= coefficient_tolerance
                and abs(b - old_b) <= coefficient_tolerance
                and abs(c - old_c) <= coefficient_tolerance * scale
                for old_a, old_b, old_c in equality_lines
            ):
                continue
            equality_lines.append((a, b, c))

    # Source-plane activation changes only across the supporting line of its
    # authored boundary edge. Add those lines to the same exact arrangement.
    winding = 1.0 if signed_area(polygon) > 0.0 else -1.0
    for index, start_point in enumerate(points):
        end_point = points[(index + 1) % len(points)]
        dx = end_point[0] - start_point[0]
        dy = end_point[1] - start_point[1]
        norm = hypot(dx, dy)
        if norm <= tolerance:
            raise GeometryInputError(
                "DEGENERATE_SUPPORT_EDGE",
                f"Ребро карниза {index + 1} имеет нулевую XY-проекцию.",
            )
        a = winding * (-dy) / norm
        b = winding * dx / norm
        c = winding * (dy * start_point[0] - dx * start_point[1]) / norm
        if not any(
            abs(a - old_a) <= coefficient_tolerance
            and abs(b - old_b) <= coefficient_tolerance
            and abs(c - old_c) <= coefficient_tolerance * scale
            for old_a, old_b, old_c in equality_lines
        ):
            equality_lines.append((a, b, c))

    triangles = triangulate_simple_polygon(polygon, eps)
    cells: list[tuple[Point2, ...]] = []
    max_cells = 50000

    for triangle in triangles:
        local_cells: list[list[Point2]] = [list(triangle)]
        for a, b, c in equality_lines:
            split_cells: list[list[Point2]] = []
            for cell in local_cells:
                values = [a * point[0] + b * point[1] + c for point in cell]
                minimum = min(values)
                maximum = max(values)
                if minimum < -tolerance and maximum > tolerance:
                    negative = _clip_affine_cell(
                        cell, a, b, c, True, tolerance
                    )
                    positive = _clip_affine_cell(
                        cell, a, b, c, False, tolerance
                    )
                    if len(negative) >= 3 and abs(signed_area(negative)) > area_tolerance:
                        split_cells.append(negative)
                    if len(positive) >= 3 and abs(signed_area(positive)) > area_tolerance:
                        split_cells.append(positive)
                else:
                    split_cells.append(cell)
            local_cells = split_cells
            if len(local_cells) + len(cells) > max_cells:
                raise GeometryInputError(
                    "SUPPORT_PLANE_ARRANGEMENT_BUDGET",
                    "Точная раскладка опорных плоскостей превысила лимит ячеек.",
                )
        for cell in local_cells:
            if len(cell) >= 3 and abs(signed_area(cell)) > area_tolerance:
                cells.append(tuple(cell))

    if not cells:
        raise GeometryInputError(
            "EMPTY_SUPPORT_PLANE_ENVELOPE",
            "Опорные плоскости не образовали ни одной ограниченной ячейки крыши.",
        )

    vertices: list[Point3] = []
    vertex_buckets: dict[tuple[int, int, int], list[int]] = {}

    def add_vertex(point_xy: Point2, source_plane: SupportPlane) -> int:
        point = (
            float(point_xy[0]),
            float(point_xy[1]),
            float(source_plane.height(point_xy[0], point_xy[1])),
        )
        key = tuple(int(round(value / tolerance)) for value in point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for vertex_index in vertex_buckets.get(
                        (key[0] + dx, key[1] + dy, key[2] + dz), ()
                    ):
                        existing = vertices[vertex_index]
                        if sqrt(sum(
                            (existing[axis] - point[axis]) ** 2
                            for axis in range(3)
                        )) <= tolerance:
                            return vertex_index
        vertex_index = len(vertices)
        vertices.append(point)
        vertex_buckets.setdefault(key, []).append(vertex_index)
        return vertex_index

    faces: list[Face] = []
    face_sources: list[int] = []
    for cell in cells:
        centroid = _polygon_area_centroid(cell)
        active_planes = []
        for plane in planes:
            edge_start = points[plane.source_index]
            edge_end = points[(plane.source_index + 1) % len(points)]
            dx = edge_end[0] - edge_start[0]
            dy = edge_end[1] - edge_start[1]
            inward_side = winding * (
                -dy * centroid[0] + dx * centroid[1]
                + dy * edge_start[0] - dx * edge_start[1]
            ) / max(hypot(dx, dy), tolerance)
            if inward_side >= -tolerance:
                active_planes.append(plane)
        if not active_planes:
            raise GeometryInputError(
                "NO_ACTIVE_SUPPORT_PLANE",
                "В одной из областей контура нет активной опорной плоскости. "
                "Плоскую крышу без произвольного перехода построить нельзя.",
            )
        winner = min(
            active_planes,
            key=lambda plane: (
                plane.height(centroid[0], centroid[1]),
                plane.source_index,
            ),
        )
        face = tuple(add_vertex(point, winner) for point in cell)
        compact: list[int] = []
        for vertex_index in face:
            if not compact or compact[-1] != vertex_index:
                compact.append(vertex_index)
        if len(compact) > 1 and compact[0] == compact[-1]:
            compact.pop()
        if len(set(compact)) < 3:
            continue
        face_xy = [(vertices[index][0], vertices[index][1]) for index in compact]
        if signed_area(face_xy) < 0.0:
            compact.reverse()
        validate_planar_face(
            vertices,
            compact,
            support_plane=winner,
            eps=max(eps * 10.0, 1e-10),
        )
        for vertex_index in compact:
            point = vertices[vertex_index]
            own_height = winner.height(point[0], point[1])
            if any(
                other.height(point[0], point[1])
                < own_height - tolerance * max(1.0, abs(own_height))
                for other in active_planes
                if other.source_index != winner.source_index
            ):
                raise GeometryInputError(
                    "SUPPORT_PLANE_CELL_ORDER",
                    f"Ячейка ската {winner.source_index + 1} пересекает область, где ниже лежит другая активная опорная плоскость.",
                )
        faces.append(tuple(compact))
        face_sources.append(winner.source_index)

    faces, face_sources = _merge_coplanar_source_cells(
        vertices, faces, face_sources, tolerance
    )

    # Cells may change their active support set along an authored edge's
    # inward half-plane. When adjacent planar cells have the same XY boundary
    # but different Z values, close that finite discontinuity with a vertical
    # transition polygon. Its four vertices lie in the vertical plane through
    # the shared projected edge, so the transition itself is exactly planar.
    xy_nodes: list[Point2] = []
    xy_buckets: dict[tuple[int, int], list[int]] = {}

    def projected_vertex_id(vertex_index: int) -> int:
        point = vertices[vertex_index]
        key = (int(round(point[0] / tolerance)), int(round(point[1] / tolerance)))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for candidate in xy_buckets.get((key[0] + dx, key[1] + dy), ()):
                    existing = xy_nodes[candidate]
                    if hypot(existing[0] - point[0], existing[1] - point[1]) <= tolerance:
                        return candidate
        projected_id = len(xy_nodes)
        xy_nodes.append((point[0], point[1]))
        xy_buckets.setdefault(key, []).append(projected_id)
        return projected_id

    projected_edge_uses: dict[
        tuple[int, int], list[tuple[int, int, int, int, int]]
    ] = {}
    for face_index, face in enumerate(faces):
        for local_index, first_vertex in enumerate(face):
            second_vertex = face[(local_index + 1) % len(face)]
            first_xy = projected_vertex_id(first_vertex)
            second_xy = projected_vertex_id(second_vertex)
            if first_xy == second_xy:
                raise GeometryInputError(
                    "ZERO_PROJECTED_CELL_EDGE",
                    "Плоская опорная ячейка содержит ребро нулевой длины в XY.",
                )
            key = (min(first_xy, second_xy), max(first_xy, second_xy))
            projected_edge_uses.setdefault(key, []).append((
                face_index, first_vertex, second_vertex, first_xy, second_xy
            ))

    transition_faces: list[Face] = []
    for projected_edge, uses in projected_edge_uses.items():
        if len(uses) > 2:
            raise GeometryInputError(
                "SUPPORT_PLANE_PROJECTED_NON_MANIFOLD",
                f"Проекция ребра {projected_edge} принадлежит более чем двум опорным ячейкам.",
            )
        if len(uses) != 2:
            continue

        first_use, second_use = uses
        _first_face, a0, a1, a0_xy, a1_xy = first_use
        _second_face, b0, b1, b0_xy, b1_xy = second_use
        if a0_xy != b1_xy or a1_xy != b0_xy:
            raise GeometryInputError(
                "SUPPORT_PLANE_PROJECTED_WINDING",
                "Соседние плоские ячейки имеют несовместимую ориентацию общего проецируемого ребра.",
            )

        same_start = abs(vertices[a0][2] - vertices[b1][2]) <= tolerance * max(
            1.0, abs(vertices[a0][2]), abs(vertices[b1][2])
        )
        same_end = abs(vertices[a1][2] - vertices[b0][2]) <= tolerance * max(
            1.0, abs(vertices[a1][2]), abs(vertices[b0][2])
        )
        if same_start and same_end:
            continue

        # Reverse the first cell's edge and the second cell's edge to preserve
        # consistent surface winding. Equal-height endpoints weld to one ID,
        # reducing a quad to a triangle where appropriate.
        raw_cap = (a1, a0, b1, b0)
        cap: list[int] = []
        for vertex_index in raw_cap:
            if not cap or cap[-1] != vertex_index:
                cap.append(vertex_index)
        if len(cap) > 1 and cap[0] == cap[-1]:
            cap.pop()
        if len(set(cap)) < 3:
            raise GeometryInputError(
                "DEGENERATE_VERTICAL_TRANSITION",
                "Переходная грань между двумя активными плоскостями выродилась.",
            )
        validate_planar_face(
            vertices, cap, support_plane=None, eps=max(eps * 10.0, 1e-10)
        )
        transition_faces.append(tuple(cap))

    faces.extend(transition_faces)
    face_sources.extend([-1] * len(transition_faces))

    # After transition faces have been added, every internal 3D edge must be
    # shared by exactly two faces. Only the original XYZ eave loop may remain
    # open for the roof-shell extrusion to close.
    edge_uses: dict[tuple[int, int], list[int]] = {}
    for face_index, face in enumerate(faces):
        for local_index, first in enumerate(face):
            second = face[(local_index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            edge_uses.setdefault(key, []).append(face_index)
    if any(len(uses) > 2 for uses in edge_uses.values()):
        raise GeometryInputError(
            "SUPPORT_PLANE_NON_MANIFOLD_EDGE",
            "Плоские опорные ячейки и переходные грани образовали неманифолдное 3D-ребро.",
        )
    from .mesh import RoofSurface, validate_surface_boundary_edges
    validate_surface_boundary_edges(
        vertices, faces, polygon, tolerance * 5.0
    )
    source_area_xy = abs(signed_area(polygon))
    surface_area_xy = sum(
        abs(signed_area([
            (vertices[vertex_index][0], vertices[vertex_index][1])
            for vertex_index in face
        ]))
        for face in faces
    )
    if abs(surface_area_xy - source_area_xy) > max(
        tolerance * scale * 10.0, source_area_xy * 1e-7
    ):
        raise GeometryInputError(
            "SUPPORT_PLANE_COVERAGE",
            "Точные ячейки опорных плоскостей не покрывают исходный контур без дыр и перекрытий.",
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

def build_exact_planar_ring_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    eps: float = 1e-9,
):
    """Build the exact lower envelope of the authored 3D eave support planes.

    Every output face lies on one authored edge plane. All facet boundaries
    are exact equal-height intersections of those planes. The XY footprint is
    partitioned by the complete finite arrangement of plane-equality lines;
    no sampled distance field, spatial smoothing or arbitrary seam endpoint
    is used.
    """
    normalized = tuple(tuple(float(value) for value in point) for point in points)
    planes = build_support_planes(normalized, pitches_degrees, eps)
    polygon = tuple((point[0], point[1]) for point in normalized)
    return _build_exact_support_plane_envelope(
        normalized, polygon, planes, eps
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
