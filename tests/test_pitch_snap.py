"""Tests for analytic pitch snapping to neighbouring roof vertices."""
from dataclasses import dataclass
import math
import unittest

from core.geometry import build_boundary_planes
from core.pitch_snap import (
    _neighbour_vertex_targets,
    find_adjacent_pitch_vertex_angle,
)


POINTS = (
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 3.0, 0.0),
    (0.0, 3.0, 0.0),
)
TARGET = (2.0, 1.0, 2.0 * math.tan(math.radians(30.0)))
TARGET_ANGLE = math.degrees(math.atan(2.0 * math.tan(math.radians(30.0))))


@dataclass(frozen=True)
class Surface:
    vertices: tuple
    faces: tuple
    face_slope_indices: tuple


def snapped_surface(target=TARGET):
    return Surface(
        vertices=POINTS + (target,),
        faces=(
            (0, 1, 4),
            (1, 2, 4),
            (2, 3, 4),
        ),
        face_slope_indices=(0, 1, 2),
    )


def neighbour_only_surface(target=TARGET):
    return Surface(
        vertices=POINTS + (target,),
        faces=(
            (1, 2, 4),
            (2, 3, 4),
        ),
        face_slope_indices=(1, 2),
    )


class PitchSnapTests(unittest.TestCase):
    def test_three_other_slopes_define_the_expected_internal_vertex(self):
        planes = build_boundary_planes(POINTS, (20.0, 30.0, 30.0, 30.0))
        targets = _neighbour_vertex_targets(POINTS, planes, 0)
        self.assertEqual(len(targets), 1)
        for actual, expected in zip(targets[0], TARGET):
            self.assertAlmostEqual(actual, expected, places=7)

    def test_next_snaps_to_nearest_higher_neighbour_vertex(self):
        def build_surface(_points, pitches):
            self.assertAlmostEqual(pitches[0], TARGET_ANGLE, places=7)
            return snapped_surface()

        result = find_adjacent_pitch_vertex_angle(
            POINTS,
            (20.0, 30.0, 30.0, 30.0),
            0,
            1,
            build_surface,
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.angle_degrees, TARGET_ANGLE, places=7)
        self.assertEqual(result.target_vertex, TARGET)

    def test_previous_snaps_to_nearest_lower_neighbour_vertex(self):
        def build_surface(_points, pitches):
            self.assertAlmostEqual(pitches[0], TARGET_ANGLE, places=7)
            return snapped_surface()

        result = find_adjacent_pitch_vertex_angle(
            POINTS,
            (55.0, 30.0, 30.0, 30.0),
            0,
            -1,
            build_surface,
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.angle_degrees, TARGET_ANGLE, places=7)

    def test_candidate_requires_shared_vertex_in_final_production_build(self):
        result = find_adjacent_pitch_vertex_angle(
            POINTS,
            (20.0, 30.0, 30.0, 30.0),
            0,
            1,
            lambda _points, _pitches: neighbour_only_surface(),
        )
        self.assertIsNone(result)

    def test_no_vertex_in_requested_direction_is_a_noop(self):
        result = find_adjacent_pitch_vertex_angle(
            POINTS,
            (60.0, 30.0, 30.0, 30.0),
            0,
            1,
            lambda _points, _pitches: snapped_surface(),
        )
        self.assertIsNone(result)

    def test_contour_with_only_two_other_slopes_has_no_interior_triple_vertex(self):
        triangle = (
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (2.0, 3.0, 0.0),
        )
        result = find_adjacent_pitch_vertex_angle(
            triangle,
            (20.0, 30.0, 30.0),
            0,
            1,
            lambda _points, _pitches: snapped_surface(),
        )
        self.assertIsNone(result)

    def test_failed_final_build_reports_the_real_build_error(self):
        def fail_build(_points, _pitches):
            raise ValueError("test roof build failure")

        with self.assertRaisesRegex(RuntimeError, "test roof build failure"):
            find_adjacent_pitch_vertex_angle(
                POINTS,
                (20.0, 30.0, 30.0, 30.0),
                0,
                1,
                fail_build,
            )


if __name__ == "__main__":
    unittest.main()
