"""Tests for preserving per-edge pitches while an editable contour changes."""
import unittest
from core.contour_mapping import remap_contour_edge_values

class ContourPitchRemappingTests(unittest.TestCase):
    def test_split_edge_inherits_parent_pitch(self):
        old=[(0,0,0),(4,0,0),(4,3,0),(0,3,0)]
        new=[(0,0,0),(2,0,0),(4,0,0),(4,3,0),(0,3,0)]
        self.assertEqual(remap_contour_edge_values(old,[17,28,39,44],new,30),[17,17,28,39,44])

    def test_removed_vertex_merges_neighbouring_pitches_by_length(self):
        old=[(0,0,0),(2,0,0),(4,0,0),(4,3,0),(0,3,0)]
        new=[(0,0,0),(4,0,0),(4,3,0),(0,3,0)]
        self.assertEqual(remap_contour_edge_values(old,[10,30,40,50,60],new,30),[20,40,50,60])

    def test_unchanged_edges_keep_values_when_one_vertex_moves(self):
        old=[(0,0,0),(4,0,0),(4,3,0),(0,3,0)]
        new=[(0,0,0),(4.2,0.1,0),(4,3,0),(0,3,0)]
        mapped=remap_contour_edge_values(old,[12,24,36,48],new,30)
        self.assertEqual(len(mapped),4)
        self.assertEqual(mapped[1:],[24,36,48])

    def test_no_history_uses_default(self):
        self.assertEqual(remap_contour_edge_values([],[],[(0,0),(4,0),(0,3)],35),[35,35,35])

if __name__=="__main__": unittest.main()
