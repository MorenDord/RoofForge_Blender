"""Generate or rebuild a validated RoofForge shell from a source contour."""
from __future__ import annotations

import bpy
import json

from ..adapters.mesh_io import read_object_boundary
from ...core.geometry import GeometryInputError
from ...core.roof_plan import surface_plan_data
from ..roof_build import (
    apply_shell_metadata,
    build_roof_payload,
    create_roof_mesh_data,
    pitch_values,
    sync_slope_settings,
    centimeters_to_blender_units,
)


def _is_scene_mesh(obj, scene) -> bool:
    try:
        return (
            obj is not None
            and obj.type == "MESH"
            and bpy.data.objects.get(obj.name) is obj
            and scene.objects.get(obj.name) is obj
        )
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def _resolve_source_object(context, settings):
    """Prefer the active source, but recover it when the generated roof is active."""
    scene = context.scene
    active = context.object
    if _is_scene_mesh(active, scene) and not active.get("roof_forge_generated", False):
        return active

    if active is not None:
        try:
            if active.get("roof_forge_generated", False):
                source_name = str(active.get("roof_forge_source_name", ""))
                candidate = scene.objects.get(source_name)
                if _is_scene_mesh(candidate, scene):
                    return candidate
        except (ReferenceError, RuntimeError):
            pass

    try:
        stored = settings.source_object
    except ReferenceError:
        stored = None
    if _is_scene_mesh(stored, scene):
        return stored

    snapshot = str(settings.source_name_snapshot or "")
    candidate = scene.objects.get(snapshot) if snapshot else None
    if _is_scene_mesh(candidate, scene) and not candidate.get("roof_forge_generated", False):
        return candidate

    raise GeometryInputError(
        "SOURCE_NOT_FOUND",
        "Выбери исходный Mesh-контур или ранее использованный объект RoofForge.",
    )


def _resolve_existing_roof(settings, source, scene):
    """Find the roof attached to a source even if its stored pointer went stale."""
    try:
        current = settings.generated_object
    except ReferenceError:
        current = None
    try:
        if (
            current is not None
            and bpy.data.objects.get(current.name) is current
            and scene.objects.get(current.name) is current
            and current.type == "MESH"
            and current.get("roof_forge_generated", False)
            and current.get("roof_forge_source_name", "") == source.name
        ):
            return current
    except (AttributeError, ReferenceError, RuntimeError):
        pass

    matches = [
        obj for obj in scene.objects
        if obj.type == "MESH"
        and obj.get("roof_forge_generated", False)
        and obj.get("roof_forge_source_name", "") == source.name
    ]
    return matches[0] if matches else None


class ROOFFORGE_OT_generate_surface(bpy.types.Operator):
    bl_idname = "roof_forge.generate_surface"
    bl_label = "Create / Update Roof"
    bl_description = "Create a roof from the active contour or update its existing RoofForge result"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.object is not None and context.object.type == "MESH":
            return True
        settings = getattr(getattr(context.scene, "roof_forge", None), "source_object", None)
        try:
            return settings is not None and settings.type == "MESH"
        except ReferenceError:
            return False

    def execute(self, context):
        settings = context.scene.roof_forge
        new_mesh = None
        roof_object = None
        created_object = False

        try:
            source = _resolve_source_object(context, settings)
            points = read_object_boundary(source)
            sync_slope_settings(settings, source, len(points))
            settings.outline_preview_json = json.dumps(
                points, separators=(",", ":")
            )
            pitches = pitch_values(settings, len(points))
            thickness_units = centimeters_to_blender_units(
                settings.thickness_cm, context.scene
            )
            overhang_units = centimeters_to_blender_units(
                settings.eave_overhang_cm, context.scene
            )
            corner_convergence = bool(settings.overhang_corner_convergence)
            surface, shell, solver = build_roof_payload(
                points,
                pitches,
                thickness_units,
                overhang_units,
                corner_convergence=corner_convergence,
                cache_owner=source,
            )
            new_mesh = create_roof_mesh_data(
                f"{source.name}_RoofForge_Mesh", surface, shell
            )

            roof_object = _resolve_existing_roof(settings, source, context.scene)
            if roof_object is not None:
                old_mesh = roof_object.data
                roof_object.data = new_mesh
                try:
                    apply_shell_metadata(
                        roof_object,
                        source,
                        surface,
                        shell,
                        pitches,
                        solver,
                        overhang_units,
                        settings.thickness_cm,
                        settings.eave_overhang_cm,
                        corner_convergence,
                    )
                except Exception:
                    roof_object.data = old_mesh
                    raise
                if old_mesh is not new_mesh and old_mesh.users == 0:
                    bpy.data.meshes.remove(old_mesh)
            else:
                roof_object = bpy.data.objects.new(
                    f"{source.name}_RoofForge", new_mesh
                )
                created_object = True
                context.scene.collection.objects.link(roof_object)
                roof_object.hide_set(False)
                apply_shell_metadata(
                    roof_object,
                    source,
                    surface,
                    shell,
                    pitches,
                    solver,
                    overhang_units,
                    settings.thickness_cm,
                    settings.eave_overhang_cm,
                    corner_convergence,
                )
                context.view_layer.update()
                if (
                    bpy.data.objects.get(roof_object.name) is not roof_object
                    or context.scene.objects.get(roof_object.name) is not roof_object
                ):
                    raise RuntimeError(
                        "Blender не зарегистрировал созданный объект крыши в активной сцене."
                    )

            settings.source_object = source
            settings.generated_object = roof_object
            settings.source_name_snapshot = source.name
            settings.generated_name_snapshot = roof_object.name
            settings.roof_plan_json = json.dumps(
                surface_plan_data(surface), separators=(",", ":")
            )
            settings.last_status = "RoofForge roof created/updated"
            new_mesh = None

        except Exception as exc:
            if created_object and roof_object is not None:
                if bpy.data.objects.get(roof_object.name) is roof_object:
                    bpy.data.objects.remove(roof_object, do_unlink=True)
            if new_mesh is not None and new_mesh.users == 0:
                bpy.data.meshes.remove(new_mesh)
            message = getattr(exc, "message", str(exc))
            settings.last_status = str(message)
            report_level = (
                {"WARNING"}
                if getattr(exc, "code", "") == "NONPLANAR_CONCAVE_CONTOUR_UNSUPPORTED"
                else {"ERROR"}
            )
            self.report(report_level, message)
            return {"CANCELLED"}

        action = "Updated" if not created_object else "Created"
        self.report({"INFO"}, f"{action} roof")
        return {"FINISHED"}
