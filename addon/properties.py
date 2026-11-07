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
        default=30.0,
        min=1.0,
        max=85.0,
        precision=1,
        update=_pitch_changed,
    )


class RoofForgeSettings(bpy.types.PropertyGroup):
    thickness_cm: bpy.props.FloatProperty(
        name="Thickness",
        description="Roof shell thickness in centimeters",
        default=1.0,
        min=0.01,
        soft_max=100.0,
        precision=2,
        update=_settings_changed,
    )
    eave_overhang_cm: bpy.props.FloatProperty(
        name="Eave Overhang",
        description="Horizontal roof extension in centimeters",
        default=0.0,
        min=0.0,
        soft_max=100.0,
        precision=2,
        update=_settings_changed,
    )
    live_update_delay_ms: bpy.props.IntProperty(
        name="Update Delay",
        description="Debounce before a live rebuild; 0 runs on the next Blender timer tick",
        default=0,
        min=0,
        max=1000,
        step=10,
    )
    live_update: bpy.props.BoolProperty(name="Live Update", default=True)
    slope_settings: bpy.props.CollectionProperty(type=RoofForgeSlopeSettings)
    source_object: bpy.props.PointerProperty(type=bpy.types.Object)
    generated_object: bpy.props.PointerProperty(type=bpy.types.Object)
    source_name_snapshot: bpy.props.StringProperty(default="")
    generated_name_snapshot: bpy.props.StringProperty(default="")
    last_status: bpy.props.StringProperty(default="")
