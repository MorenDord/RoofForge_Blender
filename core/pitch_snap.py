"""Geometric pitch snapping to vertices formed by neighbouring roof slopes.

Candidate vertices are computed directly from the analytic support planes.
This avoids trying to validate a deliberately incomplete "roof without one
slope", which is not a closed surface and can legitimately contain open edges.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math
from typing import Callable, Sequence

from .geometry import PlaneZ, build_boundary_planes


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


def _edge_projection(
    point: Sequence[float],
    start: Sequence[float],
    end: Sequence[float],
) -> float | None:
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    length_sq = dx * dx + dy * dy
    if length_sq <= 1.0e-20:
        return None
    return (
        (float(point[0]) - float(start[0])) * dx
        + (float(point[1]) - float(start[1])) * dy
    ) / length_sq


def _point_on_segment_xy(
    point: Sequence[float],
    start: Sequence[float],
    end: Sequence[float],
    tolerance: float,
) -> bool:
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    length_sq = dx * dx + dy * dy
    if length_sq <= tolerance * tolerance:
        return math.hypot(
            float(point[0]) - float(start[0]),
            float(point[1]) - float(start[1]),
        ) <= tolerance
    parameter = (
        (float(point[0]) - float(start[0])) * dx
        + (float(point[1]) - float(start[1])) * dy
    ) / length_sq
    if parameter < 0.0 or parameter > 1.0:
        return False
    closest_x = float(start[0]) + parameter * dx
    closest_y = float(start[1]) + parameter * dy
    return math.hypot(
        float(point[0]) - closest_x,
        float(point[1]) - closest_y,
    ) <= tolerance


def _strictly_inside_polygon(
    point: Sequence[float],
    polygon: Sequence[Sequence[float]],
    tolerance: float,
) -> bool:
    """Return True only for a point strictly inside the authored XY contour."""
    inside = False
    x, y = float(point[0]), float(point[1])
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if _point_on_segment_xy((x, y), start, end, tolerance):
            return False
        x0, y0 = float(start[0]), float(start[1])
        x1, y1 = float(end[0]), float(end[1])
        if (y0 > y) != (y1 > y):
            crossing_x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < crossing_x:
                inside = not inside
    return inside


def _intersect_three_planes(
    first: PlaneZ,
    second: PlaneZ,
    third: PlaneZ,
) -> Point3 | None:
    """Intersect three z=ax+by+c planes, rejecting parallel/ill-conditioned sets."""
    a11 = first.a - second.a
    a12 = first.b - second.b
    rhs1 = second.c - first.c
    a21 = first.a - third.a
    a22 = first.b - third.b
    rhs2 = third.c - first.c
    determinant = a11 * a22 - a12 * a21
    determinant_scale = max(
        1.0,
        abs(a11 * a22),
        abs(a12 * a21),
    )
    if abs(determinant) <= 1.0e-12 * determinant_scale:
        return None

    x = (rhs1 * a22 - a12 * rhs2) / determinant
    y = (a11 * rhs2 - rhs1 * a21) / determinant
    heights = (
        first.height(x, y),
        second.height(x, y),
        third.height(x, y),
    )
    z = sum(heights) / 3.0
    if not all(math.isfinite(value) for value in (x, y, z)):
        return None
    if max(heights) - min(heights) > 1.0e-7 * max(1.0, abs(z)):
        return None
    return (x, y, z)


def _neighbour_vertex_targets(
    points: Sequence[Sequence[float]],
    planes: Sequence[PlaneZ],
    excluded_slope: int,
) -> list[Point3]:
    """Find internal lower-envelope vertices made by three other finite slopes.

    Each participating plane must be active over its own finite source edge.
    A candidate is discarded when another eligible non-excluded plane lies
    below it. The selected slope is intentionally omitted from this test:
    its current pitch must not hide the vertex to which it is supposed to snap.
    """
    count = len(points)
    if count < 4 or len(planes) != count:
        return []

    scale = _coordinate_span(points)
    position_tolerance = max(1.0e-8, scale * 1.0e-8)
    projection_margin = max(1.0e-9, scale * 2.0e-8)
    height_tolerance = max(1.0e-8, scale * 1.0e-7)
    eligible_indices = [
        index for index in range(count) if index != excluded_slope
    ]
    targets: list[Point3] = []
    min_x = min(float(point[0]) for point in points)
    max_x = max(float(point[0]) for point in points)
    min_y = min(float(point[1]) for point in points)
    max_y = max(float(point[1]) for point in points)

    for triple in combinations(eligible_indices, 3):
        first, second, third = triple
        target = _intersect_three_planes(
            planes[first], planes[second], planes[third]
        )
        if target is None:
            continue
        # Cheap finite-edge and bounding-box filters run before the
        # contour point-in-polygon test. This keeps large (up to 256-edge)
        # contours responsive while preserving the exact active-edge rules.
        triple_is_active = True
        for slope_index in triple:
            projection = _edge_projection(
                target,
                points[slope_index],
                points[(slope_index + 1) % count],
            )
            if (
                projection is None
                or projection <= projection_margin
                or projection >= 1.0 - projection_margin
            ):
                triple_is_active = False
                break
        if not triple_is_active:
            continue

        # The selected slope must also reach this point over its own finite
        # edge. Its height is deliberately not compared here.
        selected_projection = _edge_projection(
            target,
            points[excluded_slope],
            points[(excluded_slope + 1) % count],
        )
        if (
            selected_projection is None
            or selected_projection <= projection_margin
            or selected_projection >= 1.0 - projection_margin
        ):
            continue

        if (
            target[0] < min_x - position_tolerance
            or target[0] > max_x + position_tolerance
            or target[1] < min_y - position_tolerance
            or target[1] > max_y + position_tolerance
            or not _strictly_inside_polygon(target, points, position_tolerance)
        ):
            continue

        # Keep only vertices of the lower envelope of the remaining slopes.
        # Ineligible finite edges do not compete at this point.
        hidden_by_neighbour = False
        for slope_index in eligible_indices:
            if slope_index in triple:
                continue
            projection = _edge_projection(
                target,
                points[slope_index],
                points[(slope_index + 1) % count],
            )
            if (
                projection is None
                or projection <= projection_margin
                or projection >= 1.0 - projection_margin
            ):
                continue
            if planes[slope_index].height(target[0], target[1]) < (
                target[2] - height_tolerance
            ):
                hidden_by_neighbour = True
                break
        if hidden_by_neighbour:
            continue

        if not any(
            math.dist(target, existing) <= position_tolerance
            for existing in targets
        ):
            targets.append(target)

    targets.sort(key=lambda point: (point[0], point[1], point[2]))
    return targets


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
    *,
    min_pitch: float = 1.0,
    max_pitch: float = 85.0,
    angle_tolerance: float = 1.0e-5,
    max_trials: int = 64,
) -> PitchSnapCandidate | None:
    """Find the nearest real neighbouring vertex in the requested angle direction.

    Neighbour vertices are solved analytically from the other finite support
    planes. No incomplete roof mesh is assembled or boundary-validated.
    Candidate angles are solved from the selected plane equation. A final
    production build verifies that selected and neighbouring slopes share the
    same 3D vertex before the value is accepted.
    """
    count = len(points)
    if count < 4 or len(pitches_degrees) != count:
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
    planes = build_boundary_planes(points, pitches_degrees)
    targets = _neighbour_vertex_targets(points, planes, slope_index)
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
    last_build_error: Exception | None = None
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
            except Exception as exc:
                tested_angles[angle_key] = None
                last_build_error = exc
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

    if last_build_error is not None:
        message = str(getattr(last_build_error, "message", last_build_error))
        raise RuntimeError(
            "Не удалось проверить ближайшую вершину на полной крыше: " + message
        ) from last_build_error
    return None


__all__ = [
    "PitchSnapCandidate",
    "find_adjacent_pitch_vertex_angle",
    "_neighbour_vertex_targets",
]
