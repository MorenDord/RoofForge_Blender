"""Persistent per-scene and per-edge RoofForge settings."""
import bpy


def _pitch_changed(self, context):
    if context is None:
        return
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    settings = getattr(scene, "roof_forge", None)
    if settings is not None:
        settings.pitch_snap_status = ""
        try:
            if scene.get("_roofforge_syncing_slopes", False):
                return
        except (AttributeError, ReferenceError, RuntimeError):
            pass
    from .live_update import schedule_live_update
    schedule_live_update(scene)


def _settings_changed(self, context):
    if context is None:
        return
    from .live_update import schedule_live_update
    schedule_live_update(context.scene)


def _preview_changed(self, context):
    if context is None or context.scene is None:
        return
    from .ui.vector_plan_preview import tag_vector_preview_redraw
    tag_vector_preview_redraw()


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
    initial_pitch: bpy.props.FloatProperty(
        name="Initial Pitch",
        description="Pitch assigned to every contour edge when a new roof is first created",
        default=30.0,
        min=1.0,
        max=85.0,
        precision=1,
    )
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
    overhang_corner_convergence: bpy.props.BoolProperty(
        name="Converge Corners",
        description="Make neighbouring roof slopes meet at one point on each eave corner",
        default=True,
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
    outline_preview_json: bpy.props.StringProperty(default="", options={"HIDDEN"})
    roof_plan_json: bpy.props.StringProperty(
        name="Roof Plan Data", default="", options={"HIDDEN"}
    )
    plan_show_vector: bpy.props.BoolProperty(
        name="Show Roof Plan",
        description="Show the direct GPU roof-plan preview in the RoofForge sidebar",
        default=True,
        update=_preview_changed,
    )
    plan_debug_bounds: bpy.props.BoolProperty(
        name="Debug UI Bounds",
        description="Overlay Region, View2D, estimated preview-slot and GPU viewport bounds",
        default=False,
        update=_preview_changed,
    )
    plan_label_scale: bpy.props.FloatProperty(
        name="Plan Label Size",
        description="Adjust the size of facet numbers in the vector roof plan",
        default=1.0,
        min=0.6,
        max=1.8,
        precision=1,
        update=_preview_changed,
    )
    plan_line_width: bpy.props.FloatProperty(
        name="Line Thickness",
        description="Thickness of antialiased boundary and ridge lines in the vector roof plan",
        default=1.8,
        min=0.5,
        max=6.0,
        precision=1,
        update=_preview_changed,
    )
    source_object: bpy.props.PointerProperty(type=bpy.types.Object)
    generated_object: bpy.props.PointerProperty(type=bpy.types.Object)
    source_name_snapshot: bpy.props.StringProperty(default="")
    generated_name_snapshot: bpy.props.StringProperty(default="")
    last_status: bpy.props.StringProperty(default="")
    pitch_snap_status: bpy.props.StringProperty(
        name="Pitch Snap Status",
        default="",
        options={"HIDDEN"},
    )

    # Optional roof details, configured in scene units and converted through scale_length.
    show_ridges: bpy.props.BoolProperty(
        name="Create ridge profiles", description="Build separate raised profile meshes along convex roof joints",
        default=True, update=_settings_changed,
    )
    ridge_width_cm: bpy.props.FloatProperty(
        name="Ridge width (cm)", default=24.0, min=0.1, max=500.0,
        precision=2, update=_settings_changed,
    )
    ridge_extrusion_cm: bpy.props.FloatProperty(
        name="Ridge rise (cm)", default=2.0, min=0.01, max=100.0,
        precision=2, update=_settings_changed,
    )
    ridge_end_offset_cm: bpy.props.FloatProperty(
        name="Ridge end offset (cm)", description="Positive extends beyond the roof boundary; negative retracts inward",
        default=0.0, min=-500.0, max=500.0, precision=2, update=_settings_changed,
    )
    show_valleys: bpy.props.BoolProperty(
        name="Create valley profiles", description="Build separate raised profile meshes along concave roof joints",
        default=True, update=_settings_changed,
    )
    valley_width_cm: bpy.props.FloatProperty(
        name="Valley width (cm)", default=24.0, min=0.1, max=500.0,
        precision=2, update=_settings_changed,
    )
    valley_extrusion_cm: bpy.props.FloatProperty(
        name="Valley rise (cm)", default=1.0, min=0.01, max=100.0,
        precision=2, update=_settings_changed,
    )
    valley_end_offset_cm: bpy.props.FloatProperty(
        name="Valley end offset (cm)", description="Positive extends beyond the roof boundary; negative retracts inward",
        default=0.0, min=-500.0, max=500.0, precision=2, update=_settings_changed,
    )
    show_standing_seams: bpy.props.BoolProperty(
        name="Create standing seams", description="Generate light folded seam ribs across each roof facet",
        default=False, update=_settings_changed,
    )
    standing_panel_width_cm: bpy.props.FloatProperty(
        name="Panel width (cm)", default=60.0, min=20.0, max=500.0,
        precision=1, update=_settings_changed,
    )
    standing_seam_height_cm: bpy.props.FloatProperty(
        name="Fold height (cm)", default=3.0, min=0.1, max=50.0,
        precision=2, update=_settings_changed,
    )
    standing_seam_width_cm: bpy.props.FloatProperty(
        name="Fold base width (cm)", default=1.4, min=0.1, max=10.0,
        precision=2, update=_settings_changed,
    )
    standing_end_offset_cm: bpy.props.FloatProperty(
        name="Seam end offset (cm)", description="Positive extends beyond the roof boundary; negative retracts inward",
        default=0.0, min=-500.0, max=500.0, precision=2, update=_settings_changed,
    )

