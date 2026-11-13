"""Geometric pitch snapping to vertices formed by neighbouring roof slopes.

The reference roof is built with the selected source plane suppressed. Its
multi-slope vertices are therefore fixed targets. For each target, solve the
selected edge pitch analytically, then ask the production roof builder to
confirm that the selected slope really shares that vertex.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Sequence


Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class PitchSnapCandidate:
    """A verified pitch and the neighbouring roof vertex it meets."""

    angle_degrees: float
    target_vertex: Point3


def _coordinate_span(points: Sequence[Sequence[float]]) -> float:
    return max(
        1.0,
        *(
            max(float(point[axis]) for point in points)
            - min(float(point[axis]) for point in points)
            for axis in range(3)
        ),
    )


def _point_lies_on_segment_3d(
    point: Sequence[float],
    start: Sequence[float],
    end: Sequence[float],
    tolerance: float,
) -> bool:
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
    closest = tuple(
        float(start[i]) + parameter * direction[i] for i in range(3)
    )
    return math.dist(point, closest) <= tolerance


def _surface_vertex_owners(surface) -> dict[int, set[int]]:
    """Return the distinct source slopes whose faces use each mesh vertex."""
    faces = getattr(surface, "faces", ())
    face_sources = getattr(surface, "face_slope_indices", ())
    if len(faces) != len(face_sources):
        return {}

    owners: dict[int, set[int]] = {}
    for face, source_index in zip(faces, face_sources):
        source_index = int(source_index)
        if source_index < 0:
            continue
        for vertex_index in face:
            owners.setdefault(int(vertex_index), set()).add(source_index)
    return owners


def _reference_vertices(
    surface,
    points: Sequence[Sequence[float]],
    selected_slope: int,
    tolerance: float,
) -> list[Point3]:
    """Collect internal vertices shared by at least two non-selected slopes."""
    vertices = getattr(surface, "vertices", ())
    owners = _surface_vertex_owners(surface)
    if not owners or not vertices:
        return []

    eave_segments = [
        (points[index], points[(index + 1) % len(points)])
        for index in range(len(points))
    ]
    result: list[Point3] = []
    for vertex_index, slope_owners in owners.items():
        if selected_slope in slope_owners or len(slope_owners) < 2:
            continue
        if vertex_index < 0 or vertex_index >= len(vertices):
            continue
        point = tuple(float(value) for value in vertices[vertex_index])
        if any(
            _point_lies_on_segment_3d(point, start, end, tolerance)
            for start, end in eave_segments
        ):
            continue
        if not any(math.dist(point, existing) <= tolerance for existing in result):
            result.append(point)
    return result


def _pitch_for_plane_through_vertex(
    points: Sequence[Sequence[float]],
    slope_index: int,
    target: Sequence[float],
) -> float | None:
    """Solve the selected edge pitch whose support plane passes through target."""
    count = len(points)
    start = tuple(float(value) for value in points[slope_index])
    end = tuple(float(value) for value in points[(slope_index + 1) % count])
    dx, dy = end[0] - start[0], end[1] - start[1]
    edge_length = math.hypot(dx, dy)
    if edge_length <= 1.0e-12:
        return None

    area_twice = sum(
        float(points[index][0]) * float(points[(index + 1) % count][1])
        - float(points[(index + 1) % count][0]) * float(points[index][1])
        for index in range(count)
    )
    if abs(area_twice) <= 1.0e-12:
        return None
    winding = 1.0 if area_twice > 0.0 else -1.0

    tangent = (dx / edge_length, dy / edge_length)
    inward = (-tangent[1] * winding, tangent[0] * winding)
    along_gradient = (end[2] - start[2]) / edge_length

    offset_x = float(target[0]) - start[0]
    offset_y = float(target[1]) - start[1]
    along_offset = offset_x * tangent[0] + offset_y * tangent[1]
    inward_offset = offset_x * inward[0] + offset_y * inward[1]
    if abs(inward_offset) <= 1.0e-10 * max(1.0, edge_length):
        return None

    required_height = float(target[2]) - (
        start[2] + along_gradient * along_offset
    )
    cross_gradient = required_height / inward_offset
    gradient_tolerance = 1.0e-10 * max(1.0, abs(along_gradient))
    if cross_gradient < -gradient_tolerance:
        return None
    cross_gradient = max(0.0, cross_gradient)

    total_gradient = math.hypot(along_gradient, cross_gradient)
    return math.degrees(math.atan(total_gradient))


def _surface_shares_target_vertex(
    surface,
    selected_slope: int,
    target: Sequence[float],
    tolerance: float,
) -> bool:
    vertices = getattr(surface, "vertices", ())
    owners = _surface_vertex_owners(surface)
    for vertex_index, slope_owners in owners.items():
        if selected_slope not in slope_owners or len(slope_owners) < 2:
            continue
        if vertex_index < 0 or vertex_index >= len(vertices):
            continue
        if math.dist(vertices[vertex_index], target) <= tolerance:
            return True
    return False


def find_adjacent_pitch_vertex_angle(
    points: Sequence[Sequence[float]],
    pitches_degrees: Sequence[float],
    slope_index: int,
    direction: int,
    build_surface: Callable[
        [Sequence[Sequence[float]], Sequence[float]], object
    ],
    build_neighbour_surface: Callable[
        [Sequence[Sequence[float]], Sequence[float], int], object
    ],
    *,
    min_pitch: float = 1.0,
    max_pitch: float = 85.0,
    angle_tolerance: float = 1.0e-5,
    max_trials: int = 64,
) -> PitchSnapCandidate | None:
    """Find the nearest real neighbouring vertex in the requested angle direction.

    The neighbour-surface builder must retain the original source slope indices
    but replace the selected source plane with an inactive/high plane. This
    gives fixed intersection vertices formed exclusively by the other slopes.
    Candidate angles are solved from the plane equation, not sampled. A final
    production build verifies that the selected and neighbouring slopes
    actually share the target coordinate before the angle is returned.
    """
    count = len(points)
    if count < 3 or len(pitches_degrees) != count:
        return None
    if slope_index < 0 or slope_index >= count:
        return None

    current_angle = float(pitches_degrees[slope_index])
    if not (
        math.isfinite(current_angle)
        and float(min_pitch) <= current_angle <= float(max_pitch)
    ):
        return None

    direction = 1 if direction >= 0 else -1
    scale = _coordinate_span(points)
    position_tolerance = max(1.0e-7, scale * 1.0e-6)
    eave_tolerance = max(1.0e-8, scale * 1.0e-8)

    reference_surface = build_neighbour_surface(
        points, pitches_degrees, slope_index
    )
    targets = _reference_vertices(
        reference_surface, points, slope_index, eave_tolerance
    )
    if not targets:
        return None

    candidates: list[tuple[float, Point3]] = []
    for target in targets:
        angle = _pitch_for_plane_through_vertex(points, slope_index, target)
        if angle is None or not math.isfinite(angle):
            continue
        if angle < float(min_pitch) - angle_tolerance:
            continue
        if angle > float(max_pitch) + angle_tolerance:
            continue
        if direction * (angle - current_angle) <= angle_tolerance:
            continue
        candidates.append((angle, target))

    candidates.sort(key=lambda item: abs(item[0] - current_angle))
    tested_angles: dict[float, object | None] = {}
    trial_count = 0
    for angle, target in candidates:
        angle_key = round(angle, 10)
        if angle_key not in tested_angles:
            if trial_count >= max(1, int(max_trials)):
                break
            trial_pitches = [float(value) for value in pitches_degrees]
            trial_pitches[slope_index] = angle
            try:
                tested_angles[angle_key] = build_surface(points, trial_pitches)
            except Exception:
                tested_angles[angle_key] = None
            trial_count += 1

        trial_surface = tested_angles[angle_key]
        if trial_surface is None:
            continue
        if _surface_shares_target_vertex(
            trial_surface, slope_index, target, position_tolerance
        ):
            return PitchSnapCandidate(
                angle_degrees=float(angle),
                target_vertex=tuple(float(value) for value in target),
            )

    return None


__all__ = [
    "PitchSnapCandidate",
    "find_adjacent_pitch_vertex_angle",
]
