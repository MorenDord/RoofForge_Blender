"""Persistent scene settings."""
import bpy


class RoofForgeSettings(bpy.types.PropertyGroup):
    pitch_default: bpy.props.FloatProperty(
        name="Default Pitch", description="Default slope angle",
        default=35.0, min=1.0, max=85.0, subtype="ANGLE", unit="ROTATION"
    )
    overhang: bpy.props.FloatProperty(
        name="Overhang", default=0.30, min=0.0, soft_max=2.0, unit="LENGTH"
    )
    thickness: bpy.props.FloatProperty(
        name="Thickness", default=0.12, min=0.001, soft_max=1.0, unit="LENGTH"
    )
    live_update: bpy.props.BoolProperty(name="Live Update", default=True)
