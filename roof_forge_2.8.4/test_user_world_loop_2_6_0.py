"""Regression tests for the six-vertex L-loop taken from the user's Blender diagnostic.

The loop is almost perfectly orthogonal but contains a 0.000014 degree angular
noise on one long edge. Both RoofForge modes must normalize that noise and build
closed roof and seam-profile meshes without changing genuine oblique contours.
"""
import math
import unittest
from collections import Counter

import straight_skeleton_2_6_0 as geometry

RAW_WORLD_LOOP = [
    (72.390197754, -4.118945122),
    (72.390197754,  7.879999638),
    (64.389793396,  7.879999638),
    (64.389793396,  3.879999876),
    (54.389999390,  3.879999876),
    (54.389999390, -4.118949413),
]


def edge_use_counts(faces):
    counts = Counter()
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            counts[tuple(sorted((a, b)))] += 1
    return counts


class UserWorldLoopRegression(unittest.TestCase):
    def test_contour_is_snapped_only_by_microscopic_amount(self):
        snapped, changed = geometry._orthogonalize_nearly_orthogonal_contour(
            RAW_WORLD_LOOP
        )
        self.assertTrue(changed)
        self.assertLess(max(math.dist(a, b) for a, b in zip(RAW_WORLD_LOOP, snapped)), 2e-6)
        self.assertAlmostEqual(geometry._poly_area_2d(RAW_WORLD_LOOP),
                               geometry._poly_area_2d(snapped), places=6)

    def test_both_roof_modes_and_profile_meshes(self):
        snapped, changed = geometry._orthogonalize_nearly_orthogonal_contour(
            RAW_WORLD_LOOP
        )
        self.assertTrue(changed)
        for allow_oblique in (False, True):
            with self.subTest(allow_oblique=allow_oblique):
                vertices, faces, sources = geometry.build_roof_mesh(
                    RAW_WORLD_LOOP,
                    math.tan(math.radians(30.0)),
                    allow_oblique=allow_oblique,
                )
                self.assertEqual(len(faces), 6)
                geometry._validate_face_planarity(vertices, faces, 1e-6)
                geometry._validate_roof_mesh_topology(vertices, faces, snapped, 1e-6)
                seams = geometry.extract_roof_seams(vertices, faces, sources, snapped)
                for kind in ("RIDGE", "VALLEY"):
                    profile_vertices, profile_faces = geometry.build_inset_seam_profile_mesh(
                        vertices, faces, seams, kind, 0.18, (0.0, 0.0, 0.01),
                        outline=snapped,
                    )
                    if profile_faces:
                        counts = edge_use_counts(profile_faces)
                        self.assertTrue(counts)
                        self.assertTrue(all(count == 2 for count in counts.values()),
                                        f"{kind} profile is not manifold: {Counter(counts.values())}")

    def test_all_cyclic_starts_and_windings(self):
        for reverse in (False, True):
            base = list(reversed(RAW_WORLD_LOOP)) if reverse else list(RAW_WORLD_LOOP)
            for shift in range(len(base)):
                points = base[shift:] + base[:shift]
                if geometry._poly_area_2d(points) < 0.0:
                    points.reverse()
                for allow_oblique in (False, True):
                    with self.subTest(reverse=reverse, shift=shift,
                                      allow_oblique=allow_oblique):
                        vertices, faces, _sources = geometry.build_roof_mesh(
                            points, math.tan(math.radians(30.0)),
                            allow_oblique=allow_oblique,
                        )
                        self.assertEqual(len(faces), 6)
                        geometry._validate_face_planarity(vertices, faces, 1e-6)

    def test_genuinely_oblique_loop_is_not_orthogonalized(self):
        oblique = [
            (0.0, 0.0), (18.0, 0.0), (18.0, 8.0),
            (8.5, 7.0), (8.0, 12.0), (0.0, 12.0),
        ]
        snapped, changed = geometry._orthogonalize_nearly_orthogonal_contour(oblique)
        self.assertFalse(changed)
        self.assertEqual(snapped, oblique)


if __name__ == "__main__":
    unittest.main(verbosity=2)
