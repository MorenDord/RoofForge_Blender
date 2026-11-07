import math
import struct
import unittest
import zlib

from core.plan_preview import render_contour_plan_png


RECTANGLE = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 3.0, 0.0),
    (0.0, 3.0, 0.0),
]


def decode_png_rgba(png):
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("invalid PNG signature")
    size_x, size_y = struct.unpack(">2I", png[16:24])
    position = 8
    compressed = bytearray()
    while position < len(png):
        length = struct.unpack(">I", png[position:position + 4])[0]
        tag = png[position + 4:position + 8]
        data = png[position + 8:position + 8 + length]
        if tag == b"IDAT":
            compressed.extend(data)
        position += length + 12
    raw = zlib.decompress(bytes(compressed))
    stride = size_x * 4
    rows = []
    for y in range(size_y):
        filter_type = raw[y * (stride + 1)]
        if filter_type != 0:
            raise AssertionError("expected unfiltered PNG rows")
        rows.append(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
    return size_x, size_y, rows


class ContourPlanPreviewTests(unittest.TestCase):
    def test_rectangle_preview_is_valid_square_png(self):
        png = render_contour_plan_png(RECTANGLE)
        width, height, rows = decode_png_rgba(png)
        self.assertEqual((width, height), (256, 256))
        self.assertEqual(len(rows), 256)

    def test_preview_is_strictly_monochrome(self):
        png = render_contour_plan_png(RECTANGLE)
        _width, _height, rows = decode_png_rgba(png)
        colours = {
            tuple(row[index:index + 4])
            for row in rows
            for index in range(0, len(row), 4)
        }
        self.assertLessEqual(
            colours,
            {(0, 0, 0, 255), (255, 255, 255, 255)},
        )

    def test_label_scale_changes_preview_pixels(self):
        small = render_contour_plan_png(RECTANGLE, text_scale=0.7)
        large = render_contour_plan_png(RECTANGLE, text_scale=1.8)
        self.assertNotEqual(small, large)

    def test_supports_two_digit_edge_numbers(self):
        points = [
            (
                math.cos(index * 2.0 * math.pi / 12.0),
                math.sin(index * 2.0 * math.pi / 12.0),
                0.0,
            )
            for index in range(12)
        ]
        png = render_contour_plan_png(points, text_scale=1.4)
        width, height, _rows = decode_png_rgba(png)
        self.assertEqual((width, height), (256, 256))
        self.assertGreater(len(png), 900)

    def test_concave_l_and_u_preview(self):
        l_shape = [
            (0, 0, 0), (8, 0, 0), (8, 3, 0),
            (3, 3, 0), (3, 8, 0), (0, 8, 0),
        ]
        u_shape = [
            (0, 0, 0), (4, 0, 0), (4, 4, 0), (3, 4, 0),
            (3, 1, 0), (1, 1, 0), (1, 4, 0), (0, 4, 0),
        ]
        self.assertTrue(render_contour_plan_png(l_shape))
        self.assertTrue(render_contour_plan_png(u_shape))

    def test_rejects_degenerate_and_non_finite_contours(self):
        invalid = (
            [(0, 0), (1, 0)],
            [(0, 0), (1, 0), (2, 0)],
            [(0, 0), (1, 0), (float("nan"), 1)],
        )
        for points in invalid:
            with self.subTest(points=points):
                with self.assertRaises(ValueError):
                    render_contour_plan_png(points)


if __name__ == "__main__":
    unittest.main(verbosity=2)
