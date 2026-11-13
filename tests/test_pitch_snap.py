"""Tests for geometric pitch snapping to neighbouring roof vertices."""
from dataclasses import dataclass
import math
from types import SimpleNamespace
import unittest

from core.pitch_snap import find_adjacent_pitch_vertex_angle


POINTS = (
    (0.0, 0.0, 0.0),
    (10.0, 0.0, 0.0),
    (10.0, 10.0, 0.0),
    (0.0, 10.0, 0.0),
)
TARGET = (5.0, 8.0, 4.0)
TARGET_ANGLE = math.degrees(math.atan(0.5))


@dataclass(frozen=True)
class Surface:
    vertices: tuple
    faces: tuple
    face_slope_indices: tuple


def neighbour_surface(target=TARGET):
    return Surface(
        vertices=POINTS + (target,),
        faces=(
            (1, 2, 4),
            (2, 3, 4),
        ),
        face_slope_indices=(1, 2),
    )


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


class PitchSnapTests(unittest.TestCase):
    def run_snap(self, current_angle, direction, *, final_surface=None):
        target_surface = neighbour_surface()

        def build_neighbours(_points, _pitches, excluded):
            self.assertEqual(excluded, 0)
            return target_surface

        def build_full(_points, pitches):
            if final_surface is not None:
                return final_surface
            self.assertAlmostEqual(pitches[0], TARGET_ANGLE, places=7)
            return snapped_surface()

        return find_adjacent_pitch_vertex_angle(
            POINTS,
            (current_angle, 30.0, 30.0, 30.0),
            0,
            direction,
            build_full,
            build_neighbours,
        )

    def test_previous_snaps_to_the_nearest_lower_pitch_vertex(self):
        result = self.run_snap(30.0, -1)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.angle_degrees, TARGET_ANGLE, places=7)
        self.assertEqual(result.target_vertex, TARGET)

    def test_next_snaps_to_the_nearest_higher_pitch_vertex(self):
        result = self.run_snap(20.0, 1)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.angle_degrees, TARGET_ANGLE, places=7)
        self.assertEqual(result.target_vertex, TARGET)

    def test_candidate_must_be_shared_in_the_final_roof(self):
        result = self.run_snap(
            20.0,
            1,
            final_surface=neighbour_surface(),
        )
        self.assertIsNone(result)

    def test_candidate_on_the_eave_is_not_a_roof_vertex_target(self):
        eave_target = POINTS[0]
        reference = Surface(
            vertices=POINTS,
            faces=((0, 1, 2), (0, 2, 3)),
            face_slope_indices=(1, 2),
        )

        result = find_adjacent_pitch_vertex_angle(
            POINTS,
            (20.0, 30.0, 30.0, 30.0),
            0,
            1,
            lambda _points, _pitches: snapped_surface(eave_target),
            lambda _points, _pitches, _excluded: reference,
        )
        self.assertIsNone(result)

    def test_no_vertex_in_requested_direction_is_a_noop(self):
        result = self.run_snap(20.0, -1)
        self.assertIsNone(result)

    def test_invalid_surface_metadata_has_no_candidate(self):
        malformed = SimpleNamespace(
            vertices=POINTS + (TARGET,),
            faces=((1, 2, 4), (2, 3, 4)),
            face_slope_indices=(1,),
        )
        result = find_adjacent_pitch_vertex_angle(
            POINTS,
            (20.0, 30.0, 30.0, 30.0),
            0,
            1,
            lambda _points, _pitches: snapped_surface(),
            lambda _points, _pitches, _excluded: malformed,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
