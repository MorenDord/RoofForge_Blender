"""Vertical-Z solid shell generation for RoofForge surfaces."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from .geometry import GeometryInputError
from .mesh import RoofSurface, validate_surface_boundary_edges
from .validation import validate_closed_mesh

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


def build_roof_shell(surface: RoofSurface, thickness: float,
                     eps: float = 1e-9) -> RoofShell:
    """Create a closed shell by extruding the top surface globally along -Z.

    All vertices are copied downward along roof-local global Z, not along
    individual face normals. Any internal crack in the upper surface is a hard
    error; it is never converted into an accidental internal wall.
    """
    if not isfinite(thickness) or thickness <= 0.0:
        raise GeometryInputError("INVALID_THICKNESS", "Толщина крыши должна быть положительным конечным числом.")
    if not surface.vertices or not surface.faces:
        raise GeometryInputError("EMPTY_SURFACE", "Нельзя создать оболочку из пустой поверхности.")
    if len(surface.face_slope_indices) != len(surface.faces):
        raise GeometryInputError("FACE_METADATA_MISMATCH", "Количество идентификаторов скатов не совпадает с количеством граней.")
    if len(surface.boundary_xy) < 3:
        raise GeometryInputError("MISSING_BOUNDARY", "Поверхность не содержит исходный контур карниза.")

    scale = max(
        1.0,
        max(v[0] for v in surface.vertices) - min(v[0] for v in surface.vertices),
        max(v[1] for v in surface.vertices) - min(v[1] for v in surface.vertices),
        max(v[2] for v in surface.vertices) - min(v[2] for v in surface.vertices),
        thickness,
    )
    tolerance = max(1e-12, eps * scale * 100.0)
    boundary_edges = validate_surface_boundary_edges(
        surface.vertices, surface.faces, surface.boundary_xy, tolerance * 5.0
    )

    top_count = len(surface.faces)
    vertex_count = len(surface.vertices)
    vertices = tuple(surface.vertices) + tuple(
        (x, y, z - thickness) for x, y, z in surface.vertices
    )
    top_faces = [tuple(face) for face in surface.faces]
    bottom_faces = [
        tuple(index + vertex_count for index in reversed(face))
        for face in surface.faces
    ]
    side_faces = [
        (first, first + vertex_count, second + vertex_count, second)
        for first, second in boundary_edges
    ]
    faces = tuple(top_faces + bottom_faces + side_faces)

    diagnostics = validate_closed_mesh(vertices, faces, eps)
    if diagnostics:
        first = diagnostics[0]
        raise GeometryInputError(first.code, first.message)

    return RoofShell(
        vertices=vertices,
        faces=faces,
        top_face_count=top_count,
        bottom_face_count=top_count,
        side_face_count=len(side_faces),
        thickness=thickness,
    )
