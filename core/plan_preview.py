"""Antialiased transparent top-view plan of the generated roof facets."""
from __future__ import annotations

import math
import struct
import zlib

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
_SUPERSAMPLE = 4


def surface_plan_data(surface) -> dict:
    """Convert a roof surface into JSON-safe preview topology."""
    return {
        "vertices": [list(point) for point in surface.vertices],
        "faces": [list(face) for face in surface.faces],
        "face_slope_indices": list(surface.face_slope_indices),
        "planes": [[float(p.a), float(p.b), float(p.c)] for p in surface.planes],
    }


def _normalise_plan(data: dict):
    if not isinstance(data, dict):
        raise ValueError("Данные схемы крыши должны быть объектом.")
    vertices = [tuple(float(v) for v in p[:3]) for p in data.get("vertices", ())]
    if len(vertices) < 3 or any(len(p) != 3 for p in vertices):
        raise ValueError("В схеме крыши недостаточно 3D-вершин.")
    if any(not all(math.isfinite(v) for v in p) for p in vertices):
        raise ValueError("Схема крыши содержит нечисловые координаты.")
    faces = [tuple(int(v) for v in f) for f in data.get("faces", ())]
    slopes = [int(v) for v in data.get("face_slope_indices", ())]
    planes = [tuple(float(v) for v in p) for p in data.get("planes", ())]
    if not faces or len(faces) != len(slopes):
        raise ValueError("В схеме не совпадает число граней и скатов.")
    if any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in planes):
        raise ValueError("Схема содержит некорректную плоскость.")
    for face, slope in zip(faces, slopes):
        if len(face) < 3 or any(v < 0 or v >= len(vertices) for v in face):
            raise ValueError("Грань схемы содержит неверные индексы.")
        if slope < 0 or slope >= len(planes):
            raise ValueError("Грань схемы ссылается на неизвестный скат.")
    return vertices, faces, slopes, planes


def _same_plane(first, second) -> bool:
    scale = max(1.0, *(abs(v) for v in first), *(abs(v) for v in second))
    return all(abs(first[i] - second[i]) <= 1.0e-8 * scale for i in range(3))


def _visible_edges(faces, slopes, planes):
    usage = {}
    for face_index, face in enumerate(faces):
        for i, first in enumerate(face):
            second = face[(i + 1) % len(face)]
            edge = (min(first, second), max(first, second))
            usage.setdefault(edge, []).append(face_index)
    visible = []
    for edge, linked_faces in usage.items():
        if len(linked_faces) != 2:
            visible.append(edge)
            continue
        first = planes[slopes[linked_faces[0]]]
        second = planes[slopes[linked_faces[1]]]
        if not _same_plane(first, second):
            visible.append(edge)
    return tuple(sorted(visible))


def visible_roof_edges(plan_data: dict):
    """Return roof boundary and ridge edges, excluding coplanar seams."""
    _vertices, faces, slopes, planes = _normalise_plan(plan_data)
    return _visible_edges(faces, slopes, planes)


def _inside(point, polygon):
    x, y = point
    inside = False
    for i, first in enumerate(polygon):
        second = polygon[(i + 1) % len(polygon)]
        if (first[1] > y) != (second[1] > y):
            cross_x = first[0] + (y - first[1]) * (second[0] - first[0]) / (second[1] - first[1])
            if x < cross_x:
                inside = not inside
    return inside


def _segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1.0e-24:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _clearance(point, polygon):
    if not _inside(point, polygon):
        return 0.0
    return min(_segment_distance(point, polygon[i], polygon[(i + 1) % len(polygon)]) for i in range(len(polygon)))


def _label_center(polygon):
    """Approximate a facet's pole of inaccessibility and its line clearance."""
    min_x, max_x = min(p[0] for p in polygon), max(p[0] for p in polygon)
    min_y, max_y = min(p[1] for p in polygon), max(p[1] for p in polygon)
    width, height = max_x - min_x, max_y - min_y
    if width <= 1.0e-12 or height <= 1.0e-12:
        return ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5), 0.0
    divisions = 28
    sx, sy = width / divisions, height / divisions
    best, best_clearance = (0.0, 0.0), -1.0
    for iy in range(divisions):
        for ix in range(divisions):
            p = (min_x + (ix + 0.5) * sx, min_y + (iy + 0.5) * sy)
            distance = _clearance(p, polygon)
            if distance > best_clearance:
                best, best_clearance = p, distance
    if best_clearance <= 0.0:
        p = (sum(x for x, _ in polygon) / len(polygon), sum(y for _, y in polygon) / len(polygon))
        return p, _clearance(p, polygon)
    for _ in range(4):
        sx *= 0.25
        sy *= 0.25
        for iy in range(-4, 5):
            for ix in range(-4, 5):
                p = (best[0] + ix * sx, best[1] + iy * sy)
                distance = _clearance(p, polygon)
                if distance > best_clearance:
                    best, best_clearance = p, distance
    return best, max(0.0, best_clearance)


def _put_white(canvas, size, x, y):
    if 0 <= x < size and 0 <= y < size:
        offset = (y * size + x) * 4
        canvas[offset:offset + 4] = b"\xff\xff\xff\xff"


def _disc(canvas, size, cx, cy, radius):
    brush = int(math.ceil(radius))
    for oy in range(-brush, brush + 1):
        for ox in range(-brush, brush + 1):
            if ox * ox + oy * oy <= radius * radius + 0.25:
                _put_white(canvas, size, cx + ox, cy + oy)


def _line(canvas, size, first, second, width):
    dx, dy = second[0] - first[0], second[1] - first[1]
    steps = max(1, int(math.ceil(max(abs(dx), abs(dy)))))
    radius = max(0.5, width * 0.5)
    for step in range(steps + 1):
        t = step / steps
        _disc(canvas, size, int(round(first[0] + dx * t)), int(round(first[1] + dy * t)), radius)


def _label(canvas, size, label, center, cell):
    glyph_width, spacing = 3, 1
    width = (len(label) * (glyph_width + spacing) - spacing) * cell
    height = 5 * cell
    left, top = int(round(center[0] - width * 0.5)), int(round(center[1] - height * 0.5))
    for char_index, char in enumerate(label):
        origin_x = left + char_index * (glyph_width + spacing) * cell
        for row_index, row in enumerate(_GLYPHS[char]):
            for column_index, bit in enumerate(row):
                if bit == "1":
                    for oy in range(cell):
                        for ox in range(cell):
                            _put_white(canvas, size, origin_x + column_index * cell + ox, top + row_index * cell + oy)


def _png(size, rgba):
    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff)
    rows = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")


def render_roof_plan_png(plan_data: dict, size: int = 512, text_scale: float = 1.0, line_width: float = 1.8) -> bytes:
    """Render white roof boundary/ridge lines and facet labels on transparent RGBA."""
    size = int(size)
    if size < 128 or size > 1024:
        raise ValueError("Размер схемы должен быть в диапазоне 128–1024 пикселей.")
    text_scale, line_width = float(text_scale), float(line_width)
    if not math.isfinite(text_scale) or not math.isfinite(line_width):
        raise ValueError("Масштаб цифр и толщина линий должны быть конечными.")
    text_scale = max(0.5, min(2.0, text_scale))
    line_width = max(0.5, min(8.0, line_width))
    vertices, faces, slopes, planes = _normalise_plan(plan_data)
    edges = _visible_edges(faces, slopes, planes)
    min_x, max_x = min(p[0] for p in vertices), max(p[0] for p in vertices)
    min_y, max_y = min(p[1] for p in vertices), max(p[1] for p in vertices)
    span_x, span_y = max_x - min_x, max_y - min_y
    span = max(span_x, span_y, 1.0e-9)
    margin = max(18.0, size * 0.075)
    scale = (size - 2.0 * margin) / span
    offset_x = (size - span_x * scale) * 0.5
    offset_y = (size - span_y * scale) * 0.5

    def screen(p):
        return (offset_x + (p[0] - min_x) * scale, size - (offset_y + (p[1] - min_y) * scale))

    supersample = _SUPERSAMPLE
    high_size = size * supersample
    canvas = bytearray(high_size * high_size * 4)
    screen_points = [screen((p[0], p[1])) for p in vertices]
    for first, second in edges:
        a = (screen_points[first][0] * supersample, screen_points[first][1] * supersample)
        b = (screen_points[second][0] * supersample, screen_points[second][1] * supersample)
        _line(canvas, high_size, a, b, line_width * supersample)

    largest = {}
    for face_index, face in enumerate(faces):
        slope_index = slopes[face_index]
        polygon = [(vertices[i][0], vertices[i][1]) for i in face]
        area = abs(sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1] - polygon[(i + 1) % len(polygon)][0] * polygon[i][1] for i in range(len(polygon)))) * 0.5
        if area > largest.get(slope_index, (0.0, ()))[0]:
            largest[slope_index] = (area, polygon)

    occupied = []
    for slope_index in sorted(largest):
        _area, polygon = largest[slope_index]
        world_center, clearance = _label_center(polygon)
        clearance_px = clearance * scale
        cell_px = min(4.2 * text_scale, clearance_px / 4.7)
        if cell_px < 1.0:
            continue
        cell = max(1, int(math.floor(cell_px * supersample)))
        center = screen(world_center)
        center_high = (center[0] * supersample, center[1] * supersample)
        label = str(slope_index + 1)
        box_w = (len(label) * 4 - 1) * cell / supersample
        box_h = 5 * cell / supersample
        box = (center[0] - box_w * 0.5, center[1] - box_h * 0.5, center[0] + box_w * 0.5, center[1] + box_h * 0.5)
        if box[0] < margin * 0.4 or box[1] < margin * 0.4 or box[2] > size - margin * 0.4 or box[3] > size - margin * 0.4:
            continue
        if any(not (box[2] + 2 < other[0] or other[2] + 2 < box[0] or box[3] + 2 < other[1] or other[3] + 2 < box[1]) for other in occupied):
            continue
        occupied.append(box)
        _label(canvas, high_size, label, center_high, cell)

    output = bytearray(size * size * 4)
    divisor = supersample * supersample
    for y in range(size):
        for x in range(size):
            alpha = 0
            for oy in range(supersample):
                row = (y * supersample + oy) * high_size
                for ox in range(supersample):
                    alpha += canvas[(row + x * supersample + ox) * 4 + 3]
            offset = (y * size + x) * 4
            output[offset:offset + 4] = bytes((255, 255, 255, int(round(alpha / divisor))))
    return _png(size, bytes(output))


__all__ = ["surface_plan_data", "visible_roof_edges", "render_roof_plan_png"]
