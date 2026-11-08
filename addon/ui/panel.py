"""Minimal RoofForge workflow: create, tune, inspect and update."""
import bpy

from .plan_preview import get_roof_plan_icon


class ROOFFORGE_PT_panel(bpy.types.Panel):
    bl_label = "RoofForge"
    bl_idname = "ROOFFORGE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RoofForge"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.roof_forge

        layout.operator(
            "roof_forge.generate_surface",
            text="Create / Update Roof",
            icon="MESH_DATA",
        )

        if not settings.slope_settings:
            return

        display = layout.column(align=True)
        display.label(text="Plan display")
        display.prop(settings, "plan_show_raster", text="Raster preview (PNG)")
        display.prop(settings, "plan_show_vector", text="Vector preview")

        if settings.plan_show_raster:
            preview_icon = get_roof_plan_icon()
            if preview_icon:
                region_width = max(180, getattr(context.region, "width", 320))
                preview_scale = max(1.0, (region_width - 24.0) / 32.0)
                layout.template_icon(preview_icon, scale=preview_scale)

        style = layout.column(align=True)
        style.enabled = settings.plan_show_raster or settings.plan_show_vector
        style.prop(settings, "plan_label_scale", text="Number size", slider=True)
        style.prop(settings, "plan_line_width", text="Line thickness", slider=True)

        if settings.plan_show_vector and settings.roof_plan_json:
            layout.label(text="Vector plan", icon="SHADING_WIRE")
            preview_slot = layout.row()
            preview_slot.scale_y = 10.0
            preview_slot.label(text=" ")

        pitch_column = layout.column(align=True)
        for index, item in enumerate(settings.slope_settings, start=1):
            row = pitch_column.row(align=True)
            row.label(text=f"{index:02d}")
            row.prop(item, "pitch", text="°")

        layout.separator(factor=0.5)
        layout.prop(settings, "thickness_cm", text="Thickness (cm)")
        layout.prop(settings, "eave_overhang_cm", text="Overhang (cm)")

        convergence_row = layout.row()
        convergence_row.enabled = settings.eave_overhang_cm > 0.0
        convergence_row.prop(
            settings,
            "overhang_corner_convergence",
            text="Converge corners",
        )

        layout.prop(settings, "live_update", text="Live update")
        delay_row = layout.row()
        delay_row.enabled = settings.live_update
        delay_row.prop(
            settings,
            "live_update_delay_ms",
            text="Debounce (ms)",
            slider=True,
        )

