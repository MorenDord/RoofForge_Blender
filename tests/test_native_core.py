"""Differential tests for the optional Rust geometry extension."""
from __future__ import annotations

import math
import random
import unittest

from core.geometry import (
    _validate_simple_polygon_python,
    validate_simple_polygon,
)
from core.native_bridge import (
    NATIVE_BACKEND_AVAILABLE,
    validate_simple_polygon_native,
)


def _diagnostic_tuples(items):
    return [(item.code, item.message, item.severity) for item in items]


def _radial_polygon(count: int):
    points = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        radius = 10.0 + 0.07 * math.sin(7.0 * angle) + 0.03 * math.cos(11.0 * angle)
        points.append((radius * math.cos(angle), radius * math.sin(angle)))
    return points


@unittest.skipUnless(NATIVE_BACKEND_AVAILABLE, "Rust extension wheel is not installed")
class TestRustGeometryParity(unittest.TestCase):
    def test_native_api_matches_python_for_fixed_cases(self):
        fixtures = [
            [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)],
            [(0.0, 1.0), (2.0, 1.0), (2.0, 0.0), (0.0, 0.0)],
            [(0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (4.0, 4.0),
             (4.0, 8.0), (0.0, 8.0)],
            [(0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0)],
            [(0.0, 0.0), (1.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)],
            [(0.0, 0.0), (float("nan"), 0.0), (0.0, 1.0)],
            [(0.0, 0.0), (1.0, 0.0)],
        ]

        for points in fixtures:
            with self.subTest(points=points):
                expected = _diagnostic_tuples(
                    _validate_simple_polygon_python(points)
                )
                actual = validate_simple_polygon_native(points)
                self.assertIsNotNone(actual)
                self.assertEqual(actual, expected)

    def test_native_api_matches_python_for_deterministic_generated_contours(self):
        rng = random.Random(917_204)
        fixtures = [_radial_polygon(count) for count in (24, 32, 48, 64, 96)]

        for count in (24, 40, 72):
            angles = sorted(rng.random() * 2.0 * math.pi for _ in range(count))
            fixtures.append([
                (
                    (5.0 + rng.random() * 4.0) * math.cos(angle),
                    (5.0 + rng.random() * 4.0) * math.sin(angle),
                )
                for angle in angles
            ])

        for points in fixtures:
            with self.subTest(count=len(points)):
                expected = _diagnostic_tuples(
                    _validate_simple_polygon_python(points)
                )
                actual = validate_simple_polygon_native(points)
                self.assertEqual(actual, expected)

    def test_production_dispatch_uses_a_parity_checked_native_path(self):
        points = _radial_polygon(48)
        expected = _validate_simple_polygon_python(points)
        actual = validate_simple_polygon(points)
        self.assertEqual(_diagnostic_tuples(actual), _diagnostic_tuples(expected))


if __name__ == "__main__":
    unittest.main()
