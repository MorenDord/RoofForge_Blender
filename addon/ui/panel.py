"""RoofForge's compact workflow panels."""
import bpy

from .vector_plan_preview import preview_icon_scale


def _draw_common_settings(layout, settings):
    layout.prop(settings, "thickness_cm", text="Thickness (cm)")
    layout.prop(settings, "eave_overhang_cm", text="Overhang (cm)")

    convergence_row = layout.row()
    convergence_row.enabled = settings.eave_overhang_cm > 0.0
    convergence_row.prop(
        settings,
        "overhang_corner_convergence",
        text="Converge corners",
    )

    layout.separator(factor=0.5)
    layout.prop(settings, "live_update", text="Live update")
    delay_row = layout.row()
    delay_row.enabled = settings.live_update
    delay_row.prop(
        settings,
        "live_update_delay_ms",
        text="Debounce (ms)",
        slider=True,
    )


class ROOFFORGE_PT_panel(bpy.types.Panel):
    bl_label = "RoofForge"
    bl_idname = "ROOFFORGE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RoofForge"
    bl_order = 0

    def draw(self, context):
        self.layout.operator(
            "roof_forge.generate_surface",
            text="Create / Update Roof",
            icon="MESH_DATA",
        )


class ROOFFORGE_PT_plan_preview(bpy.types.Panel):
    bl_label = "Roof Plan"
    bl_idname = "ROOFFORGE_PT_plan_preview"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RoofForge"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        settings = getattr(getattr(context, "scene", None), "roof_forge", None)
        return bool(settings and settings.roof_plan_json)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.roof_forge
        layout.prop(settings, "plan_show_vector", text="Show preview")

        if not settings.plan_show_vector:
            return

        region_width = getattr(context.region, "width", 320)
        icon_scale = preview_icon_scale(region_width)
        if icon_scale is None:
            layout.label(text="Widen the N-panel to view the plan", icon="INFO")
        else:
            # ICON_NONE reserves the exact square in normal UI flow. The GPU
            # handler paints only inside this slot; no bitmap is generated.
            layout.template_icon(0, scale=icon_scale)

        style = layout.column(align=True)
        style.prop(settings, "plan_label_scale", text="Number size", slider=True)
        style.prop(settings, "plan_line_width", text="Line thickness", slider=True)


class ROOFFORGE_PT_settings(bpy.types.Panel):
    bl_label = "Pitch & Settings"
    bl_idname = "ROOFFORGE_PT_settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RoofForge"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        settings = context.scene.roof_forge

        if not settings.slope_settings:
            layout.label(text="Initial settings")
            layout.prop(settings, "initial_pitch", text="Initial pitch (°)", slider=True)
        else:
            pitch_column = layout.column(align=True)
            for index, item in enumerate(settings.slope_settings, start=1):
                row = pitch_column.row(align=True)
                row.label(text=f"{index:02d}")
                row.prop(item, "pitch", text="°")

        layout.separator(factor=0.5)
        _draw_common_settings(layout, settings)


__all__ = [
    "ROOFFORGE_PT_panel",
    "ROOFFORGE_PT_plan_preview",
    "ROOFFORGE_PT_settings",
]
