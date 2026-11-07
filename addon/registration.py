"""Registration entry point."""
import bpy

from .properties import RoofForgeSettings, RoofForgeSlopeSettings
from .operators import (
    ROOFFORGE_OT_generate_surface,
    ROOFFORGE_OT_prepare_slopes,
    ROOFFORGE_OT_select_slope_edge,
)
from .ui.panel import ROOFFORGE_PT_panel
from .live_update import cancel_pending_live_update
from .roof_build import clear_surface_cache

_CLASSES = (
    RoofForgeSlopeSettings,
    RoofForgeSettings,
    ROOFFORGE_OT_prepare_slopes,
    ROOFFORGE_OT_select_slope_edge,
    ROOFFORGE_OT_generate_surface,
    ROOFFORGE_PT_panel,
)


def register():
    for cls in _CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass
    if not hasattr(bpy.types.Scene, "roof_forge"):
        bpy.types.Scene.roof_forge = bpy.props.PointerProperty(type=RoofForgeSettings)


def unregister():
    cancel_pending_live_update()
    clear_surface_cache()
    if hasattr(bpy.types.Scene, "roof_forge"):
        del bpy.types.Scene.roof_forge
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
