"""RoofForge's compact workflow panel."""
import bpy


class ROOFFORGE_PT_panel(bpy.types.Panel):
    bl_label = "RoofForge"
    bl_idname = "ROOFFORGE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RoofForge"

    @staticmethod
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

    def draw(self, context):
        layout = self.layout
        settings = context.scene.roof_forge

        layout.operator(
            "roof_forge.generate_surface",
            text="Create / Update Roof",
            icon="MESH_DATA",
        )

        if not settings.slope_settings:
            layout.separator(factor=0.5)
            layout.label(text="Initial settings")
            layout.prop(settings, "initial_pitch", text="Initial pitch (°)", slider=True)
            self._draw_common_settings(layout, settings)
            return

        if settings.roof_plan_json:
            preview = layout.column(align=True)
            preview.label(text="Roof plan")
            preview.prop(settings, "plan_show_vector", text="Show preview")
            if settings.plan_show_vector:
                # Keep the draw-handler canvas immediately below the toggle.
                # The matching GPU layout uses this compact top anchor.
                preview_slot = layout.row()
                preview_slot.scale_y = 8.0
                preview_slot.label(text=" ")

                style = layout.column(align=True)
                style.prop(settings, "plan_label_scale", text="Number size", slider=True)
                style.prop(settings, "plan_line_width", text="Line thickness", slider=True)

        pitch_column = layout.column(align=True)
        for index, item in enumerate(settings.slope_settings, start=1):
            row = pitch_column.row(align=True)
            row.label(text=f"{index:02d}")
            row.prop(item, "pitch", text="°")

        layout.separator(factor=0.5)
        self._draw_common_settings(layout, settings)
