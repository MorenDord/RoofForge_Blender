import math
import unittest

from core.geometry import GeometryInputError, validate_simple_polygon
from core.mesh import build_roof_surface
from core.wavefront import build_wavefront_roof_surface
from core.overhang import extend_convex_roof_surface
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh


FLAT_RECTANGLE = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 3.0, 0.0),
    (0.0, 3.0, 0.0),
]
MIXED_Z_RECTANGLE = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.2),
    (4.0, 3.0, 0.4),
    (0.0, 3.0, 0.1),
]
CONCAVE_L = [
    (0.0, 0.0, 0.0),
    (8.0, 0.0, 0.0),
    (8.0, 3.0, 0.0),
    (3.0, 3.0, 0.0),
    (3.0, 8.0, 0.0),
    (0.0, 8.0, 0.0),
]
CONCAVE_U = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 4.0, 0.0),
    (3.0, 4.0, 0.0),
    (3.0, 1.0, 0.0),
    (1.0, 1.0, 0.0),
    (1.0, 4.0, 0.0),
    (0.0, 4.0, 0.0),
]


class RoofOverhangTests(unittest.TestCase):
    def _assert_extended_shell(self, surface, overhang):
        edge_uses = {}
        for face in surface.faces:
            for index, first in enumerate(face):
                second = face[(index + 1) % len(face)]
                key = (min(first, second), max(first, second))
                edge_uses[key] = edge_uses.get(key, 0) + 1
        source_boundary_edge_count = sum(
            1 for count in edge_uses.values() if count == 1
        )

        extended = extend_convex_roof_surface(surface, overhang)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        self.assertEqual(
            validate_simple_polygon(extended.boundary_xy),
            [],
            "the generated eave outline must be one non-self-intersecting polygon",
        )
        added = list(zip(
            extended.faces[len(surface.faces):],
            extended.face_slope_indices[len(surface.faces):],
        ))
        strips = [(face, slope_id) for face, slope_id in added if slope_id >= 0]
        caps = [(face, slope_id) for face, slope_id in added if slope_id == -1]
        self.assertEqual(
            len(strips), source_boundary_edge_count,
            "there must be exactly one support-plane strip per source boundary segment",
        )
        self.assertTrue(
            all(len(face) == 3 for face, _slope_id in caps),
            "the only non-plane faces must be local triangular miter caps",
        )
        for face, slope_id in strips:
            plane = surface.planes[slope_id]
            for vertex_id in face:
                x, y, z = extended.vertices[vertex_id]
                self.assertAlmostEqual(plane.height(x, y), z, places=7)

        # Prove the upper surface has exactly one directed perimeter loop.
        open_edges_by_key = {}
        for face in extended.faces:
            for index, first in enumerate(face):
                second = face[(index + 1) % len(face)]
                key = (min(first, second), max(first, second))
                open_edges_by_key.setdefault(key, []).append((first, second))
        open_edges = [
            uses[0] for uses in open_edges_by_key.values() if len(uses) == 1
        ]
        self.assertEqual(
            len(open_edges), len(extended.boundary_xy),
            "the top surface boundary must be one edge for every perimeter segment",
        )
        outgoing = {}
        incoming = {}
        for first, second in open_edges:
            self.assertNotIn(first, outgoing, "outer boundary branches at a vertex")
            self.assertNotIn(second, incoming, "outer boundary has multiple predecessors")
            outgoing[first] = second
            incoming[second] = first
        self.assertEqual(set(outgoing), set(incoming))
        start = open_edges[0][0]
        current = start
        visited = set()
        while current not in visited:
            visited.add(current)
            self.assertIn(current, outgoing)
            current = outgoing[current]
        self.assertEqual(current, start)
        self.assertEqual(
            len(visited), len(open_edges),
            "the eave must be one closed loop, not several loops or protruding branches",
        )

        shell = build_roof_shell(extended, 0.01)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])
        return extended
    def test_equal_pitch_flat_contour_has_exact_miter_offset(self):
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, [35.0] * 4)
        extended = self._assert_extended_shell(surface, 0.25)
        expected = {
            (-0.25, -0.25),
            (4.25, -0.25),
            (4.25, 3.25),
            (-0.25, 3.25),
        }
        actual = {
            (round(point[0], 6), round(point[1], 6))
            for point in extended.boundary_xy
        }
        self.assertEqual(actual, expected)

    def test_individual_pitches_on_flat_convex_contour_keep_overhang_parallel(self):
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, [30.0, 35.0, 40.0, 32.0])
        extended = self._assert_extended_shell(surface, 0.2)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        strip_faces = [
            (face, slope_id)
            for face, slope_id in zip(
                extended.faces[len(surface.faces):],
                extended.face_slope_indices[len(surface.faces):],
            )
            if slope_id >= 0
        ]
        for face, slope_id in strip_faces:
            start = FLAT_RECTANGLE[slope_id]
            end = FLAT_RECTANGLE[(slope_id + 1) % len(FLAT_RECTANGLE)]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = (dx * dx + dy * dy) ** 0.5
            offset_vertices = []
            for vertex_id in face:
                x, y, _z = extended.vertices[vertex_id]
                signed_distance = (
                    dx * (y - start[1]) - dy * (x - start[0])
                ) / length
                if abs(signed_distance + 0.2) < 1e-6:
                    offset_vertices.append((x, y))
            self.assertEqual(len(offset_vertices), 2)
            outer_dx = offset_vertices[1][0] - offset_vertices[0][0]
            outer_dy = offset_vertices[1][1] - offset_vertices[0][1]
            self.assertAlmostEqual(dx * outer_dy - dy * outer_dx, 0.0, places=6)

    def test_custom_pitch_uses_one_mitered_xy_perimeter_without_ridge_tails(self):
        surface = build_wavefront_roof_surface(
            FLAT_RECTANGLE, [30.0, 35.0, 40.0, 32.0]
        )
        extended = self._assert_extended_shell(surface, 0.2)

        # A 4 x 3 rectangle with a 0.2 m parallel offset has exactly this
        # outer perimeter. Ridge intersections may split its edges, but no
        # topological point is allowed to protrude beyond these four lines.
        expected_corners = {
            (-0.2, -0.2),
            (4.2, -0.2),
            (4.2, 3.2),
            (-0.2, 3.2),
        }
        actual_corners = {
            (round(x, 7), round(y, 7))
            for x, y in extended.boundary_xy
            if min(
                abs(y + 0.2),
                abs(x - 4.2),
                abs(y - 3.2),
                abs(x + 0.2),
            ) < 1e-7
        }
        self.assertTrue(expected_corners.issubset(actual_corners))
        for x, y in extended.boundary_xy:
            distance_to_offset_line = min(
                abs(y + 0.2),
                abs(x - 4.2),
                abs(y - 3.2),
                abs(x + 0.2),
            )
            self.assertLessEqual(
                distance_to_offset_line,
                1e-6,
                f"outer perimeter point ({x:.7g}, {y:.7g}) protrudes outside the single miter loop",
            )

        cap_faces = [
            face for face, slope_id in zip(
                extended.faces[len(surface.faces):],
                extended.face_slope_indices[len(surface.faces):],
            )
            if slope_id == -1
        ]
        self.assertGreater(
            len(cap_faces), 0,
            "custom pitch differences should be closed with local miter caps",
        )

    def test_mixed_z_contour_supports_individual_pitch_overhang(self):
        surface = build_roof_surface(MIXED_Z_RECTANGLE, [38.0, 40.0, 42.0, 39.0])
        extended = self._assert_extended_shell(surface, 0.2)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)

    def test_mixed_z_contour_with_equal_pitch_supports_overhang(self):
        surface = build_roof_surface(MIXED_Z_RECTANGLE, [35.0] * 4)
        self._assert_extended_shell(surface, 0.2)

    def test_concave_l_with_individual_pitch_supports_overhang(self):
        pitches = [31.0, 32.5, 34.0, 35.5, 37.0, 38.5]
        surface = build_wavefront_roof_surface(CONCAVE_L, pitches)
        extended = self._assert_extended_shell(surface, 0.15)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)

    def test_concave_u_with_individual_pitch_supports_overhang(self):
        speeds = [0.8, 0.75, 1.0, 1.25, 1.2, 1.4, 1.0, 0.6]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        surface = build_wavefront_roof_surface(CONCAVE_U, pitches)
        extended = self._assert_extended_shell(surface, 0.1)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)

    def test_too_large_concave_overhang_is_rejected_instead_of_self_intersecting(self):
        speeds = [0.8, 0.75, 1.0, 1.25, 1.2, 1.4, 1.0, 0.6]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        surface = build_wavefront_roof_surface(CONCAVE_U, pitches)
        with self.assertRaises(GeometryInputError):
            extend_convex_roof_surface(surface, 1.5)

    def test_small_resolvable_convex_overhang_is_not_discarded_by_tolerance(self):
        surface = build_wavefront_roof_surface(FLAT_RECTANGLE, [35.0] * 4)
        self._assert_extended_shell(surface, 0.001)


if __name__ == "__main__":
    unittest.main()
