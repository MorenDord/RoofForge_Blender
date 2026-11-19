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
_PREVIEW_DEBUG_MESSAGES = {}
_PREVIEW_REGION_TOP_VIEW_Y = {}
_PANEL_CATEGORY = "RoofForge"
_DRAW_REGION_TYPE = "UI"
_LINE_SHADER_NAME = "POLYLINE_UNIFORM_COLOR"

# A blank template_icon slot reserves space in the nested Roof Plan UI flow.
_PREVIEW_SLOT_TOP_UNITS = 4.0
_PREVIEW_SLOT_MIN_SIDE = 96.0
_PREVIEW_MARGIN_FRACTION = 0.075
_PREVIEW_DRAW_INSET = 8.0
_TEMPLATE_ICON_SCALE_BASE = 32.0
_TEMPLATE_ICON_SIDE_MARGIN = 24.0
_WIDGET_UNIT_BASE = 20.0
# Blender reserves a vertical category-tab rail on the left of the UI region.
# Preview placement and sizing use the remaining active-tab content rectangle.
_PANEL_CATEGORY_RAIL_UNITS = 1.0
# In a VIEW_3D sidebar the category-tab rail is on the outer edge of the UI region.
# RIGHT-aligned N-panels have tabs on the right; LEFT-aligned panels have tabs on the left.
_PANEL_CATEGORY_RAIL_SIDE = "RIGHT"


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


def preview_category_rail_width(widget_unit=20.0, *, region=None, compact=False):
    """Estimate Blender's category-tab gutter in region-local UI pixels.

    Blender uses one UI widget unit for normal sidebar tabs and 1.4 units for
    compact tabs. The gutter is horizontal, so its View2D zoom must be measured
    along X. Using the region's vertical zoom shifts the preview whenever the
    UI region is zoomed or scaled differently on the two axes.
    """
    tab_units = 1.4 if compact else _PANEL_CATEGORY_RAIL_UNITS
    zoom_x = 1.0
    if region is not None:
        try:
            view2d = region.view2d
            width = max(1.0, float(region.width))
            height = max(1.0, float(region.height))
            sample_y = (height - 1.0) * 0.5
            left_x = float(view2d.region_to_view(0.0, sample_y)[0])
            right_x = float(view2d.region_to_view(width - 1.0, sample_y)[0])
            view_width = abs(right_x - left_x)
            if view_width > 1.0e-9:
                zoom_x = (width - 1.0) / view_width
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    return max(0.0, float(widget_unit) * tab_units * zoom_x)


def preview_category_rail_side(region=None):
    """Return the edge occupied by category tabs for this sidebar region."""
    alignment = str(getattr(region, "alignment", "") or "").upper()
    if alignment in {"LEFT", "RIGHT"}:
        return alignment
    return _PANEL_CATEGORY_RAIL_SIDE


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
    category_rail_width=None,
    category_rail_side=None,
):
    """Fit the roof inside the active sidebar tab's content rectangle.

    The UI region also contains Blender's vertical category-tab rail. Its side
    follows Region.alignment: on the outer edge of a right- or left-aligned
    sidebar. Centering uses only the remaining active-tab content rectangle.
    The blank UI row remains a vertical spacer; GPU coordinates match its UI
    anchor within that same rectangle.
    """
    ui_scale = max(0.5, float(ui_scale))
    width = max(0.0, float(region_width))
    height = max(0.0, float(region_height))
    if widget_unit is None:
        widget_unit = estimate_widget_unit(ui_scale)
    widget_unit = max(1.0, float(widget_unit))
    if category_rail_width is None:
        category_rail_width = preview_category_rail_width(widget_unit)
    category_rail_width = min(max(0.0, float(category_rail_width)), width * 0.4)
    category_rail_side = str(
        category_rail_side or _PANEL_CATEGORY_RAIL_SIDE
    ).upper()
    if category_rail_side not in {"LEFT", "RIGHT"}:
        category_rail_side = _PANEL_CATEGORY_RAIL_SIDE
    if category_rail_side == "RIGHT":
        panel_content_left = 0.0
        panel_content_right = width - category_rail_width
    else:
        panel_content_left = category_rail_width
        panel_content_right = width
    panel_content_width = max(0.0, panel_content_right - panel_content_left)
    icon_scale = preview_icon_scale(
        panel_content_width,
        widget_unit=widget_unit,
    )
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

    # Exclude the category-tab rail on the actual outer edge of this sidebar.
    region_center_x = panel_content_left + panel_content_width * 0.5
    slot_left = region_center_x - slot_side * 0.5
    slot_top = height - _PREVIEW_SLOT_TOP_UNITS * widget_unit
    slot_bottom = slot_top - slot_side
    if (
        slot_bottom < 8.0 * ui_scale
        or slot_left < panel_content_left
        or slot_left + slot_side > panel_content_right
    ):
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
        "region_center_x": region_center_x,
        "panel_content_left": panel_content_left,
        "panel_content_right": panel_content_right,
        "panel_content_width": panel_content_width,
        "category_rail_width": category_rail_width,
        "category_rail_side": category_rail_side,
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
    """Approximate scroll state using public View2D mapping and a top baseline.

    Blender's internal View2D.cur/tot rectangles are not exposed in Python.
    At first visible draw, remember the view coordinate at the top pixel.
    Scrolling down decreases that coordinate; expanding content at the top
    may increase it, in which case the baseline is refreshed.
    """
    key = _region_key(region)
    if key is None:
        return False
    try:
        view2d = region.view2d
        top_pixel = max(0.0, float(region.height) - 1.0)
        current_top = float(view2d.region_to_view(0.0, top_pixel)[1])
        baseline = _PREVIEW_REGION_TOP_VIEW_Y.get(key)
        if baseline is None or current_top > float(baseline) + 2.0:
            _PREVIEW_REGION_TOP_VIEW_Y[key] = current_top
            return False
        return (float(baseline) - current_top) > 2.0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False



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
        if settings is None or not settings.roof_plan_json:
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
        compact_tabs = False
        try:
            compact_tabs = bool(context.preferences.system.show_panel_tabs_compact)
        except (AttributeError, ReferenceError, TypeError, ValueError):
            pass
        category_rail_width = preview_category_rail_width(
            widget_unit,
            region=region,
            compact=compact_tabs,
        )
        category_rail_side = preview_category_rail_side(region)
        layout = _compute_canvas_layout(
            region.width,
            region.height,
            geometry["bounds"],
            ui_scale=ui_scale,
            widget_unit=widget_unit,
            category_rail_width=category_rail_width,
            category_rail_side=category_rail_side,
        )
        if layout is None:
            return

        viewport = tuple(int(value) for value in gpu.state.viewport_get())
        color = _line_color(context)
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")

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
    _PREVIEW_DEBUG_MESSAGES.clear()
    _PREVIEW_REGION_TOP_VIEW_Y.clear()


__all__ = [
    "register_vector_preview",
    "unregister_vector_preview",
    "tag_vector_preview_redraw",
    "set_preview_slot_visible",
    "_compute_canvas_layout",
    "_view2d_visible_rect",
    "_translate_scissor",
    "_view2d_mapping_info",
    "estimate_widget_unit",
    "preview_icon_scale",
    "preview_category_rail_width",
    "preview_category_rail_side",
]
