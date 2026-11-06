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


def lower_envelope_restricted_cells(domain: Sequence[Point2], planes: Sequence[PlaneZ],
                                    eps: float = 1e-9) -> list[list[list[Point2]]]:
    """Compute a lower envelope while restricting each plane to its edge halfspace.

    For a concave polygon, an infinite plane extension can cut through a remote
    part of the contour. This function subdivides the domain by every source
    edge's supporting line. Within each convex arrangement cell, only planes
    whose inward halfspace contains the cell are allowed to compete.
    """
    if len(domain) != len(planes):
        raise GeometryInputError("PLANE_COUNT", "Для каждого ребра контура нужна одна плоскость ската.")
    triangles = triangulate_simple_polygon(domain, eps)
    output: list[list[list[Point2]]] = [[] for _ in planes]
    winding = 1.0 if signed_area(domain) > 0.0 else -1.0
    scale = _bbox_scale(domain)
    area_eps = eps * scale * scale

    edge_lines: list[tuple[float, float, float, float]] = []
    for index, start in enumerate(domain):
        end = domain[(index + 1) % len(domain)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        edge_length = hypot(dx, dy)
        # f(x,y) >= 0 is the polygon-interior side of the directed edge.
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
            active = [
                index for index, (a, b, c, edge_length) in enumerate(edge_lines)
                if a * centroid[0] + b * centroid[1] + c >= -eps * scale * edge_length
            ]
            if not active:
                raise GeometryInputError(
                    "NO_ACTIVE_SLOPE",
                    "Внутри контура найдена область, в которой нет активной плоскости ската."
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
