import unittest

from core.geometry import GeometryInputError
from core.mesh import build_roof_surface
from core.overhang import extend_convex_roof_surface
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
    def _assert_extended_shell(self, surface, overhang):
        extended = extend_convex_roof_surface(surface, overhang)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        self.assertEqual(len(extended.boundary_xy), len(surface.boundary_xy))
        shell = build_roof_shell(extended, 0.01)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])
        return extended

    def test_equal_pitch_flat_contour_has_exact_miter_offset(self):
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, [35.0] * 4)
        extended = self._assert_extended_shell(surface, 0.25)
        expected = {
            (-0.25, -0.25),
            (4.25, -0.25),
            (4.25, 3.25),
            (-0.25, 3.25),
        }
        actual = {
            (round(point[0], 6), round(point[1], 6))
            for point in extended.boundary_xy
        }
        self.assertEqual(actual, expected)

    def test_individual_pitches_on_flat_convex_contour_keep_overhang_parallel(self):
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, [30.0, 35.0, 40.0, 32.0])
        extended = self._assert_extended_shell(surface, 0.2)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        for index, start in enumerate(FLAT_RECTANGLE):
            end = FLAT_RECTANGLE[(index + 1) % len(FLAT_RECTANGLE)]
            outer_start = extended.boundary_xy[index]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = (dx * dx + dy * dy) ** 0.5
            signed_distance = (
                dx * (outer_start[1] - start[1])
                - dy * (outer_start[0] - start[0])
            ) / length
            self.assertAlmostEqual(signed_distance, -0.2, places=7)

    def test_mixed_z_contour_supports_individual_pitch_overhang(self):
        surface = build_roof_surface(MIXED_Z_RECTANGLE, [38.0, 40.0, 42.0, 39.0])
        extended = self._assert_extended_shell(surface, 0.2)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)

    def test_mixed_z_contour_with_equal_pitch_supports_overhang(self):
        surface = build_roof_surface(MIXED_Z_RECTANGLE, [35.0] * 4)
        self._assert_extended_shell(surface, 0.2)

    def test_concave_l_with_individual_pitch_supports_overhang(self):
        pitches = [31.0, 32.5, 34.0, 35.5, 37.0, 38.5]
        surface = build_wavefront_roof_surface(CONCAVE_L, pitches)
        extended = self._assert_extended_shell(surface, 0.15)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)

    def test_concave_u_with_individual_pitch_supports_overhang(self):
        pitches = [30.0, 32.5, 35.0, 37.5, 30.0, 32.5, 35.0, 37.5]
        surface = build_wavefront_roof_surface(CONCAVE_U, pitches)
        extended = self._assert_extended_shell(surface, 0.1)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)

    def test_too_large_concave_overhang_is_rejected_instead_of_self_intersecting(self):
        surface = build_wavefront_roof_surface(CONCAVE_L, [32.0] * len(CONCAVE_L))
        with self.assertRaises(GeometryInputError):
            extend_convex_roof_surface(surface, 3.0)

    def test_small_resolvable_convex_overhang_is_not_discarded_by_tolerance(self):
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, [35.0] * 4)
        self._assert_extended_shell(surface, 0.001)


if __name__ == "__main__":
    unittest.main()
