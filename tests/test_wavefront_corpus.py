import math
import unittest

from core.geometry import signed_area
from core.mesh import build_roof_shell
from core.validation import validate_closed_mesh
from core.wavefront import (
    build_wavefront_roof_surface,
    collect_loop_events,
    create_wavefront_state,
    run_weighted_wavefront,
)


class WeightedWavefrontCorpusTests(unittest.TestCase):
    def test_multi_notch_equal_and_variable_pitch(self):
        points_xy = [
            (0.0, 0.0),
            (12.0, 0.0),
            (12.0, 8.0),
            (10.0, 8.0),
            (9.0, 4.0),
            (8.0, 4.0),
            (7.0, 7.0),
            (5.0, 7.0),
            (4.0, 4.0),
            (3.0, 4.0),
            (2.0, 8.0),
            (0.0, 8.0),
        ]
        self.assertGreater(signed_area(points_xy), 0.0)

        state = create_wavefront_state(
            [(x, y, 0.0) for x, y in points_xy],
            [35.0] * len(points_xy),
        )
        initial_events = collect_loop_events(
            state.loops[0],
            state.edges,
            state.current_time,
            state.epsilon,
        )
        split_events = [
            event for event in initial_events
            if event.kind.value == "SPLIT_CANDIDATE"
        ]
        self.assertGreaterEqual(
            len(split_events),
            2,
            "Fixture should contain a genuinely simultaneous multi-split opportunity.",
        )

        pitch_sets = [
            [35.0] * len(points_xy),
            [
                34.0 + 4.0 * math.sin(index * 0.83)
                + 2.0 * math.cos(index * 1.17)
                for index in range(len(points_xy))
            ],
        ]

        for pitches in pitch_sets:
            with self.subTest(variable_pitch=not all(
                abs(value - pitches[0]) < 1e-9 for value in pitches
            )):
                points = [(x, y, 0.0) for x, y in points_xy]
                trace = run_weighted_wavefront(points, pitches)
                self.assertTrue(trace.is_complete)
                self.assertAlmostEqual(
                    trace.projected_facet_area,
                    abs(signed_area(points_xy)),
                    places=5,
                )

                surface = build_wavefront_roof_surface(points, pitches)
                self.assertAlmostEqual(
                    surface.surface_area_xy,
                    surface.source_area_xy,
                    places=5,
                )
                self.assertEqual(
                    len(surface.face_slope_indices),
                    len(surface.faces),
                )

                shell = build_roof_shell(surface, 0.10)
                self.assertEqual(
                    validate_closed_mesh(shell.vertices, shell.faces),
                    [],
                )

    def test_multi_notch_pitch_profile_stays_on_authored_planes(self):
        points = [
            (0.0, 0.0, 0.0),
            (12.0, 0.0, 0.0),
            (12.0, 8.0, 0.0),
            (10.0, 8.0, 0.0),
            (9.0, 4.0, 0.0),
            (8.0, 4.0, 0.0),
            (7.0, 7.0, 0.0),
            (5.0, 7.0, 0.0),
            (4.0, 4.0, 0.0),
            (3.0, 4.0, 0.0),
            (2.0, 8.0, 0.0),
            (0.0, 8.0, 0.0),
        ]
        pitches = [30.0, 36.0, 41.0, 33.0, 38.0, 42.0, 31.0, 39.0, 35.0, 40.0, 34.0, 37.0]

        surface = build_wavefront_roof_surface(points, pitches)

        self.assertGreater(len(surface.faces), 0)
        for face, slope_index in zip(surface.faces, surface.face_slope_indices):
            plane = surface.planes[slope_index]
            for vertex_index in face:
                x, y, z = surface.vertices[vertex_index]
                self.assertAlmostEqual(
                    plane.height(x, y),
                    z,
                    places=7,
                )


if __name__ == "__main__":
    unittest.main()
