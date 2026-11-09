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
_PREVIEW_REGION_VISIBILITY = {}
_PANEL_CATEGORY = "RoofForge"
_DRAW_REGION_TYPE = "UI"
_LINE_SHADER_NAME = "POLYLINE_UNIFORM_COLOR"

# The preview is its own panel directly below the Create / Update panel.
# Its blank template_icon slot reserves space in normal Blender UI flow.
_PREVIEW_SLOT_TOP_UNITS = 4.0
_PREVIEW_SLOT_MIN_SIDE = 96.0
_PREVIEW_MARGIN_FRACTION = 0.075
_PREVIEW_DRAW_INSET = 8.0
_PANEL_CONTENT_LEFT_MARGIN_UNITS = 0.4
_TEMPLATE_ICON_SCALE_BASE = 32.0
_TEMPLATE_ICON_SIDE_MARGIN = 24.0
_WIDGET_UNIT_BASE = 20.0


def _prepare_geometry(plan_data):
    vertices, faces, slopes, planes = normalise_roof_plan(plan_data)
    edges = visible_roof_edges(plan_data)
    min_x = min(point[0] for point in vertices)
    max_x = max(point[0] for point in vertices)
    min_y = min(point[1] for point in vertices)
    max_y = max(point[1] for point in vertices)
    if max(max_x - min_x, max_y - min_y) <= 1.0e-12:
        raise ValueError("Roof plan has zero area")
    # Geometry stores source-slope indices as zero-based; the sidebar rows are 01-based.
    labels = tuple(
        (slope_index + 1, center, clearance)
        for slope_index, center, clearance
        in slope_region_centers(vertices, faces, slopes)
    )
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

def _region_key(region):
    """Return a stable key for one live UI region."""
    try:
        return int(region.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def set_preview_slot_visible(region, visible):
    """Enable GPU drawing only while the nested UI layout slot is present."""
    key = _region_key(region)
    if key is None:
        return
    _PREVIEW_REGION_VISIBILITY[key] = bool(visible)


def _is_preview_slot_visible(region):
    key = _region_key(region)
    return bool(key is not None and _PREVIEW_REGION_VISIBILITY.get(key, False))


def estimate_widget_unit(ui_scale=1.0):
    """Estimate Blender's UI_UNIT_X/Y from its exposed resolution scale.

    Blender's template_icon uses U.widget_unit for both button dimensions.
    There is no public Python accessor for U.widget_unit; Blender documents
    it as approximately 20 * UI_SCALE_FAC, with small DPI/line-width effects.
    """
    scale = float(ui_scale)
    if scale <= 0.0:
        scale = 1.0
    return max(1.0, round(_WIDGET_UNIT_BASE * scale))


def preview_icon_scale(region_width, *, widget_unit=20.0):
    """Return the historical template_icon scale, not its pixel dimension.

    Blender creates the actual UI item at UI_UNIT_X/Y * scale. The UI unit is
    U.widget_unit; it must not be replaced by the unrelated 32px scale divisor.
    """
    width = max(0.0, float(region_width))
    unit = max(1.0, float(widget_unit))
    side = width - _TEMPLATE_ICON_SIDE_MARGIN
    if side <= 0.0:
        return None
    scale = side / _TEMPLATE_ICON_SCALE_BASE
    if scale < 1.0 or unit * scale < _PREVIEW_SLOT_MIN_SIDE:
        return None
    return min(100.0, scale)


def _compute_canvas_layout(
    region_width,
    region_height,
    bounds,
    *,
    ui_scale=1.0,
    widget_unit=None,
):
    """Fit the roof inside the reserved square UI slot.

    The UI slot follows normal panel layout and pushes the next panel down.
    Its horizontal centre is shifted half the right scrollbar gutter so the
    drawing is centred in the usable content width, not in the whole region.
    A small inset keeps antialiased strokes inside the slot boundaries.
    """
    ui_scale = max(0.5, float(ui_scale))
    width = max(0.0, float(region_width))
    height = max(0.0, float(region_height))
    if widget_unit is None:
        widget_unit = estimate_widget_unit(ui_scale)
    widget_unit = max(1.0, float(widget_unit))
    icon_scale = preview_icon_scale(width, widget_unit=widget_unit)
    if icon_scale is None:
        return None

    # template_icon() allocates U.widget_unit * icon_scale on each axis.
    slot_side = widget_unit * icon_scale
    min_x, min_y, max_x, max_y = (float(value) for value in bounds)
    span_x, span_y = max_x - min_x, max_y - min_y
    span = max(span_x, span_y)
    if span <= 1.0e-12:
        return None

    inset = _PREVIEW_DRAW_INSET * ui_scale
    draw_side = slot_side - 2.0 * inset
    if draw_side <= 2.0:
        return None

    margin = draw_side * _PREVIEW_MARGIN_FRACTION
    scale = (draw_side - 2.0 * margin) / span
    if scale <= 0.0:
        return None

    # A normal panel column starts at Blender's UI_PANEL_MARGIN_X:
    # 0.4 * U.widget_unit. The template_icon is left-aligned in that column;
    # centring it in the whole region incorrectly shifts it to the right.
    slot_left = _PANEL_CONTENT_LEFT_MARGIN_UNITS * widget_unit
    slot_top = height - _PREVIEW_SLOT_TOP_UNITS * widget_unit
    slot_bottom = slot_top - slot_side
    if slot_bottom < 8.0 * ui_scale or slot_left + slot_side > width:
        return None

    draw_left = slot_left + inset
    draw_bottom = slot_bottom + inset
    offset_x = (draw_side - span_x * scale) * 0.5
    offset_y = (draw_side - span_y * scale) * 0.5
    origin_x = draw_left + offset_x
    origin_y = draw_bottom + offset_y
    bbox_center = (
        origin_x + (span_x * scale) * 0.5,
        origin_y + (span_y * scale) * 0.5,
    )
    target_center = (
        slot_left + slot_side * 0.5,
        slot_bottom + slot_side * 0.5,
    )
    return {
        "side": slot_side,
        "slot_side": slot_side,
        "slot_left": slot_left,
        "slot_bottom": slot_bottom,
        "slot_top": slot_top,
        "draw_side": draw_side,
        "inset": inset,
        "scale": scale,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "canvas_left": draw_left,
        "canvas_bottom": draw_bottom,
        "canvas_top": draw_bottom + draw_side,
        "target_center": target_center,
        "bbox_center": bbox_center,
        "margin": margin,
        "icon_scale": icon_scale,
        "widget_unit": widget_unit,
        "scissor": (
            round(slot_left),
            round(slot_bottom),
            round(slot_side),
            round(slot_side),
        ),
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



def _view2d_visible_rect(region):
    """Return (visible_rect, error) in region-local pixel coordinates."""
    try:
        view2d = region.view2d
        current = view2d.cur
        first = view2d.view_to_region(
            float(current.xmin), float(current.ymin), clip=False
        )
        last = view2d.view_to_region(
            float(current.xmax), float(current.ymax), clip=False
        )
        if first is None or last is None:
            return None, "view_to_region returned None"
        left = min(float(first[0]), float(last[0]))
        bottom = min(float(first[1]), float(last[1]))
        right = max(float(first[0]), float(last[0])) + 1.0
        top = max(float(first[1]), float(last[1])) + 1.0
        if right <= left or top <= bottom:
            return None, "empty transformed rectangle"
        return (left, bottom, right, top), None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _translate_scissor(scissor, viewport):
    """Translate region-local scissor coordinates into framebuffer pixels."""
    x, y, width, height = (float(value) for value in scissor)
    viewport_x, viewport_y = float(viewport[0]), float(viewport[1])
    return (
        round(viewport_x + x),
        round(viewport_y + y),
        round(width),
        round(height),
    )


def _rectangle_line_positions(rect):
    """Return the four outline edges for a half-open pixel rectangle."""
    left, bottom, right, top = (float(value) for value in rect)
    right -= 1.0
    top -= 1.0
    return (
        (left, bottom), (right, bottom),
        (right, bottom), (right, top),
        (right, top), (left, top),
        (left, top), (left, bottom),
    )


def _draw_debug_overlay(
    context, region, layout, viewport, ui_scale, text_color, icon_scale
):
    """Draw actual Region/GPU bounds and the measured template-icon estimate."""
    width = float(region.width)
    height = float(region.height)
    region_rect = (0.0, 0.0, max(1.0, width), max(1.0, height))
    view_rect, view_error = _view2d_visible_rect(region)
    slot_rect = (
        float(layout["slot_left"]),
        float(layout["slot_bottom"]),
        float(layout["slot_left"] + layout["slot_side"]),
        float(layout["slot_bottom"] + layout["slot_side"]),
    )

    # Region = red, View2D visible mask = green, GPU viewport local = cyan,
    # estimated template_icon slot = amber. GPU viewport coordinates already
    # use the UI region's local framebuffer origin; Region.x/y are window-space.
    rectangles = [
        (region_rect, (1.0, 0.12, 0.12, 1.0)),
    ]
    if view_rect is not None:
        rectangles.append((view_rect, (0.12, 1.0, 0.28, 1.0)))
    rectangles.append((slot_rect, (1.0, 0.72, 0.08, 1.0)))

    viewport_x, viewport_y, viewport_width, viewport_height = (
        float(value) for value in viewport
    )
    viewport_rect = (
        viewport_x,
        viewport_y,
        viewport_x + viewport_width,
        viewport_y + viewport_height,
    )
    if (
        viewport_width > 0.0
        and viewport_height > 0.0
        and viewport_rect[0] < width
        and viewport_rect[1] < height
        and viewport_rect[2] > 0.0
        and viewport_rect[3] > 0.0
    ):
        viewport_rect = (
            max(0.0, viewport_rect[0]),
            max(0.0, viewport_rect[1]),
            min(width, viewport_rect[2]),
            min(height, viewport_rect[3]),
        )
        rectangles.append((viewport_rect, (0.12, 0.72, 1.0, 1.0)))

    shader = gpu.shader.from_builtin(_LINE_SHADER_NAME)
    for rect, color in rectangles:
        positions = _rectangle_line_positions(rect)
        batch = batch_for_shader(shader, "LINES", {"pos": positions})
        shader.bind()
        shader.uniform_float(
            "viewportSize",
            (float(viewport_width), float(viewport_height)),
        )
        shader.uniform_float("lineWidth", max(1.0, 1.6 * ui_scale))
        shader.uniform_float("color", color)
        batch.draw(shader)

    def format_rect(rect):
        if rect is None:
            return "unavailable"
        return ",".join(str(round(value)) for value in rect)

    region_origin = (
        round(float(getattr(region, "x", 0))),
        round(float(getattr(region, "y", 0))),
    )
    lines = [
        f"REGION {round(width)}x{round(height)} @ {region_origin[0]},{region_origin[1]}",
        f"VIEW2D L,B,R,T = {format_rect(view_rect)}",
        f"EST SLOT L,B,S = {round(slot_rect[0])},{round(slot_rect[1])},{round(layout['slot_side'])}",
    ]
    if view_rect is None:
        lines.append(f"VIEW2D ERROR = {view_error or 'unavailable'}")
    lines.append(
        f"UI UNIT~{round(layout['widget_unit'], 1)} ICON SCALE={icon_scale:.2f} SLOT~{round(layout['slot_side'])}"
    )
    lines.append(
        f"GPU VP LOCAL={round(viewport_x)},{round(viewport_y)} {round(viewport_width)}x{round(viewport_height)}"
    )

    font_id = 0
    font_size = max(9, int(10 * ui_scale))
    blf.size(font_id, font_size)
    blf.enable(font_id, blf.SHADOW)
    try:
        shadow_color = (
            (0.0, 0.0, 0.0, 0.95)
            if text_color[0] > 0.5
            else (1.0, 1.0, 1.0, 0.95)
        )
        blf.shadow(font_id, 3, *shadow_color)
        blf.shadow_offset(font_id, 1, -1)
        blf.color(font_id, *text_color)
        label_y = max(4.0, height - 15.0 * ui_scale)
        for line in lines:
            blf.position(font_id, round(6.0 * ui_scale), round(label_y), 0)
            blf.draw(font_id, line)
            label_y -= 12.0 * ui_scale
    finally:
        blf.disable(font_id, blf.SHADOW)


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
    scissor_enabled = False
    shadow_enabled = False
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
        if not _is_preview_slot_visible(region):
            return
        if _is_panel_scrolled(region):
            return

        geometry = _cached_geometry(settings.roof_plan_json)
        ui_scale = 1.0
        try:
            ui_scale = max(0.5, float(context.preferences.system.ui_scale))
        except (AttributeError, TypeError, ValueError):
            pass
        widget_unit = estimate_widget_unit(ui_scale)
        layout = _compute_canvas_layout(
            region.width,
            region.height,
            geometry["bounds"],
            ui_scale=ui_scale,
            widget_unit=widget_unit,
        )
        if layout is None:
            return

        viewport = tuple(int(value) for value in gpu.state.viewport_get())
        color = _line_color(context)
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")

        if getattr(settings, "plan_debug_bounds", False):
            try:
                _draw_debug_overlay(
                    context,
                    region,
                    layout,
                    viewport,
                    ui_scale,
                    color,
                    layout["icon_scale"],
                )
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass

        # scissor_set uses active-framebuffer pixels, whereas the preview slot
        # is calculated in region-local POST_PIXEL coordinates.
        gpu.state.scissor_test_set(True)
        gpu.state.scissor_set(*_translate_scissor(layout["scissor"], viewport))
        scissor_enabled = True

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

        if line_positions:
            shader = gpu.shader.from_builtin(_LINE_SHADER_NAME)
            batch = batch_for_shader(shader, "LINES", {"pos": line_positions})
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
        shadow_color = (1.0, 1.0, 1.0, 0.95) if color[0] < 0.5 else (0.0, 0.0, 0.0, 0.9)
        blf.enable(font_id, blf.SHADOW)
        shadow_enabled = True
        blf.shadow(font_id, 6, *shadow_color)
        blf.shadow_offset(font_id, 0, 0)
        blf.color(font_id, *color)
        for number, center, _clearance in geometry["labels"]:
            px = screen(center)
            text = str(number)
            text_width, text_height = blf.dimensions(font_id, text)
            blf.position(
                font_id,
                round(px[0] - text_width * 0.5),
                round(px[1] - text_height * 0.5),
                0,
            )
            blf.draw(font_id, text)
        blf.disable(font_id, blf.SHADOW)
        shadow_enabled = False

    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        pass
    finally:
        if shadow_enabled:
            try:
                blf.disable(0, blf.SHADOW)
            except (AttributeError, RuntimeError):
                pass
        if scissor_enabled:
            try:
                gpu.state.scissor_test_set(False)
            except (AttributeError, RuntimeError):
                pass
        try:
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
    _PREVIEW_REGION_VISIBILITY.clear()


__all__ = [
    "register_vector_preview",
    "unregister_vector_preview",
    "tag_vector_preview_redraw",
    "set_preview_slot_visible",
    "_compute_canvas_layout",
    "_view2d_visible_rect",
    "_translate_scissor",
    "estimate_widget_unit",
    "preview_icon_scale",
]
