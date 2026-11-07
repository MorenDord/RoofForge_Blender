import math
import unittest

from core.geometry import GeometryInputError, signed_area, validate_simple_polygon
from core.mesh import build_roof_surface
from core.overhang import offset_contour_outward
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh
from core.wavefront import build_wavefront_roof_surface


FLAT_RECTANGLE = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 3.0, 0.0),
    (0.0, 3.0, 0.0),
]
MIXED_Z_RECTANGLE = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.2),
    (4.0, 3.0, 0.4),
    (0.0, 3.0, 0.1),
]
CONCAVE_L = [
    (0.0, 0.0, 0.0),
    (8.0, 0.0, 0.0),
    (8.0, 3.0, 0.0),
    (3.0, 3.0, 0.0),
    (3.0, 8.0, 0.0),
    (0.0, 8.0, 0.0),
]
CONCAVE_U = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 4.0, 0.0),
    (3.0, 4.0, 0.0),
    (3.0, 1.0, 0.0),
    (1.0, 1.0, 0.0),
    (1.0, 4.0, 0.0),
    (0.0, 4.0, 0.0),
]


class RoofOverhangTests(unittest.TestCase):
    def _build_offset_roof(self, points, pitches, overhang):
        offset_points = offset_contour_outward(points, overhang)
        offset_xy = [(point[0], point[1]) for point in offset_points]
        self.assertEqual(validate_simple_polygon(offset_xy), [])
        self.assertGreater(
            abs(signed_area(offset_xy)),
            abs(signed_area([(p[0], p[1]) for p in points])),
        )

        # Edge order and count are unchanged, so pitch[i] still belongs to
        # edge offset_points[i] -> offset_points[i+1].
        if max(point[2] for point in offset_points) - min(
            point[2] for point in offset_points
        ) <= 1e-12:
            surface = build_wavefront_roof_surface(offset_points, pitches)
        else:
            surface = build_roof_surface(offset_points, pitches)

        self.assertEqual(surface.boundary_xy, tuple(offset_xy))
        self.assertAlmostEqual(
            surface.surface_area_xy,
            abs(signed_area(offset_xy)),
            delta=max(1e-7, abs(signed_area(offset_xy)) * 1e-7),
        )
        shell = build_roof_shell(surface, 0.01)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])
        return offset_points, surface, shell

    def _assert_offset_edge_geometry(self, source, offset, distance):
        source_xy = [(p[0], p[1]) for p in source]
        offset_xy = [(p[0], p[1]) for p in offset]
        winding = 1.0 if signed_area(source_xy) > 0.0 else -1.0
        self.assertEqual(len(source), len(offset))
        for index, start in enumerate(source_xy):
            end = source_xy[(index + 1) % len(source_xy)]
            outer_start = offset_xy[index]
            outer_end = offset_xy[(index + 1) % len(offset_xy)]
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            self.assertGreater(length, 1e-9)
            parallel_error = abs(
                dx * (outer_end[1] - outer_start[1])
                - dy * (outer_end[0] - outer_start[0])
            ) / length
            signed_distance = winding * (
                dx * (outer_start[1] - start[1])
                - dy * (outer_start[0] - start[0])
            ) / length
            self.assertAlmostEqual(parallel_error, 0.0, places=7)
            self.assertAlmostEqual(signed_distance, -distance, places=7)

    def test_equal_pitch_rectangle_creates_one_exact_offset_contour(self):
        offset, surface, _shell = self._build_offset_roof(
            FLAT_RECTANGLE, [35.0] * 4, 0.25
        )
        expected = (
            (-0.25, -0.25, 0.0),
            (4.25, -0.25, 0.0),
            (4.25, 3.25, 0.0),
            (-0.25, 3.25, 0.0),
        )
        for actual, wanted in zip(offset, expected):
            for actual_value, expected_value in zip(actual, wanted):
                self.assertAlmostEqual(actual_value, expected_value, places=7)
        self.assertEqual(len(surface.boundary_xy), 4)

    def test_custom_pitch_rectangle_uses_same_single_outer_loop(self):
        pitches = [30.0, 35.0, 40.0, 32.0]
        offset, surface, _shell = self._build_offset_roof(
            FLAT_RECTANGLE, pitches, 0.2
        )
        self._assert_offset_edge_geometry(FLAT_RECTANGLE, offset, 0.2)
        self.assertEqual(len(offset), len(pitches))
        self.assertEqual(len(surface.planes), len(pitches))
        self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
        self.assertTrue(
            all(0 <= slope_index < len(pitches) for slope_index in surface.face_slope_indices)
        )

    def test_mixed_z_contour_preserves_vertex_heights_and_custom_pitches(self):
        pitches = [38.0, 40.0, 42.0, 39.0]
        offset, _surface, _shell = self._build_offset_roof(
            MIXED_Z_RECTANGLE, pitches, 0.2
        )
        for source_point, offset_point in zip(MIXED_Z_RECTANGLE, offset):
            self.assertAlmostEqual(source_point[2], offset_point[2], places=9)
        self._assert_offset_edge_geometry(MIXED_Z_RECTANGLE, offset, 0.2)

    def test_mixed_z_contour_with_equal_pitch_supports_offset_rebuild(self):
        offset, _surface, _shell = self._build_offset_roof(
            MIXED_Z_RECTANGLE, [35.0] * 4, 0.2
        )
        self.assertEqual(len(offset), 4)

    def test_concave_l_contour_supports_custom_pitch_and_one_offset_loop(self):
        pitches = [31.0, 32.5, 34.0, 35.5, 37.0, 38.5]
        offset, surface, _shell = self._build_offset_roof(
            CONCAVE_L, pitches, 0.15
        )
        self._assert_offset_edge_geometry(CONCAVE_L, offset, 0.15)
        self.assertEqual(len(surface.planes), len(CONCAVE_L))

    def test_concave_u_contour_supports_custom_pitch_and_one_offset_loop(self):
        speeds = [0.8, 0.75, 1.0, 1.25, 1.2, 1.4, 1.0, 0.6]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        offset, surface, _shell = self._build_offset_roof(
            CONCAVE_U, pitches, 0.1
        )
        self._assert_offset_edge_geometry(CONCAVE_U, offset, 0.1)
        self.assertEqual(len(surface.planes), len(CONCAVE_U))

    def test_too_large_u_offset_is_rejected_before_roof_build(self):
        with self.assertRaises(GeometryInputError):
            offset_contour_outward(CONCAVE_U, 1.5)

    def test_clockwise_contour_offsets_outward_and_preserves_order(self):
        clockwise = list(reversed(FLAT_RECTANGLE))
        offset = offset_contour_outward(clockwise, 0.2)
        self._assert_offset_edge_geometry(clockwise, offset, 0.2)
        self.assertGreater(
            abs(signed_area([(p[0], p[1]) for p in offset])),
            abs(signed_area([(p[0], p[1]) for p in clockwise])),
        )

    def test_zero_distance_returns_same_contour(self):
        result = offset_contour_outward(MIXED_Z_RECTANGLE, 0.0)
        self.assertEqual(result, tuple(MIXED_Z_RECTANGLE))

    def test_negative_or_non_finite_distance_is_rejected(self):
        for distance in (-0.1, float("nan"), float("inf")):
            with self.subTest(distance=distance):
                with self.assertRaises(GeometryInputError):
                    offset_contour_outward(FLAT_RECTANGLE, distance)


if __name__ == "__main__":
    unittest.main()
