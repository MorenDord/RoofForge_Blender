import math
import random
import unittest

from standing_seams_2_6_0 import build_standing_seam_mesh
from straight_skeleton_2_6_0 import build_roof_mesh, extract_roof_seams


class StandingSeamTests(unittest.TestCase):
    def make_gable(self):
        # Two roof facets meeting at a ridge. Each panel should run from ridge
        # toward its own eave; Y is the across-panel direction.
        verts = [
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 1.154700538),
            (2.0, 5.0, 1.154700538),
            (0.0, 5.0, 0.0),
            (4.0, 0.0, 0.0),
            (4.0, 5.0, 0.0),
        ]
        faces = [(0, 1, 2, 3), (1, 4, 5, 2)]
        ridge = [(verts[1], verts[2], 0, 1, "RIDGE")]
        return verts, faces, ridge

    def test_gable_generates_seams_on_both_facets(self):
        verts, faces, ridge = self.make_gable()
        out_v, out_f, stats = build_standing_seam_mesh(
            verts, faces, ridge, panel_width=0.5, seam_height=0.02,
            seam_base_width=0.014, roof_thickness=0.01, ridge_height=0.05,
        )
        self.assertGreater(stats["segments"], 0)
        self.assertEqual(stats["segments"], 2 * (round(5.0 / 0.5) - 1))
        self.assertEqual(len(out_v), stats["segments"] * 8)
        # Three visible longitudinal faces per rib plus only the eave-facing cap.
        self.assertEqual(len(out_f), stats["segments"] * 4)
        self.assertEqual(stats["ridge_ends_buried"], stats["segments"])
        self.assertEqual(stats["visible_end_caps"], stats["segments"])

    def test_two_shoulder_edges_at_each_end_are_reported_for_uv_seams(self):
        verts, faces, ridge = self.make_gable()
        out_v, out_f, stats = build_standing_seam_mesh(
            verts, faces, ridge, panel_width=1.0, seam_height=0.02,
            seam_base_width=0.014, roof_thickness=0.01, ridge_height=0.05,
        )
        self.assertEqual(len(stats["seam_edge_pairs"]), stats["segments"] * 2)
        edge_uses = {}
        for face in out_f:
            for a, b in zip(face, face[1:] + face[:1]):
                key = tuple(sorted((a, b)))
                edge_uses[key] = edge_uses.get(key, 0) + 1
        for edge in stats["seam_edge_pairs"]:
            self.assertEqual(len(edge), 2)
            self.assertNotEqual(edge[0], edge[1])
            self.assertTrue(all(0 <= index < len(out_v) for index in edge))
            self.assertEqual(edge_uses.get(tuple(sorted(edge))), 2)

    def test_signed_end_offset_uses_real_roof_boundary_only(self):
        verts, faces, ridge = self.make_gable()
        uses = {}
        for face in faces:
            for a, b in zip(face, face[1:] + face[:1]):
                uses[tuple(sorted((a, b)))] = uses.get(tuple(sorted((a, b))), 0) + 1
        boundary_edges = [
            (verts[a], verts[b])
            for face in faces
            for a, b in zip(face, face[1:] + face[:1])
            if uses[tuple(sorted((a, b)))] == 1
        ]
        results = []
        for offset in (0.0, 0.1, -0.1):
            out_v, out_f, stats = build_standing_seam_mesh(
                verts, faces, ridge, panel_width=1.0, seam_height=0.02,
                roof_thickness=0.01, ridge_height=0.05,
                end_offset=offset, boundary_edges=boundary_edges,
            )
            self.assertTrue(out_f)
            results.append((min(v[0] for v in out_v), max(v[0] for v in out_v)))
        self.assertLess(results[1][0], results[0][0])
        self.assertGreater(results[1][1], results[0][1])
        self.assertGreater(results[2][0], results[0][0])
        self.assertLess(results[2][1], results[0][1])

    def test_underside_is_removed_and_foot_is_sunk(self):
        verts, faces, ridge = self.make_gable()
        out_v, out_f, stats = build_standing_seam_mesh(
            verts, faces, ridge, panel_width=1.0, seam_height=0.02,
            roof_thickness=0.02, ridge_height=0.05,
        )
        self.assertGreater(len(out_f), 0)
        self.assertAlmostEqual(stats["sink_depth"], 0.01)
        for index in range(0, len(out_v), 8):
            base_z = (out_v[index][2] + out_v[index + 3][2]) * 0.5
            top_z = (out_v[index + 1][2] + out_v[index + 2][2]) * 0.5
            self.assertLess(base_z, top_z)
            base_ids = {index, index + 3, index + 4, index + 7}
            self.assertFalse(any(set(face) == base_ids for face in out_f))

    def test_height_clamped_to_ninety_percent_of_ridge_height(self):
        verts, faces, ridge = self.make_gable()
        out_v, out_f, stats = build_standing_seam_mesh(
            verts, faces, ridge, panel_width=0.5, seam_height=0.5,
            roof_thickness=0.01, ridge_height=0.02,
        )
        self.assertTrue(out_f)
        self.assertAlmostEqual(stats["height_limit_world_z"], 0.018)
        normal_z = 1.0 / math.sqrt(1.0 + (1.154700538 / 2.0) ** 2)
        self.assertLessEqual(stats["effective_height_max"] * normal_z, 0.018 + 1.0e-6)

    def test_flat_surface_is_skipped(self):
        verts = [(0, 0, 0), (4, 0, 0), (4, 5, 0), (0, 5, 0)]
        out_v, out_f, stats = build_standing_seam_mesh(
            verts, [(0, 1, 2, 3)], [], panel_width=0.5,
            seam_height=0.02, ridge_height=0.05,
        )
        self.assertEqual(out_v, [])
        self.assertEqual(out_f, [])
        self.assertEqual(stats["skipped_flat_faces"], 1)

    def test_invalid_panel_width_is_safely_clamped(self):
        verts, faces, ridge = self.make_gable()
        out_v, out_f, stats = build_standing_seam_mesh(
            verts, faces, ridge, panel_width=0.0, seam_height=0.02,
            ridge_height=0.05,
        )
        self.assertIsInstance(out_v, list)
        self.assertIsInstance(out_f, list)
        self.assertLessEqual(stats["panel_width_actual_max"], 0.2)

    def test_seam_layout_on_100_affine_concave_l_roofs(self):
        base = [
            (0.0, 0.0), (8.0, 0.0), (8.0, 2.0),
            (3.0, 2.0), (3.0, 8.0), (0.0, 8.0),
        ]
        rng = random.Random(2600)
        for case_index in range(100):
            sx, sy = rng.uniform(0.7, 1.5), rng.uniform(0.7, 1.5)
            shx, shy = rng.uniform(-0.8, 0.8), rng.uniform(-0.8, 0.8)
            if sx * sy - shx * shy <= 0.25:
                continue
            polygon = [
                (sx * x + shx * y + 1.25, shy * x + sy * y - 0.75)
                for x, y in base
            ]
            roof_v, roof_f, source = build_roof_mesh(
                polygon, math.tan(math.radians(30.0)), 0.0, allow_oblique=True
            )
            ridge_graph = extract_roof_seams(roof_v, roof_f, source, polygon)
            seam_v, seam_f, stats = build_standing_seam_mesh(
                roof_v, roof_f, ridge_graph, panel_width=0.6,
                seam_height=0.03, seam_base_width=0.014,
                roof_thickness=0.01, ridge_height=0.01,
            )
            self.assertGreater(stats["segments"], 0, case_index)
            self.assertEqual(len(seam_v), stats["segments"] * 8, case_index)
            self.assertGreaterEqual(len(seam_f), stats["segments"] * 3, case_index)
            self.assertGreaterEqual(stats["ridge_ends_buried"], 1, case_index)

    def test_roofforge_control_roofs_get_seams(self):
        cases = {
            "square": [(0, 0), (6, 0), (6, 6), (0, 6)],
            "rectangle": [(0, 0), (10, 0), (10, 5), (0, 5)],
            "L": [(0, 0), (8, 0), (8, 4), (4, 4), (4, 8), (0, 8)],
            "oblique_L": [(0, 0), (8, 0), (9, 4), (5, 5), (4, 8), (0, 7)],
        }
        for _name, polygon in cases.items():
            roof_v, roof_f, source = build_roof_mesh(
                polygon, math.tan(math.radians(30.0)), 0.0, allow_oblique=True
            )
            ridge_graph = extract_roof_seams(roof_v, roof_f, source, polygon)
            seam_v, seam_f, stats = build_standing_seam_mesh(
                roof_v, roof_f, ridge_graph, panel_width=0.6,
                seam_height=0.03, seam_base_width=0.014,
                roof_thickness=0.01, ridge_height=0.01,
            )
            self.assertGreater(stats["segments"], 0, _name)
            self.assertEqual(len(seam_v), stats["segments"] * 8, _name)
            self.assertEqual(len(seam_f), stats["segments"] * 4, _name)
            self.assertGreater(stats["ridge_ends_buried"], 0, _name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
