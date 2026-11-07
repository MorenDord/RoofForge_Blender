"""Blender preview-icon lifecycle for the generated roof facet plan."""
from __future__ import annotations

import json
import os
import tempfile

import bpy
import bpy.utils.previews

from ...core.plan_preview import render_roof_plan_png

_PREVIEWS = None
_PREVIEW_PATH = None
_PREVIEW_SIGNATURE = None
_PREVIEW_KEY = "roof_forge_roof_plan"


def get_roof_plan_icon(plan_data, text_scale: float = 1.0, line_width: float = 1.8) -> int:
    """Return a cached transparent PNG preview of the actual roof facets."""
    global _PREVIEWS, _PREVIEW_PATH, _PREVIEW_SIGNATURE
    if not isinstance(plan_data, dict) or not plan_data.get("faces"):
        return 0

    try:
        signature = (
            json.dumps(plan_data, sort_keys=True, separators=(",", ":")),
            round(float(text_scale), 3),
            round(float(line_width), 3),
        )
        if _PREVIEWS is not None and signature == _PREVIEW_SIGNATURE:
            try:
                if _PREVIEW_KEY in _PREVIEWS:
                    return _PREVIEWS[_PREVIEW_KEY].icon_id
            except (ReferenceError, RuntimeError):
                _PREVIEWS = None
                _PREVIEW_PATH = None
                _PREVIEW_SIGNATURE = None

        png = render_roof_plan_png(
            plan_data, size=512, text_scale=text_scale, line_width=line_width
        )
        if _PREVIEWS is None:
            _PREVIEWS = bpy.utils.previews.new()
        if _PREVIEW_PATH is None:
            handle, _PREVIEW_PATH = tempfile.mkstemp(
                prefix="roof_forge_plan_", suffix=".png"
            )
            os.close(handle)
        with open(_PREVIEW_PATH, "wb") as file:
            file.write(png)
        if _PREVIEW_KEY in _PREVIEWS:
            del _PREVIEWS[_PREVIEW_KEY]
        _PREVIEWS.load(_PREVIEW_KEY, _PREVIEW_PATH, "IMAGE")
        _PREVIEW_SIGNATURE = signature
        return _PREVIEWS[_PREVIEW_KEY].icon_id
    except (OSError, TypeError, ValueError, RuntimeError, ReferenceError):
        return 0


def clear_contour_plan_preview() -> None:
    """Release the preview collection and its temporary PNG."""
    global _PREVIEWS, _PREVIEW_PATH, _PREVIEW_SIGNATURE
    if _PREVIEWS is not None:
        try:
            bpy.utils.previews.remove(_PREVIEWS)
        except (ReferenceError, RuntimeError, ValueError):
            pass
    _PREVIEWS = None
    if _PREVIEW_PATH:
        try:
            os.remove(_PREVIEW_PATH)
        except OSError:
            pass
    _PREVIEW_PATH = None
    _PREVIEW_SIGNATURE = None
