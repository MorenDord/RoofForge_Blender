"""RoofForge's always-visible workflow panel."""
import bpy

from .vector_plan_preview import (
    estimate_widget_unit,
    preview_category_rail_width,
    preview_icon_scale,
    set_preview_slot_visible,
)


def _draw_common_settings(layout, settings):
    layout.prop(settings, "thickness_cm", text="Thickness (cm)")
    layout.prop(settings, "eave_overhang_cm", text="Overhang (cm)")
    layout.separator(factor=0.5)
    layout.prop(settings, "live_update", text="Live update")


class ROOFFORGE_PT_panel(bpy.types.Panel):
    bl_label = "RoofForge"
    bl_idname = "ROOFFORGE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RoofForge"

    def draw_header(self, context):
        # The root panel can be collapsed by Blender. Do not keep a stale GPU
        # preview slot visible after its contents disappear.
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
        normal_status = (
            status in {
                "RoofForge roof created/updated",
                "RoofForge live update completed",
            }
            or status.startswith("Загружено скатов:")
            or status.startswith("Контур изменён:")
        )
        if status and not normal_status:
            status_row = layout.row()
            status_row.alert = True
            status_row.label(text=status[:180], icon="ERROR")

        # The plan is always shown when a roof exists. There is no Show Preview
        # switch and no collapsible child panel that can accidentally hide it.
        if settings.roof_plan_json:
            preview_box = layout.box()
            preview_box.label(text="Roof Plan", icon="IMAGE_DATA")
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
                compact_tabs = bool(
                    context.preferences.system.show_panel_tabs_compact
                )
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
                preview_box.label(
                    text="Widen the N-panel to view the plan",
                    icon="INFO",
                )
            else:
                preview_row = preview_box.row()
                preview_row.alignment = "CENTER"
                preview_row.template_icon(icon_value=0, scale=icon_scale)
                set_preview_slot_visible(context.region, True)

            style = preview_box.column(align=True)
            style.prop(
                settings,
                "plan_label_scale",
                text="Number size",
                slider=True,
            )
            style.prop(
                settings,
                "plan_line_width",
                text="Line thickness",
                slider=True,
            )

        if not settings.slope_settings:
            layout.separator(factor=0.5)
            layout.label(text="Initial settings")
            layout.prop(
                settings,
                "initial_pitch",
                text="Initial pitch (°)",
                slider=True,
            )
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
            is_snap_success = (
                "общая вершина" in settings.pitch_snap_status.lower()
            )
            status_row.alert = not is_snap_success
            status_row.label(
                text=settings.pitch_snap_status,
                icon="CHECKMARK" if is_snap_success else "INFO",
            )

        layout.separator(factor=0.5)
        _draw_common_settings(layout, settings)

        # Keep optional roof details visible instead of hiding their controls
        # inside a collapsible UILayout.panel.
        details_box = layout.box()
        details_box.label(text="Ridges, valleys & standing seams")

        ridge_box = details_box.box()
        ridge_box.prop(settings, "show_ridges", text="Create ridges")
        if settings.show_ridges:
            ridge_box.prop(settings, "ridge_width_cm")
            ridge_box.prop(settings, "ridge_extrusion_cm")
            ridge_box.prop(settings, "ridge_end_offset_cm")

        valley_box = details_box.box()
        valley_box.prop(settings, "show_valleys", text="Create valleys")
        if settings.show_valleys:
            valley_box.prop(settings, "valley_width_cm")
            valley_box.prop(settings, "valley_extrusion_cm")
            valley_box.prop(settings, "valley_end_offset_cm")

        seams_box = details_box.box()
        seams_box.prop(
            settings,
            "show_standing_seams",
            text="Create standing seams",
        )
        if settings.show_standing_seams:
            seams_box.prop(settings, "standing_panel_width_cm")
            seams_box.prop(settings, "standing_seam_height_cm")
            seams_box.prop(settings, "standing_seam_width_cm")
            seams_box.prop(settings, "standing_end_offset_cm")
            seams_box.label(
                text="Seam height is limited by the ridge rise.",
                icon="INFO",
            )

        update_row = details_box.row()
        update_row.enabled = settings.generated_object is not None
        update_row.operator(
            "roof_forge.rebuild_details",
            text="Rebuild roof details",
            icon="FILE_REFRESH",
        )
        if settings.generated_object is not None:
            detail_obj = settings.generated_object
            details_box.label(
                text=(
                    f"Ridge joints: {int(detail_obj.get('roof_forge_ridge_edge_count', 0))} "
                    f"| Valley joints: {int(detail_obj.get('roof_forge_valley_edge_count', 0))}"
                ),
                icon="INFO",
            )
            details_box.label(
                text=(
                    "Standing-seam segments: "
                    f"{int(detail_obj.get('roof_forge_standing_segment_count', 0))}"
                ),
                icon="INFO",
            )
            detail_error = str(
                detail_obj.get("roof_forge_details_error", "")
            )
            if detail_error:
                details_box.alert = True
                details_box.label(text=detail_error[:140], icon="ERROR")


__all__ = ["ROOFFORGE_PT_panel"]
