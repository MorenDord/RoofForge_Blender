"""Experimental exact roof construction from boundary support-plane intersections.

The solver builds the lower envelope of one analytical plane per 3D eave
edge. It does not search for a central ring, fit a height field, or move
vertices away from their support planes. Finite source-edge activation keeps
a reflex edge from competing outside its authored projection interval.
"""
from __future__ import annotations

from math import isfinite
from typing import Sequence

from .geometry import GeometryInputError, _bbox_scale, signed_area
from .mesh import RoofSurface, build_roof_surface_from_planes
from .planes import boundary_envelope_conflicts, build_boundary_planes

Point3 = tuple[float, float, float]
Point2 = tuple[float, float]


def build_intersection_envelope_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    eps: float = 1e-9,
) -> RoofSurface:
    """Build a roof from exact per-edge planes and their lower-envelope seams.

    The result is accepted only when:
    * each input edge has a valid support plane at its requested pitch;
    * no competing finite source edge undercuts an authored eave segment;
    * the plane-envelope cells cover the footprint without cracks or
      non-manifold edges; and
    * every authored support plane owns at least one non-zero roof face.

    This is an experimental alternative to the spatial event/ring solver. It
    is intentionally not wired into the add-on's default generation path yet.
    """
    if len(points) < 3:
        raise GeometryInputError(
            "POLY_TOO_SMALL",
            "Контур должен содержать минимум три вершины.",
        )

    raw_points = tuple(
        tuple(float(value) for value in point)
        for point in points
    )
    if any(
        len(point) != 3 or not all(isfinite(value) for value in point)
        for point in raw_points
    ):
        raise GeometryInputError(
            "NON_FINITE",
            "Координаты 3D-контура должны быть конечными числами.",
        )
    normalized: tuple[Point3, ...] = raw_points  # type: ignore[assignment]
    domain: tuple[Point2, ...] = tuple(
        (point[0], point[1]) for point in normalized
    )

    planes = build_boundary_planes(normalized, pitches_degrees, eps)
    conflicts = boundary_envelope_conflicts(
        normalized,
        planes,
        eps,
        active_contour=normalized,
    )
    if conflicts:
        first = conflicts[0]
        raise GeometryInputError(first.code, first.message)

    area = abs(signed_area(domain))
    scale = max(
        _bbox_scale(domain),
        max(point[2] for point in normalized)
        - min(point[2] for point in normalized),
        1.0,
    )
    if area <= eps * scale * scale:
        raise GeometryInputError(
            "DEGENERATE_DOMAIN",
            "Проекция контура имеет практически нулевую площадь.",
        )

    # Cell assembly analytically clips the footprint by support-plane
    # inequalities, welds exact intersection vertices, splits T-junctions,
    # and validates domain coverage plus the outer boundary chain.
    surface = build_roof_surface_from_planes(
        domain,
        planes,
        source_area_xy=area,
        eps=eps,
        active_contour=domain,
    )

    used_sources = {
        source_index
        for source_index in surface.face_slope_indices
        if source_index >= 0
    }
    missing = sorted(set(range(len(planes))) - used_sources)
    if missing:
        raise GeometryInputError(
            "PLANE_ENVELOPE_UNUSED_SUPPORT",
            "Нижняя огибающая не сохранила области следующих заданных скатов: "
            + ", ".join(str(index + 1) for index in missing),
        )

    tolerance = max(1e-12, eps * scale * 100.0)
    for face_index, (face, source_index) in enumerate(
        zip(surface.faces, surface.face_slope_indices)
    ):
        plane = planes[source_index]
        for vertex_index in face:
            x, y, z = surface.vertices[vertex_index]
            residual = abs(z - plane.height(x, y))
            if residual > tolerance * max(1.0, abs(z)):
                raise GeometryInputError(
                    "PLANE_ENVELOPE_OFF_SUPPORT",
                    f"Вершина грани {face_index + 1} вышла из плоскости ската {source_index + 1}.",
                )

    return surface


__all__ = ["build_intersection_envelope_surface"]
