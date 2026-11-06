"""Roof surface mesh assembly from plane-envelope cells."""
from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Sequence

from .geometry import GeometryInputError, PlaneZ, signed_area
from .planes import boundary_envelope_conflicts, build_boundary_planes
from .envelope import lower_envelope_restricted_cells

Point3 = tuple[float, float, float]
Face = tuple[int, ...]


@dataclass(frozen=True)
class RoofSurface:
    """Open upper roof surface; thickness and eaves are later build stages."""
    vertices: tuple[Point3, ...]
    faces: tuple[Face, ...]
    face_slope_indices: tuple[int, ...]
    planes: tuple[PlaneZ, ...]
    source_area_xy: float
    surface_area_xy: float

    @property
    def is_empty(self) -> bool:
        return not self.faces


class _VertexRegistry:
    """Deterministic 3D vertex welding with a scale-aware spatial hash."""

    def __init__(self, tolerance: float):
        self.tolerance = tolerance
        self.vertices: list[Point3] = []
        self.buckets: dict[tuple[int, int, int], list[int]] = {}

    def _key(self, point: Point3) -> tuple[int, int, int]:
        return tuple(floor(value / self.tolerance) for value in point)

    def add(self, point: Point3) -> int:
        key = self._key(point)
        tol_sq = self.tolerance * self.tolerance
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    nearby = self.buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ())
                    for index in nearby:
                        existing = self.vertices[index]
                        distance_sq = sum((existing[i] - point[i]) ** 2 for i in range(3))
                        if distance_sq <= tol_sq:
                            return index
        index = len(self.vertices)
        self.vertices.append(point)
        self.buckets.setdefault(key, []).append(index)
        return index


def _mesh_edge_usage(faces: Sequence[Face]) -> dict[tuple[int, int], int]:
    usage: dict[tuple[int, int], int] = {}
    for face in faces:
        for index, first in enumerate(face):
            second = face[(index + 1) % len(face)]
            edge = (min(first, second), max(first, second))
            usage[edge] = usage.get(edge, 0) + 1
    return usage


def build_roof_surface(points: Sequence[Point3], pitches_degrees: Sequence[float],
                       eps: float = 1e-9) -> RoofSurface:
    """Build an open planar upper surface from a closed 3D boundary loop.

    The function does not create Blender datablocks. It returns welded vertex
    and polygon arrays ready for an adapter. The source contour is never
    modified. Concave contours are partitioned by the valid halfspace of each
    source edge before the lower envelope is evaluated.
    """
    planes = build_boundary_planes(points, pitches_degrees, eps)
    conflicts = boundary_envelope_conflicts(points, planes)
    if conflicts:
        raise GeometryInputError(conflicts[0].code, conflicts[0].message)

    domain = [(point[0], point[1]) for point in points]
    domain_area = abs(signed_area(domain))
    scale = max(
        1.0,
        max(point[0] for point in points) - min(point[0] for point in points),
        max(point[1] for point in points) - min(point[1] for point in points),
        max(point[2] for point in points) - min(point[2] for point in points),
    )
    weld_tolerance = max(1e-12, eps * scale * 100.0)
    area_tolerance = eps * scale * scale

    cells_by_slope = lower_envelope_restricted_cells(domain, planes, eps)
    registry = _VertexRegistry(weld_tolerance)
    faces: list[Face] = []
    face_slope_indices: list[int] = []
    face_keys: set[tuple[int, ...]] = set()

    for slope_index, cells in enumerate(cells_by_slope):
        plane = planes[slope_index]
        for cell in cells:
            if len(cell) < 3 or abs(signed_area(cell)) <= area_tolerance:
                continue
            face_indices = [
                registry.add((x, y, plane.height(x, y)))
                for x, y in cell
            ]
            compact: list[int] = []
            for vertex_index in face_indices:
                if not compact or compact[-1] != vertex_index:
                    compact.append(vertex_index)
            if len(compact) > 1 and compact[0] == compact[-1]:
                compact.pop()
            if len(set(compact)) < 3:
                continue
            key = tuple(sorted(compact))
            if key in face_keys:
                continue
            face_keys.add(key)
            faces.append(tuple(compact))
            face_slope_indices.append(slope_index)

    if not faces:
        raise GeometryInputError("EMPTY_ROOF", "Нижняя огибающая не создала ни одной области крыши.")

    surface_area_xy = sum(
        abs(signed_area([(registry.vertices[i][0], registry.vertices[i][1]) for i in face]))
        for face in faces
    )
    if abs(surface_area_xy - domain_area) > max(area_tolerance * 100.0, domain_area * 1e-7):
        raise GeometryInputError(
            "DOMAIN_COVERAGE_MISMATCH",
            f"Области крыши покрывают {surface_area_xy:.9g} м² из {domain_area:.9g} м² контура."
        )

    edge_usage = _mesh_edge_usage(faces)
    non_manifold_edges = [edge for edge, count in edge_usage.items() if count > 2]
    if non_manifold_edges:
        raise GeometryInputError(
            "NON_MANIFOLD_SURFACE",
            f"При сборке поверхности обнаружено рёбер с более чем двумя гранями: {len(non_manifold_edges)}."
        )

    return RoofSurface(
        vertices=tuple(registry.vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(face_slope_indices),
        planes=tuple(planes),
        source_area_xy=domain_area,
        surface_area_xy=surface_area_xy,
    )
