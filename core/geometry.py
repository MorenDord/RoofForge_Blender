"""Pure-Python geometry primitives for RoofForge.

This module intentionally does not import bpy or bmesh so it can be unit-tested
outside Blender. Coordinates are 2D tuples unless explicitly documented.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Sequence

Point2 = tuple[float, float]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: str = "ERROR"


@dataclass(frozen=True)
class PlaneZ:
    """Plane represented as z = ax + by + c."""
    a: float
    b: float
    c: float

    def height(self, x: float, y: float) -> float:
        return self.a * x + self.b * y + self.c


def signed_area(poly: Sequence[Point2]) -> float:
    if len(poly) < 3:
        return 0.0
    return 0.5 * sum(
        poly[i][0] * poly[(i + 1) % len(poly)][1]
        - poly[(i + 1) % len(poly)][0] * poly[i][1]
        for i in range(len(poly))
    )


def _cross(a: Point2, b: Point2, c: Point2) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(p: Point2, a: Point2, b: Point2, eps: float) -> bool:
    return (
        abs(_cross(a, b, p)) <= eps
        and min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
    )


def _segments_intersect(a: Point2, b: Point2, c: Point2, d: Point2, eps: float) -> bool:
    o1, o2 = _cross(a, b, c), _cross(a, b, d)
    o3, o4 = _cross(c, d, a), _cross(c, d, b)
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and (
        (o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)
    ):
        return True
    return (
        _on_segment(c, a, b, eps) or _on_segment(d, a, b, eps)
        or _on_segment(a, c, d, eps) or _on_segment(b, c, d, eps)
    )


def validate_simple_polygon(poly: Sequence[Point2], eps: float = 1e-9) -> list[Diagnostic]:
    issues: list[Diagnostic] = []
    if len(poly) < 3:
        return [Diagnostic("POLY_TOO_SMALL", "Контур должен содержать минимум 3 вершины.")]
    if any(not (isfinite(x) and isfinite(y)) for x, y in poly):
        issues.append(Diagnostic("NON_FINITE", "Контур содержит NaN или бесконечные координаты."))
        return issues
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        if (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 <= eps * eps:
            issues.append(Diagnostic("ZERO_EDGE", f"Ребро {i} имеет нулевую длину."))
    if abs(signed_area(poly)) <= eps:
        issues.append(Diagnostic("ZERO_AREA", "Площадь контура практически равна нулю."))
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or j == (i + 1) % n or (j + 1) % n == i:
                continue
            c, d = poly[j], poly[(j + 1) % n]
            if _segments_intersect(a, b, c, d, eps):
                issues.append(Diagnostic("SELF_INTERSECTION", f"Рёбра {i} и {j} пересекаются."))
    return issues


def clip_half_plane(poly: Sequence[Point2], a: float, b: float, c: float,
                    eps: float = 1e-9) -> list[Point2]:
    """Clip polygon by a*x + b*y + c <= 0 using Sutherland-Hodgman."""
    if not poly:
        return []
    result: list[Point2] = []
    for i, current in enumerate(poly):
        previous = poly[i - 1]
        fp = a * previous[0] + b * previous[1] + c
        fc = a * current[0] + b * current[1] + c
        pin, cin = fp <= eps, fc <= eps
        if pin != cin:
            denom = fp - fc
            if abs(denom) > eps:
                t = fp / denom
                result.append((
                    previous[0] + t * (current[0] - previous[0]),
                    previous[1] + t * (current[1] - previous[1]),
                ))
        if cin:
            result.append(current)
    return result


def lower_envelope_regions(domain: Sequence[Point2], planes: Sequence[PlaneZ],
                           eps: float = 1e-9) -> list[list[Point2]]:
    """Return one clipped polygon per plane where that plane is <= all others.

    This routine assumes the domain is convex. Concave domains must be
    decomposed by a constrained triangulator before clipping.
    """
    regions: list[list[Point2]] = []
    for i, plane in enumerate(planes):
        cell = list(domain)
        for j, other in enumerate(planes):
            if i == j:
                continue
            # z_i - z_j <= 0
            cell = clip_half_plane(
                cell, plane.a - other.a, plane.b - other.b, plane.c - other.c, eps
            )
            if len(cell) < 3:
                cell = []
                break
        regions.append(cell)
    return regions
