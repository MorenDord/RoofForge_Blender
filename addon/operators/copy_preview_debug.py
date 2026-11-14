"""Copy the latest RoofForge preview diagnostic snapshot to the clipboard."""
from __future__ import annotations

import bpy

from ..ui.vector_plan_preview import get_preview_debug_message


class ROOFFORGE_OT_copy_preview_debug(bpy.types.Operator):
    bl_idname = "roof_forge.copy_preview_debug"
    bl_label = "Copy Debug Text"
    bl_description = "Copy the latest RoofForge preview diagnostics as plain text"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        region = getattr(context, "region", None)
        return (
            region is not None
            and getattr(region, "type", None) == "UI"
            and getattr(region, "active_panel_category", "") == "RoofForge"
        )

    def execute(self, context):
        message = get_preview_debug_message(context.region)
        if not message:
            self.report(
                {"WARNING"},
                "No preview diagnostics yet. Let the roof plan draw once, then copy again.",
            )
            return {"CANCELLED"}

        try:
            context.window_manager.clipboard = message
        except (AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
            self.report({"ERROR"}, f"Could not access clipboard: {exc}")
            return {"CANCELLED"}

        self.report({"INFO"}, "RoofForge debug text copied to clipboard")
        return {"FINISHED"}
