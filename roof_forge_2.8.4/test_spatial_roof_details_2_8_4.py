"""Regression tests for spatial eave extensions and 3D ridge/valley profiles."""
import math
import unittest
from collections import Counter, defaultdict

from spatial_roof_2_8_4 import build_spatial_roof_mesh, extend_spatial_roof_eaves
from straight_skeleton_2_6_0 import extract_roof_seams, build_inset_seam_profile_mesh


def edge_uses(faces):
    counts = Counter()
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            counts[tuple(sorted((a, b)))] += 1
    return counts


def face_normal(vertices, face):
    pts = [vertices[i] for i in face]
    nx = ny = nz = 0.0
    for a, b in zip(pts, pts[1:] + pts[:1]):
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (nx / length, ny / length, nz / length)


class SpatialRoofDetailsTests(unittest.TestCase):
    def setUp(self):
        self.outline = [
            (0.0, 0.0, 0.0),
            (10.0, 0.0, 0.8),
            (10.0, 8.0, 1.1),
            (0.0, 8.0, 0.2),
        ]
        self.pitches = [math.radians(v) for v in (35.0, 40.0, 30.0, 45.0)]
        self.vertices, self.faces, self.sources = build_spatial_roof_mesh(
            self.outline, self.pitches
        )

    def test_3d_ridge_graph_and_profile_are_manifold(self):
        outline_xy = [(p[0], p[1]) for p in self.outline]
        seams = extract_roof_seams(self.vertices, self.faces, self.sources, outline_xy)
        self.assertTrue(seams)
        self.assertTrue(all(s[4] == "RIDGE" for s in seams))
        vertices, faces = build_inset_seam_profile_mesh(
            self.vertices, self.faces, seams, "RIDGE", 0.18, (0.0, 0.0, 0.01),
            end_offset=0.0, seat_sink_offset=(0.0, 0.0, -0.0002), outline=outline_xy,
        )
        self.assertTrue(vertices)
        uses = edge_uses(faces)
        self.assertTrue(uses)
        self.assertTrue(all(count == 2 for count in uses.values()))
        self.assertTrue(any(abs(v[2]) > 1.0e-3 for v in vertices))

    def test_spatial_overhang_is_a_connected_manifold_surface(self):
        distance = 0.45
        vertices, faces, sources = extend_spatial_roof_eaves(
            self.vertices, self.faces, self.sources, distance
        )
        self.assertEqual(len(faces), len(sources))
        self.assertGreater(len(vertices), len(self.vertices))
        uses = edge_uses(faces)
        self.assertTrue(all(count in (1, 2) for count in uses.values()))
        self.assertEqual(sum(count == 1 for count in uses.values()), 4)
        # Every original eave corner connects to exactly one shared miter
        # vertex; the old two-spoke corner triangle is no longer present.
        original_count = len(self.vertices)
        added_faces = faces[len(self.faces):]
        boundary_ids = {
            vertex_id
            for edge, count in edge_uses(self.faces).items() if count == 1
            for vertex_id in edge
        }
        for vertex_id in boundary_ids:
            new_neighbours = set()
            for face in added_faces:
                if vertex_id not in face:
                    continue
                position = face.index(vertex_id)
                for neighbour in (face[position - 1], face[(position + 1) % len(face)]):
                    if neighbour >= original_count:
                        new_neighbours.add(neighbour)
            self.assertEqual(len(new_neighbours), 1)
        # Each new edge strip is one upward-oriented mitered quad.
        for face in faces[len(self.faces):]:
            self.assertGreater(face_normal(vertices, face)[2], 0.0)


    def test_flat_individual_pitch_overhang_uses_single_miter_per_corner(self):
        outline = [(0.0, 0.0), (8.0, 0.0), (8.0, 5.0), (0.0, 5.0)]
        pitches = [math.radians(v) for v in (30.0, 36.0, 42.0, 34.0)]
        vertices, faces, sources = build_spatial_roof_mesh(
            [(x, y, 0.0) for x, y in outline], pitches
        )
        extended_vertices, extended_faces, extended_sources = extend_spatial_roof_eaves(
            vertices, faces, sources, 0.35
        )
        self.assertEqual(len(extended_faces), len(extended_sources))
        uses = edge_uses(extended_faces)
        self.assertTrue(all(count in (1, 2) for count in uses.values()))
        self.assertEqual(sum(count == 1 for count in uses.values()), 4)
        original_count = len(vertices)
        added_faces = extended_faces[len(faces):]
        boundary_ids = {
            vertex_id
            for edge, count in edge_uses(faces).items() if count == 1
            for vertex_id in edge
        }
        for vertex_id in boundary_ids:
            new_neighbours = set()
            for face in added_faces:
                if vertex_id not in face:
                    continue
                position = face.index(vertex_id)
                for neighbour in (face[position - 1], face[(position + 1) % len(face)]):
                    if neighbour >= original_count:
                        new_neighbours.add(neighbour)
            self.assertEqual(len(new_neighbours), 1)

    def test_overhang_preserves_original_facet_geometry(self):
        vertices, faces, sources = extend_spatial_roof_eaves(
            self.vertices, self.faces, self.sources, 0.25
        )
        self.assertEqual(faces[:len(self.faces)], self.faces)
        self.assertEqual(vertices[:len(self.vertices)], self.vertices)
        self.assertTrue(all(len(face) >= 3 for face in faces))

    def test_3d_valley_seam_is_detected_and_profile_is_closed(self):
        # Two individually planar sloping facets form a genuine 3D valley.
        vertices = [
            (-1.0, 0.0, 1.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.2), (-1.0, 1.0, 1.2),
            (1.0, 0.0, 1.0), (1.0, 1.0, 1.2),
        ]
        faces = [(0, 1, 2, 3), (1, 4, 5, 2)]
        seams = extract_roof_seams(vertices, faces, [-1, -1], [])
        valleys = [edge for edge in seams if edge[4] == "VALLEY"]
        self.assertEqual(len(valleys), 1)
        profile_vertices, profile_faces = build_inset_seam_profile_mesh(
            vertices, faces, seams, "VALLEY", 0.15, (0.0, 0.0, 0.03),
            end_offset=0.0, seat_sink_offset=(0.0, 0.0, -0.0002),
        )
        self.assertTrue(profile_vertices)
        uses = edge_uses(profile_faces)
        self.assertTrue(uses)
        self.assertTrue(all(count == 2 for count in uses.values()))
        self.assertTrue(any(abs(v[2]) > 0.0 for v in profile_vertices))


    def test_spatial_overhang_works_with_reversed_contour_winding(self):
        outline = list(reversed(self.outline))
        pitches = list(reversed(self.pitches))
        vertices, faces, sources = build_spatial_roof_mesh(outline, pitches)
        extended_vertices, extended_faces, extended_sources = extend_spatial_roof_eaves(
            vertices, faces, sources, 0.3
        )
        self.assertEqual(len(extended_faces), len(extended_sources))
        uses = edge_uses(extended_faces)
        self.assertTrue(all(count in (1, 2) for count in uses.values()))
        self.assertEqual(sum(count == 1 for count in uses.values()), 4)

    def test_spatial_ridge_profile_seats_on_thickness_offset_surface(self):
        top = [(x, y, z + 0.012) for x, y, z in self.vertices]
        outline_xy = [(p[0], p[1]) for p in self.outline]
        seams = extract_roof_seams(top, self.faces, self.sources, outline_xy)
        profile_vertices, profile_faces = build_inset_seam_profile_mesh(
            top, self.faces, seams, "RIDGE", 0.18, (0.0, 0.0, 0.01),
            end_offset=0.0, seat_sink_offset=(0.0, 0.0, -0.0002), outline=outline_xy,
        )
        self.assertTrue(profile_vertices)
        self.assertTrue(all(v[2] > -0.001 for v in profile_vertices))
        self.assertTrue(all(count == 2 for count in edge_uses(profile_faces).values()))

    def test_spatial_concave_l_is_reported_as_unsupported_not_silently_capped(self):
        outline = [(0, 0, 0), (10, 0, 0), (10, 4, 0), (4, 4, 0), (4, 10, 0), (0, 10, 0)]
        with self.assertRaisesRegex(ValueError, "граница|карниза|совместим"):
            build_spatial_roof_mesh(outline, [math.radians(35.0)] * len(outline))


    def test_rectangular_combination_matrix_pitch_overhang_and_profile_type(self):
        outline = list(self.outline)
        pitch_sets = (
            self.pitches,
            [math.radians(v) for v in (35, 35, 35, 35)],
            [math.radians(v) for v in (30, 40, 35, 45)],
            [math.radians(v) for v in (50, 45, 55, 50)],
        )
        for pitches in pitch_sets:
            vertices, faces, sources = build_spatial_roof_mesh(outline, pitches)
            seams = extract_roof_seams(vertices, faces, sources, [(p[0], p[1]) for p in outline])
            for overhang in (0.0, 0.15, 0.45):
                ev, ef, es = extend_spatial_roof_eaves(vertices, faces, sources, overhang)
                self.assertEqual(len(ef), len(es))
                uses = edge_uses(ef)
                self.assertTrue(all(count in (1, 2) for count in uses.values()))
                for seam_type in ("RIDGE", "VALLEY"):
                    pv, pf = build_inset_seam_profile_mesh(
                        vertices, faces, seams, seam_type, 0.15, (0.0, 0.0, 0.02),
                        end_offset=0.0, seat_sink_offset=(0.0, 0.0, -0.0002),
                        outline=[(p[0], p[1]) for p in outline],
                    )
                    self.assertEqual(bool(pv), bool(pf))
                    if pf:
                        self.assertTrue(all(count == 2 for count in edge_uses(pf).values()))

    def test_zero_overhang_is_exact_identity_and_positive_overhang_is_deterministic(self):
        identity = extend_spatial_roof_eaves(self.vertices, self.faces, self.sources, 0.0)
        self.assertEqual(identity, (self.vertices, self.faces, self.sources))
        a = extend_spatial_roof_eaves(self.vertices, self.faces, self.sources, 0.32)
        b = extend_spatial_roof_eaves(self.vertices, self.faces, self.sources, 0.32)
        self.assertEqual(a, b)


class SpatialRoofIntegrationSourceTests(unittest.TestCase):
    def test_blender_addon_exposes_numbered_plan_and_spatial_overhang(self):
        from pathlib import Path
        source = Path(__file__).with_name("__init__.py").read_text(encoding="utf-8")
        self.assertIn("template_icon(preview_icon", source)
        self.assertIn('layout.prop(settings, "overhang", text="Свес карниза")', source)
        self.assertIn("extend_spatial_roof_eaves(", source)
        self.assertIn("_store_spatial_profile_source_mesh(", source)
        self.assertIn("_spatial_profile_surface_from_source_mesh(roof_obj)", source)
        self.assertIn('row.operator("roofforge.create_ridges"', source)
        self.assertIn('row.operator("roofforge.create_valleys"', source)

    def test_standing_seam_rebuild_defines_spatial_guard(self):
        from pathlib import Path
        source = Path(__file__).with_name("__init__.py").read_text(encoding="utf-8")
        start = source.index("def _rebuild_standing_seams_for_mesh(")
        end = source.index("def _rebuild_generated_roof(", start)
        function_source = source[start:end]
        self.assertIn('is_spatial = bool(roof_obj.get("roofforge_spatial", False))', function_source)
        self.assertIn('if settings.show_standing_seams and not is_spatial:', function_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SpatialModulePackageImportRegression(unittest.TestCase):
    def test_package_import_symbol(self):
        import spatial_roof_2_8_4 as module
        self.assertTrue(callable(module.extend_spatial_roof_eaves))
        self.assertTrue(callable(module.build_spatial_roof_mesh))
