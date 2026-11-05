import ast
import math
import struct
import unittest
import zlib
from pathlib import Path

SOURCE = Path(__file__).with_name('__init__.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
NODE = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == '_spatial_preview_png')
NS = {'math': math, 'struct': struct, 'zlib': zlib}
exec(compile(ast.Module(body=[NODE], type_ignores=[]), '<preview-helper>', 'exec'), NS)
render = NS['_spatial_preview_png']


class SpatialPreviewTests(unittest.TestCase):
    def test_l_contour_preview_is_valid_png(self):
        points = [(0, 0, 0), (8, 0, 0.5), (8, 5, 1), (3, 5, 1.5), (3, 9, 2), (0, 9, 2.5)]
        png = render(points)
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(struct.unpack('>2I', png[16:24]), (256, 256))
        self.assertIn(b'IDAT', png)

    def test_preview_supports_two_digit_edge_labels(self):
        points = [(math.cos(i*2*math.pi/12), math.sin(i*2*math.pi/12), i*0.1) for i in range(12)]
        png = render(points)
        self.assertEqual(struct.unpack('>2I', png[16:24]), (256, 256))
        self.assertGreater(len(png), 1000)

    def test_degenerate_loop_is_rejected(self):
        with self.assertRaises(ValueError):
            render([(0, 0), (1, 0)])


    def test_preview_is_monochrome_and_text_size_changes_pixels(self):
        points = [(0, 0, 0), (8, 0, .5), (8, 5, 1), (0, 5, .2)]
        small = render(points, text_scale=0.7)
        large = render(points, text_scale=1.8)
        self.assertNotEqual(small, large)
        # PNG RGBA data contains only black and white pixels (no coloured badges).
        def rgba(png):
            pos = 8; compressed = bytearray()
            while pos < len(png):
                length = struct.unpack('>I', png[pos:pos+4])[0]
                tag = png[pos+4:pos+8]; data = png[pos+8:pos+8+length]
                if tag == b'IDAT': compressed.extend(data)
                pos += 12 + length
            raw = zlib.decompress(bytes(compressed))
            colors = set()
            stride = 1 + 256*4
            for y in range(256):
                row = raw[y*stride+1:(y+1)*stride]
                for x in range(256):
                    i=x*4; colors.add(tuple(row[i:i+4]))
            return colors
        colors = rgba(large)
        self.assertTrue(colors.issubset({(0,0,0,255),(255,255,255,255)}))

    def test_preview_ui_scales_to_panel_width_and_exposes_digit_size(self):
        self.assertIn('region_width / 42.0', SOURCE)
        self.assertIn('spatial_preview_text_scale', SOURCE)
        self.assertIn('text="Размер цифр"', SOURCE)
        self.assertNotIn('disk(lx,ly,10,(245,190,82))', SOURCE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
