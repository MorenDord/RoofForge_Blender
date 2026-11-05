"""Pure-Python tests for the independent per-edge weighted wavefront."""
import math
import unittest
from collections import Counter

from weighted_skeleton_2_9_0 import (
    build_weighted_roof_mesh, _merge_face_patches, SkeletonError,
)


def support_plane(p, q, pitch):
    dx, dy, dz = q[0]-p[0], q[1]-p[1], q[2]-p[2]
    length = math.hypot(dx, dy)
    tx, ty = dx/length, dy/length
    nx, ny = -ty, tx
    along = dz/length
    normal = math.sqrt(math.tan(pitch)**2 - along**2)
    a = along*tx + normal*nx
    b = along*ty + normal*ny
    return a, b, p[2] - a*p[0] - b*p[1]


def edge_uses(faces):
    result = Counter()
    for face in faces:
        for a, b in zip(face, face[1:]+face[:1]):
            result[tuple(sorted((a,b)))] += 1
    return result


class WeightedWavefrontTests(unittest.TestCase):
    def build(self, outline, degrees):
        pitches = [math.radians(v) for v in degrees]
        planes = [support_plane(outline[i], outline[(i+1)%len(outline)], pitches[i])
                  for i in range(len(outline))]
        speeds = [1.0 / math.sqrt(
            math.tan(pitches[i])**2 -
            ((outline[(i+1)%len(outline)][2]-outline[i][2]) /
             math.hypot(outline[(i+1)%len(outline)][0]-outline[i][0],
                        outline[(i+1)%len(outline)][1]-outline[i][1]))**2
        ) for i in range(len(outline))]
        vertices, faces, sources = build_weighted_roof_mesh(
            [(p[0],p[1]) for p in outline], speeds, planes
        )
        self.assertTrue(vertices)
        self.assertTrue(faces)
        self.assertEqual(len(faces), len(sources))
        uses = edge_uses(faces)
        self.assertTrue(all(v in (1,2) for v in uses.values()))
        self.assertTrue(any(v == 1 for v in uses.values()))
        self.assertTrue(any(v == 2 for v in uses.values()))
        for face, source in zip(faces, sources):
            a,b,c = planes[source]
            for index in face:
                x,y,z = vertices[index]
                self.assertAlmostEqual(z, a*x+b*y+c, places=5)
        return vertices, faces, sources

    def test_rectangle_uniform_speed_matches_classic_topology(self):
        outline=[(0,0,0),(8,0,0),(8,5,0),(0,5,0)]
        self.build(outline,[35]*4)

    def test_rectangle_individual_pitches(self):
        outline=[(0,0,0),(8,0,0),(8,5,0),(0,5,0)]
        self.build(outline,[30,36,42,34])

    def test_concave_l_individual_pitches(self):
        outline=[(0,0,0),(8,0,0),(8,4,0),(4,4,0),(4,8,0),(0,8,0)]
        self.build(outline,[30,36,42,34,39,32])

    def test_concave_u_individual_pitches(self):
        outline=[(0,0,0),(10,0,0),(10,8,0),(7,8,0),
                 (7,3,0),(3,3,0),(3,8,0),(0,8,0)]
        self.build(outline,[32,35,38,40,34,37,31,36])


    def test_nonplanar_l_micro_height_variation(self):
        outline=[(0,0,0),(8,0,.005),(8,4,.010),
                 (4,4,.015),(4,8,.020),(0,8,.010)]
        self.build(outline,[38]*6)

    def test_nonplanar_l_equal_pitch(self):
        outline=[(0,0,0),(8,0,.08),(8,4,.12),(4,4,.16),(4,8,.20),(0,8,.10)]
        self.build(outline,[38]*6)

    def test_identical_swept_patch_is_counted_once(self):
        patch = [
            (0.0, 0.0, 0.0), (2.0, 0.0, 0.4),
            (2.0, 1.0, 0.6), (0.0, 1.0, 0.2),
        ]
        loops = _merge_face_patches([patch, list(patch)], 2.0)
        self.assertEqual(len(loops), 1)

    def test_collinear_duplicate_split_patch_is_counted_once(self):
        base = [
            (0.0, 0.0, 0.0), (2.0, 0.0, 0.4),
            (2.0, 1.0, 0.6), (0.0, 1.0, 0.2),
        ]
        with_middle_vertex = [
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.2), (2.0, 0.0, 0.4),
            (2.0, 1.0, 0.6), (0.0, 1.0, 0.2),
        ]
        loops = _merge_face_patches([base, with_middle_vertex], 2.0)
        self.assertEqual(len(loops), 1)

    def test_partial_same_direction_overlap_is_still_rejected(self):
        first = [
            (0.0, 0.0, 0.0), (2.0, 0.0, 0.0),
            (2.0, 2.0, 0.0), (0.0, 2.0, 0.0),
        ]
        second = [
            (1.0, 0.0, 0.0), (3.0, 0.0, 0.0),
            (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
        ]
        with self.assertRaisesRegex(SkeletonError, "неманифолдную границу"):
            _merge_face_patches([first, second], 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
