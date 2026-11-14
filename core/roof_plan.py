"""Topology helpers for the direct GPU roof-plan preview."""
from __future__ import annotations

import math


def surface_plan_data(surface) -> dict:
    """Convert a roof surface into JSON-safe preview topology."""
    return {
        "vertices": [list(point) for point in surface.vertices],
        "faces": [list(face) for face in surface.faces],
        "face_slope_indices": list(surface.face_slope_indices),
        "planes": [[float(p.a), float(p.b), float(p.c)] for p in surface.planes],
    }


def normalise_roof_plan(data: dict):
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
    _vertices, faces, slopes, planes = normalise_roof_plan(plan_data)
    return _visible_edges(faces, slopes, planes)


def point_in_polygon(point, polygon, epsilon=1.0e-9):
    """Inclusive point-in-polygon test, including points on polygon edges."""
    x, y = point
    inside = False
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        dx, dy = second[0] - first[0], second[1] - first[1]
        length_sq = dx * dx + dy * dy
        if length_sq > 1.0e-24:
            t = max(0.0, min(1.0, ((x - first[0]) * dx + (y - first[1]) * dy) / length_sq))
            closest = (first[0] + t * dx, first[1] + t * dy)
            if math.hypot(x - closest[0], y - closest[1]) <= epsilon:
                return True
        if (first[1] > y) != (second[1] > y):
            cross_x = first[0] + (y - first[1]) * dx / dy
            if x < cross_x:
                inside = not inside
    return inside


def polygon_area_centroid(polygon):
    """Return unsigned area and the continuous area centroid of a 2D polygon."""
    twice_area = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    for index, first in enumerate(polygon):
        second = polygon[(index + 1) % len(polygon)]
        cross = first[0] * second[1] - second[0] * first[1]
        twice_area += cross
        centroid_x += (first[0] + second[0]) * cross
        centroid_y += (first[1] + second[1]) * cross
    if abs(twice_area) <= 1.0e-15:
        center = (
            sum(point[0] for point in polygon) / len(polygon),
            sum(point[1] for point in polygon) / len(polygon),
        )
        return 0.0, center
    return abs(twice_area) * 0.5, (
        centroid_x / (3.0 * twice_area),
        centroid_y / (3.0 * twice_area),
    )


def _segment_distance(point, first, second):
    dx, dy = second[0] - first[0], second[1] - first[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1.0e-24:
        return math.hypot(point[0] - first[0], point[1] - first[1])
    t = max(0.0, min(1.0, (
        (point[0] - first[0]) * dx + (point[1] - first[1]) * dy
    ) / length_sq))
    return math.hypot(
        point[0] - (first[0] + t * dx),
        point[1] - (first[1] + t * dy),
    )


def _clearance(point, polygon):
    if not point_in_polygon(point, polygon):
        return 0.0
    return min(
        _segment_distance(point, polygon[index], polygon[(index + 1) % len(polygon)])
        for index in range(len(polygon))
    )


def _label_center(polygon):
    """Higher-resolution fallback for strongly concave, disconnected face pieces."""
    min_x = min(point[0] for point in polygon)
    max_x = max(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_y = max(point[1] for point in polygon)
    width, height = max_x - min_x, max_y - min_y
    if width <= 1.0e-12 or height <= 1.0e-12:
        return ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5), 0.0
    divisions = 48
    sx, sy = width / divisions, height / divisions
    best, best_clearance = polygon_area_centroid(polygon)[1], -1.0
    for iy in range(divisions):
        for ix in range(divisions):
            candidate = (min_x + (ix + 0.5) * sx, min_y + (iy + 0.5) * sy)
            distance = _clearance(candidate, polygon)
            if distance > best_clearance:
                best, best_clearance = candidate, distance
    if best_clearance <= 0.0:
        return best, 0.0
    for _ in range(5):
        sx *= 0.2
        sy *= 0.2
        for iy in range(-3, 4):
            for ix in range(-3, 4):
                candidate = (best[0] + ix * sx, best[1] + iy * sy)
                distance = _clearance(candidate, polygon)
                if distance > best_clearance:
                    best, best_clearance = candidate, distance
    return best, max(0.0, best_clearance)


def slope_region_centers(vertices, faces, slopes):
    """Find stable label anchors from the area centroid of every slope region.

    Averaging all faces assigned to a slope prevents the label from jumping
    between whichever individual face happens to be largest after a rebuild.
    A pole-of-inaccessibility fallback is used only when the aggregate centroid
    falls outside a strongly concave region.
    """
    grouped = {}
    for face, slope_index in zip(faces, slopes):
        polygon = [(vertices[index][0], vertices[index][1]) for index in face]
        area, center = polygon_area_centroid(polygon)
        if area <= 1.0e-15:
            continue
        group = grouped.setdefault(slope_index, [])
        group.append((area, center, polygon))

    labels = []
    for slope_index in sorted(grouped):
        pieces = grouped[slope_index]
        total_area = sum(piece[0] for piece in pieces)
        center = (
            sum(area * item_center[0] for area, item_center, _poly in pieces) / total_area,
            sum(area * item_center[1] for area, item_center, _poly in pieces) / total_area,
        )
        containing = [polygon for _area, _item_center, polygon in pieces if point_in_polygon(center, polygon)]
        if containing:
            clearance = max(_clearance(center, polygon) for polygon in containing)
        else:
            largest_polygon = max(pieces, key=lambda piece: piece[0])[2]
            center, clearance = _label_center(largest_polygon)
        labels.append((slope_index, center, clearance))
    return tuple(labels)


__all__ = [
    "surface_plan_data",
    "normalise_roof_plan",
    "visible_roof_edges",
    "polygon_area_centroid",
    "point_in_polygon",
    "slope_region_centers",
]
