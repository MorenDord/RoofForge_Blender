import math
import unittest

from core.geometry import GeometryInputError, signed_area
from core.intersection_envelope import build_intersection_envelope_surface
from core.mesh import build_roof_surface
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh
from core.exact_spatial import validate_planar_face


def _double_acute_notch_outline():
    # Two narrow inward V-notches create multiple reflex events. Non-zero
    # elevations at several boundary vertices exercise genuinely spatial
    # support planes rather than a flat XY-only roof.
    points = [
        (0.0, 0.0, 0.00),
        (10.0, 0.0, 0.03),
        (10.0, 8.0, 0.01),
        (7.0, 8.0, 0.04),
        (6.0, 5.0, 0.01),
        (5.0, 8.0, 0.03),
        (3.0, 8.0, 0.00),
        (2.0, 5.0, 0.02),
        (1.0, 8.0, 0.04),
        (0.0, 8.0, 0.00),
    ]
    pitches = [
        31.0 + 3.5 * math.sin(index * 0.83)
        + 1.2 * math.cos(index * 1.17)
        for index in range(len(points))
    ]
    return points, pitches


def _reverse_boundary_and_pitches(points, pitches):
    count = len(points)
    reversed_points = list(reversed(points))
    # A reversed edge corresponds to the preceding authored edge.
    reversed_pitches = [
        pitches[(count - 2 - index) % count]
        for index in range(count)
    ]
    return reversed_points, reversed_pitches


def _three_notch_contour():
    xy = [
        (0.0, 0.0), (14.0, 0.0), (14.0, 10.0),
        (11.5, 10.0), (11.0, 6.5), (10.5, 10.0),
        (7.5, 10.0), (7.0, 6.5), (6.5, 10.0),
        (3.5, 10.0), (3.0, 6.5), (2.5, 10.0),
        (0.0, 10.0),
    ]
    points = [
        (x, y, 0.012 * math.sin(index * 0.73)
         + 0.006 * math.cos(index * 1.19))
        for index, (x, y) in enumerate(xy)
    ]
    pitches = [
        32.0 + 2.8 * math.sin(index * 0.67)
        + 1.4 * math.cos(index * 1.03)
        for index in range(len(points))
    ]
    return points, pitches


def _narrow_neck_contour(neck_width):
    lower = 4.0 - 0.5 * neck_width
    upper = 4.0 + 0.5 * neck_width
    xy = [
        (0.0, 0.0), (6.0, 0.0), (6.0, lower), (14.0, lower),
        (14.0, 0.0), (20.0, 0.0), (20.0, 8.0), (14.0, 8.0),
        (14.0, upper), (6.0, upper), (6.0, 8.0), (0.0, 8.0),
    ]
    points = [
        (x, y, 0.009 * math.sin(index * 0.81)
         + 0.004 * math.cos(index * 1.31))
        for index, (x, y) in enumerate(xy)
    ]
    pitches = [
        30.0 + 2.5 * math.sin(index * 0.91)
        + 1.0 * math.cos(index * 0.47)
        for index in range(len(points))
    ]
    return points, pitches


class TransitionTopologyRegressionTests(unittest.TestCase):
    def assert_exact_closed_transition_surface(self, points, pitches, surface):
        source_count = len(points)
        self.assertTrue(surface.faces)
        self.assertEqual(surface.approximation_error, 0.0)
        self.assertEqual(surface.refinement_depth, 0)
        self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
        self.assertEqual(
            set(index for index in surface.face_slope_indices if index >= 0),
            set(range(source_count)),
        )
        self.assertIn(-1, surface.face_slope_indices)

        expected_area = abs(signed_area([
            (point[0], point[1]) for point in points
        ]))
        self.assertAlmostEqual(surface.surface_area_xy, expected_area, places=7)
        self.assertAlmostEqual(surface.source_area_xy, expected_area, places=7)

        edge_uses = {}
        for face, source_index in zip(
            surface.faces, surface.face_slope_indices
        ):
            for local_index, first in enumerate(face):
                second = face[(local_index + 1) % len(face)]
                edge = (min(first, second), max(first, second))
                edge_uses.setdefault(edge, []).append(source_index)

            if source_index == -1:
                self.assertEqual(len(face), 3)
                validate_planar_face(surface.vertices, face, eps=1e-8)
            else:
                plane = surface.planes[source_index]
                for vertex_index in face:
                    x, y, z = surface.vertices[vertex_index]
                    self.assertAlmostEqual(
                        z, plane.height(x, y), places=7
                    )

        for face, source_index in zip(
            surface.faces, surface.face_slope_indices
        ):
            if source_index != -1:
                continue
            for local_index, first in enumerate(face):
                second = face[(local_index + 1) % len(face)]
                edge = (min(first, second), max(first, second))
                self.assertEqual(
                    len(edge_uses[edge]), 2,
                    "each transition-facet edge must be shared by exactly two faces",
                )

        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_two_acute_notches_and_multiple_raised_eaves(self):
        points, pitches = _double_acute_notch_outline()
        surface = build_intersection_envelope_surface(points, pitches)
        reference = build_roof_surface(points, pitches)

        self.assert_exact_closed_transition_surface(points, pitches, surface)
        self.assertTrue(reference.faces)
        self.assertEqual(reference.approximation_error, 0.0)
        self.assertEqual(reference.refinement_depth, 0)
        self.assertAlmostEqual(
            reference.surface_area_xy, surface.surface_area_xy, places=7
        )
        self.assertAlmostEqual(
            reference.source_area_xy, surface.source_area_xy, places=7
        )

    def test_two_acute_notches_are_independent_of_boundary_winding(self):
        points, pitches = _double_acute_notch_outline()
        forward = build_intersection_envelope_surface(points, pitches)
        reversed_points, reversed_pitches = _reverse_boundary_and_pitches(
            points, pitches
        )
        backward = build_intersection_envelope_surface(
            reversed_points, reversed_pitches
        )

        self.assert_exact_closed_transition_surface(points, pitches, forward)
        self.assert_exact_closed_transition_surface(
            reversed_points, reversed_pitches, backward
        )
        self.assertAlmostEqual(
            forward.surface_area_xy, backward.surface_area_xy, places=7
        )
        self.assertEqual(
            len(forward.faces), len(backward.faces),
            "reversing the authored contour must not change the exact topology size",
        )


    def test_three_reflex_notches_keep_exact_transition_topology(self):
        points, pitches = _three_notch_contour()
        surface = build_intersection_envelope_surface(points, pitches)
        self.assert_exact_closed_transition_surface(points, pitches, surface)

    def test_four_reflex_neck_fails_closed_at_event_ambiguity_budget(self):
        points, pitches = _narrow_neck_contour(0.60)
        with self.assertRaises(GeometryInputError) as context:
            build_intersection_envelope_surface(points, pitches)
        self.assertEqual(
            context.exception.code,
            "EXACT_SPATIAL_TOPOLOGY_UNRESOLVED",
        )
        self.assertIn("300000", str(context.exception))
        self.assertIn("без аппроксимации", str(context.exception))

    def test_sub_tolerance_neck_is_rejected_before_surface_assembly(self):
        points, pitches = _narrow_neck_contour(1.0e-8)
        with self.assertRaises(GeometryInputError) as context:
            build_intersection_envelope_surface(points, pitches)
        self.assertEqual(
            getattr(context.exception, "code", None),
            "SELF_INTERSECTION",
            "a neck below the robust polygon tolerance must fail closed",
        )

if __name__ == "__main__":
    unittest.main()
