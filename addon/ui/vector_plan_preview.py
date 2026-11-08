"""Direct, antialiased GPU vector overlay for the RoofForge sidebar."""
from __future__ import annotations

import json

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from ...core.roof_plan import (
    normalise_roof_plan,
    slope_region_centers,
    visible_roof_edges,
)

_DRAW_HANDLE = None
_CACHE_SIGNATURE = None
_CACHE_GEOMETRY = None
_PANEL_CATEGORY = "RoofForge"
_DRAW_REGION_TYPE = "UI"
_LINE_SHADER_NAME = "POLYLINE_UNIFORM_COLOR"

# The controls above the placeholder row occupy this part of the N-panel.
_PANEL_TOP_RESERVED = 188
_PANEL_BOTTOM_RESERVED = 10
_PANEL_MAX_SIZE = 208
_PANEL_MIN_SIZE = 76
_CANVAS_MARGIN = 10


def _prepare_geometry(plan_data):
    vertices, faces, slopes, planes = normalise_roof_plan(plan_data)
    edges = visible_roof_edges(plan_data)
    min_x = min(point[0] for point in vertices)
    max_x = max(point[0] for point in vertices)
    min_y = min(point[1] for point in vertices)
    max_y = max(point[1] for point in vertices)
    if max(max_x - min_x, max_y - min_y) <= 1.0e-12:
        raise ValueError("Roof plan has zero area")
    labels = slope_region_centers(vertices, faces, slopes)
    return {
        "vertices": [(point[0], point[1]) for point in vertices],
        "edges": edges,
        "labels": labels,
        "bounds": (min_x, min_y, max_x, max_y),
    }


def _cached_geometry(plan_json):
    global _CACHE_SIGNATURE, _CACHE_GEOMETRY
    if plan_json != _CACHE_SIGNATURE:
        _CACHE_GEOMETRY = _prepare_geometry(json.loads(plan_json))
        _CACHE_SIGNATURE = plan_json
    return _CACHE_GEOMETRY


def _compute_canvas_layout(
    region_width,
    region_height,
    bounds,
    *,
    ui_scale=1.0,
    top_reserved=None,
):
    """Fit the roof bounding box inside the reserved slot without overflow."""
    ui_scale = max(0.5, float(ui_scale))
    safe = _CANVAS_MARGIN * ui_scale
    top_reserved = (
        _PANEL_TOP_RESERVED * ui_scale
        if top_reserved is None else float(top_reserved)
    )
    available_width = float(region_width) - 2.0 * safe
    available_height = float(region_height) - top_reserved - _PANEL_BOTTOM_RESERVED * ui_scale
    side = min(
        _PANEL_MAX_SIZE * ui_scale,
        available_width,
        available_height,
    )
    if side < _PANEL_MIN_SIZE * ui_scale:
        return None

    min_x, min_y, max_x, max_y = (float(value) for value in bounds)
    span_x, span_y = max_x - min_x, max_y - min_y
    largest_span = max(span_x, span_y)
    if largest_span <= 1.0e-12:
        return None

    padding = _CANVAS_MARGIN * ui_scale
    inner_side = max(1.0, side - 2.0 * padding)
    scale = inner_side / largest_span

    # Anchor the actual model bounding-box centre to the centre of the slot.
    target_x = float(region_width) * 0.5
    target_y = float(region_height) - top_reserved - side * 0.5
    bbox_center_x = (min_x + max_x) * 0.5
    bbox_center_y = (min_y + max_y) * 0.5
    return {
        "side": side,
        "scale": scale,
        "origin_x": target_x - (bbox_center_x - min_x) * scale,
        "origin_y": target_y - (bbox_center_y - min_y) * scale,
        "target_center": (target_x, target_y),
    }


def _is_panel_scrolled(region):
    """Return True when the UI region's vertical view is not at its top."""
    try:
        view2d = region.view2d
        current_top = float(view2d.cur.ymax)
        content_top = float(view2d.tot.ymax)
        return (content_top - current_top) > 2.0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _line_color(context):
    """Choose a contrasting line/text colour from the active Blender UI theme."""
    try:
        ui_theme = context.preferences.themes[0].user_interface
        background = ui_theme.wcol_regular.inner
        luminance = (
            0.2126 * float(background[0])
            + 0.7152 * float(background[1])
            + 0.0722 * float(background[2])
        )
        if luminance > 0.52:
            return (0.10, 0.12, 0.15, 1.0)
    except (AttributeError, IndexError, ReferenceError, TypeError, ValueError):
        pass
    return (0.94, 0.97, 1.0, 1.0)


def _draw_vector_preview():
    try:
        context = bpy.context
        region = context.region
        scene = context.scene
        if region is None or region.type != _DRAW_REGION_TYPE or scene is None:
            return
        if getattr(region, "active_panel_category", "") != _PANEL_CATEGORY:
            return
        settings = getattr(scene, "roof_forge", None)
        if settings is None or not settings.plan_show_vector or not settings.roof_plan_json:
            return
        if _is_panel_scrolled(region):
            return

        geometry = _cached_geometry(settings.roof_plan_json)
        ui_scale = 1.0
        try:
            ui_scale = max(0.5, float(context.preferences.system.ui_scale))
        except (AttributeError, TypeError, ValueError):
            pass
        layout = _compute_canvas_layout(
            region.width,
            region.height,
            geometry["bounds"],
            ui_scale=ui_scale,
        )
        # A narrow N-panel must hide the canvas instead of painting over the
        # neighbouring editor. The normal layout controls remain available.
        if layout is None:
            return

        origin_x = layout["origin_x"]
        origin_y = layout["origin_y"]
        scale = layout["scale"]
        min_x, min_y, _max_x, _max_y = geometry["bounds"]

        def screen(point):
            return (
                origin_x + (point[0] - min_x) * scale,
                origin_y + (point[1] - min_y) * scale,
            )

        line_positions = []
        for first, second in geometry["edges"]:
            line_positions.extend((
                screen(geometry["vertices"][first]),
                screen(geometry["vertices"][second]),
            ))

        color = _line_color(context)
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        if line_positions:
            shader = gpu.shader.from_builtin(_LINE_SHADER_NAME)
            batch = batch_for_shader(shader, "LINES", {"pos": line_positions})
            viewport = gpu.state.viewport_get()
            shader.bind()
            shader.uniform_float("viewportSize", (float(viewport[2]), float(viewport[3])))
            shader.uniform_float(
                "lineWidth",
                max(1.0, min(6.0, float(settings.plan_line_width) * ui_scale)),
            )
            shader.uniform_float("color", color)
            batch.draw(shader)

        font_id = 0
        font_size = max(10, int(13 * float(settings.plan_label_scale) * ui_scale))
        blf.size(font_id, font_size)
        # Outline keeps the number legible over lines in both light and dark themes.
        shadow_color = (1.0, 1.0, 1.0, 0.95) if color[0] < 0.5 else (0.0, 0.0, 0.0, 0.9)
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, 6, *shadow_color)
        blf.shadow_offset(font_id, 0, 0)
        blf.color(font_id, *color)
        for number, center, _clearance in geometry["labels"]:
            px = screen(center)
            text = str(number)
            width, height = blf.dimensions(font_id, text)
            blf.position(
                font_id,
                round(px[0] - width * 0.5),
                round(px[1] - height * 0.5),
                0,
            )
            blf.draw(font_id, text)
        blf.disable(font_id, blf.SHADOW)

        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        try:
            blf.disable(0, blf.SHADOW)
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.blend_set("NONE")
        except (AttributeError, RuntimeError):
            pass


def tag_vector_preview_redraw():
    try:
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    for region in area.regions:
                        if region.type == "UI":
                            region.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def register_vector_preview():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is None:
        try:
            _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
                _draw_vector_preview, (), _DRAW_REGION_TYPE, "POST_PIXEL"
            )
        except (AttributeError, RuntimeError, TypeError):
            _DRAW_HANDLE = None
    tag_vector_preview_redraw()


def unregister_vector_preview():
    global _DRAW_HANDLE, _CACHE_SIGNATURE, _CACHE_GEOMETRY
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, _DRAW_REGION_TYPE)
        except (ReferenceError, RuntimeError, ValueError):
            pass
    _DRAW_HANDLE = None
    _CACHE_SIGNATURE = None
    _CACHE_GEOMETRY = None


__all__ = [
    "register_vector_preview",
    "unregister_vector_preview",
    "tag_vector_preview_redraw",
    "_compute_canvas_layout",
]
