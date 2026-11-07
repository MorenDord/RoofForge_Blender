"""Shared Blender-side roof build and mesh serialization helpers."""
from __future__ import annotations

from math import isfinite

import bpy

from ..core.geometry import GeometryInputError
from ..core.mesh import build_roof_surface
from ..core.shell import build_roof_shell
from ..core.wavefront import build_wavefront_roof_surface, is_flat_eave_contour


def pitch_values(settings, edge_count: int) -> list[float]:
    """Return one validated pitch per ordered source boundary edge."""
    if len(settings.slope_settings) == edge_count:
        values = [float(item.pitch) for item in settings.slope_settings]
    else:
        values = [float(settings.pitch_default)] * edge_count
    if len(values) != edge_count or any(not isfinite(value) for value in values):
        raise GeometryInputError(
            "PITCH_COUNT_MISMATCH",
            "Количество углов скатов не соответствует количеству рёбер контура. Обнови список скатов."
        )
    return values


def build_roof_payload(points, pitches, thickness):
    """Build and validate a roof surface and a closed shell.

    The weighted wavefront solver is used for constant-height eaves and
    supports the tested concave / per-edge pitch cases. Mixed-height 3D
    contours stay on the existing support-plane envelope path; no flattening
    or coordinate projection is applied to the source vertices.
    """
    if len(points) < 3 or len(pitches) != len(points):
        raise GeometryInputError(
            "INPUT_COUNT",
            "Нужно минимум три вершины и по одному углу на каждое ребро."
        )
    if is_flat_eave_contour(points):
        surface = build_wavefront_roof_surface(points, pitches)
        solver = "WEIGHTED_WAVEFRONT_FLAT_EAVE"
    else:
        surface = build_roof_surface(points, pitches)
        solver = "SUPPORT_PLANE_ENVELOPE_3D"
    shell = build_roof_shell(surface, thickness)
    return surface, shell, solver


def create_roof_mesh_data(name: str, surface, shell):
    """Serialize a validated shell into a new Blender mesh datablock."""
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.from_pydata(shell.vertices, [], shell.faces)
        mesh.update(calc_edges=True)
        if len(mesh.polygons) != len(shell.faces):
            raise RuntimeError(
                "Blender изменил количество граней при создании сетки."
            )

        component = mesh.attributes.new(
            name="roof_forge_component", type="INT", domain="FACE"
        )
        slope = mesh.attributes.new(
            name="roof_forge_slope_index", type="INT", domain="FACE"
        )
        component_values = (
            [0] * shell.top_face_count
            + [1] * shell.bottom_face_count
            + [2] * shell.side_face_count
        )
        slope_values = (
            list(surface.face_slope_indices)
            + list(surface.face_slope_indices)
            + [-1] * shell.side_face_count
        )
        for index, value in enumerate(component_values):
            component.data[index].value = value
        for index, value in enumerate(slope_values):
            slope.data[index].value = int(value)
        return mesh
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise


def sync_slope_settings(settings, source, edge_count: int) -> bool:
    """Initialize per-edge pitches when the source object / contour changes.

    Existing values are preserved while the source object and edge count stay
    unchanged. Topology edits that change the number of edges require an
    explicit refresh, preventing accidental remapping of authored pitches.
    """
    if (
        settings.source_object == source
        and len(settings.slope_settings) == edge_count
    ):
        return False

    settings.slope_settings.clear()
    for edge_index in range(edge_count):
        item = settings.slope_settings.add()
        item.edge_index = edge_index
        item.start_vertex_index = edge_index
        item.end_vertex_index = (edge_index + 1) % edge_count
        item.pitch = float(settings.pitch_default)
    settings.source_object = source
    settings.source_name_snapshot = source.name
    settings.generated_object = None
    settings.generated_name_snapshot = ""
    settings.last_status = (
        f"Загружено скатов: {edge_count}. Углы можно задавать отдельно."
    )
    return True


def apply_shell_metadata(roof_object, source, surface, shell, pitches, solver):
    """Write stable links and diagnostic metadata onto the generated object."""
    roof_object["roof_forge_generated"] = True
    roof_object["roof_forge_source_name"] = source.name
    roof_object["roof_forge_source_edge_count"] = len(pitches)
    roof_object["roof_forge_stage"] = "CLOSED_SHELL"
    roof_object["roof_forge_solver"] = solver
    roof_object["roof_forge_pitch_values"] = ",".join(
        f"{value:.6f}" for value in pitches
    )
    roof_object["roof_forge_thickness"] = float(shell.thickness)
    roof_object.matrix_world = source.matrix_world.copy()
