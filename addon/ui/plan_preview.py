"""Blender preview-icon lifecycle for the numbered contour plan."""
from __future__ import annotations

import os
import tempfile

import bpy
import bpy.utils.previews

from ...core.plan_preview import render_contour_plan_png

_PREVIEWS = None
_PREVIEW_PATH = None
_PREVIEW_SIGNATURE = None
_PREVIEW_KEY = "roof_forge_contour_plan"


def get_contour_plan_icon(points, text_scale: float = 1.0) -> int:
    """Return a cached Blender preview icon for the current ordered contour."""
    global _PREVIEWS, _PREVIEW_PATH, _PREVIEW_SIGNATURE
    if not points or len(points) < 3:
        return 0

    signature = (
        tuple(tuple(round(float(value), 7) for value in point[:3]) for point in points),
        round(float(text_scale), 3),
    )
    if _PREVIEWS is not None and signature == _PREVIEW_SIGNATURE:
        try:
            if _PREVIEW_KEY in _PREVIEWS:
                return _PREVIEWS[_PREVIEW_KEY].icon_id
        except (ReferenceError, RuntimeError):
            _PREVIEWS = None
            _PREVIEW_PATH = None
            _PREVIEW_SIGNATURE = None

    try:
        png = render_contour_plan_png(points, size=256, text_scale=text_scale)
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
    except (OSError, ValueError, RuntimeError, ReferenceError):
        return 0


def clear_contour_plan_preview() -> None:
    """Release the Blender preview collection and its temporary PNG."""
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
