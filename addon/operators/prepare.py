"""Prepare a numbered per-edge pitch list for the active mesh contour."""
import bpy

from ..adapters.mesh_io import read_object_boundary
from ..roof_build import sync_slope_settings


class ROOFFORGE_OT_prepare_slopes(bpy.types.Operator):
    bl_idname = "roof_forge.prepare_slopes"
    bl_label = "Load / Refresh Slope Angles"
    bl_description = "Read the active object's contour and prepare one pitch value for each boundary edge"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        settings = context.scene.roof_forge
        try:
            points = read_object_boundary(context.object)
            changed = sync_slope_settings(settings, context.object, len(points))
        except Exception as exc:
            self.report({"ERROR"}, str(getattr(exc, "message", exc)))
            return {"CANCELLED"}

        action = "Создан список" if changed else "Список сохранён"
        self.report(
            {"INFO"},
            f"{action}: {len(points)} скатов. Углы соответствуют рёбрам контура по порядку обхода."
        )
        return {"FINISHED"}
