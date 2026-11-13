"""RoofForge's compact workflow panel."""
import bpy

from .vector_plan_preview import (
    estimate_widget_unit,
    preview_category_rail_width,
    preview_icon_scale,
    set_preview_slot_visible,
)

from ...core import native_bridge


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
                    compact_tabs = False
                    try:
                        compact_tabs = bool(context.preferences.system.show_panel_tabs_compact)
                    except (AttributeError, ReferenceError, TypeError, ValueError):
                        pass
                    category_rail_width = preview_category_rail_width(
                        widget_unit,
                        region=context.region,
                        compact=compact_tabs,
                    )
                    icon_scale = preview_icon_scale(
                        max(0.0, region_width - category_rail_width),
                        widget_unit=widget_unit,
                    )
                    if icon_scale is None:
                        body.label(text="Widen the N-panel to view the plan", icon="INFO")
                    else:
                        # Reserve vertical space only. GPU drawing is centered
                        # against the active tab's content rectangle, excluding
                        # Blender's category-tab rail at the left of the UI region.
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
                row.alignment = "EXPAND"
                row.label(text=f"{index:02d}")

                previous_button = row.operator(
                    "roof_forge.pitch_intersection_step",
                    text="",
                    icon="TRIA_LEFT",
                )
                previous_button.edge_index = index - 1
                previous_button.direction = "PREVIOUS"

                row.prop(item, "pitch", text="°", slider=True)

                next_button = row.operator(
                    "roof_forge.pitch_intersection_step",
                    text="",
                    icon="TRIA_RIGHT",
                )
                next_button.edge_index = index - 1
                next_button.direction = "NEXT"

        if settings.pitch_snap_status:
            status_row = layout.row()
            is_snap_success = "общая вершина" in settings.pitch_snap_status.lower()
            status_row.alert = not is_snap_success
            status_row.label(
                text=settings.pitch_snap_status,
                icon="CHECKMARK" if is_snap_success else "INFO",
            )

        layout.separator(factor=0.5)
        _draw_common_settings(layout, settings)

        native_kernel_count = sum((
            native_bridge.NATIVE_BACKEND_AVAILABLE,
            native_bridge.NATIVE_WAVEFRONT_EVENTS_AVAILABLE,
            native_bridge.NATIVE_WAVEFRONT_INTERVAL_AVAILABLE,
            native_bridge.NATIVE_VERTEX_WELD_AVAILABLE,
            native_bridge.NATIVE_FACE_CONFORMANCE_AVAILABLE,
        ))
        backend_row = layout.row()
        backend_row.enabled = False
        if native_kernel_count == 5:
            backend_row.label(text="Geometry core: Rust (5/5 kernels)", icon="CHECKMARK")
        elif native_kernel_count:
            backend_row.label(
                text=f"Geometry core: Rust ({native_kernel_count}/5 kernels)",
                icon="INFO",
            )
        else:
            backend_row.label(text="Geometry core: Python fallback", icon="INFO")


__all__ = ["ROOFFORGE_PT_panel"]
