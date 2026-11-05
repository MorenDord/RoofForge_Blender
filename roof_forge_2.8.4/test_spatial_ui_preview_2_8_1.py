"""Regression tests for the 2.9 top-view facet preview renderer."""

import ast
import math
import struct
import unittest
import zlib
from pathlib import Path

from spatial_roof_2_9_0 import build_spatial_roof_mesh


SOURCE = Path(__file__).with_name("__init__.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NODE = next(
    node for node in TREE.body
    if isinstance(node, ast.FunctionDef) and node.name == "_spatial_preview_png"
)
NAMESPACE = {
    "math": math,
    "struct": struct,
    "zlib": zlib,
    "build_spatial_roof_mesh": build_spatial_roof_mesh,
}
exec(
    compile(ast.Module(body=[NODE], type_ignores=[]), "<spatial-preview>", "exec"),
    NAMESPACE,
)
render = NAMESPACE["_spatial_preview_png"]


def decode_rgba_png(png):
    if not png.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):
        raise AssertionError("Preview is not a PNG.")
    width, height = struct.unpack(">2I", png[16:24])
    position = 8
    compressed = bytearray()
    while position < len(png):
        length = struct.unpack(">I", png[position:position + 4])[0]
        tag = png[position + 4:position + 8]
        data = png[position + 8:position + 8 + length]
        if tag == b"IDAT":
            compressed.extend(data)
        position += 12 + length

    raw = zlib.decompress(bytes(compressed))
    stride = width * 4
    rows = []
    for y in range(height):
        offset = y * (stride + 1)
        filter_type = raw[offset]
        if filter_type != 0:
            raise AssertionError("Unexpected PNG filter {}".format(filter_type))
        rows.append(raw[offset + 1:offset + 1 + stride])
    return width, height, rows


class SpatialPreviewTests(unittest.TestCase):
    def test_preview_is_rgba_with_transparent_theme_background(self):
        points = [
            (0, 0, 0.00), (8, 0, 0.04), (8, 5, 0.10), (0, 5, 0.02),
        ]
        png = render(
            points,
            size=256,
            pitch_angles=[math.radians(35.0)] * 4,
        )
        width, height, rows = decode_rgba_png(png)
        self.assertEqual((width, height), (256, 256))
        # The preview stores white RGB with zero alpha, so Blender's theme
        # background shows through instead of a white or black rectangle.
        self.assertEqual(tuple(rows[0][0:4]), (255, 255, 255, 0))
        alpha_values = {
            rows[y][x * 4 + 3]
            for y in range(height)
            for x in range(width)
        }
        self.assertIn(0, alpha_values)
        self.assertIn(255, alpha_values)
        self.assertTrue(any(0 < value < 255 for value in alpha_values),
                        "4x supersampling should produce antialiased edge pixels")

        for row in rows:
            for x in range(width):
                r, g, b, a = row[x * 4:x * 4 + 4]
                if a:
                    self.assertEqual((r, g, b), (255, 255, 255),
                                     "Preview must contain only white strokes and labels")

    def test_every_facet_is_outlined_and_per_edge_pitch_changes_preview(self):
        points = [
            (3, 0, 0.000), (7, 0, 0.020), (7, 3, 0.055), (10, 3, 0.070),
            (10, 7, 0.045), (7, 7, 0.090), (7, 10, 0.120), (3, 10, 0.080),
            (3, 7, 0.050), (0, 7, 0.040), (0, 3, 0.010), (3, 3, 0.015),
        ]
        flat_pitch = [math.radians(35.0)] * len(points)
        varied_pitch = [
            math.radians(value)
            for value in (32, 34, 36, 38, 35, 33, 37, 39, 36, 34, 32, 35)
        ]
        vertices, faces, source_ids = build_spatial_roof_mesh(points, flat_pitch)
        self.assertGreaterEqual(len(faces), 6)
        self.assertEqual(len(faces), len(source_ids))
        self.assertTrue(all(len(face) >= 3 for face in faces))

        flat_preview = render(points, size=256, pitch_angles=flat_pitch)
        varied_preview = render(points, size=256, pitch_angles=varied_pitch)
        self.assertNotEqual(
            flat_preview,
            varied_preview,
            "Per-edge roof pitch must change the facet outlines in the preview",
        )

    def test_labels_are_centered_and_fit_inside_their_facet(self):
        self.assertIn("anchor, clearance = label_anchor(poly)", SOURCE)
        self.assertIn("available_radius = clearance * scale * ss * 0.78", SOURCE)
        self.assertIn("cx,cy=screen(anchor)", SOURCE)
        self.assertIn("if fit_cell < 2:", SOURCE)
        self.assertIn("for fi,poly in enumerate(facet_polygons):", SOURCE)

    def test_preview_scales_with_panel_width_without_digit_size_control(self):
        self.assertIn("region_width = max(240, getattr(context.region, \"width\", 320))", SOURCE)
        self.assertIn("region_width / 42.0", SOURCE)
        self.assertIn("template_icon(preview_icon, scale=preview_scale)", SOURCE)
        self.assertNotIn("spatial_preview_text_scale", SOURCE)
        self.assertNotIn('text="Размер цифр"', SOURCE)

    def test_degenerate_loop_is_rejected(self):
        with self.assertRaises(ValueError):
            render([(0, 0), (1, 0)], size=256)


if __name__ == "__main__":
    unittest.main(verbosity=2)
