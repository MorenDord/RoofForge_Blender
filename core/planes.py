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


def boundary_envelope_conflicts(points: Sequence[Point3], planes: Sequence[PlaneZ],
                                eps: float = 1e-8) -> list[Diagnostic]:
    """Report eave undercuts only from planes whose inward edge halfspace is active."""
    if len(points) != len(planes):
        return [Diagnostic("PLANE_COUNT", "Для каждого ребра контура должна быть построена своя плоскость.")]
    polygon_xy = [(point[0], point[1]) for point in points]
    winding = 1.0 if signed_area(polygon_xy) > 0.0 else -1.0
    scale = _bbox_scale(polygon_xy)
    z_tol = eps * scale
    diagnostics: list[Diagnostic] = []

    for edge_index, start in enumerate(points):
        end = points[(edge_index + 1) % len(points)]
        own = planes[edge_index]
        for other_index, other in enumerate(planes):
            if other_index == edge_index:
                continue
            other_start = points[other_index]
            other_end = points[(other_index + 1) % len(points)]
            ox, oy = other_end[0] - other_start[0], other_end[1] - other_start[1]
            line_a, line_b = winding * -oy, winding * ox
            line_c = winding * (oy * other_start[0] - ox * other_start[1])
            side_tol = eps * scale * hypot(ox, oy)

            def side_at(t: float) -> float:
                x = start[0] + (end[0] - start[0]) * t
                y = start[1] + (end[1] - start[1]) * t
                return line_a * x + line_b * y + line_c

            side0, side1 = side_at(0.0), side_at(1.0)
            breaks = [0.0, 1.0]
            delta = side1 - side0
            if abs(delta) > side_tol:
                crossing = (-side_tol - side0) / delta
                if 0.0 < crossing < 1.0:
                    breaks.append(crossing)
            breaks.sort()

            for t0, t1 in zip(breaks, breaks[1:]):
                if side_at((t0 + t1) * 0.5) < -side_tol:
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
                        f"Плоскость ската {other_index + 1} опускается ниже карниза ската {edge_index + 1} в области пересечения их внутренних полуплоскостей.",
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
