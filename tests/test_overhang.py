import unittest

from core.geometry import GeometryInputError
from core.overhang import extend_convex_roof_surface
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh
from core.wavefront import build_wavefront_roof_surface


class RoofOverhangTests(unittest.TestCase):
    def test_convex_variable_pitch_overhang_extends_boundary_and_closes_shell(self):
        points = [
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0),
            (0.0, 3.0, 0.0),
        ]
        pitches = [30.0, 35.0, 40.0, 32.0]
        surface = build_wavefront_roof_surface(points, pitches)
        extended = extend_convex_roof_surface(surface, 0.25)

        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        self.assertLess(min(point[0] for point in extended.boundary_xy), 0.0)
        self.assertLess(min(point[1] for point in extended.boundary_xy), 0.0)
        self.assertGreater(max(point[0] for point in extended.boundary_xy), 4.0)
        self.assertGreater(max(point[1] for point in extended.boundary_xy), 3.0)
        self.assertEqual(len(extended.faces), len(extended.face_slope_indices))

        corner_faces = [
            face for face, slope_id in zip(
                extended.faces[len(surface.faces):],
                extended.face_slope_indices[len(surface.faces):],
            )
            if slope_id == -1
        ]
        self.assertEqual(len(corner_faces), 4)

        shell = build_roof_shell(extended, 0.12)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_overhang_strip_vertices_stay_on_authored_support_planes(self):
        points = [
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0),
            (0.0, 3.0, 0.0),
        ]
        pitches = [30.0, 35.0, 40.0, 32.0]
        surface = build_wavefront_roof_surface(points, pitches)
        extended = extend_convex_roof_surface(surface, 0.2)

        for face, slope_id in zip(
            extended.faces[len(surface.faces):],
            extended.face_slope_indices[len(surface.faces):],
        ):
            if slope_id < 0:
                continue
            plane = surface.planes[slope_id]
            for vertex_index in face:
                x, y, z = extended.vertices[vertex_index]
                self.assertAlmostEqual(plane.height(x, y), z, places=7)

    def test_small_resolvable_convex_overhang_is_not_discarded_by_area_tolerance(self):
        points = [
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0),
            (0.0, 3.0, 0.0),
        ]
        surface = build_wavefront_roof_surface(points, [35.0] * 4)
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
