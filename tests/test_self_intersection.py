"""Regression tests for geometric self-intersection validation."""
from __future__ import annotations

import math
import unittest

from core.validation import _triangles_intersect, validate_closed_mesh
from core.wavefront import build_wavefront_roof_surface
from core.shell import build_roof_shell
from core.overhang import build_source_anchored_overhang_surface


TETRA_FACES = (
    (0, 2, 1),
    (0, 1, 3),
    (0, 3, 2),
    (1, 2, 3),
)


class SelfIntersectionTests(unittest.TestCase):
    def test_connected_bipyramid_with_crossing_faces_is_rejected(self):
        base = tuple(
            (math.cos(index * math.pi / 2.0), math.sin(index * math.pi / 2.0), 0.0)
            for index in range(4)
        )
        vertices = base + ((0.0, 0.0, 1.0), (0.3, 0.0, 0.8))
        faces = tuple(
            [(4, index, (index + 1) % 4) for index in range(4)]
            + [(5, (index + 1) % 4, index) for index in range(4)]
        )
        diagnostics = validate_closed_mesh(vertices, faces)
        self.assertEqual({item.code for item in diagnostics}, {"SELF_INTERSECTION"})
        self.assertTrue(any("Грани" in item.message for item in diagnostics))

    def test_overlapping_closed_components_report_self_intersection(self):
        first = (
            (0.0, 0.0, 0.0), (2.0, 0.0, 0.0),
            (0.0, 2.0, 0.0), (0.0, 0.0, 2.0),
        )
        second = tuple((x + 0.5, y + 0.5, z + 0.5) for x, y, z in first)
        vertices = first + second
        faces = TETRA_FACES + tuple(
            tuple(index + 4 for index in face) for face in TETRA_FACES
        )
        codes = {item.code for item in validate_closed_mesh(vertices, faces)}
        self.assertIn("DISCONNECTED_COMPONENTS", codes)
        self.assertIn("SELF_INTERSECTION", codes)

    def test_separate_closed_components_do_not_report_self_intersection(self):
        first = (
            (0.0, 0.0, 0.0), (2.0, 0.0, 0.0),
            (0.0, 2.0, 0.0), (0.0, 0.0, 2.0),
        )
        second = tuple((x + 10.0, y, z) for x, y, z in first)
        vertices = first + second
        faces = TETRA_FACES + tuple(
            tuple(index + 4 for index in face) for face in TETRA_FACES
        )
        codes = {item.code for item in validate_closed_mesh(vertices, faces)}
        self.assertNotIn("SELF_INTERSECTION", codes)

    def test_coplanar_overlapping_triangles_intersect(self):
        first = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0))
        second = ((0.5, 0.5, 0.0), (2.5, 0.5, 0.0), (0.5, 2.5, 0.0))
        self.assertTrue(_triangles_intersect(first, second, 1e-9))

    def test_coplanar_disjoint_triangles_do_not_intersect(self):
        first = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0))
        second = ((3.0, 3.0, 0.0), (5.0, 3.0, 0.0), (3.0, 5.0, 0.0))
        self.assertFalse(_triangles_intersect(first, second, 1e-9))

    def test_non_coplanar_triangles_cross(self):
        first = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0))
        second = ((1.0, -1.0, -1.0), (1.0, 2.0, -1.0), (1.0, 0.0, 1.0))
        self.assertTrue(_triangles_intersect(first, second, 1e-9))

    def test_non_coplanar_separated_triangles_do_not_intersect(self):
        first = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0))
        second = ((1.0, -1.0, 2.0), (1.0, 2.0, 2.0), (1.0, 0.0, 3.0))
        self.assertFalse(_triangles_intersect(first, second, 1e-9))

    def test_generated_rectangle_shell_has_no_false_positive(self):
        points = (
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),
        )
        surface = build_wavefront_roof_surface(points, (35.0,) * 4)
        shell = build_roof_shell(surface, 0.1)
        codes = {item.code for item in validate_closed_mesh(shell.vertices, shell.faces)}
        self.assertNotIn("SELF_INTERSECTION", codes)

    def test_concave_l_and_u_overhang_shells_have_no_false_positive(self):
        fixtures = (
            (
                (
                    (0.0, 0.0, 0.0), (8.0, 0.0, 0.0), (8.0, 4.0, 0.0),
                    (4.0, 4.0, 0.0), (4.0, 8.0, 0.0), (0.0, 8.0, 0.0),
                ),
                (31.0, 32.5, 34.0, 35.5, 37.0, 38.5),
            ),
            (
                (
                    (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0),
                    (3.0, 4.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
                    (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
                ),
                (30.0,) * 8,
            ),
        )
        for points, pitches in fixtures:
            surface = build_source_anchored_overhang_surface(points, pitches, 0.15)
            shell = build_roof_shell(surface, 0.01, extrude_up=True)
            codes = {item.code for item in validate_closed_mesh(shell.vertices, shell.faces)}
            self.assertNotIn("SELF_INTERSECTION", codes)


if __name__ == "__main__":
    unittest.main()
