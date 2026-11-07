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
    """Compute a lower envelope with finite source-edge influence regions.

    A source plane competes where the orthogonal projection onto its finite
    authored edge lies between the edge endpoints. Supporting-edge lines and
    the perpendicular endpoint lines partition the domain into cells where
    that candidate set is constant. For the overhang corner wedges, where no
    segment projection is valid, the two planes incident to the nearest source
    vertex are allowed to meet and form the corner transition.
    """
    support = tuple(domain if active_contour is None else active_contour)
    if len(domain) < 3 or len(support) != len(planes):
        raise GeometryInputError("PLANE_COUNT", "Для каждого ребра контура нужна одна плоскость ската.")
    triangles = triangulate_simple_polygon(domain, eps)
    output: list[list[list[Point2]]] = [[] for _ in planes]
    scale = max(_bbox_scale(domain), _bbox_scale(support), 1.0)
    area_eps = eps * scale * scale
    point_tolerance = eps * scale * 20.0

    edge_data: list[tuple[float, float, float, float, float, float]] = []
    for index, start in enumerate(support):
        end = support[(index + 1) % len(support)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_sq = dx * dx + dy * dy
        length = length_sq ** 0.5
        if length <= eps * scale:
            raise GeometryInputError("DEGENERATE_EDGE", f"Ребро {index + 1} исходного контура имеет нулевую длину.")
        edge_data.append((start[0], start[1], dx, dy, length_sq, length))

    def split_cells(cells, a, b, c_line):
        function_eps = eps * scale * hypot(a, b)
        next_cells = []
        for cell in cells:
            negative = clip_half_plane(cell, -a, -b, -c_line, function_eps)
            positive = clip_half_plane(cell, a, b, c_line, function_eps)
            negative_valid = len(negative) >= 3 and abs(signed_area(negative)) > area_eps
            positive_valid = len(positive) >= 3 and abs(signed_area(positive)) > area_eps
            if negative_valid and positive_valid:
                next_cells.extend((negative, positive))
            elif negative_valid:
                next_cells.append(negative)
            elif positive_valid:
                next_cells.append(positive)
        return next_cells

    for triangle in triangles:
        arrangement_cells = [list(triangle)]
        for index, (sx, sy, dx, dy, length_sq, length) in enumerate(edge_data):
            # Edge support line, then the two lines where projection onto the
            # finite edge enters and leaves its [0, 1] parameter interval.
            a, b, c_line = -dy, dx, dy * sx - dx * sy
            arrangement_cells = split_cells(arrangement_cells, a, b, c_line)
            arrangement_cells = split_cells(
                arrangement_cells, dx, dy, -(dx * sx + dy * sy)
            )
            ex, ey = sx + dx, sy + dy
            arrangement_cells = split_cells(
                arrangement_cells, dx, dy, -(dx * ex + dy * ey)
            )
            if not arrangement_cells:
                break

        # Miter connectors partition the exterior around corners into
        # stable vertex-transition wedges.
        if active_contour is not None and len(domain) == len(support):
            for index, (sx, sy, _dx, _dy, _length_sq, _length) in enumerate(edge_data):
                ex, ey = domain[index]
                dx, dy = ex - sx, ey - sy
                if hypot(dx, dy) <= point_tolerance:
                    continue
                arrangement_cells = split_cells(
                    arrangement_cells, -dy, dx, dy * sx - dx * sy
                )
                if not arrangement_cells:
                    break

        for cell in arrangement_cells:
            sample = (
                sum(point[0] for point in cell) / len(cell),
                sum(point[1] for point in cell) / len(cell),
            )
            active = []
            for index, (sx, sy, dx, dy, length_sq, _length) in enumerate(edge_data):
                projection = (
                    (sample[0] - sx) * dx + (sample[1] - sy) * dy
                ) / length_sq
                if point_tolerance < projection < 1.0 - point_tolerance:
                    active.append(index)

            if not active:
                nearest_vertex = min(
                    range(len(support)),
                    key=lambda index: (
                        (sample[0] - support[index][0]) ** 2
                        + (sample[1] - support[index][1]) ** 2
                    ),
                )
                active = [
                    (nearest_vertex - 1) % len(support),
                    nearest_vertex,
                ]

            local_regions = lower_envelope_regions(
                cell, [planes[index] for index in active], eps
            )
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
