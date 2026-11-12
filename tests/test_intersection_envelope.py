import unittest

from core.geometry import GeometryInputError, signed_area
from core.intersection_envelope import build_intersection_envelope_surface
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh


class PlaneIntersectionEnvelopeTests(unittest.TestCase):
    def assert_exact_support_surface(self, points, surface):
        self.assertEqual(surface.approximation_error, 0.0)
        self.assertEqual(surface.refinement_depth, 0)
        self.assertTrue(surface.faces)
        self.assertEqual(
            set(surface.face_slope_indices),
            set(range(len(points))),
            "every authored edge plane must own a non-zero exact roof region",
        )

        edge_uses = {}
        for face, source_index in zip(surface.faces, surface.face_slope_indices):
            self.assertGreaterEqual(source_index, 0)
            plane = surface.planes[source_index]
            projected = []
            for vertex_index in face:
                x, y, z = surface.vertices[vertex_index]
                self.assertAlmostEqual(z, plane.height(x, y), places=7)
                projected.append((x, y))
            self.assertGreater(abs(signed_area(projected)), 1e-10)
            for local_index, first in enumerate(face):
                second = face[(local_index + 1) % len(face)]
                key = (min(first, second), max(first, second))
                edge_uses.setdefault(key, []).append((first, second, source_index))

        for edge, uses in edge_uses.items():
            self.assertLessEqual(len(uses), 2, f"non-manifold roof edge {edge}")
            if len(uses) == 2 and uses[0][2] != uses[1][2]:
                for vertex_index in edge:
                    x, y, z = surface.vertices[vertex_index]
                    for _first, _second, source_index in uses:
                        plane = surface.planes[source_index]
                        self.assertAlmostEqual(
                            z, plane.height(x, y), places=7,
                            msg=f"seam vertex is off support plane {source_index}",
                        )

        expected_area = abs(signed_area([(p[0], p[1]) for p in points]))
        self.assertAlmostEqual(surface.surface_area_xy, expected_area, places=7)
        self.assertAlmostEqual(surface.source_area_xy, expected_area, places=7)

    def test_four_different_pitches_close_without_a_common_apex(self):
        # Four exact support planes have four different inclinations. The
        # roof is their clipped lower envelope; a shared four-way apex is
        # neither required nor imposed.
        points = [
            (0.0, 0.0, 0.0),
            (10.0, 0.0, 0.0),
            (10.0, 10.0, 0.0),
            (0.0, 10.0, 0.0),
        ]
        pitches = [30.0, 40.0, 25.0, 50.0]

        surface = build_intersection_envelope_surface(points, pitches)
        self.assert_exact_support_surface(points, surface)

        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_four_support_planes_preserve_a_nonplanar_eave_loop(self):
        # Each edge has a different 3D grade and a different requested pitch.
        points = [
            (0.0, 0.0, 0.0),
            (10.0, 0.0, 0.4),
            (10.0, 8.0, 0.2),
            (0.0, 8.0, 0.0),
        ]
        pitches = [30.0, 40.0, 25.0, 50.0]

        surface = build_intersection_envelope_surface(points, pitches)
        self.assert_exact_support_surface(points, surface)

        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_impossible_edge_pitch_is_rejected_without_fitting(self):
        points = [
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 2.0),
            (4.0, 3.0, 2.0),
            (0.0, 3.0, 0.0),
        ]
        with self.assertRaises(GeometryInputError) as context:
            build_intersection_envelope_surface(points, [20.0, 35.0, 20.0, 35.0])
        self.assertEqual(context.exception.code, "PITCH_BELOW_EAVE_GRADE")


if __name__ == "__main__":
    unittest.main()
