"""Blender integration for ridge, valley and standing-seam roof details."""
from __future__ import annotations

import json
from collections import defaultdict

import bpy
from mathutils import Vector

from ..core.roof_details import (
    build_inset_seam_profile_mesh,
    extract_roof_seams,
)
from ..core.standing_seams import build_standing_seam_mesh
from .roof_build import centimeters_to_blender_units


_HELPERS = {
    "RIDGE": ("roof_forge_ridges_object", "_Ridges"),
    "VALLEY": ("roof_forge_valleys_object", "_Valleys"),
    "STANDING": ("roof_forge_standing_seams_object", "_StandingSeams"),
}


def _remove_helper(roof_obj, key):
    name = str(roof_obj.get(key, ""))
    helper = bpy.data.objects.get(name) if name else None
    if helper is not None and helper.get("roof_forge_helper", False):
        if helper.get("roof_forge_owner_name", "") == roof_obj.name:
            mesh = helper.data if helper.type == "MESH" else None
            bpy.data.objects.remove(helper, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    roof_obj[key] = ""


def _ensure_helper(roof_obj, kind):
    key, suffix = _HELPERS[kind]
    name = str(roof_obj.get(key, ""))
    helper = bpy.data.objects.get(name) if name else None
    if helper is None or helper.type != "MESH" or not helper.get("roof_forge_helper", False):
        mesh = bpy.data.meshes.new(roof_obj.name + suffix + "_Mesh")
        helper = bpy.data.objects.new(roof_obj.name + suffix, mesh)
        collection = roof_obj.users_collection[0] if roof_obj.users_collection else bpy.context.scene.collection
        collection.objects.link(helper)
        helper["roof_forge_helper"] = True
        roof_obj[key] = helper.name

    if helper.parent is not None:
        saved_world = helper.matrix_world.copy()
        helper.parent = None
        helper.matrix_world = saved_world
    collection = roof_obj.users_collection[0] if roof_obj.users_collection else bpy.context.scene.collection
    if collection not in helper.users_collection:
        collection.objects.link(helper)
    helper.parent = None
    helper.matrix_world = roof_obj.matrix_world.copy()
    helper["roof_forge_helper"] = True
    helper["roof_forge_owner_name"] = roof_obj.name
    helper["roof_forge_helper_kind"] = kind
    constraint = next(
        (item for item in helper.constraints
         if item.type == "COPY_TRANSFORMS" and item.name == "RoofForge Follow Roof"),
        None,
    )
    if constraint is None:
        constraint = helper.constraints.new(type="COPY_TRANSFORMS")
        constraint.name = "RoofForge Follow Roof"
    constraint.target = roof_obj
    try:
        constraint.owner_space = "WORLD"
        constraint.target_space = "WORLD"
    except (AttributeError, TypeError):
        pass
    return helper


def _replace_mesh(helper, vertices, faces, seam_edge_pairs=()):
    mesh = bpy.data.meshes.new(helper.name + "_Mesh")
    try:
        mesh.from_pydata(vertices, [], faces)
        mesh.validate(verbose=False)
        mesh.update(calc_edges=True)
        if seam_edge_pairs:
            marked = {
                tuple(sorted((int(edge[0]), int(edge[1]))))
                for edge in seam_edge_pairs if len(edge) == 2
            }
            for edge in mesh.edges:
                if tuple(sorted(int(index) for index in edge.vertices)) in marked:
                    edge.use_seam = True
        for polygon in mesh.polygons:
            polygon.use_smooth = False
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise
    old = helper.data
    helper.data = mesh
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)


def _top_surface_from_roof(roof_obj):
    mesh = roof_obj.data
    if mesh is None or not mesh.polygons:
        raise RuntimeError("У объекта крыши нет полигональной геометрии.")
    component = mesh.attributes.get("roof_forge_component")
    slope = mesh.attributes.get("roof_forge_slope_index")
    if component is None:
        raise RuntimeError(
            "У меша нет атрибута roof_forge_component. Пересоздай крышу через RoofForge 0.4.0."
        )

    transform = roof_obj.matrix_world
    world_points = [
        tuple(float(value) for value in (transform @ vertex.co))
        for vertex in mesh.vertices
    ]
    source_faces = []
    source_ids = []
    for polygon in mesh.polygons:
        if int(component.data[polygon.index].value) != 0:
            continue
        face = tuple(int(index) for index in polygon.vertices)
        if len(face) < 3:
            continue
        # Profiles are derived only from upward-facing top-surface facets.
        normal = transform.to_3x3().inverted_safe().transposed() @ polygon.normal
        length = normal.length
        if length <= 1.0e-12 or normal.z / length <= 0.05:
            continue
        source_faces.append(face)
        source_ids.append(
            int(slope.data[polygon.index].value) if slope is not None else -1
        )

    if not source_faces:
        raise RuntimeError("Не найдены верхние грани крыши для анализа коньков и ендов.")

    used = sorted({index for face in source_faces for index in face})
    remap = {old: new for new, old in enumerate(used)}
    vertices = [world_points[index] for index in used]
    faces = [tuple(remap[index] for index in face) for face in source_faces]

    edge_uses = defaultdict(list)
    for face_index, face in enumerate(faces):
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((a, b))
    boundary_edges = [
        (vertices[uses[0][0]], vertices[uses[0][1]])
        for uses in edge_uses.values() if len(uses) == 1
    ]
    seams = extract_roof_seams(vertices, faces, source_ids, [])
    return vertices, faces, source_ids, seams, boundary_edges


def _store_profile(roof_obj, kind, vertices, faces):
    key, suffix = _HELPERS[kind]
    if not vertices or not faces:
        _remove_helper(roof_obj, key)
        return 0
    inverse = roof_obj.matrix_world.inverted_safe()
    local_vertices = []
    for vertex in vertices:
        point = inverse @ Vector(vertex)
        local_vertices.append((float(point.x), float(point.y), float(point.z)))
    helper = _ensure_helper(roof_obj, kind)
    _replace_mesh(helper, local_vertices, faces)
    return len(faces)


def rebuild_roof_details(roof_obj, settings, scene):
    """Regenerate enabled details from the actual generated roof top mesh.

    Existing helper meshes are kept when a particular profile fails to build;
    the roof shell itself is never modified by this operation.
    """
    if roof_obj is None or roof_obj.type != "MESH":
        raise RuntimeError("Сначала создай крышу RoofForge.")
    if not roof_obj.get("roof_forge_generated", False):
        raise RuntimeError("Выбранный объект не является сгенерированной крышей RoofForge.")

    vertices, faces, source_ids, seams, boundary_edges = _top_surface_from_roof(roof_obj)
    ridge_count = sum(1 for edge in seams if edge[4] == "RIDGE")
    valley_count = sum(1 for edge in seams if edge[4] == "VALLEY")
    roof_obj["roof_forge_seam_edge_count"] = len(seams)
    roof_obj["roof_forge_ridge_edge_count"] = ridge_count
    roof_obj["roof_forge_valley_edge_count"] = valley_count

    errors = []
    sink = centimeters_to_blender_units(0.02, scene)

    for kind, enabled, width_cm, extrusion_cm, end_cm in (
        ("RIDGE", bool(settings.show_ridges), settings.ridge_width_cm,
         settings.ridge_extrusion_cm, settings.ridge_end_offset_cm),
        ("VALLEY", bool(settings.show_valleys), settings.valley_width_cm,
         settings.valley_extrusion_cm, settings.valley_end_offset_cm),
    ):
        key, _suffix = _HELPERS[kind]
        error_key = "roof_forge_" + kind.lower() + "_error"
        face_key = "roof_forge_" + kind.lower() + "_face_count"
        if not enabled:
            _remove_helper(roof_obj, key)
            roof_obj[error_key] = ""
            roof_obj[face_key] = 0
            continue
        try:
            width = centimeters_to_blender_units(width_cm, scene)
            extrusion = centimeters_to_blender_units(extrusion_cm, scene)
            end_offset = centimeters_to_blender_units(abs(end_cm), scene)
            if float(end_cm) < 0.0:
                end_offset = -end_offset
            profile_vertices, profile_faces = build_inset_seam_profile_mesh(
                vertices, faces, seams, kind, width,
                (0.0, 0.0, extrusion),
                end_offset=end_offset,
                seat_sink_offset=(0.0, 0.0, -sink),
                boundary_edges=boundary_edges,
            )
            profile_face_count = _store_profile(
                roof_obj, kind, profile_vertices, profile_faces
            )
            roof_obj[error_key] = ""
            roof_obj[face_key] = profile_face_count
        except Exception as exc:
            message = str(exc)
            roof_obj[error_key] = message
            errors.append(kind + ": " + message)

    standing_stats = {"segments": 0, "effective_height_max": 0.0}
    if not settings.show_standing_seams:
        _remove_helper(roof_obj, _HELPERS["STANDING"][0])
        roof_obj["roof_forge_standing_error"] = ""
    else:
        try:
            panel_width = centimeters_to_blender_units(settings.standing_panel_width_cm, scene)
            seam_height = centimeters_to_blender_units(settings.standing_seam_height_cm, scene)
            seam_width = centimeters_to_blender_units(settings.standing_seam_width_cm, scene)
            roof_thickness = centimeters_to_blender_units(settings.thickness_cm, scene)
            ridge_height = centimeters_to_blender_units(settings.ridge_extrusion_cm, scene)
            end_offset = centimeters_to_blender_units(abs(settings.standing_end_offset_cm), scene)
            if float(settings.standing_end_offset_cm) < 0.0:
                end_offset = -end_offset
            seam_vertices, seam_faces, standing_stats = build_standing_seam_mesh(
                vertices,
                faces,
                seams,
                panel_width=panel_width,
                seam_height=seam_height,
                seam_base_width=seam_width,
                roof_thickness=roof_thickness,
                ridge_height=ridge_height,
                minimum_segment_length=centimeters_to_blender_units(5.0, scene),
                end_offset=end_offset,
                boundary_edges=boundary_edges,
            )
            if seam_vertices and seam_faces:
                inverse = roof_obj.matrix_world.inverted_safe()
                local_vertices = []
                for vertex in seam_vertices:
                    point = inverse @ Vector(vertex)
                    local_vertices.append((float(point.x), float(point.y), float(point.z)))
                helper = _ensure_helper(roof_obj, "STANDING")
                _replace_mesh(
                    helper, local_vertices, seam_faces,
                    seam_edge_pairs=standing_stats.get("seam_edge_pairs", ()),
                )
            else:
                _remove_helper(roof_obj, _HELPERS["STANDING"][0])
            roof_obj["roof_forge_standing_error"] = ""
        except Exception as exc:
            message = str(exc)
            roof_obj["roof_forge_standing_error"] = message
            errors.append("STANDING: " + message)

    roof_obj["roof_forge_standing_segment_count"] = int(standing_stats.get("segments", 0))
    roof_obj["roof_forge_standing_effective_height"] = float(
        standing_stats.get("effective_height_max", 0.0)
    )
    safe_stats = {
        key: value for key, value in standing_stats.items()
        if key != "seam_edge_pairs"
    }
    roof_obj["roof_forge_standing_stats"] = json.dumps(safe_stats, separators=(",", ":"))
    roof_obj["roof_forge_details_error"] = "; ".join(errors)
    return {
        "seam_edges": len(seams),
        "ridge_edges": ridge_count,
        "valley_edges": valley_count,
        "standing_segments": int(standing_stats.get("segments", 0)),
        "errors": tuple(errors),
    }


def remove_roof_details(roof_obj):
    """Remove only RoofForge-owned sibling detail objects."""
    if roof_obj is None:
        return
    for key, _suffix in _HELPERS.values():
        _remove_helper(roof_obj, key)


class ROOFFORGE_OT_rebuild_details(bpy.types.Operator):
    bl_idname = "roof_forge.rebuild_details"
    bl_label = "Rebuild Roof Details"
    bl_description = "Rebuild ridges, valleys and standing seams from the current roof mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(getattr(context.scene, "roof_forge", None), "generated_object", None)
        obj = context.object or settings
        return obj is not None and getattr(obj, "type", None) == "MESH"

    def execute(self, context):
        settings = context.scene.roof_forge
        roof_obj = settings.generated_object
        if roof_obj is None:
            roof_obj = context.object
        try:
            result = rebuild_roof_details(roof_obj, settings, context.scene)
        except Exception as exc:
            self.report({"ERROR"}, "RoofForge: " + str(exc))
            return {"CANCELLED"}
        if result["errors"]:
            self.report({"WARNING"}, "Детали обновлены частично: " + "; ".join(result["errors"])[:180])
        else:
            self.report(
                {"INFO"},
                "Коньки: {}, ендовы: {}, линии фальца: {}.".format(
                    result["ridge_edges"], result["valley_edges"], result["standing_segments"]
                ),
            )
        return {"FINISHED"}


__all__ = ["rebuild_roof_details", "remove_roof_details", "ROOFFORGE_OT_rebuild_details"]
