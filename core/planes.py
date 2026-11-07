"""Roof slope plane construction helpers and edge-activity diagnostics."""
from __future__ import annotations

from math import hypot
from typing import Sequence

from .geometry import (
    Diagnostic,
    GeometryInputError,
    PlaneZ,
    _bbox_scale,
    build_boundary_planes,
    plane_from_boundary_edge,
    signed_area,
)

Point3 = tuple[float, float, float]


def boundary_envelope_conflicts(
    points: Sequence[Point3],
    planes: Sequence[PlaneZ],
    eps: float = 1e-8,
    *,
    active_contour: Sequence[Point3] | None = None,
) -> list[Diagnostic]:
    """Check support edges against source planes.

    The default path preserves the established halfspace validation for normal
    roof generation. Source-anchored overhangs use finite segment projections
    so the infinite extensions of reflex edges cannot undercut another eave.
    """
    active_points = points if active_contour is None else active_contour
    if len(points) != len(planes) or len(active_points) != len(planes):
        return [Diagnostic("PLANE_COUNT", "Для каждого ребра контура должна быть построена своя плоскость.")]
    polygon_xy = [(point[0], point[1]) for point in active_points]
    winding = 1.0 if signed_area(polygon_xy) > 0.0 else -1.0
    scale = max(_bbox_scale(polygon_xy), 1.0)
    z_tol = eps * scale
    diagnostics: list[Diagnostic] = []

    for edge_index, start in enumerate(points):
        end = points[(edge_index + 1) % len(points)]
        own = planes[edge_index]
        for other_index, other in enumerate(planes):
            if other_index == edge_index:
                continue
            other_start = active_points[other_index]
            other_end = active_points[(other_index + 1) % len(active_points)]
            ox, oy = other_end[0] - other_start[0], other_end[1] - other_start[1]
            length_sq = ox * ox + oy * oy
            if length_sq <= (eps * scale) ** 2:
                continue

            if active_contour is None:
                # Historical validation used the inward halfspace of each
                # source edge. Leave this untouched for zero-overhang roofs.
                line_a, line_b = winding * -oy, winding * ox
                line_c = winding * (oy * other_start[0] - ox * other_start[1])
                side_tol = eps * scale * hypot(ox, oy)

                def active_at(t: float) -> bool:
                    x = start[0] + (end[0] - start[0]) * t
                    y = start[1] + (end[1] - start[1]) * t
                    return line_a * x + line_b * y + line_c >= -side_tol

                checks = (0.0, 0.5, 1.0)
                active_checks = checks
                if not any(active_at(t) for t in checks):
                    continue
            else:
                def projection_at(t: float) -> float:
                    x = start[0] + (end[0] - start[0]) * t
                    y = start[1] + (end[1] - start[1]) * t
                    return ((x - other_start[0]) * ox + (y - other_start[1]) * oy) / length_sq

                p0, p1 = projection_at(0.0), projection_at(1.0)
                breaks = [0.0, 1.0]
                delta = p1 - p0
                if abs(delta) > eps:
                    for boundary in (0.0, 1.0):
                        crossing = (boundary - p0) / delta
                        if 0.0 < crossing < 1.0:
                            breaks.append(crossing)
                breaks.sort()
                intervals = [
                    (t0, t1)
                    for t0, t1 in zip(breaks, breaks[1:])
                    if eps < projection_at((t0 + t1) * 0.5) < 1.0 - eps
                ]
                if not intervals:
                    continue
                active_checks = tuple(
                    value for t0, t1 in intervals for value in (t0, (t0 + t1) * 0.5, t1)
                )

            undercut = False
            for t in active_checks:
                x = start[0] + (end[0] - start[0]) * t
                y = start[1] + (end[1] - start[1]) * t
                if other.height(x, y) - own.height(x, y) < -z_tol:
                    undercut = True
                    break
            if undercut:
                diagnostics.append(Diagnostic(
                    "BOUNDARY_UNDERCUT",
                    f"Плоскость ската {other_index + 1} опускается ниже карниза ската {edge_index + 1}.",
                    "ERROR"
                ))
                break
    return diagnostics


__all__ = [
    "GeometryInputError",
    "PlaneZ",
    "build_boundary_planes",
    "plane_from_boundary_edge",
    "boundary_envelope_conflicts",
]
