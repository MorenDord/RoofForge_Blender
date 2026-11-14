"""Regression tests for positive overhang on supported concave footprints."""
from __future__ import annotations

import unittest

from core.geometry import GeometryInputError, signed_area
from core.overhang import build_source_anchored_overhang_surface, corner_converged_overhang_contour
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh


L_POINTS = (
    (0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (8.0, 4.0, 0.0),
    (4.0, 4.0, 0.0), (4.0, 8.0, 0.0), (0.0, 8.0, 0.0),
)
L_PITCHES = (31.0, 32.5, 34.0, 35.5, 37.0, 38.5)
U_POINTS = (
    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0),
    (3.0, 4.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
    (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
)
U_PITCHES = (30.0,) * 8


def reverse_with_edge_pitch_mapping(points, pitches):
    """Reverse a ring while retaining pitch identity for each geometric edge."""
    count = len(points)
    return tuple(reversed(points)), tuple(pitches[(count - 2 - i) % count] for i in range(count))


class ConcaveOverhangTests(unittest.TestCase):
    def assert_surface_is_planar_and_closed(self, surface):
        self.assertEqual(len(surface.faces), len(surface.face_slope_indices))
        for face, slope_index in zip(surface.faces, surface.face_slope_indices):
            plane = surface.planes[slope_index]
            for vertex_index in face:
                x, y, z = surface.vertices[vertex_index]
                self.assertAlmostEqual(z, plane.height(x, y), places=7)
        shell = build_roof_shell(surface, 0.1, extrude_up=True)
        self.assertTrue(shell.extrude_up)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_l_contour_supports_asymmetric_positive_overhang(self):
        surface = build_source_anchored_overhang_surface(L_POINTS, L_PITCHES, 0.15)
        self.assertGreater(surface.surface_area_xy, abs(signed_area([(p[0], p[1]) for p in L_POINTS])))
        self.assertGreater(len(surface.faces), len(L_POINTS))
        self.assert_surface_is_planar_and_closed(surface)

    def test_u_contour_supports_positive_overhang(self):
        surface = build_source_anchored_overhang_surface(U_POINTS, U_PITCHES, 0.15)
        self.assertGreater(surface.surface_area_xy, abs(signed_area([(p[0], p[1]) for p in U_POINTS])))
        self.assertGreater(len(surface.faces), len(U_POINTS))
        self.assert_surface_is_planar_and_closed(surface)

    def test_l_and_u_are_winding_independent(self):
        for points, pitches in ((L_POINTS, L_PITCHES), (U_POINTS, U_PITCHES)):
            reversed_points, reversed_pitches = reverse_with_edge_pitch_mapping(points, pitches)
            forward = build_source_anchored_overhang_surface(points, pitches, 0.15)
            reverse = build_source_anchored_overhang_surface(reversed_points, reversed_pitches, 0.15)
            self.assertAlmostEqual(forward.surface_area_xy, reverse.surface_area_xy, places=7)
            self.assert_surface_is_planar_and_closed(reverse)

    def test_too_wide_u_overhang_is_rejected(self):
        with self.assertRaises(GeometryInputError) as context:
            build_source_anchored_overhang_surface(U_POINTS, U_PITCHES, 1.5)
        self.assertEqual(context.exception.code, "OVERHANG_OFFSET_INVALID")

    def test_concave_overhang_requires_corner_convergence(self):
        with self.assertRaises(GeometryInputError) as context:
            build_source_anchored_overhang_surface(L_POINTS, L_PITCHES, 0.15, corner_convergence=False)
        self.assertEqual(context.exception.code, "OVERHANG_CONCAVE_NEEDS_CORNER_CONVERGENCE")

    def test_concave_overhang_rejects_mixed_height_eaves(self):
        mixed = list(L_POINTS)
        mixed[1] = (mixed[1][0], mixed[1][1], 0.2)
        with self.assertRaises(GeometryInputError) as context:
            build_source_anchored_overhang_surface(mixed, L_PITCHES, 0.15)
        self.assertEqual(context.exception.code, "OVERHANG_CONCAVE_NON_FLAT_EAVES")

    def test_corner_converged_contour_preserves_source_vertex_count(self):
        expanded = corner_converged_overhang_contour(L_POINTS, L_PITCHES, 0.15)
        self.assertEqual(len(expanded), len(L_POINTS))
        self.assertGreater(
            abs(signed_area([(p[0], p[1]) for p in expanded])),
            abs(signed_area([(p[0], p[1]) for p in L_POINTS])),
        )


if __name__ == "__main__":
    unittest.main()
