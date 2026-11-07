"""Lower-envelope partitioning for convex and concave roof domains."""
from __future__ import annotations

from math import hypot
from typing import Sequence

from .geometry import (
    GeometryInputError,
    PlaneZ,
    _bbox_scale,
    clip_half_plane,
    lower_envelope_cells,
    lower_envelope_regions,
    signed_area,
    triangulate_simple_polygon,
)

Point2 = tuple[float, float]


def _point_on_segment(point: Point2, start: Point2, end: Point2, tolerance: float) -> bool:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= tolerance * tolerance:
        return hypot(point[0] - start[0], point[1] - start[1]) <= tolerance
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    if t < -tolerance or t > 1.0 + tolerance:
        return False
    projection = (start[0] + t * dx, start[1] + t * dy)
    return hypot(point[0] - projection[0], point[1] - projection[1]) <= tolerance


def _point_in_polygon(point: Point2, polygon: Sequence[Point2], tolerance: float) -> bool:
    x, y = point
    inside = False
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _point_on_segment(point, start, end, tolerance):
            return True
        if (start[1] > y) != (end[1] > y):
            crossing = start[0] + (y - start[1]) * (end[0] - start[0]) / (end[1] - start[1])
            if x < crossing:
                inside = not inside
    return inside


def _closest_boundary_point(point: Point2, polygon: Sequence[Point2]) -> Point2:
    best = polygon[0]
    best_distance = float("inf")
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= 1.0e-24:
            candidate = start
        else:
            t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq))
            candidate = (start[0] + t * dx, start[1] + t * dy)
        distance = hypot(point[0] - candidate[0], point[1] - candidate[1])
        if distance < best_distance:
            best, best_distance = candidate, distance
    return best


def lower_envelope_restricted_cells(
    domain: Sequence[Point2],
    planes: Sequence[PlaneZ],
    eps: float = 1e-9,
    *,
    active_contour: Sequence[Point2] | None = None,
) -> list[list[list[Point2]]]:
    """Compute a lower envelope using the original contour's active halfspaces.

    The domain polygon may be an expanded eave contour. The optional active
    contour is the authored polygon whose edges own the planes. At points
    inside it, active planes are selected from that point. At points in the
    exterior overhang band, the active set is sampled at the closest point on
    the authored contour. This prevents a shifted reflex edge from allowing
    its plane to undercut a neighbouring region still inside the original
    roof, while continuing that plane outwards from its own eave.
    """
    support = tuple(domain if active_contour is None else active_contour)
    if len(domain) < 3 or len(support) != len(planes):
        raise GeometryInputError("PLANE_COUNT", "Для каждого ребра контура нужна одна плоскость ската.")
    triangles = triangulate_simple_polygon(domain, eps)
    output: list[list[list[Point2]]] = [[] for _ in planes]
    winding = 1.0 if signed_area(support) > 0.0 else -1.0
    scale = max(_bbox_scale(domain), _bbox_scale(support), 1.0)
    area_eps = eps * scale * scale
    point_tolerance = eps * scale * 20.0

    edge_lines: list[tuple[float, float, float, float]] = []
    for index, start in enumerate(support):
        end = support[(index + 1) % len(support)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        edge_length = hypot(dx, dy)
        if edge_length <= eps * scale:
            raise GeometryInputError("DEGENERATE_EDGE", f"Ребро {index + 1} исходного контура имеет нулевую длину.")
        a = winding * -dy
        b = winding * dx
        c = winding * (dy * start[0] - dx * start[1])
        edge_lines.append((a, b, c, edge_length))

    for triangle in triangles:
        arrangement_cells: list[list[Point2]] = [list(triangle)]
        for a, b, c, edge_length in edge_lines:
            function_eps = eps * scale * edge_length
            next_cells: list[list[Point2]] = []
            for cell in arrangement_cells:
                inside = clip_half_plane(cell, -a, -b, -c, function_eps)
                outside = clip_half_plane(cell, a, b, c, function_eps)
                inside_valid = len(inside) >= 3 and abs(signed_area(inside)) > area_eps
                outside_valid = len(outside) >= 3 and abs(signed_area(outside)) > area_eps
                if inside_valid and outside_valid:
                    next_cells.extend((inside, outside))
                elif inside_valid:
                    next_cells.append(inside)
                elif outside_valid:
                    next_cells.append(outside)
            arrangement_cells = next_cells
            if not arrangement_cells:
                break

        for cell in arrangement_cells:
            centroid = (
                sum(point[0] for point in cell) / len(cell),
                sum(point[1] for point in cell) / len(cell),
            )
            sample = (
                centroid if _point_in_polygon(centroid, support, point_tolerance)
                else _closest_boundary_point(centroid, support)
            )
            active = [
                index for index, (a, b, c, edge_length) in enumerate(edge_lines)
                if a * sample[0] + b * sample[1] + c >= -eps * scale * edge_length
            ]
            if not active:
                raise GeometryInputError(
                    "NO_ACTIVE_SLOPE",
                    "В расширенной области найдена ячейка без активной исходной плоскости ската."
                )

            local_regions = lower_envelope_regions(cell, [planes[index] for index in active], eps)
            for local_index, region in enumerate(local_regions):
                if len(region) >= 3 and abs(signed_area(region)) > area_eps:
                    output[active[local_index]].append(region)

    return output


__all__ = [
    "GeometryInputError",
    "PlaneZ",
    "lower_envelope_cells",
    "lower_envelope_regions",
    "lower_envelope_restricted_cells",
    "triangulate_simple_polygon",
]
