"""Topology-aware snapping to adjacent roof-slope intersection events.

The helpers in this module are deliberately Blender-independent so the
search and its vertex-count semantics can be covered by the normal unit suite.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence


def _point_lies_on_segment_3d(point, start, end, tolerance):
    direction = tuple(float(end[i]) - float(start[i]) for i in range(3))
    relative = tuple(float(point[i]) - float(start[i]) for i in range(3))
    length_sq = sum(value * value for value in direction)
    if length_sq <= tolerance * tolerance:
        return math.dist(point, start) <= tolerance
    parameter = sum(relative[i] * direction[i] for i in range(3)) / length_sq
    parameter_tolerance = tolerance / math.sqrt(length_sq)
    if parameter < -parameter_tolerance or parameter > 1.0 + parameter_tolerance:
        return False
    parameter = max(0.0, min(1.0, parameter))
    closest = tuple(float(start[i]) + parameter * direction[i] for i in range(3))
    return math.dist(point, closest) <= tolerance


def count_slope_upper_vertices(surface, points, slope_index, *, tolerance=None):
    """Count unique vertices of a source slope excluding its original eave edge.

    Roof surfaces may split one source slope into several coplanar face pieces.
    Collecting their shared vertex indices counts each actual intersection
    node once. Every point on the authored eave segment is excluded, leaving
    the upper ridge/valley chain that the pitch controls are intended to snap.
    """
    faces = getattr(surface, "faces", ())
    face_sources = getattr(surface, "face_slope_indices", ())
    vertices = getattr(surface, "vertices", ())
    if len(faces) != len(face_sources) or len(points) < 2:
        return None
    if slope_index < 0 or slope_index >= len(points):
        return None

    vertex_ids = set()
    for face, source_index in zip(faces, face_sources):
        if int(source_index) == int(slope_index):
            vertex_ids.update(int(index) for index in face)

    if not vertex_ids:
        return None
    if any(index < 0 or index >= len(vertices) for index in vertex_ids):
        return None

    coordinate_span = max(
        max(float(point[axis]) for point in points)
        - min(float(point[axis]) for point in points)
        for axis in range(3)
    )
    linear_tolerance = (
        max(1.0e-10, coordinate_span * 1.0e-8)
        if tolerance is None
        else max(1.0e-12, float(tolerance))
    )
    eave_start = tuple(float(value) for value in points[slope_index])
    eave_end = tuple(float(value) for value in points[(slope_index + 1) % len(points)])

    return sum(
        not _point_lies_on_segment_3d(
            vertices[vertex_id], eave_start, eave_end, linear_tolerance
        )
        for vertex_id in vertex_ids
    )


def find_adjacent_pitch_angle(
    points: Sequence[Sequence[float]],
    pitches_degrees: Sequence[float],
    slope_index: int,
    direction: int,
    build_surface: Callable[[Sequence[Sequence[float]], Sequence[float]], object],
    *,
    min_pitch: float = 1.0,
    max_pitch: float = 85.0,
    coarse_step: float = 0.25,
    max_coarse_step: float = 2.0,
    iterations: int = 24,
) -> float | None:
    """Find the nearest pitch where the selected slope has exactly one fewer
    upper intersection vertex.

    A growing coarse step brackets the first topology reduction without
    requiring a dense, fixed-angle scan. Bisection then approaches the event
    from the side on which the reduced topology is already valid. Unsupported
    trial geometries fail silently and never produce a proposed angle.
    """
    if len(points) < 3 or len(pitches_degrees) != len(points):
        return None
    if slope_index < 0 or slope_index >= len(pitches_degrees):
        return None

    direction = 1 if direction >= 0 else -1
    current_angle = float(pitches_degrees[slope_index])
    lower_limit = float(min_pitch)
    upper_limit = float(max_pitch)
    if not (lower_limit <= current_angle <= upper_limit):
        return None
    limit = upper_limit if direction > 0 else lower_limit
    if abs(limit - current_angle) <= 1.0e-9:
        return None

    def count_at(angle):
        trial_pitches = [float(value) for value in pitches_degrees]
        trial_pitches[slope_index] = float(angle)
        try:
            surface = build_surface(points, trial_pitches)
            return count_slope_upper_vertices(surface, points, slope_index)
        except Exception:
            return None

    current_count = count_at(current_angle)
    if current_count is None or current_count < 1:
        return None
    target_count = current_count - 1

    unchanged_angle = current_angle
    changed_angle = None
    step = min(max(float(coarse_step), 1.0e-4), abs(limit - current_angle))
    maximum_step = max(step, float(max_coarse_step))

    while abs(limit - unchanged_angle) > 1.0e-9:
        remaining = abs(limit - unchanged_angle)
        trial_angle = unchanged_angle + direction * min(step, remaining)
        trial_count = count_at(trial_angle)
        if trial_count is None:
            return None
        if trial_count < current_count:
            changed_angle = trial_angle
            break
        unchanged_angle = trial_angle
        step = min(step * 1.6, maximum_step)

    if changed_angle is None:
        return None

    low = min(unchanged_angle, changed_angle)
    high = max(unchanged_angle, changed_angle)
    for _iteration in range(max(1, int(iterations))):
        middle = (low + high) * 0.5
        middle_count = count_at(middle)
        if middle_count is None:
            return None
        is_changed = middle_count < current_count
        if direction > 0:
            if is_changed:
                high = middle
            else:
                low = middle
        else:
            if is_changed:
                low = middle
            else:
                high = middle

    candidate = high if direction > 0 else low
    if count_at(candidate) != target_count:
        return None
    return candidate


__all__ = [
    "count_slope_upper_vertices",
    "find_adjacent_pitch_angle",
]
