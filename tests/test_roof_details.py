"""Regression tests for roof ridge, valley and standing-seam details."""
from __future__ import annotations

import math
import unittest
from collections import defaultdict

from core.roof_details import (
    RoofDetailsError,
    build_inset_seam_profile_mesh,
    extract_roof_seams,
    roof_face_plane,
)
from core.standing_seams import build_standing_seam_mesh


def two_facet_surface(centre_z):
    vertices = [
        (0.0, 0.0, 0.0), (2.0, 0.0, centre_z), (4.0, 0.0, 0.0),
        (0.0, 4.0, 0.0), (2.0, 4.0, centre_z), (4.0, 4.0, 0.0),
    ]
    faces = [(0, 1, 4, 3), (1, 2, 5, 4)]
    edge_uses = defaultdict(list)
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((a, b))
    boundary_edges = [
        (vertices[uses[0][0]], vertices[uses[0][1]])
        for uses in edge_uses.values() if len(uses) == 1
    ]
    seams = extract_roof_seams(vertices, faces, [0, 1], [])
    return vertices, faces, seams, boundary_edges


class RoofDetailsTests(unittest.TestCase):
    def test_convex_shared_joint_is_classified_as_ridge(self):
        vertices, faces, seams, _boundary = two_facet_surface(1.0)
        self.assertEqual(len(seams), 1)
        self.assertEqual(seams[0][4], "RIDGE")
        plane = roof_face_plane(vertices, faces[0])
        self.assertAlmostEqual(plane[0] * 2.0 + plane[1] * 2.0 + plane[2], 1.0)

    def test_concave_shared_joint_is_classified_as_valley(self):
        _vertices, _faces, seams, _boundary = two_facet_surface(-1.0)
        self.assertEqual(len(seams), 1)
        self.assertEqual(seams[0][4], "VALLEY")

    def test_coplanar_shared_edge_is_not_a_profile_joint(self):
        vertices, _faces, _seams, boundary = two_facet_surface(0.0)
        faces = [(0, 1, 4, 3), (1, 2, 5, 4)]
        graph = extract_roof_seams(vertices, faces, [0, 0], [])
        self.assertEqual(graph, [])

    def test_inset_ridge_profile_is_a_closed_mesh(self):
        vertices, faces, seams, boundary = two_facet_surface(1.0)
        profile_vertices, profile_faces = build_inset_seam_profile_mesh(
            vertices, faces, seams, "RIDGE", 0.12, (0.0, 0.0, 0.02),
            seat_sink_offset=(0.0, 0.0, -0.0002),
            boundary_edges=boundary,
        )
        self.assertGreater(len(profile_vertices), 0)
        self.assertGreater(len(profile_faces), 0)
        edge_uses = defaultdict(int)
        for face in profile_faces:
            for a, b in zip(face, face[1:] + face[:1]):
                edge_uses[tuple(sorted((a, b)))] += 1
        self.assertTrue(all(count == 2 for count in edge_uses.values()))

    def test_standing_seams_follow_both_slope_facets(self):
        vertices, faces, seams, boundary = two_facet_surface(1.0)
        seam_vertices, seam_faces, stats = build_standing_seam_mesh(
            vertices, faces, seams,
            panel_width=0.60,
            seam_height=0.015,
            seam_base_width=0.014,
            roof_thickness=0.01,
            ridge_height=0.02,
            minimum_segment_length=0.05,
            end_offset=0.0,
            boundary_edges=boundary,
        )
        self.assertGreater(stats.get("segments", 0), 0)
        self.assertGreater(len(seam_vertices), 0)
        self.assertGreater(len(seam_faces), 0)
        self.assertTrue(stats.get("seam_edge_pairs"))

    def test_profile_builder_rejects_unknown_kind(self):
        vertices, faces, seams, boundary = two_facet_surface(1.0)
        with self.assertRaises(RoofDetailsError):
            build_inset_seam_profile_mesh(
                vertices, faces, seams, "HIP", 0.1, (0.0, 0.0, 0.01),
                boundary_edges=boundary,
            )


if __name__ == "__main__":
    unittest.main()
