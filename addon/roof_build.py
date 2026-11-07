"""Shared Blender-side roof build and mesh serialization helpers."""
from __future__ import annotations

from collections import OrderedDict
from math import isfinite

import bpy

from ..core.geometry import GeometryInputError
from ..core.mesh import build_roof_surface
from ..core.overhang import offset_contour_outward
from ..core.shell import build_roof_shell
from ..core.wavefront import build_wavefront_roof_surface, is_flat_eave_contour


def pitch_values(settings, edge_count: int) -> list[float]:
    """Return one validated pitch per ordered source boundary edge."""
    if len(settings.slope_settings) != edge_count:
        raise GeometryInputError(
            "PITCH_COUNT_MISMATCH",
            "Количество индивидуальных углов не соответствует числу рёбер контура. "
            "Обнови список скатов.",
        )
    values = [float(item.pitch) for item in settings.slope_settings]
    if len(values) != edge_count or any(not isfinite(value) for value in values):
        raise GeometryInputError(
            "PITCH_COUNT_MISMATCH",
            "Количество углов скатов не соответствует количеству рёбер контура. Обнови список скатов."
        )
    return values


def centimeters_to_blender_units(value_cm: float, scene) -> float:
    """Convert a UI centimeter value to Blender's internal local coordinates.

    Blender stores mesh coordinates in internal units. Scene scale_length
    controls how those units map to physical meters; object scale should be
    applied for dimensions to remain physically exact in every direction.
    """
    value_cm = float(value_cm)
    scale_length = float(scene.unit_settings.scale_length)
    if (
        not isfinite(value_cm)
        or value_cm < 0.0
        or not isfinite(scale_length)
        or scale_length <= 0.0
    ):
        raise GeometryInputError(
            "INVALID_CENTIMETER_VALUE",
            "Размер в сантиметрах и масштаб единиц сцены должны быть конечными "
            "неотрицательными значениями.",
        )
    return value_cm * 0.01 / scale_length


_SURFACE_CACHE: OrderedDict[tuple, tuple[object, str]] = OrderedDict()
_SURFACE_CACHE_LIMIT = 12


def _cache_owner_id(owner) -> int | None:
    if owner is None:
        return None
    try:
        return int(owner.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError):
        return id(owner)


def _build_roof_surface(points, pitches, overhang):
    # Eaves are part of the source contour now. Offset the contour once, then
    # build the entire roof from that one new closed boundary. No strips or
    # corner patches are appended to a previously generated roof.
    build_points = (
        offset_contour_outward(points, overhang)
        if overhang > 0.0
        else tuple(tuple(float(value) for value in point) for point in points)
    )
    if is_flat_eave_contour(build_points):
        surface = build_wavefront_roof_surface(build_points, pitches)
        solver = "WEIGHTED_WAVEFRONT_FLAT_EAVE"
    else:
        surface = build_roof_surface(build_points, pitches)
        solver = "SUPPORT_PLANE_ENVELOPE_3D"
    if overhang > 0.0:
        solver = f"{solver}_OFFSET_CONTOUR"
    return surface, solver


def build_roof_payload(
    points,
    pitches,
    thickness,
    overhang: float = 0.0,
    *,
    cache_owner=None,
):
    """Build a validated roof shell, reusing unchanged surface geometry.

    Thickness is deliberately excluded from the surface-cache signature.
    A thickness-only Live Update therefore rebuilds the shell without running
    the weighted wavefront or plane-envelope solver again.
    """
    if len(points) < 3 or len(pitches) != len(points):
        raise GeometryInputError(
            "INPUT_COUNT",
            "Нужно минимум три вершины и по одному углу на каждое ребро."
        )
    overhang = float(overhang)
    if not isfinite(overhang) or overhang < 0.0:
        raise GeometryInputError(
            "INVALID_OVERHANG",
            "Свес должен быть конечным неотрицательным расстоянием."
        )

    owner_id = _cache_owner_id(cache_owner)
    signature = (
        tuple(tuple(float(value) for value in point) for point in points),
        tuple(float(value) for value in pitches),
        overhang,
    )
    cache_key = (owner_id, signature) if owner_id is not None else None
    cached = _SURFACE_CACHE.get(cache_key) if cache_key is not None else None

    if cached is not None:
        surface, solver = cached
        _SURFACE_CACHE.move_to_end(cache_key)
    else:
        surface, solver = _build_roof_surface(points, pitches, overhang)
        if cache_key is not None:
            _SURFACE_CACHE[cache_key] = (surface, solver)
            _SURFACE_CACHE.move_to_end(cache_key)
            while len(_SURFACE_CACHE) > _SURFACE_CACHE_LIMIT:
                _SURFACE_CACHE.popitem(last=False)

    shell = build_roof_shell(surface, thickness)
    return surface, shell, solver


def clear_surface_cache() -> None:
    """Release cached pure-Python roof surfaces when the extension unregisters."""
    _SURFACE_CACHE.clear()


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
        component.data.foreach_set("value", component_values)
        slope.data.foreach_set("value", slope_values)
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
        item.pitch = 30.0
    settings.source_object = source
    settings.source_name_snapshot = source.name
    settings.generated_object = None
    settings.generated_name_snapshot = ""
    settings.last_status = (
        f"Загружено скатов: {edge_count}. Углы можно задавать отдельно."
    )
    return True


def apply_shell_metadata(
    roof_object, source, surface, shell, pitches, solver,
    overhang=0.0, thickness_cm=None, overhang_cm=None,
):
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
    roof_object["roof_forge_overhang"] = float(overhang)
    if thickness_cm is not None:
        roof_object["roof_forge_thickness_cm"] = float(thickness_cm)
    if overhang_cm is not None:
        roof_object["roof_forge_overhang_cm"] = float(overhang_cm)
    roof_object.matrix_world = source.matrix_world.copy()
