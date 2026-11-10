"""Blender background checks for the direct vector roof-plan renderer."""
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
assert extension.bl_info["version"] == (0, 3, 8)
extension.register()

settings = bpy.context.scene.roof_forge
assert not hasattr(settings, "plan_show_raster")
assert hasattr(settings, "plan_show_vector")
assert hasattr(settings, "initial_pitch")
assert hasattr(bpy.types, "ROOFFORGE_PT_main")
assert hasattr(bpy.types, "ROOFFORGE_OT_copy_preview_debug")
assert not hasattr(bpy.types, "ROOFFORGE_PT_plan_preview")
assert not hasattr(bpy.types, "ROOFFORGE_PT_settings")
assert not hasattr(bpy.types, "ROOFFORGE_PT_vector_preview")
assert settings.plan_show_vector is True
assert settings.plan_debug_bounds is False
assert abs(settings.initial_pitch - 30.0) < 1.0e-7

module = importlib.import_module(f"{extension.__name__}.addon.ui.vector_plan_preview")
assert module._PANEL_CATEGORY == "RoofForge"
assert module._DRAW_REGION_TYPE == "UI"
assert module._LINE_SHADER_NAME == "POLYLINE_UNIFORM_COLOR"
assert module._PREVIEW_SLOT_TOP_UNITS == 4.0
assert "scissor_set" in module._draw_vector_preview.__code__.co_names
assert "scissor_test_set" in module._draw_vector_preview.__code__.co_names
assert "viewport_get" in module._draw_vector_preview.__code__.co_names
assert "_build_debug_message" in module._draw_vector_preview.__code__.co_names
assert "_draw_debug_overlay" in module._draw_vector_preview.__code__.co_names
assert "set_preview_slot_visible" in module._draw_vector_preview.__code__.co_names
panel_module = importlib.import_module(f"{extension.__name__}.addon.ui.panel")
assert "panel" in panel_module.ROOFFORGE_PT_panel.draw.__code__.co_names
assert "template_icon" in panel_module.ROOFFORGE_PT_panel.draw.__code__.co_names
assert "set_preview_slot_visible" in panel_module.ROOFFORGE_PT_panel.draw.__code__.co_names
assert "plan_debug_bounds" in panel_module.ROOFFORGE_PT_panel.draw.__code__.co_names
assert "copy_preview_debug" in panel_module.ROOFFORGE_PT_panel.draw.__code__.co_names
assert "set_preview_slot_visible" in panel_module.ROOFFORGE_PT_panel.draw_header.__code__.co_names
fake_region = type("Region", (), {"as_pointer": lambda self: 4242})()
module.set_preview_slot_visible(fake_region, True)
assert module._is_preview_slot_visible(fake_region)
module.set_preview_slot_visible(fake_region, False)
assert not module._is_preview_slot_visible(fake_region)
assert "initial_pitch" in panel_module.ROOFFORGE_PT_panel.draw.__code__.co_names

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

# template_icon reserves U.widget_unit * scale. The previous 32px assumption
# made the GPU square larger than the real UI item and shifted it to the right.
assert module.estimate_widget_unit(1.333) == 27
assert module.preview_icon_scale(72, widget_unit=20.0) is None
layout = module._compute_canvas_layout(
    320, 900, (-2.0, 1.0, 8.0, 6.0), ui_scale=1.0, widget_unit=20.0
)
wider_layout = module._compute_canvas_layout(
    420, 900, (-2.0, 1.0, 8.0, 6.0), ui_scale=1.0, widget_unit=20.0
)
assert layout is not None and wider_layout is not None
assert abs(layout["slot_side"] - 185.0) < 1.0e-7
assert abs(layout["icon_scale"] - (296.0 / 32.0)) < 1.0e-7
assert abs(layout["slot_left"] - 8.0) < 1.0e-7
assert abs(layout["slot_top"] - 820.0) < 1.0e-7
assert abs(layout["slot_bottom"] - 635.0) < 1.0e-7
assert abs(layout["margin"] - layout["draw_side"] * 0.075) < 1.0e-7
center_x = layout["origin_x"] + (3.0 - (-2.0)) * layout["scale"]
center_y = layout["origin_y"] + (3.5 - 1.0) * layout["scale"]
assert abs(center_x - layout["target_center"][0]) < 1.0e-7
assert abs(center_y - layout["target_center"][1]) < 1.0e-7
assert abs(layout["target_center"][0] - 100.5) < 1.0e-7
assert abs(layout["target_center"][1] - 727.5) < 1.0e-7
assert layout["scissor"] == (8, 635, 185, 185)
assert module._translate_scissor(
    layout["scissor"], (100, 200, 320, 900)
) == (108, 835, 185, 185)
assert abs(layout["draw_side"] - 169.0) < 1.0e-7
assert wider_layout["slot_side"] > layout["slot_side"]
assert wider_layout["scale"] > layout["scale"]
assert abs(wider_layout["target_center"][0] - 131.75) < 1.0e-7
assert abs(wider_layout["target_center"][1] - 696.25) < 1.0e-7

fake_view2d = type("View2D", (), {
    "region_to_view": lambda self, x, y: (x / 2.0, y / 4.0),
    "view_to_region": lambda self, x, y, clip=True: (round(x * 2.0), round(y * 4.0)),
})()
fake_region = type("Region", (), {
    "width": 100,
    "height": 50,
    "x": 1729,
    "y": 29,
    "view2d": fake_view2d,
    "as_pointer": lambda self: 4242,
})()
mapping, mapping_error = module._view2d_mapping_info(fake_region)
assert mapping_error is None
assert mapping["bottom_left_view"] == (0.0, 0.0)
assert mapping["top_right_view"] == (49.5, 12.25)
assert mapping["bottom_left_pixel"] == (0, 0)
assert mapping["top_right_pixel"] == (99, 49)

message = module._build_debug_message(
    SimpleNamespace(scene=bpy.context.scene),
    fake_region,
    layout,
    (0, 0, 100, 50),
    1.25,
)
assert "ROOFFORGE PREVIEW DEBUG" in message
assert "Region: 100x50 @ 1729,29" in message
assert "View2D error:" not in message
assert "View2D roundtrip pixels TR: 99.000,49.000" in message
module._PREVIEW_DEBUG_MESSAGES[4242] = message
assert module.get_preview_debug_message(fake_region) == message

class FakeOperator:
    def report(self, levels, text):
        self.last_report = (levels, text)

fake_operator = FakeOperator()
fake_context = SimpleNamespace(
    region=fake_region,
    window_manager=SimpleNamespace(clipboard=""),
)
copy_operator = bpy.types.ROOFFORGE_OT_copy_preview_debug
assert copy_operator.execute(fake_operator, fake_context) == {"FINISHED"}
assert fake_context.window_manager.clipboard == message
assert fake_operator.last_report[0] == {"INFO"}
module._PREVIEW_DEBUG_MESSAGES.pop(4242, None)

scroll_state = {"offset_y": 0.0}
scroll_view2d = type("View2D", (), {
    "region_to_view": lambda self, x, y: (x, y + scroll_state["offset_y"]),
})()
scroll_region = type("Region", (), {
    "width": 300,
    "height": 100,
    "view2d": scroll_view2d,
    "as_pointer": lambda self: 5151,
})()
assert not module._is_panel_scrolled(scroll_region)
scroll_state["offset_y"] = -25.0
assert module._is_panel_scrolled(scroll_region)
scroll_state["offset_y"] = 0.0
assert not module._is_panel_scrolled(scroll_region)
assert "cur" not in module._is_panel_scrolled.__code__.co_names
assert "tot" not in module._is_panel_scrolled.__code__.co_names

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
print("ROOFFORGE_VECTOR_PREVIEW_SMOKE_OK")
