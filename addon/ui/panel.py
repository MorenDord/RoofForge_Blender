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
        col.operator("roof_forge.validate_input", icon="CHECKMARK")
        col.operator("roof_forge.generate_surface", icon="MESH_PLANE")

        col.separator()
        col.label(text="Alpha: open upper surface only", icon="INFO")
        col.label(text="No thickness, overhang or live link yet")
