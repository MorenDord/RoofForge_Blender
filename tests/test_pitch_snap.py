"""Tests for counting and snapping adjacent slope intersection nodes."""
from types import SimpleNamespace
import unittest

from core.pitch_snap import (
    count_slope_upper_vertices,
    find_adjacent_pitch_angle,
)


POINTS = (
    (0.0, 0.0, 0.0),
    (10.0, 0.0, 0.0),
    (10.0, 10.0, 0.0),
)


def make_surface(upper_count):
    vertices = [
        POINTS[0],
        (5.0, 0.0, 0.0),  # A collinear eave point is not an upper intersection.
        POINTS[1],
    ]
    vertices.extend(
        (float(index), 3.0 + index, 4.0 + index)
        for index in range(upper_count)
    )
    face = tuple(range(len(vertices)))
    return SimpleNamespace(
        vertices=tuple(vertices),
        faces=(face,),
        face_slope_indices=(0,),
    )


class PitchSnapTests(unittest.TestCase):
    def test_counts_unique_upper_vertices_and_ignores_eave_points(self):
        surface = make_surface(3)
        self.assertEqual(count_slope_upper_vertices(surface, POINTS, 0), 3)

    def test_next_finds_first_reduction_in_increasing_direction(self):
        def build_surface(_points, pitches):
            angle = pitches[0]
            count = 1 if angle < 30.0 else 2 if angle < 35.0 else 3 if angle < 40.0 else 2
            return make_surface(count)

        candidate = find_adjacent_pitch_angle(
            POINTS, (35.0, 30.0, 30.0), 0, 1, build_surface
        )
        self.assertIsNotNone(candidate)
        self.assertGreaterEqual(candidate, 40.0)
        self.assertLess(candidate, 40.001)

    def test_previous_finds_first_reduction_in_decreasing_direction(self):
        def build_surface(_points, pitches):
            angle = pitches[0]
            count = 1 if angle < 30.0 else 2 if angle < 35.0 else 3 if angle < 40.0 else 2
            return make_surface(count)

        candidate = find_adjacent_pitch_angle(
            POINTS, (35.0, 30.0, 30.0), 0, -1, build_surface
        )
        self.assertIsNotNone(candidate)
        self.assertLess(candidate, 35.0)
        self.assertGreater(candidate, 34.999)

    def test_previous_from_two_upper_nodes_finds_one(self):
        def build_surface(_points, pitches):
            count = 1 if pitches[0] < 30.0 else 2
            return make_surface(count)

        candidate = find_adjacent_pitch_angle(
            POINTS, (32.0, 30.0, 30.0), 0, -1, build_surface
        )
        self.assertIsNotNone(candidate)
        self.assertLess(candidate, 30.0)
        self.assertGreater(candidate, 29.999)

    def test_missing_adjacent_reduction_is_a_noop(self):
        def build_surface(_points, _pitches):
            return make_surface(2)

        self.assertIsNone(
            find_adjacent_pitch_angle(
                POINTS, (35.0, 30.0, 30.0), 0, 1, build_surface
            )
        )


if __name__ == "__main__":
    unittest.main()
