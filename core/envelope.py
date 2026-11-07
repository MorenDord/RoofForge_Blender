"""Lower-envelope partitioning for convex and concave roof domains."""
from __future__ import annotations

from math import hypot, isfinite
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


def lower_envelope_restricted_cells(
    domain: Sequence[Point2],
    planes: Sequence[PlaneZ],
    eps: float = 1e-9,
    *,
    activation_boundary: Sequence[Point2] | None = None,
    exterior_distance: float = 0.0,
) -> list[list[list[Point2]]]:
    """Compute a lower envelope with edge-local support-plane activation.

    activation_boundary maps one support plane to each original eave edge.
    domain may be a polygon offset outward from that contour. With a positive
    exterior_distance, an edge's support plane remains eligible in the outward
    band up to that distance. The extended domain is subdivided by these
    expanded edge halfspaces so neighbouring planes meet at their true
    intersection rather than at guessed corner vertices. Concave domains use
    the same arrangement logic.
    """
    if not isfinite(exterior_distance) or exterior_distance < 0.0:
        raise GeometryInputError(
            "INVALID_EXTERIOR_DISTANCE",
            "Расстояние расширения огибающей должно быть конечным и неотрицательным.",
        )
    if activation_boundary is None:
        activation_boundary = domain
    if len(activation_boundary) != len(planes):
        raise GeometryInputError(
            "PLANE_COUNT",
            "Для каждого исходного ребра контура нужна одна плоскость ската.",
        )
    triangles = triangulate_simple_polygon(domain, eps)
    output: list[list[list[Point2]]] = [[] for _ in planes]
    winding = 1.0 if signed_area(activation_boundary) > 0.0 else -1.0
    scale = max(_bbox_scale(domain), _bbox_scale(activation_boundary))
    area_eps = eps * scale * scale

    edge_lines: list[tuple[float, float, float, float, float]] = []
    for index, start in enumerate(activation_boundary):
        end = activation_boundary[(index + 1) % len(activation_boundary)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        edge_length = hypot(dx, dy)
        if edge_length <= eps * scale:
            raise GeometryInputError(
                "ZERO_LENGTH_ACTIVATION_EDGE",
                f"Исходное ребро {index + 1} имеет нулевую длину.",
            )
        # f(x,y) >= 0 is the polygon-interior side. The expanded support
        # region is f(x,y) >= -exterior_distance * edge_length.
        a = winding * -dy
        b = winding * dx
        c = winding * (dy * start[0] - dx * start[1])
        margin = exterior_distance * edge_length
        edge_lines.append((a, b, c, edge_length, margin))

    for triangle in triangles:
        arrangement_cells: list[list[Point2]] = [list(triangle)]
        for a, b, c, edge_length, margin in edge_lines:
            function_eps = eps * scale * edge_length
            threshold_c = c + margin
            next_cells: list[list[Point2]] = []
            for cell in arrangement_cells:
                inside = clip_half_plane(
                    cell, -a, -b, -threshold_c, function_eps
                )
                outside = clip_half_plane(
                    cell, a, b, threshold_c, function_eps
                )
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
                index
                for index, (a, b, c, edge_length, margin) in enumerate(edge_lines)
                if (
                    a * centroid[0] + b * centroid[1] + c
                    >= -margin - eps * scale * edge_length
                )
            ]
            if not active:
                raise GeometryInputError(
                    "NO_ACTIVE_SLOPE",
                    "В расширенном контуре найдена область, в которой нет активной плоскости ската. "
                    "Попробуй уменьшить свес или проверь расстояние между рёбрами.",
                )

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
