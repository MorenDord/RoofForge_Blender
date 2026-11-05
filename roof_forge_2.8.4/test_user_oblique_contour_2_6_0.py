"""Regression tests for the exact six-vertex oblique concave contour supplied by the user."""
import math
import unittest
from collections import Counter

import straight_skeleton_2_6_0 as geometry


USER_WORLD_LOOP = [
    (136.835800171, -10.854114532),
    (146.152648926, 12.384898186),
    (131.269317627, 16.137248993),
    (124.118904114, 3.752349854),
    (103.318794250, 3.752348900),
    (103.318794250, -10.854116440),
]


def edge_use_counts(faces):
    return Counter(
        tuple(sorted((a, b)))
        for face in faces
        for a, b in zip(face, face[1:] + face[:1])
    )


def assert_closed_oriented(testcase, faces):
    uses = {}
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            uses.setdefault(tuple(sorted((a, b))), []).append((a, b))
    testcase.assertTrue(uses)
    for edge, directed in uses.items():
        testcase.assertEqual(len(directed), 2, f"edge {edge} is not manifold")
        testcase.assertEqual(directed[0], directed[1][::-1],
                             f"edge {edge} has inconsistent winding")


class UserObliqueConcaveRegression(unittest.TestCase):
    def _build(self, allow_oblique):
        vertices, faces, sources = geometry.build_roof_mesh(
            USER_WORLD_LOOP, math.tan(math.radians(30.0)),
            allow_oblique=allow_oblique,
        )
        self.assertEqual(len(faces), 6)
        geometry._validate_face_planarity(vertices, faces, 1.0e-6)
        geometry._validate_roof_mesh_topology(
            vertices, faces, USER_WORLD_LOOP, 1.0e-6
        )
        return vertices, faces, sources

    def test_exact_user_contour_builds_in_both_modes(self):
        for allow_oblique in (False, True):
            with self.subTest(allow_oblique=allow_oblique):
                vertices, faces, sources = self._build(allow_oblique)
                self.assertEqual(len(vertices), 10)
                seams = geometry.extract_roof_seams(
                    vertices, faces, sources, USER_WORLD_LOOP
                )
                self.assertEqual(sum(item[4] == "RIDGE" for item in seams), 8)
                self.assertEqual(sum(item[4] == "VALLEY" for item in seams), 1)

    def test_ridge_and_valley_profiles_are_manifold_at_multiple_widths(self):
        vertices, faces, sources = self._build(False)
        seams = geometry.extract_roof_seams(
            vertices, faces, sources, USER_WORLD_LOOP
        )
        for kind in ("RIDGE", "VALLEY"):
            for width in (0.01, 0.18, 0.50):
                with self.subTest(kind=kind, width=width):
                    profile_vertices, profile_faces = geometry.build_inset_seam_profile_mesh(
                        vertices, faces, seams, kind, width, (0.0, 0.0, 0.01),
                        outline=USER_WORLD_LOOP,
                    )
                    self.assertTrue(profile_faces)
                    self.assertTrue(all(count == 2 for count in edge_use_counts(profile_faces).values()))
                    assert_closed_oriented(self, profile_faces)

    def test_all_cyclic_starts_and_both_windings(self):
        for reverse in (False, True):
            base = list(reversed(USER_WORLD_LOOP)) if reverse else list(USER_WORLD_LOOP)
            for shift in range(len(base)):
                polygon = base[shift:] + base[:shift]
                if geometry._poly_area_2d(polygon) < 0.0:
                    polygon.reverse()
                for allow_oblique in (False, True):
                    with self.subTest(reverse=reverse, shift=shift,
                                      allow_oblique=allow_oblique):
                        vertices, faces, _sources = geometry.build_roof_mesh(
                            polygon, math.tan(math.radians(30.0)),
                            allow_oblique=allow_oblique,
                        )
                        self.assertEqual(len(faces), 6)
                        geometry._validate_face_planarity(vertices, faces, 1.0e-6)
                        geometry._validate_roof_mesh_topology(
                            vertices, faces, polygon, 1.0e-6
                        )

    def test_contour_is_not_misclassified_as_orthogonal(self):
        normalized, changed = geometry._orthogonalize_nearly_orthogonal_contour(
            USER_WORLD_LOOP
        )
        self.assertFalse(changed)
        self.assertEqual(normalized, USER_WORLD_LOOP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
