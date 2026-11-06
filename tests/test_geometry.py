import unittest

from core.geometry import (
    PlaneZ, clip_half_plane, lower_envelope_regions,
    signed_area, validate_simple_polygon,
)


class PolygonTests(unittest.TestCase):
    def test_rectangle_area(self):
        poly = [(0, 0), (4, 0), (4, 3), (0, 3)]
        self.assertAlmostEqual(signed_area(poly), 12.0)
        self.assertEqual(validate_simple_polygon(poly), [])

    def test_bow_tie_rejected(self):
        poly = [(0, 0), (2, 2), (0, 2), (2, 0)]
        codes = {item.code for item in validate_simple_polygon(poly)}
        self.assertIn("SELF_INTERSECTION", codes)

    def test_half_plane_clip(self):
        square = [(0, 0), (2, 0), (2, 2), (0, 2)]
        clipped = clip_half_plane(square, 1, 0, -1)
        self.assertAlmostEqual(abs(signed_area(clipped)), 2.0)

    def test_lower_envelope_two_planes(self):
        domain = [(0, 0), (2, 0), (2, 2), (0, 2)]
        planes = [PlaneZ(1, 0, 0), PlaneZ(-1, 0, 2)]
        regions = lower_envelope_regions(domain, planes)
        self.assertAlmostEqual(abs(signed_area(regions[0])), 2.0)
        self.assertAlmostEqual(abs(signed_area(regions[1])), 2.0)


if __name__ == "__main__":
    unittest.main()
