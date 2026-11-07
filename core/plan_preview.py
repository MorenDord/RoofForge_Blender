"""Pure-Python, monochrome top-view contour plan for RoofForge's Pitch UI."""
from __future__ import annotations

import math
import struct
import zlib
from typing import Sequence

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]

_GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


def _inside(point: Point2, polygon: Sequence[Point2]) -> bool:
    x, y = point
    inside = False
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        if (first[1] > y) != (second[1] > y):
            crossing_x = first[0] + (
                (y - first[1]) * (second[0] - first[0])
                / (second[1] - first[1])
            )
            if x < crossing_x:
                inside = not inside
    return inside


def _draw_line(canvas: bytearray, size: int, start, end, radius=1) -> None:
    x0, y0 = (int(round(start[0])), int(round(start[1])))
    x1, y1 = (int(round(end[0])), int(round(end[1])))
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        for oy in range(-radius, radius + 1):
            for ox in range(-radius, radius + 1):
                if ox * ox + oy * oy <= radius * radius + radius:
                    px, py = x0 + ox, y0 + oy
                    if 0 <= px < size and 0 <= py < size:
                        offset = (py * size + px) * 4
                        canvas[offset:offset + 4] = b"\x00\x00\x00\xff"
        if x0 == x1 and y0 == y1:
            break
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy


def _draw_label(canvas: bytearray, size: int, label: str, center, cell: int) -> tuple[int, int, int, int]:
    glyph_width = 3
    spacing = 1
    width_cells = len(label) * (glyph_width + spacing) - spacing
    height_cells = 5
    width = width_cells * cell
    height = height_cells * cell
    left = int(round(center[0] - width * 0.5))
    top = int(round(center[1] - height * 0.5))

    for char_index, char in enumerate(label):
        glyph = _GLYPHS[char]
        origin_x = left + char_index * (glyph_width + spacing) * cell
        for row_index, row in enumerate(glyph):
            for column_index, bit in enumerate(row):
                if bit != "1":
                    continue
                x0 = origin_x + column_index * cell
                y0 = top + row_index * cell
                for py in range(y0, y0 + cell):
                    if not 0 <= py < size:
                        continue
                    for px in range(x0, x0 + cell):
                        if 0 <= px < size:
                            offset = (py * size + px) * 4
                            canvas[offset:offset + 4] = b"\x00\x00\x00\xff"
    return (left, top, left + width, top + height)


def _png_rgba(size: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    rows = b"".join(
        b"\x00" + rgba[y * size * 4:(y + 1) * size * 4]
        for y in range(size)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def render_contour_plan_png(
    points: Sequence[Sequence[float]],
    size: int = 256,
    text_scale: float = 1.0,
) -> bytes:
    """Render a white top-view plan with a black outline and edge numbers.

    Edge labels use the same 1-based deterministic contour order as the
    RoofForge Pitch collection. No Blender APIs or roof geometry solver are
    imported here, so this function is safe to unit-test outside Blender.
    """
    if size < 96 or size > 1024:
        raise ValueError("Размер схемы должен быть в диапазоне 96–1024 пикселей.")
    text_scale = float(text_scale)
    if not math.isfinite(text_scale):
        raise ValueError("Масштаб цифр должен быть конечным числом.")
    text_scale = min(2.0, max(0.5, text_scale))

    polygon: list[Point2] = []
    for index, point in enumerate(points):
        if len(point) < 2:
            raise ValueError(f"Вершина {index + 1} не содержит координаты XY.")
        x, y = float(point[0]), float(point[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"Вершина {index + 1} содержит некорректные координаты.")
        polygon.append((x, y))

    if len(polygon) < 3:
        raise ValueError("Для плана контура нужны минимум три вершины.")

    twice_area = sum(
        first[0] * polygon[(i + 1) % len(polygon)][1]
        - polygon[(i + 1) % len(polygon)][0] * first[1]
        for i, first in enumerate(polygon)
    )
    if abs(twice_area) <= 1.0e-12:
        raise ValueError("Контур для плана имеет нулевую площадь.")

    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    span_x = max_x - min_x
    span_y = max_y - min_y
    span = max(span_x, span_y, 1.0e-9)
    margin = max(22.0, size * 0.12)
    scale = (size - 2.0 * margin) / span
    offset_x = (size - span_x * scale) * 0.5
    offset_y = (size - span_y * scale) * 0.5

    def screen(point: Point2) -> Point2:
        return (
            offset_x + (point[0] - min_x) * scale,
            size - (offset_y + (point[1] - min_y) * scale),
        )

    canvas = bytearray(b"\xff" * (size * size * 4))
    screen_points = [screen(point) for point in polygon]

    for index, first in enumerate(screen_points):
        _draw_line(
            canvas, size, first,
            screen_points[(index + 1) % len(screen_points)],
            radius=max(1, int(round(size / 180.0))),
        )

    winding = 1.0 if twice_area > 0.0 else -1.0
    placed: list[tuple[int, int, int, int]] = []
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        dx, dy = second[0] - first[0], second[1] - first[1]
        edge_length = math.hypot(dx, dy)
        edge_pixels = edge_length * scale
        label = str(index + 1)

        # Keep labels small enough for short edges, but readable on normal
        # contours. Two-digit labels are supported through the 64-edge limit.
        max_cell = int(edge_pixels / (len(label) * 4 + 2))
        cell = min(max(1, int(round(2.5 * text_scale))), max_cell)
        if max_cell < 1:
            continue

        if winding > 0.0:
            inward = (-dy / edge_length, dx / edge_length)
        else:
            inward = (dy / edge_length, -dx / edge_length)
        midpoint = ((first[0] + second[0]) * 0.5, (first[1] + second[1]) * 0.5)
        label_height_world = (5.0 * cell + 4.0) / scale
        base_offset = max(label_height_world * 0.72, span * 0.018, edge_length * 0.035)

        chosen = None
        chosen_box = None
        for multiplier in (1.0, 1.35, 1.8, 2.4, 3.2):
            offset = base_offset * multiplier
            candidate = (
                midpoint[0] + inward[0] * offset,
                midpoint[1] + inward[1] * offset,
            )
            if not _inside(candidate, polygon):
                continue
            center = screen(candidate)
            label_width = (len(label) * 4 - 1) * cell
            label_height = 5 * cell
            box = (
                int(round(center[0] - label_width * 0.5)),
                int(round(center[1] - label_height * 0.5)),
                int(round(center[0] + label_width * 0.5)),
                int(round(center[1] + label_height * 0.5)),
            )
            if (
                box[0] < margin * 0.35
                or box[1] < margin * 0.35
                or box[2] > size - margin * 0.35
                or box[3] > size - margin * 0.35
            ):
                continue
            overlap = any(
                not (
                    box[2] + 2 < other[0]
                    or other[2] + 2 < box[0]
                    or box[3] + 2 < other[1]
                    or other[3] + 2 < box[1]
                )
                for other in placed
            )
            if not overlap:
                chosen, chosen_box = center, box
                break

        if chosen is None:
            # Try the closest point inside the polygon; skip only if there is
            # genuinely no room for the index, rather than placing it outside.
            for multiplier in (0.45, 0.65, 0.85):
                candidate = (
                    midpoint[0] + inward[0] * base_offset * multiplier,
                    midpoint[1] + inward[1] * base_offset * multiplier,
                )
                if _inside(candidate, polygon):
                    chosen = screen(candidate)
                    chosen_box = (
                        int(round(chosen[0] - (len(label) * 4 - 1) * cell * 0.5)),
                        int(round(chosen[1] - 5 * cell * 0.5)),
                        int(round(chosen[0] + (len(label) * 4 - 1) * cell * 0.5)),
                        int(round(chosen[1] + 5 * cell * 0.5)),
                    )
                    break

        if chosen is not None:
            placed.append(chosen_box)
            _draw_label(canvas, size, label, chosen, cell)

    return _png_rgba(size, bytes(canvas))


__all__ = ["render_contour_plan_png"]
