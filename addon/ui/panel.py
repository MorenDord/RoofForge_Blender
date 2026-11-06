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
        col.label(text="Roof input")
        col.prop(settings, "pitch_default")
        col.prop(settings, "overhang")
        col.prop(settings, "thickness")
        col.prop(settings, "live_update")
        col.operator("roof_forge.validate_input", icon="CHECKMARK")
        layout.label(text="1.0 development scaffold", icon="INFO")
