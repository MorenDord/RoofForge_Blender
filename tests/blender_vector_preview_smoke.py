"""Blender background checks for the always-visible vector roof-plan UI."""
from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
extension = importlib.import_module(ROOT.name)
assert extension.bl_info["version"] == (0, 4, 2)
extension.register()

settings = bpy.context.scene.roof_forge
assert not hasattr(settings, "plan_show_vector")
assert not hasattr(settings, "plan_debug_bounds")
assert hasattr(settings, "plan_label_scale")
assert hasattr(settings, "plan_line_width")
assert settings.live_update_delay_ms == 250
assert settings.overhang_corner_convergence is True
assert hasattr(bpy.types, "ROOFFORGE_PT_main")
assert not hasattr(bpy.ops.roof_forge, "copy_preview_debug")

registration_module = importlib.import_module(
    f"{extension.__name__}.addon.registration"
)
assert all(
    "copy_preview_debug" not in cls.__name__.lower()
    for cls in registration_module._CLASSES
)

module = importlib.import_module(
    f"{extension.__name__}.addon.ui.vector_plan_preview"
)
assert module._PANEL_CATEGORY == "RoofForge"
assert module._DRAW_REGION_TYPE == "UI"
assert module._LINE_SHADER_NAME == "POLYLINE_UNIFORM_COLOR"
assert module._PREVIEW_SLOT_TOP_UNITS == 4.0
assert module._DRAW_HANDLE is not None
assert not hasattr(module, "_build_debug_message")
assert not hasattr(module, "_draw_debug_overlay")
assert not hasattr(module, "get_preview_debug_message")

panel_module = importlib.import_module(
    f"{extension.__name__}.addon.ui.panel"
)
draw_code = panel_module.ROOFFORGE_PT_panel.draw.__code__
assert "box" in draw_code.co_names
assert "template_icon" in draw_code.co_names
assert "set_preview_slot_visible" in draw_code.co_names
assert "layout.panel" not in draw_code.co_names
assert "plan_show_vector" not in draw_code.co_consts
assert "plan_debug_bounds" not in draw_code.co_consts
assert "roof_forge.copy_preview_debug" not in draw_code.co_consts
assert "roof_forge_plan_preview" not in draw_code.co_consts
assert "roof_forge_details" not in draw_code.co_consts

# The preview draw handler is no longer gated by a Show Preview property or
# by any debug state. Its only per-region gate is the actual visible UI slot.
draw_names = module._draw_vector_preview.__code__.co_names
assert "plan_show_vector" not in draw_names
assert "plan_debug_bounds" not in draw_names
assert "_build_debug_message" not in draw_names
assert "_draw_debug_overlay" not in draw_names
assert "_is_preview_slot_visible" in draw_names

fake_region = type("Region", (), {"as_pointer": lambda self: 4242})()
module.set_preview_slot_visible(fake_region, True)
assert module._is_preview_slot_visible(fake_region)
module.set_preview_slot_visible(fake_region, False)
assert not module._is_preview_slot_visible(fake_region)

# Roof-plan topology and labels still come from the shared geometry pipeline.
plan = {
    "vertices": [
        [0.0, 0.0, 0.0],
        [4.0, 0.0, 0.0],
        [4.0, 3.0, 0.0],
        [0.0, 3.0, 0.0],
    ],
    "faces": [[0, 1, 2], [0, 2, 3]],
    "face_slope_indices": [0, 1],
    "planes": [[0.0, 0.0, 0.0], [1.0, -4.0 / 3.0, 0.0]],
}
prepared = module._prepare_geometry(plan)
assert len(prepared["edges"]) == 5
assert [label[0] for label in prepared["labels"]] == [1, 2]
assert prepared["bounds"] == (0.0, 0.0, 4.0, 3.0)

assert module.preview_category_rail_side(
    SimpleNamespace(alignment="RIGHT")
) == "RIGHT"
assert module.preview_category_rail_side(
    SimpleNamespace(alignment="LEFT")
) == "LEFT"
assert module.preview_category_rail_side(
    SimpleNamespace(alignment="NONE")
) == "RIGHT"

layout = module._compute_canvas_layout(
    320, 900, (-2.0, 1.0, 8.0, 6.0),
    ui_scale=1.0, widget_unit=20.0,
)
assert layout is not None
assert abs(module.preview_category_rail_width(20.0) - 20.0) < 1e-7
assert abs(layout["panel_content_width"] - 300.0) < 1e-7
assert layout["category_rail_side"] == "RIGHT"
assert module._translate_scissor(
    layout["scissor"], (100, 200, 320, 900)
) == (
    layout["scissor"][0] + 100,
    layout["scissor"][1] + 200,
    layout["scissor"][2],
    layout["scissor"][3],
)

settings.roof_plan_json = json.dumps(plan)
assert module._DRAW_HANDLE is not None
assert settings.plan_label_scale == 1.0
assert settings.plan_line_width == 1.8

# Initial pitch is consumed only when a source contour is first initialized.
source_mesh = bpy.data.meshes.new("RoofForge_InitialPitchSmoke_Mesh")
source_mesh.from_pydata(
    [
        (0.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
        (4.0, 3.0, 0.0),
        (0.0, 3.0, 0.0),
    ],
    [(0, 1), (1, 2), (2, 3), (3, 0)],
    [],
)
source = bpy.data.objects.new("RoofForge_InitialPitchSmoke", source_mesh)
bpy.context.scene.collection.objects.link(source)
settings.initial_pitch = 42.5
roof_build = importlib.import_module(
    f"{extension.__name__}.addon.roof_build"
)
assert roof_build.sync_slope_settings(settings, source, 4) is True
assert all(
    abs(item.pitch - 42.5) < 1e-7
    for item in settings.slope_settings
)
settings.slope_settings[0].pitch = 38.0
settings.initial_pitch = 27.0
assert abs(settings.slope_settings[0].pitch - 38.0) < 1e-7

settings.generated_object = None
settings.roof_plan_json = ""
module.unregister_vector_preview()
assert module._DRAW_HANDLE is None
extension.unregister()
extension.unregister()
print("ROOFFORGE_VECTOR_PREVIEW_SMOKE_OK")
