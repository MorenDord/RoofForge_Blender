"""Validate the same geometry path used by Create / Update Roof."""
import bpy

from ..adapters.mesh_io import read_object_boundary
from ..roof_build import build_roof_payload, pitch_values, sync_slope_settings


class ROOFFORGE_OT_validate_input(bpy.types.Operator):
    bl_idname = "roof_forge.validate_input"
    bl_label = "Validate Roof Boundary"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        settings = context.scene.roof_forge
        try:
            points = read_object_boundary(context.object)
            sync_slope_settings(settings, context.object, len(points))
            pitches = pitch_values(settings, len(points))
            surface, shell, solver = build_roof_payload(
                points, pitches, settings.thickness, settings.eave_overhang,
                cache_owner=context.object,
            )
        except Exception as exc:
            message = getattr(exc, "message", str(exc))
            settings.last_status = f"Проверка не пройдена: {message}"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        settings.last_status = (
            f"Проверка пройдена: {len(points)} скатов, "
            f"{len(surface.faces)} верхних граней ({solver})."
        )
        self.report(
            {"INFO"},
            f"Проверка пройдена: верх {len(surface.faces)} граней, "
            f"оболочка {len(shell.faces)} граней; {solver}."
        )
        return {"FINISHED"}
