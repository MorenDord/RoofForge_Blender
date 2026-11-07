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
    """Check whether another finite source-edge plane undercuts an eave.

    A competing edge plane is active only while the orthogonal projection of
    the inspected point lies on that finite edge segment. This avoids treating
    the infinite extension of a reflex edge as a roof face across a notch.
    """
    active_points = points if active_contour is None else active_contour
    if len(points) != len(planes) or len(active_points) != len(planes):
        return [Diagnostic("PLANE_COUNT", "Для каждого ребра контура должна быть построена своя плоскость.")]

    scale = max(_bbox_scale([(p[0], p[1]) for p in active_points]), 1.0)
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
            dx = other_end[0] - other_start[0]
            dy = other_end[1] - other_start[1]
            length_sq = dx * dx + dy * dy
            if length_sq <= (eps * scale) ** 2:
                continue

            def projection_at(t: float) -> float:
                x = start[0] + (end[0] - start[0]) * t
                y = start[1] + (end[1] - start[1]) * t
                return ((x - other_start[0]) * dx + (y - other_start[1]) * dy) / length_sq

            p0, p1 = projection_at(0.0), projection_at(1.0)
            breaks = [0.0, 1.0]
            delta = p1 - p0
            if abs(delta) > eps:
                for boundary in (0.0, 1.0):
                    crossing = (boundary - p0) / delta
                    if 0.0 < crossing < 1.0:
                        breaks.append(crossing)
            breaks.sort()

            for t0, t1 in zip(breaks, breaks[1:]):
                midpoint_projection = projection_at((t0 + t1) * 0.5)
                # A perpendicular through an endpoint is not an infinite
                # extension of that finite eave. Adjacent slopes are allowed
                # together only in the local vertex transition region.
                if not (eps < midpoint_projection < 1.0 - eps):
                    continue
                undercut = False
                for t in (t0, t1):
                    x = start[0] + (end[0] - start[0]) * t
                    y = start[1] + (end[1] - start[1]) * t
                    if other.height(x, y) - own.height(x, y) < -z_tol:
                        undercut = True
                        break
                if undercut:
                    diagnostics.append(Diagnostic(
                        "BOUNDARY_UNDERCUT",
                        f"Плоскость ската {other_index + 1} опускается ниже карниза ската {edge_index + 1} на конечном участке своего ребра.",
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
