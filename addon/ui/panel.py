"""RoofForge sidebar with a numbered top-view pitch plan."""
import json

import bpy

from .plan_preview import get_contour_plan_icon


class ROOFFORGE_PT_panel(bpy.types.Panel):
    bl_label = "RoofForge"
    bl_idname = "ROOFFORGE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RoofForge"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.roof_forge
        source = context.object

        col = layout.column(align=True)
        col.label(text="Roof boundary")
        col.label(text="Active mesh object; no vertex/edge selection")
        col.operator("roof_forge.prepare_slopes", icon="EDGESEL")

        if settings.slope_settings:
            plan_box = layout.box()
            plan_box.label(
                text="Top view — numbers match Pitch fields",
                icon="MESH_CIRCLE",
            )
            try:
                outline = json.loads(settings.outline_preview_json)
            except (TypeError, ValueError):
                outline = []
            if len(outline) >= 3:
                preview_icon = get_contour_plan_icon(
                    outline,
                    text_scale=settings.plan_label_scale,
                )
                if preview_icon:
                    region_width = max(240, getattr(context.region, "width", 320))
                    preview_scale = max(4.0, min(14.0, region_width / 42.0))
                    plan_box.template_icon(preview_icon, scale=preview_scale)
                else:
                    plan_box.label(text="Could not draw contour plan", icon="INFO")
            else:
                plan_box.label(
                    text="Load / Refresh Slope Angles to create the numbered plan",
                    icon="INFO",
                )
            plan_box.prop(
                settings,
                "plan_label_scale",
                text="Number size",
                slider=True,
            )
            plan_box.label(text="Edge number = matching Pitch field below")

            pitch_box = layout.box()
            pitch_box.label(
                text=f"Individual slope pitch ({len(settings.slope_settings)})"
            )
            for item in settings.slope_settings:
                row = pitch_box.row(align=True)
                row.label(
                    text=f"Edge {item.edge_index + 1:02d} "
                         f"(V{item.start_vertex_index + 1}→V{item.end_vertex_index + 1})"
                )
                row.prop(item, "pitch", text="°")
            pitch_box.label(
                text="Edit Pitch directly; no Edit Mode selection needed",
                icon="INFO",
            )

        col.separator()
        col.label(text="Solid roof shell")
        col.prop(settings, "thickness_cm", text="Thickness (cm)")
        col.prop(settings, "eave_overhang_cm", text="Eave Overhang (cm)")
        col.prop(settings, "live_update")
        delay_row = col.row()
        delay_row.enabled = settings.live_update
        delay_row.prop(
            settings,
            "live_update_delay_ms",
            text="Update delay (ms)",
            slider=True,
        )
        if settings.live_update_delay_ms == 0:
            delay_row.label(text="No debounce", icon="TIME")
        col.operator("roof_forge.generate_surface", icon="MESH_CUBE")

        if settings.last_status:
            status = layout.box()
            status.label(text=settings.last_status[:110], icon="INFO")

        if source is not None and source.type == "MESH":
            col.separator()
            col.label(text="Flat-Z: weighted wavefront")
            col.label(text="Mixed-Z: 3D plane envelope")
            col.label(text="Overhang: one offset contour")
        else:
            col.label(text="Select a mesh object to begin", icon="INFO")
