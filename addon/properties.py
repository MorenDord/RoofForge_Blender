"""Persistent per-scene and per-edge RoofForge settings."""
import bpy


def _pitch_changed(self, context):
    if context is None:
        return
    from .live_update import schedule_live_update
    schedule_live_update(context.scene)


def _settings_changed(self, context):
    if context is None:
        return
    from .live_update import schedule_live_update
    schedule_live_update(context.scene)


class RoofForgeSlopeSettings(bpy.types.PropertyGroup):
    edge_index: bpy.props.IntProperty(name="Edge Index", default=0, min=0)
    start_vertex_index: bpy.props.IntProperty(name="Start Vertex", default=0, min=0)
    end_vertex_index: bpy.props.IntProperty(name="End Vertex", default=1, min=0)
    pitch: bpy.props.FloatProperty(
        name="Pitch",
        description="Inclination angle for this boundary edge",
        default=35.0,
        min=1.0,
        max=85.0,
        precision=1,
        update=_pitch_changed,
    )


class RoofForgeSettings(bpy.types.PropertyGroup):
    pitch_default: bpy.props.FloatProperty(
        name="Default Pitch",
        description="Default angle used when a new contour is loaded",
        default=35.0,
        min=1.0,
        max=85.0,
        precision=1,
    )
    thickness: bpy.props.FloatProperty(
        name="Thickness",
        default=0.12,
        min=0.001,
        soft_max=1.0,
        unit="LENGTH",
        update=_settings_changed,
    )
    eave_overhang: bpy.props.FloatProperty(
        name="Eave Overhang",
        description="Horizontal extension of the roof beyond a convex source boundary",
        default=0.0,
        min=0.0,
        soft_max=1.0,
        unit="LENGTH",
        update=_settings_changed,
    )
    live_update: bpy.props.BoolProperty(name="Live Update", default=True)
    slope_settings: bpy.props.CollectionProperty(type=RoofForgeSlopeSettings)
    source_object: bpy.props.PointerProperty(type=bpy.types.Object)
    generated_object: bpy.props.PointerProperty(type=bpy.types.Object)
    source_name_snapshot: bpy.props.StringProperty(default="")
    generated_name_snapshot: bpy.props.StringProperty(default="")
    last_status: bpy.props.StringProperty(default="")
