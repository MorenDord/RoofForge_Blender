"""Deferred Blender preview-icon lifecycle for the generated roof plan.

The expensive raster renderer never runs inside a panel draw callback. Geometry
updates keep displaying the previous cached icon; a new icon is rendered once
after the latest geometry/style edit has been quiet for the debounce interval.
"""
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
_PENDING_JSON = None
_PENDING_TEXT_SCALE = 1.0
_PENDING_LINE_WIDTH = 1.8
_PREVIEW_TIMER_DELAY = 0.75


def _signature(plan_json: str, text_scale: float, line_width: float):
    return (
        plan_json,
        round(float(text_scale), 3),
        round(float(line_width), 3),
    )


def _has_cached_icon() -> bool:
    if _PREVIEWS is None:
        return False
    try:
        return _PREVIEW_KEY in _PREVIEWS
    except (ReferenceError, RuntimeError):
        return False


def get_roof_plan_icon(*_args, **_kwargs) -> int:
    """Return the last completed preview icon; never render during panel draw."""
    if not _has_cached_icon():
        return 0
    try:
        return int(_PREVIEWS[_PREVIEW_KEY].icon_id)
    except (KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def _tag_view3d_redraw() -> None:
    try:
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def refresh_roof_plan_icon(
    plan_data,
    text_scale: float = 1.0,
    line_width: float = 1.8,
) -> int:
    """Synchronously render and store one preview. Intended for timer/tests only."""
    global _PREVIEWS, _PREVIEW_PATH, _PREVIEW_SIGNATURE
    try:
        plan_json = json.dumps(
            plan_data, sort_keys=True, separators=(",", ":")
        )
        signature = _signature(plan_json, text_scale, line_width)
        if signature == _PREVIEW_SIGNATURE and _has_cached_icon():
            return get_roof_plan_icon()

        png = render_roof_plan_png(
            plan_data, size=384, text_scale=text_scale, line_width=line_width
        )
        if _PREVIEWS is None:
            _PREVIEWS = bpy.utils.previews.new()
        if _PREVIEW_PATH is None:
            handle, _PREVIEW_PATH = tempfile.mkstemp(
                prefix="roof_forge_plan_", suffix=".png"
            )
            os.close(handle)
        if _PREVIEW_KEY in _PREVIEWS:
            del _PREVIEWS[_PREVIEW_KEY]
        with open(_PREVIEW_PATH, "wb") as file:
            file.write(png)
        _PREVIEWS.load(_PREVIEW_KEY, _PREVIEW_PATH, "IMAGE")
        _PREVIEW_SIGNATURE = signature
        _tag_view3d_redraw()
        return get_roof_plan_icon()
    except (OSError, TypeError, ValueError, RuntimeError, ReferenceError):
        return 0


def _cancel_preview_timer() -> None:
    try:
        if bpy.app.timers.is_registered(_run_pending_preview):
            bpy.app.timers.unregister(_run_pending_preview)
    except (AttributeError, RuntimeError, ValueError):
        pass


def _run_pending_preview():
    global _PENDING_JSON
    plan_json = _PENDING_JSON
    _PENDING_JSON = None
    if not plan_json:
        return None
    try:
        plan_data = json.loads(plan_json)
    except (TypeError, ValueError):
        return None
    refresh_roof_plan_icon(
        plan_data,
        text_scale=_PENDING_TEXT_SCALE,
        line_width=_PENDING_LINE_WIDTH,
    )
    return None


def schedule_roof_plan_refresh(
    settings,
    *,
    delay: float = _PREVIEW_TIMER_DELAY,
) -> bool:
    """Refresh the image once settings have been quiet; old image remains visible."""
    global _PENDING_JSON, _PENDING_TEXT_SCALE, _PENDING_LINE_WIDTH
    try:
        plan_json = str(settings.roof_plan_json or "")
        if not plan_json:
            return False
        plan_data = json.loads(plan_json)
        if not isinstance(plan_data, dict) or not plan_data.get("faces"):
            return False
        plan_json = json.dumps(
            plan_data, sort_keys=True, separators=(",", ":")
        )
        signature = _signature(
            plan_json,
            settings.plan_label_scale,
            settings.plan_line_width,
        )
        if signature == _PREVIEW_SIGNATURE and _has_cached_icon():
            _cancel_preview_timer()
            _PENDING_JSON = None
            return False

        _PENDING_JSON = plan_json
        _PENDING_TEXT_SCALE = float(settings.plan_label_scale)
        _PENDING_LINE_WIDTH = float(settings.plan_line_width)
        _cancel_preview_timer()
        bpy.app.timers.register(
            _run_pending_preview,
            first_interval=max(0.05, float(delay)),
        )
        return True
    except (AttributeError, TypeError, ValueError, RuntimeError, ReferenceError):
        return False


def cancel_pending_roof_plan_refresh() -> None:
    global _PENDING_JSON
    _cancel_preview_timer()
    _PENDING_JSON = None


def clear_contour_plan_preview() -> None:
    """Release pending timer, preview collection and its temporary PNG."""
    global _PREVIEWS, _PREVIEW_PATH, _PREVIEW_SIGNATURE
    cancel_pending_roof_plan_refresh()
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


__all__ = [
    "get_roof_plan_icon",
    "refresh_roof_plan_icon",
    "schedule_roof_plan_refresh",
    "cancel_pending_roof_plan_refresh",
    "clear_contour_plan_preview",
]
