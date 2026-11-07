import math
import unittest

from core.geometry import GeometryInputError
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
        extended = extend_convex_roof_surface(surface, overhang)
        self.assertGreater(extended.surface_area_xy, surface.surface_area_xy)
        self.assertGreaterEqual(len(extended.boundary_xy), len(surface.boundary_xy))
        added_faces = list(zip(
            extended.faces[len(surface.faces):],
            extended.face_slope_indices[len(surface.faces):],
        ))
        strips = [
            (face, slope_id) for face, slope_id in added_faces
            if slope_id >= 0
        ]
        caps = [
            (face, slope_id) for face, slope_id in added_faces
            if slope_id == -1
        ]
        self.assertEqual(
            len(strips), len(surface.boundary_xy),
            "there must be exactly one plane-preserving strip per boundary edge",
        )
        for face, slope_id in strips:
            plane = surface.planes[slope_id]
            for vertex_id in face:
                x, y, z = extended.vertices[vertex_id]
                self.assertAlmostEqual(plane.height(x, y), z, places=7)
        self.assertTrue(
            all(len(face) == 4 for face, _slope_id in caps),
            "custom-angle joins must use one quad cap, not a fan of spokes",
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
