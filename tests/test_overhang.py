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


class RoofOverhangTests(unittest.TestCase):
    def _assert_extended_shell(self, surface, overhang):
        extended = extend_convex_roof_surface(surface, overhang)
        self.assertEqual(
            len(extended.faces) - len(surface.faces),
            len(surface.boundary_xy),
            "there must be one overhang strip per boundary segment, not corner fan faces",
        )
        added_slope_ids = extended.face_slope_indices[len(surface.faces):]
        self.assertTrue(
            all(slope_id >= 0 for slope_id in added_slope_ids),
            "every overhang strip must retain its originating edge plane",
        )
        shell = build_roof_shell(extended, 0.01)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])
        return extended

    def test_equal_pitch_flat_contour_uses_one_shared_miter_vertex(self):
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, [35.0] * 4)
        extended = self._assert_extended_shell(surface, 0.25)

        expected_corners = {
            (-0.25, -0.25),
            (4.25, -0.25),
            (4.25, 3.25),
            (-0.25, 3.25),
        }
        actual = {
            (round(point[0], 6), round(point[1], 6))
            for point in extended.boundary_xy
        }
        self.assertEqual(actual, expected_corners)
        for x, y in expected_corners:
            matching = [
                point for point in extended.vertices
                if abs(point[0] - x) < 1e-7 and abs(point[1] - y) < 1e-7
            ]
            self.assertEqual(len(matching), 1)

    def test_individual_pitches_on_flat_contour_support_overhang(self):
        pitches = [30.0, 35.0, 40.0, 32.0]
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, pitches)
        extended = self._assert_extended_shell(surface, 0.2)

        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        for face, slope_id in zip(
            extended.faces[len(surface.faces):],
            extended.face_slope_indices[len(surface.faces):],
        ):
            plane = surface.planes[slope_id]
            for vertex_index in face:
                x, y, z = extended.vertices[vertex_index]
                self.assertAlmostEqual(plane.height(x, y), z, places=7)

    def test_mixed_z_contour_supports_individual_pitch_overhang(self):
        pitches = [38.0, 40.0, 42.0, 39.0]
        surface = build_roof_surface(MIXED_Z_RECTANGLE, pitches)
        extended = self._assert_extended_shell(surface, 0.2)

        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        for face, slope_id in zip(
            extended.faces[len(surface.faces):],
            extended.face_slope_indices[len(surface.faces):],
        ):
            plane = surface.planes[slope_id]
            for vertex_index in face:
                x, y, z = extended.vertices[vertex_index]
                self.assertAlmostEqual(plane.height(x, y), z, places=7)

    def test_mixed_z_contour_with_equal_pitch_supports_overhang(self):
        surface = build_roof_surface(MIXED_Z_RECTANGLE, [35.0] * 4)
        self._assert_extended_shell(surface, 0.2)

    def test_small_resolvable_convex_overhang_is_not_discarded_by_area_tolerance(self):
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, [35.0] * 4)
        self._assert_extended_shell(surface, 0.001)

    def test_reflex_contour_rejects_overhang_without_creating_folded_top_faces(self):
        points = [
            (0.0, 0.0, 0.0),
            (8.0, 0.0, 0.0),
            (8.0, 4.0, 0.0),
            (4.0, 4.0, 0.0),
            (4.0, 8.0, 0.0),
            (0.0, 8.0, 0.0),
        ]
        surface = build_wavefront_roof_surface(points, [30.0] * len(points))
        with self.assertRaises(GeometryInputError) as context:
            extend_convex_roof_surface(surface, 0.25)
        self.assertEqual(context.exception.code, "OVERHANG_REFLEX_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
