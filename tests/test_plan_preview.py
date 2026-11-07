import struct
import unittest
import zlib

from core.plan_preview import (
    render_roof_plan_png,
    surface_plan_data,
    visible_roof_edges,
)


def decode_png_rgba(png):
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError("invalid PNG signature")
    width, height = struct.unpack(">2I", png[16:24])
    position = 8
    compressed = bytearray()
    while position < len(png):
        length = struct.unpack(">I", png[position:position + 4])[0]
        tag = png[position + 4:position + 8]
        if tag == b"IDAT":
            compressed.extend(png[position + 8:position + 8 + length])
        position += length + 12
    raw = zlib.decompress(bytes(compressed))
    stride = width * 4
    rows = []
    for y in range(height):
        start = y * (stride + 1) + 1
        rows.append(raw[start:start + stride])
    return width, height, rows


def square_plan(second_plane=(0.0, 0.0, 0.0), second_slope=1):
    return {
        "vertices": [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),
        ],
        "faces": [(0, 1, 2), (0, 2, 3)],
        "face_slope_indices": [0, second_slope],
        "planes": [(0.0, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * (second_slope - 1) + [second_plane],
    }


class RoofPlanPreviewTests(unittest.TestCase):
    def test_ridge_is_visible_between_different_planes(self):
        plan = square_plan(second_plane=(1.0, -4.0 / 3.0, 0.0))
        self.assertEqual(len(visible_roof_edges(plan)), 5)

    def test_coplanar_internal_edge_is_hidden(self):
        plan = square_plan()
        self.assertEqual(len(visible_roof_edges(plan)), 4)

    def test_png_is_transparent_white_rgba_with_antialiasing(self):
        png = render_roof_plan_png(
            square_plan(second_plane=(1.0, -4.0 / 3.0, 0.0)), size=256
        )
        width, height, rows = decode_png_rgba(png)
        self.assertEqual((width, height), (256, 256))
        pixels = [tuple(row[i:i + 4]) for row in rows for i in range(0, len(row), 4)]
        self.assertIn((255, 255, 255, 0), pixels)
        self.assertIn((255, 255, 255, 255), pixels)
        self.assertTrue(any(0 < pixel[3] < 255 for pixel in pixels))
        self.assertTrue(all(pixel[:3] == (255, 255, 255) for pixel in pixels))

    def test_line_thickness_changes_preview(self):
        plan = square_plan(second_plane=(1.0, -4.0 / 3.0, 0.0))
        thin = render_roof_plan_png(plan, size=256, line_width=0.7)
        thick = render_roof_plan_png(plan, size=256, line_width=4.5)
        self.assertNotEqual(thin, thick)

    def test_number_size_changes_preview(self):
        plan = square_plan(second_plane=(1.0, -4.0 / 3.0, 0.0))
        small = render_roof_plan_png(plan, size=256, text_scale=0.5)
        large = render_roof_plan_png(plan, size=256, text_scale=1.8)
        self.assertNotEqual(small, large)

    def test_two_digit_labels_are_supported(self):
        plan = square_plan(second_slope=10)
        plan["planes"] = [(0.0, 0.0, 0.0)] * 11
        png = render_roof_plan_png(plan, size=256)
        self.assertGreater(len(png), 500)

    def test_concave_l_and_u_facets_render(self):
        shapes = (
            [(0, 0, 0), (8, 0, 0), (8, 3, 0), (3, 3, 0), (3, 8, 0), (0, 8, 0)],
            [(0, 0, 0), (4, 0, 0), (4, 4, 0), (3, 4, 0), (3, 1, 0), (1, 1, 0), (1, 4, 0), (0, 4, 0)],
        )
        for shape in shapes:
            with self.subTest(count=len(shape)):
                plan = {
                    "vertices": shape,
                    "faces": [tuple(range(len(shape)))],
                    "face_slope_indices": [0],
                    "planes": [(0.0, 0.0, 0.0)],
                }
                self.assertTrue(render_roof_plan_png(plan, size=256))

    def test_surface_data_is_json_safe(self):
        class Plane:
            a, b, c = 1.0, 2.0, 3.0
        class Surface:
            vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 1.0, 2.0))
            faces = ((0, 1, 2),)
            face_slope_indices = (0,)
            planes = (Plane(),)
        data = surface_plan_data(Surface())
        self.assertEqual(data["faces"], [[0, 1, 2]])
        self.assertEqual(data["planes"], [[1.0, 2.0, 3.0]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
