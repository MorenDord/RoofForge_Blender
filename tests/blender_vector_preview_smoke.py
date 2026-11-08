"""Blender background checks for the direct vector roof-plan renderer."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
extension = importlib.import_module(ROOT.name)
assert extension.bl_info["version"] == (0, 3, 1)
extension.register()

settings = bpy.context.scene.roof_forge
assert not hasattr(settings, "plan_show_raster")
assert hasattr(settings, "plan_show_vector")
assert hasattr(settings, "initial_pitch")
assert hasattr(bpy.types, "ROOFFORGE_PT_main")
assert not hasattr(bpy.types, "ROOFFORGE_PT_vector_preview")
assert settings.plan_show_vector is True
assert abs(settings.initial_pitch - 30.0) < 1.0e-7

module = importlib.import_module(f"{extension.__name__}.addon.ui.vector_plan_preview")
assert module._PANEL_CATEGORY == "RoofForge"
assert module._DRAW_REGION_TYPE == "UI"
assert module._LINE_SHADER_NAME == "POLYLINE_UNIFORM_COLOR"
assert module._PANEL_TOP_RESERVED == 152
assert module._PANEL_MAX_SIZE == 140

plan = {
    "vertices": [[0.0, 0.0, 0.0], [4.0, 0.0, 0.0], [4.0, 3.0, 0.0], [0.0, 3.0, 0.0]],
    "faces": [[0, 1, 2], [0, 2, 3]],
    "face_slope_indices": [0, 1],
    "planes": [[0.0, 0.0, 0.0], [1.0, -4.0 / 3.0, 0.0]],
}
prepared = module._prepare_geometry(plan)
assert len(prepared["edges"]) == 5
assert [label[0] for label in prepared["labels"]] == [1, 2]
assert prepared["bounds"] == (0.0, 0.0, 4.0, 3.0)

# Area-weighted labels remain at the same position when a slope is split into
# different-sized faces during an update.
def split_rectangle(split_x):
    return {
        "vertices": [
            [0.0, 0.0, 0.0], [split_x, 0.0, 0.0], [10.0, 0.0, 0.0],
            [10.0, 4.0, 0.0], [split_x, 4.0, 0.0], [0.0, 4.0, 0.0],
        ],
        "faces": [[0, 1, 4, 5], [1, 2, 3, 4]],
        "face_slope_indices": [0, 0],
        "planes": [[0.0, 0.0, 0.0]],
    }

center_a = module._prepare_geometry(split_rectangle(4.0))["labels"][0][1]
center_b = module._prepare_geometry(split_rectangle(6.0))["labels"][0][1]
assert abs(center_a[0] - 5.0) < 1.0e-7
assert abs(center_b[0] - 5.0) < 1.0e-7
assert abs(center_a[1] - center_b[1]) < 1.0e-7

# Layout centres the actual model bounding box and hides the canvas before it
# could spill into the adjacent editor when the sidebar becomes too narrow.
assert module._compute_canvas_layout(72, 900, (0.0, 0.0, 4.0, 3.0)) is None
layout = module._compute_canvas_layout(320, 900, (-2.0, 1.0, 8.0, 6.0))
assert layout is not None
center_x = layout["origin_x"] + (3.0 - (-2.0)) * layout["scale"]
center_y = layout["origin_y"] + (3.5 - 1.0) * layout["scale"]
assert abs(center_x - layout["target_center"][0]) < 1.0e-7
assert abs(center_y - layout["target_center"][1]) < 1.0e-7
assert layout["side"] <= module._PANEL_MAX_SIZE
assert layout["target_center"][1] < 900.0 - module._PANEL_TOP_RESERVED

assert not module._is_panel_scrolled(
    type("Region", (), {"view2d": type("View2D", (), {
        "cur": type("Rect", (), {"ymax": 100.0})(),
        "tot": type("Rect", (), {"ymax": 100.0})(),
    })()})()
)
assert module._is_panel_scrolled(
    type("Region", (), {"view2d": type("View2D", (), {
        "cur": type("Rect", (), {"ymax": 75.0})(),
        "tot": type("Rect", (), {"ymax": 100.0})(),
    })()})()
)

settings.roof_plan_json = json.dumps(plan)
assert module._DRAW_HANDLE is not None
settings.plan_show_vector = False
settings.plan_show_vector = True

# Initial pitch is consumed only when a source contour is first initialized.
source_mesh = bpy.data.meshes.new("RoofForge_InitialPitchSmoke_Mesh")
source_mesh.from_pydata(
    [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
    [(0, 1), (1, 2), (2, 3), (3, 0)],
    [],
)
source = bpy.data.objects.new("RoofForge_InitialPitchSmoke", source_mesh)
bpy.context.scene.collection.objects.link(source)
settings.initial_pitch = 42.5
roof_build = importlib.import_module(f"{extension.__name__}.addon.roof_build")
assert roof_build.sync_slope_settings(settings, source, 4) is True
assert all(abs(item.pitch - 42.5) < 1.0e-7 for item in settings.slope_settings)
# Changing the initial value must not overwrite already-prepared per-edge edits.
settings.slope_settings[0].pitch = 38.0
settings.initial_pitch = 27.0
assert abs(settings.slope_settings[0].pitch - 38.0) < 1.0e-7

settings.generated_object = None
settings.roof_plan_json = ""
module.unregister_vector_preview()
assert module._DRAW_HANDLE is None
extension.unregister()
print("RoofForge vector preview smoke tests passed")
