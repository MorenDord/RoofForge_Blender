"""Vertical-Z solid shell generation for RoofForge surfaces.

The roof surface remains an immutable input. Thickness is created by copying
all vertices downward along the roof-local global Z axis, not along normals.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Sequence

from .geometry import GeometryInputError
from .mesh import RoofSurface, _mesh_edge_usage

Point3 = tuple[float, float, float]
Face = tuple[int, ...]


@dataclass(frozen=True)
class RoofShell:
    """Closed mesh payload split into top, bottom and boundary-wall faces."""
    vertices: tuple[Point3, ...]
    faces: tuple[Face, ...]
    top_face_count: int
    bottom_face_count: int
    side_face_count: int
    thickness: float


def _point_on_segment(point: tuple[float, float], start: tuple[float, float],
                      end: tuple[float, float], tolerance: float) -> bool:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy)
    if length <= tolerance:
        return False
    px, py = point[0] - start[0], point[1] - start[1]
    cross_distance = abs(dx * py - dy * px) / length
    if cross_distance > tolerance:
        return False
    projection = (px * dx + py * dy) / (length * length)
    margin = tolerance / length
    return -margin <= projection <= 1.0 + margin


def build_roof_shell(surface: RoofSurface, thickness: float,
                     eps: float = 1e-9) -> RoofShell:
    """Create a closed shell by extruding the top surface globally along -Z.

    All single-use top-surface edges must lie on the original boundary loop.
    Their projected lengths must fully cover every original boundary segment;
    this catches internal cracks that a simple edge-use-count test would miss.
    """
    if not isfinite(thickness) or thickness <= 0.0:
        raise GeometryInputError("INVALID_THICKNESS", "Толщина крыши должна быть положительным конечным числом.")
    if not surface.vertices or not surface.faces:
        raise GeometryInputError("EMPTY_SURFACE", "Нельзя создать оболочку из пустой поверхности.")
    if len(surface.face_slope_indices) != len(surface.faces):
        raise GeometryInputError("FACE_METADATA_MISMATCH", "Количество идентификаторов скатов не совпадает с количеством граней.")
    boundary = getattr(surface, "boundary_xy", ())
    if len(boundary) < 3:
        raise GeometryInputError("MISSING_BOUNDARY", "Поверхность не содержит исходный контур для проверки карнизов.")

    scale = max(
        1.0,
        max(v[0] for v in surface.vertices) - min(v[0] for v in surface.vertices),
        max(v[1] for v in surface.vertices) - min(v[1] for v in surface.vertices),
        max(v[2] for v in surface.vertices) - min(v[2] for v in surface.vertices),
        thickness,
    )
    tolerance = max(1e-12, eps * scale * 100.0)

    directed_uses: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for face in surface.faces:
        if len(face) < 3:
            raise GeometryInputError("DEGENERATE_FACE", "Поверхность содержит грань менее чем с тремя вершинами.")
        for index, first in enumerate(face):
            second = face[(index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            directed_uses.setdefault(key, []).append((first, second))

    open_edges: list[tuple[int, int]] = []
    for key, uses in directed_uses.items():
        if len(uses) > 2:
            raise GeometryInputError("NON_MANIFOLD_SURFACE", f"Верхняя поверхность имеет ребро с {len(uses)} смежными гранями.")
        if len(uses) == 1:
            open_edges.append(uses[0])

    if not open_edges:
        raise GeometryInputError("MISSING_BOUNDARY_EDGES", "Не найдены открытые рёбра карниза.")

    covered_lengths = [0.0 for _ in boundary]
    for first, second in open_edges:
        p = surface.vertices[first]
        q = surface.vertices[second]
        matching_segments = []
        for index, start in enumerate(boundary):
            end = boundary[(index + 1) % len(boundary)]
            if (_point_on_segment((p[0], p[1]), start, end, tolerance)
                    and _point_on_segment((q[0], q[1]), start, end, tolerance)):
                matching_segments.append(index)
        if len(matching_segments) != 1:
            raise GeometryInputError(
                "INTERNAL_OPEN_EDGE",
                f"Открытое ребро ({p[0]:.9g}, {p[1]:.9g}) → ({q[0]:.9g}, {q[1]:.9g}) не сопоставлено с единственным сегментом контура (совпадений: {len(matching_segments)})."
            )
        segment_index = matching_segments[0]
        covered_lengths[segment_index] += hypot(q[0] - p[0], q[1] - p[1])

    for index, start in enumerate(boundary):
        end = boundary[(index + 1) % len(boundary)]
        expected = hypot(end[0] - start[0], end[1] - start[1])
        allowed_error = max(tolerance * 10.0, expected * 1e-7)
        if abs(covered_lengths[index] - expected) > allowed_error:
            raise GeometryInputError(
                "BOUNDARY_COVERAGE_MISMATCH",
                f"Карнизное ребро {index + 1}: покрыто {covered_lengths[index]:.9g} из {expected:.9g} единиц."
            )

    top_count = len(surface.faces)
    vertex_count = len(surface.vertices)
    top_vertices = list(surface.vertices)
    bottom_vertices = [
        (x, y, z - thickness) for x, y, z in surface.vertices
    ]
    vertices = tuple(top_vertices + bottom_vertices)

    top_faces = [tuple(face) for face in surface.faces]
    bottom_faces = [
        tuple(index + vertex_count for index in reversed(face))
        for face in surface.faces
    ]
    side_faces = [
        (first, first + vertex_count, second + vertex_count, second)
        for first, second in open_edges
    ]
    faces = tuple(top_faces + bottom_faces + side_faces)

    final_usage = _mesh_edge_usage(faces)
    invalid_edges = [edge for edge, count in final_usage.items() if count != 2]
    if invalid_edges:
        raise GeometryInputError(
            "SHELL_NOT_MANIFOLD",
            f"После создания оболочки найдено рёбер с числом смежных граней не равным двум: {len(invalid_edges)}."
        )

    return RoofShell(
        vertices=vertices,
        faces=faces,
        top_face_count=top_count,
        bottom_face_count=top_count,
        side_face_count=len(side_faces),
        thickness=thickness,
    )
