"""RoofForge 0.2.0 alpha sidebar panel."""
import bpy


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
            box = layout.box()
            box.label(text=f"Individual slope pitch ({len(settings.slope_settings)})")
            for item in settings.slope_settings:
                row = box.row(align=True)
                row.label(
                    text=f"Edge {item.edge_index + 1:02d} "
                         f"(V{item.start_vertex_index + 1}→V{item.end_vertex_index + 1})"
                )
                show = row.operator(
                    "roof_forge.select_slope_edge",
                    text="Show",
                    icon="EDGESEL",
                )
                show.edge_index = item.edge_index
                row.prop(item, "pitch", text="°")
            box.label(text="Show selects the matching source edge in Edit Mode")

        col.separator()
        col.label(text="Solid roof shell")
        col.prop(settings, "thickness_cm", text="Thickness (cm)")
        col.prop(settings, "eave_overhang_cm", text="Eave Overhang (cm)")
        col.prop(settings, "live_update")
        delay_row = col.row()
        delay_row.enabled = settings.live_update
        delay_row.prop(
            settings, "live_update_delay_ms",
            text="Update delay (ms)", slider=True,
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
