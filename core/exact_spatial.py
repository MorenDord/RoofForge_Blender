"""Exact 3D support-plane and junction primitives for spatial roof construction.

This module is deliberately independent of the historical spatial solvers and
of height-field approximation. It only creates exact support planes, exact
pairwise intersections and planar junction patches. A topology builder may
compose these primitives, but may not move a point off its defining plane.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite, radians, sqrt, tan
from typing import Sequence

from .geometry import (
    GeometryInputError,
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
