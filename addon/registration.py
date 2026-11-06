"""Registration entry point."""
import bpy

from .properties import RoofForgeSettings
from .operators import ROOFFORGE_OT_generate_surface, ROOFFORGE_OT_validate_input
from .ui.panel import ROOFFORGE_PT_panel

_CLASSES = (
    RoofForgeSettings,
    ROOFFORGE_OT_validate_input,
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
    if hasattr(bpy.types.Scene, "roof_forge"):
        del bpy.types.Scene.roof_forge
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
