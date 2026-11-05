"""Temporary diagnostic for the non-planar concave envelope."""
import math
import unittest
from collections import defaultdict
from spatial_roof_2_9_0 import (
    _edge_plane,
    _build_triangulated_lower_envelope,
    _distance2,
)


def edge_uses(faces):
    result=defaultdict(list)
    for fi,face in enumerate(faces):
        for a,b in zip(face,face[1:]+face[:1]):
            result[tuple(sorted((a,b)))].append(fi)
    return result


class Diagnostic(unittest.TestCase):
    def test_l_open_edges(self):
        outline=[
            (0,0,0.000),(8,0,0.020),(8,4,0.030),
            (4,4,0.040),(4,8,0.050),(0,8,0.025)
        ]
        pitches=[math.radians(35)]*6
        planes=[
            _edge_plane(outline[i],outline[(i+1)%6],pitches[i],0.0)
            for i in range(6)
        ]
        vertices,faces,sources=_build_triangulated_lower_envelope(
            outline,planes,1.0e-9
        )
        uses=edge_uses(faces)
        open_edges=[(edge,uses[edge]) for edge in uses if len(uses[edge])==1]
        self.assertTrue(open_edges)
        for edge,face_ids in open_edges[:20]:
            fi=face_ids[0]
            print("OPEN",edge,"face",fi,"source",sources[fi])
            a,b=edge
            p0=vertices[a]; p1=vertices[b]
            print("  p0",p0,"p1",p1)
            for fj,(face,source) in enumerate(zip(faces,sources)):
                if fj==fi: continue
                if a in face or b in face:
                    print("  related",fj,"source",source)
        self.fail("diagnostic open edge count={}".format(len(open_edges)))


if __name__=="__main__":
    unittest.main(verbosity=2)
