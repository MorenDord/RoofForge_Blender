"""Blender background checks for the experimental vector plan overlay."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
extension = importlib.import_module(ROOT.name)
extension.register()

settings = bpy.context.scene.roof_forge
assert hasattr(settings, "plan_show_raster")
assert hasattr(settings, "plan_show_vector")
assert hasattr(bpy.types, "ROOFFORGE_PT_vector_preview")
assert bpy.types.ROOFFORGE_PT_vector_preview.bl_category == "Roof Plan"
assert settings.plan_show_raster is True
assert settings.plan_show_vector is False

plan = {
    "vertices": [[0.0, 0.0, 0.0], [4.0, 0.0, 0.0], [4.0, 3.0, 0.0], [0.0, 3.0, 0.0]],
    "faces": [[0, 1, 2], [0, 2, 3]],
    "face_slope_indices": [0, 1],
    "planes": [[0.0, 0.0, 0.0], [1.0, -4.0 / 3.0, 0.0]],
}
module = importlib.import_module(f"{extension.__name__}.addon.ui.vector_plan_preview")
prepared = module._prepare_geometry(plan)
assert len(prepared["edges"]) == 5
assert [label[0] for label in prepared["labels"]] == [1, 2]
assert prepared["bounds"] == (0.0, 0.0, 4.0, 3.0)

settings.roof_plan_json = json.dumps(plan)
settings.plan_show_raster = False
settings.plan_show_vector = True
assert module._DRAW_HANDLE is not None
assert module._DRAW_REGION_TYPE == "UI"
plan_preview = importlib.import_module(f"{extension.__name__}.addon.ui.plan_preview")
assert plan_preview.schedule_roof_plan_refresh(settings) is False
assert plan_preview._PENDING_JSON is None
settings.plan_show_raster = True
settings.plan_show_vector = True
settings.plan_show_raster = False
assert settings.plan_show_vector is True
settings.plan_show_vector = False
assert settings.plan_show_raster is False
module.unregister_vector_preview()
assert module._DRAW_HANDLE is None
extension.unregister()
print("RoofForge vector preview smoke tests passed")
