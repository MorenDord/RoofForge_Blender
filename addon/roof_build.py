"""Shared Blender-side roof build and mesh serialization helpers."""
from __future__ import annotations

from collections import OrderedDict
from math import isfinite

import bpy
import bmesh

from ..core.geometry import GeometryInputError
from ..core.mesh import build_roof_surface
from ..core.overhang import build_source_anchored_overhang_surface
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


def _build_roof_surface(points, pitches, overhang, corner_convergence):
    authored_points = tuple(tuple(float(value) for value in point) for point in points)
    if overhang > 0.0:
        surface = build_source_anchored_overhang_surface(
            authored_points, pitches, overhang,
            corner_convergence=corner_convergence,
        )
        return surface, "SOURCE_ANCHORED_PLANE_ENVELOPE_OFFSET_CONTOUR"
    if is_flat_eave_contour(authored_points):
        return build_wavefront_roof_surface(authored_points, pitches), "WEIGHTED_WAVEFRONT_FLAT_EAVE"
    return build_roof_surface(authored_points, pitches), "SUPPORT_PLANE_ENVELOPE_3D"

def build_roof_payload(
    points,
    pitches,
    thickness,
    overhang: float = 0.0,
    *,
    corner_convergence: bool = True,
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
        bool(corner_convergence),
    )
    cache_key = (owner_id, signature) if owner_id is not None else None
    cached = _SURFACE_CACHE.get(cache_key) if cache_key is not None else None

    if cached is not None:
        surface, solver = cached
        _SURFACE_CACHE.move_to_end(cache_key)
    else:
        surface, solver = _build_roof_surface(
            points, pitches, overhang, bool(corner_convergence)
        )
        if cache_key is not None:
            _SURFACE_CACHE[cache_key] = (surface, solver)
            _SURFACE_CACHE.move_to_end(cache_key)
            while len(_SURFACE_CACHE) > _SURFACE_CACHE_LIMIT:
                _SURFACE_CACHE.popitem(last=False)

    shell = build_roof_shell(surface, thickness, extrude_up=overhang > 0.0)
    return surface, shell, solver


def clear_surface_cache() -> None:
    """Release cached pure-Python roof surfaces when the extension unregisters."""
    _SURFACE_CACHE.clear()


def _dissolve_coplanar_edges(mesh) -> None:
    """Remove internal BMesh edges whose two linked faces share one plane."""
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.normal_update()
        coordinates = [vertex.co for vertex in bm.verts]
        if coordinates:
            span = max(
                max(v.x for v in coordinates) - min(v.x for v in coordinates),
                max(v.y for v in coordinates) - min(v.y for v in coordinates),
                max(v.z for v in coordinates) - min(v.z for v in coordinates),
                1.0,
            )
        else:
            span = 1.0
        distance_tolerance = span * 1.0e-7
        angular_tolerance = 1.0e-8
        dissolve = []
        for edge in bm.edges:
            if len(edge.link_faces) != 2:
                continue
            first, second = edge.link_faces
            if first.normal.dot(second.normal) < 1.0 - angular_tolerance:
                continue
            origin = first.verts[0].co
            if all(
                abs(first.normal.dot(vertex.co - origin)) <= distance_tolerance
                for vertex in second.verts
            ):
                dissolve.append(edge)
        if dissolve:
            bmesh.ops.dissolve_edges(
                bm, edges=dissolve, use_verts=False, use_face_split=False
            )
        bm.normal_update()
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update(calc_edges=True)


def _roof_face_metadata(mesh, surface, shell):
    """Rebuild face attributes after coplanar BMesh dissolves."""
    scale = max(
        1.0,
        max(v.co.x for v in mesh.vertices) - min(v.co.x for v in mesh.vertices),
        max(v.co.y for v in mesh.vertices) - min(v.co.y for v in mesh.vertices),
        max(v.co.z for v in mesh.vertices) - min(v.co.z for v in mesh.vertices),
    )
    tolerance = scale * 2.0e-6
    component_values = []
    slope_values = []
    for polygon in mesh.polygons:
        if polygon.normal.z > 1.0e-6:
            component = 0
            z_adjust = -shell.thickness if shell.extrude_up else 0.0
        elif polygon.normal.z < -1.0e-6:
            component = 1
            z_adjust = 0.0 if shell.extrude_up else shell.thickness
        else:
            component = 2
            z_adjust = 0.0

        matched_slope = -1
        if component != 2:
            polygon_points = [
                mesh.vertices[index].co for index in polygon.vertices
            ]
            for slope_index, plane in enumerate(surface.planes):
                if all(
                    abs(
                        vertex.z + z_adjust
                        - plane.height(vertex.x, vertex.y)
                    ) <= tolerance
                    for vertex in polygon_points
                ):
                    matched_slope = slope_index
                    break
            if matched_slope < 0:
                component = 2
        component_values.append(component)
        slope_values.append(matched_slope if component != 2 else -1)

    component = mesh.attributes.new(
        name="roof_forge_component", type="INT", domain="FACE"
    )
    slope = mesh.attributes.new(
        name="roof_forge_slope_index", type="INT", domain="FACE"
    )
    component.data.foreach_set("value", component_values)
    slope.data.foreach_set("value", slope_values)


def create_roof_mesh_data(name: str, surface, shell):
    """Serialize a closed shell, dissolving coplanar seams in the actual mesh."""
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.from_pydata(shell.vertices, [], shell.faces)
        mesh.update(calc_edges=True)
        _dissolve_coplanar_edges(mesh)
        _roof_face_metadata(mesh, surface, shell)
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
        item.pitch = float(settings.initial_pitch)
    settings.source_object = source
    settings.source_name_snapshot = source.name
    settings.generated_object = None
    settings.generated_name_snapshot = ""
    if hasattr(settings, "roof_plan_json"):
        settings.roof_plan_json = ""
    settings.last_status = (
        f"Загружено скатов: {edge_count}. Углы можно задавать отдельно."
    )
    return True


def apply_shell_metadata(
    roof_object, source, surface, shell, pitches, solver,
    overhang=0.0, thickness_cm=None, overhang_cm=None,
    corner_convergence=True,
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
    roof_object["roof_forge_overhang_support"] = (
        "SOURCE_CONTOUR_UNDERSIDE" if overhang > 0.0 else "STANDARD_TOP_SURFACE"
    )
    roof_object["roof_forge_overhang_corner_convergence"] = bool(
        overhang > 0.0 and corner_convergence
    )
    if thickness_cm is not None:
        roof_object["roof_forge_thickness_cm"] = float(thickness_cm)
    if overhang_cm is not None:
        roof_object["roof_forge_overhang_cm"] = float(overhang_cm)
    roof_object.matrix_world = source.matrix_world.copy()
