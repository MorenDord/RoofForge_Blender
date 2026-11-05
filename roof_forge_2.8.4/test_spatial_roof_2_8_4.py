import math, unittest
from collections import Counter
from spatial_roof_2_8_4 import build_spatial_roof_mesh, SpatialRoofError

class SpatialRoofTests(unittest.TestCase):
    def test_sloped_rectangle_individual_pitches(self):
        outline=[(0,0,0),(8,0,1),(8,5,1),(0,5,0)]
        v,f,s=build_spatial_roof_mesh(outline,[math.radians(35)]*4)
        self.assertTrue(v and f)
        self.assertEqual(len(f),len(s))
        self.assertTrue(all(len(x)>=3 for x in f))
        self.assertTrue(all(math.isfinite(c) for p in v for c in p))
    def test_nonplanar_convex_loop_with_individual_pitches(self):
        outline=[(0,0,0),(8,0,0.5),(8,5,0.8),(0,5,0.1)]
        angles=[math.radians(x) for x in (30,35,40,35)]
        v,f,s=build_spatial_roof_mesh(outline,angles)
        self.assertTrue(v and f)
        self.assertEqual(len(f),len(s))
        self.assertEqual(len(f),4)

    def test_nonplanar_concave_l_rejects_unclosed_envelope(self):
        outline=[(0,0,0),(8,0,0.2),(8,4,0.4),(4,4,0.8),(4,8,0.6),(0,8,0.1)]
        angles=[math.radians(x) for x in (35,38,40,36,42,37)]
        with self.assertRaises(SpatialRoofError):
            build_spatial_roof_mesh(outline,angles)

    def test_cyclic_start_and_reversed_winding_preserve_spatial_build(self):
        outline=[(0,0,0),(8,0,0.5),(8,5,0.8),(0,5,0.1)]
        pitches=[math.radians(x) for x in (30,35,40,35)]
        for reverse in (False, True):
            pts=list(reversed(outline)) if reverse else list(outline)
            ang=([pitches[(len(pitches)-2-i) % len(pitches)] for i in range(len(pitches))]
                 if reverse else list(pitches))
            for shift in range(len(pts)):
                rp=pts[shift:]+pts[:shift]
                ra=ang[shift:]+ang[:shift]
                v,f,s=build_spatial_roof_mesh(rp,ra)
                self.assertEqual(len(f),4)
                self.assertEqual(len(f),len(s))

    def test_pitch_must_exceed_eave_grade(self):
        with self.assertRaises(SpatialRoofError):
            build_spatial_roof_mesh([(0,0,0),(1,0,2),(1,1,2),(0,1,0)],[math.radians(30)]*4)

if __name__=='__main__': unittest.main(verbosity=2)
