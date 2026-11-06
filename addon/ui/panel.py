"""RoofForge sidebar panel."""
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
        col = layout.column(align=True)
        col.label(text="Roof boundary")
        col.label(text="Select one closed edge loop in Edit Mode")
        col.prop(settings, "pitch_default")

        col.separator()
        col.label(text="Solid shell")
        col.prop(settings, "thickness")
        col.operator("roof_forge.validate_input", icon="CHECKMARK")
        col.operator("roof_forge.generate_surface", icon="MESH_CUBE")

        col.separator()
        col.label(text="Thickness is extruded along local -Z", icon="INFO")
        col.label(text="Per-slope pitch map and live link are next")
