"""Topology adjacency diagnostic for stable 2D skeleton."""
import math
import unittest
from collections import defaultdict
from straight_skeleton_2_6_0 import build_roof_mesh


class TopologyDiagnostic(unittest.TestCase):
    def test_l_topology(self):
        outline=[(0,0),(8,0),(8,4),(4,4),(4,8),(0,8)]
        vertices,faces,sources=build_roof_mesh(outline,1.0,0.0,allow_oblique=True)
        edge_faces=defaultdict(list)
        for fi,face in enumerate(faces):
            for a,b in zip(face,face[1:]+face[:1]):
                edge_faces[tuple(sorted((a,b)))].append(fi)
        print("L vertices",vertices)
        print("L faces",list(zip(sources,faces)))
        for edge,ids in edge_faces.items():
            if len(ids)==2 and sources[ids[0]]!=sources[ids[1]]:
                print("ADJ",edge,"sources",sources[ids[0]],sources[ids[1]],
                      "p0",vertices[edge[0]],"p1",vertices[edge[1]])
        self.assertTrue(faces)

    def test_u_topology(self):
        outline=[(0,0),(10,0),(10,8),(7,8),(7,3),(3,3),(3,8),(0,8)]
        vertices,faces,sources=build_roof_mesh(outline,1.0,0.0,allow_oblique=True)
        edge_faces=defaultdict(list)
        for fi,face in enumerate(faces):
            for a,b in zip(face,face[1:]+face[:1]):
                edge_faces[tuple(sorted((a,b)))].append(fi)
        print("U faces",list(zip(sources,faces)))
        for edge,ids in edge_faces.items():
            if len(ids)==2 and sources[ids[0]]!=sources[ids[1]]:
                print("ADJ",edge,"sources",sources[ids[0]],sources[ids[1]],
                      "p0",vertices[edge[0]],"p1",vertices[edge[1]])
        self.assertTrue(faces)


if __name__=="__main__":
    unittest.main(verbosity=2)
