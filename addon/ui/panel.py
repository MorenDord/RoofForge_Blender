"""RoofForge's compact workflow panel."""
import bpy

from .vector_plan_preview import (
    estimate_widget_unit,
    preview_icon_scale,
    set_preview_slot_visible,
)


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

    def draw_header(self, context):
        # The root panel itself can also be collapsed. Never leave a stale
        # draw-handler visibility flag behind when its body is not drawn.
        set_preview_slot_visible(context.region, False)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.roof_forge
        set_preview_slot_visible(context.region, False)

        layout.operator(
            "roof_forge.generate_surface",
            text="Create / Update Roof",
            icon="MESH_DATA",
        )

        status = str(settings.last_status or "")
        if "временно отключено построение крыши" in status.lower():
            layout.label(text=status, icon="ERROR")

        if settings.roof_plan_json:
            header, body = layout.panel(
                "roof_forge_plan_preview",
                default_closed=False,
            )
            header.label(text="Roof Plan")

            # A collapsed UILayout.panel() returns body=None. The handler is
            # enabled only while this real layout slot is present in the UI.
            if body is not None:
                body.prop(settings, "plan_show_vector", text="Show preview")
                if settings.plan_show_vector:
                    region_width = getattr(context.region, "width", 320)
                    ui_scale = 1.0
                    try:
                        ui_scale = max(
                            0.5,
                            float(context.preferences.system.ui_scale),
                        )
                    except (AttributeError, TypeError, ValueError):
                        pass
                    widget_unit = estimate_widget_unit(ui_scale)
                    icon_scale = preview_icon_scale(
                        region_width,
                        widget_unit=widget_unit,
                    )
                    if icon_scale is None:
                        body.label(text="Widen the N-panel to view the plan", icon="INFO")
                    else:
                        # Reserve vertical space only. This row expands across
                        # the full panel body; GPU drawing is centered separately
                        # against context.region.width, not this nested layout's
                        # potentially indented content rectangle.
                        preview_row = body.row()
                        preview_row.scale_y = icon_scale
                        preview_row.label(text=" ")

                    debug_row = body.row()
                    debug_row.enabled = icon_scale is not None
                    debug_row.prop(settings, "plan_debug_bounds", text="Debug UI bounds")

                    copy_row = body.row()
                    copy_row.enabled = icon_scale is not None
                    copy_row.operator(
                        "roof_forge.copy_preview_debug",
                        text="Copy debug text",
                        icon="COPYDOWN",
                    )

                    style = body.column(align=True)
                    style.prop(settings, "plan_label_scale", text="Number size", slider=True)
                    style.prop(settings, "plan_line_width", text="Line thickness", slider=True)
                    set_preview_slot_visible(context.region, icon_scale is not None)

        if not settings.slope_settings:
            layout.separator(factor=0.5)
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


__all__ = ["ROOFFORGE_PT_panel"]
