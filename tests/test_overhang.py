import unittest

from core.geometry import GeometryInputError
from core.overhang import extend_convex_roof_surface
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh
from core.wavefront import build_wavefront_roof_surface


RECTANGLE = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 3.0, 0.0),
    (0.0, 3.0, 0.0),
]


class RoofOverhangTests(unittest.TestCase):
    def test_convex_mitered_overhang_uses_one_shared_corner_vertex(self):
        surface = build_wavefront_roof_surface(RECTANGLE, [35.0] * 4)
        extended = extend_convex_roof_surface(surface, 0.25)

        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        self.assertEqual(
            len(extended.faces) - len(surface.faces),
            len(surface.boundary_xy),
            "there must be exactly one strip per original boundary segment",
        )
        self.assertEqual(
            len(extended.boundary_xy),
            len(extended.faces) - len(surface.faces),
        )
        self.assertTrue(
            all(index >= 0 for index in extended.face_slope_indices[len(surface.faces):]),
            "mitered overhang must not create separate corner fan faces",
        )

        expected_corners = {
            (-0.25, -0.25),
            (4.25, -0.25),
            (4.25, 3.25),
            (-0.25, 3.25),
        }
        actual = {(round(point[0], 6), round(point[1], 6)) for point in extended.boundary_xy}
        self.assertEqual(actual, expected_corners)

        # Each corner is one welded 3D vertex, not two offset vertices joined
        # by a triangular patch that emits two spokes from the source corner.
        for x, y in expected_corners:
            matching = [
                point for point in extended.vertices
                if abs(point[0] - x) < 1e-7 and abs(point[1] - y) < 1e-7
            ]
            self.assertEqual(len(matching), 1)

        shell = build_roof_shell(extended, 0.12)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_mitered_overhang_strips_stay_on_authored_support_planes(self):
        pitches = [35.0] * 4
        surface = build_wavefront_roof_surface(RECTANGLE, pitches)
        extended = extend_convex_roof_surface(surface, 0.2)

        for face, slope_id in zip(
            extended.faces[len(surface.faces):],
            extended.face_slope_indices[len(surface.faces):],
        ):
            plane = surface.planes[slope_id]
            for vertex_index in face:
                x, y, z = extended.vertices[vertex_index]
                self.assertAlmostEqual(plane.height(x, y), z, places=7)

    def test_pitch_discontinuity_at_miter_is_rejected_instead_of_creating_spokes(self):
        pitches = [30.0, 35.0, 40.0, 32.0]
        surface = build_wavefront_roof_surface(RECTANGLE, pitches)
        with self.assertRaises(GeometryInputError) as context:
            extend_convex_roof_surface(surface, 0.2)
        self.assertEqual(context.exception.code, "OVERHANG_PITCH_DISCONTINUITY")
        self.assertIn("совместимые", context.exception.message)

    def test_small_resolvable_convex_overhang_is_not_discarded_by_area_tolerance(self):
        surface = build_wavefront_roof_surface(RECTANGLE, [35.0] * 4)
        extended = extend_convex_roof_surface(surface, 0.001)
        shell = build_roof_shell(extended, 0.12)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_reflex_contour_rejects_overhang_without_creating_folded_top_faces(self):
        points = [
            (0.0, 0.0, 0.0),
            (8.0, 0.0, 0.0),
            (8.0, 4.0, 0.0),
            (4.0, 4.0, 0.0),
            (4.0, 8.0, 0.0),
            (0.0, 8.0, 0.0),
        ]
        surface = build_wavefront_roof_surface(points, [35.0] * len(points))
        with self.assertRaises(GeometryInputError) as context:
            extend_convex_roof_surface(surface, 0.25)
        self.assertEqual(context.exception.code, "OVERHANG_REFLEX_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
