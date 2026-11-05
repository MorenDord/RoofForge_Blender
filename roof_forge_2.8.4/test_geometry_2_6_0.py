"""RoofForge geometry regression tests (pure Python; no Blender required)."""
import collections
import math
import random
import unittest

import straight_skeleton_2_6_0 as geometry


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, factor):
    return (a[0] * factor, a[1] * factor)


def _norm(a):
    length = math.hypot(a[0], a[1])
    return (a[0] / length, a[1] / length)


def _line_intersection(p, r, q, s):
    denominator = _cross(r, s)
    if abs(denominator) <= 1.0e-12:
        raise ValueError("Parallel edges in test offset")
    amount = _cross(_sub(q, p), s) / denominator
    return _add(p, _mul(r, amount))


def _offset_polygon(poly, distance):
    if distance <= 1.0e-10:
        return list(poly)
    shifted = []
    for i, point in enumerate(poly):
        edge = _norm(_sub(poly[(i + 1) % len(poly)], point))
        outward = (edge[1], -edge[0])
        shifted.append((_add(point, _mul(outward, distance)), edge))
    return [
        _line_intersection(
            shifted[i - 1][0], shifted[i - 1][1],
            shifted[i][0], shifted[i][1],
        )
        for i in range(len(poly))
    ]


def _edge_use_counts(faces):
    return collections.Counter(
        tuple(sorted((a, b)))
        for face in faces
        for a, b in zip(face, face[1:] + face[:1])
    )


def _assert_directed_edges_are_opposed(testcase, faces):
    uses = collections.defaultdict(list)
    for face_index, face in enumerate(faces):
        for a, b in zip(face, face[1:] + face[:1]):
            uses[tuple(sorted((a, b)))].append((a, b, face_index))
    for edge, pair in uses.items():
        testcase.assertEqual(len(pair), 2, f"edge {edge} is not used twice")
        testcase.assertEqual(
            pair[0][:2], (pair[1][1], pair[1][0]),
            f"edge {edge} has inconsistent face winding",
        )


def _component_count(vertex_count, faces):
    adjacency = [set() for _ in range(vertex_count)]
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            adjacency[a].add(b)
            adjacency[b].add(a)
    seen = set()
    components = 0
    for start in range(vertex_count):
        if start in seen:
            continue
        components += 1
        stack = [start]
        seen.add(start)
        while stack:
            current = stack.pop()
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
    return components, len(seen)


def _assert_vertex_links_are_cycles(testcase, vertex_count, faces):
    """For a closed polygon mesh, every vertex link must be one cycle."""
    for vertex_id in range(vertex_count):
        link = collections.defaultdict(set)
        for face in faces:
            if vertex_id not in face:
                continue
            index = face.index(vertex_id)
            previous = face[(index - 1) % len(face)]
            following = face[(index + 1) % len(face)]
            link[previous].add(following)
            link[following].add(previous)
        testcase.assertTrue(link, f"orphan vertex {vertex_id}")
        testcase.assertTrue(
            all(len(neighbours) == 2 for neighbours in link.values()),
            f"vertex {vertex_id} has a non-cyclic link: {dict(link)}",
        )
        seed = next(iter(link))
        reached = {seed}
        stack = [seed]
        while stack:
            item = stack.pop()
            for neighbour in link[item]:
                if neighbour not in reached:
                    reached.add(neighbour)
                    stack.append(neighbour)
        testcase.assertEqual(
            len(reached), len(link), f"vertex {vertex_id} has disconnected face fans"
        )


SCREEN_OUTLINE = [
    (899, 72), (1172, 72), (1172, 904), (1050, 904),
    (1050, 1096), (722, 1096), (722, 904), (551, 904),
    (551, 695), (157, 695), (157, 409), (899, 409),
]
SCREEN_POLYGON = list(reversed([(x, -y) for x, y in SCREEN_OUTLINE]))


class RoofForge256Tests(unittest.TestCase):
    def test_screenshot_ridge_branch_is_one_closed_connected_shell(self):
        pitch_tan = math.tan(math.radians(35.0))
        vertices, faces, sources = geometry.build_roof_mesh(SCREEN_POLYGON, pitch_tan)
        seams = geometry.extract_roof_seams(vertices, faces, sources, SCREEN_POLYGON)

        # Before 2.5.3 this contour failed for every width, including 0.01 m.
        for width in (0.01, 0.18, 0.5):
            with self.subTest(width=width):
                ridge_vertices, ridge_faces = geometry.build_inset_seam_profile_mesh(
                    vertices, faces, seams, "RIDGE", width, (0.0, 0.0, 0.01),
                    outline=SCREEN_POLYGON,
                )
                self.assertTrue(ridge_faces)
                self.assertTrue(all(v == 2 for v in _edge_use_counts(ridge_faces).values()))
                _assert_directed_edges_are_opposed(self, ridge_faces)
                components, reached = _component_count(len(ridge_vertices), ridge_faces)
                # Coplanar false-ridge edges are removed, so one formerly
                # connected profile may correctly become separate components.
                self.assertGreaterEqual(components, 1)
                self.assertEqual(reached, len(ridge_vertices))
                _assert_vertex_links_are_cycles(self, len(ridge_vertices), ridge_faces)

    def test_valley_pipeline_is_unchanged_and_manifold(self):
        vertices, faces, sources = geometry.build_roof_mesh(
            SCREEN_POLYGON, math.tan(math.radians(35.0))
        )
        seams = geometry.extract_roof_seams(vertices, faces, sources, SCREEN_POLYGON)
        valley_vertices, valley_faces = geometry.build_inset_seam_profile_mesh(
            vertices, faces, seams, "VALLEY", 0.24, (0.0, 0.0, 0.01),
            outline=SCREEN_POLYGON,
        )
        self.assertTrue(valley_faces)
        self.assertTrue(all(v == 2 for v in _edge_use_counts(valley_faces).values()))
        _assert_directed_edges_are_opposed(self, valley_faces)
        _assert_vertex_links_are_cycles(self, len(valley_vertices), valley_faces)

    def test_overhang_changes_eave_only_and_preserves_skeleton_nodes(self):
        pitch_tan = math.tan(math.radians(35.0))
        vertices, faces, sources = geometry.build_roof_mesh(SCREEN_POLYGON, pitch_tan)
        base_internal = {
            tuple(round(value, 7) for value in point)
            for point in vertices
            if not any(
                abs(_cross(_sub(b, a), (point[0] - a[0], point[1] - a[1]))) < 1.0e-6
                and -1.0e-7 <= (
                    (point[0] - a[0]) * (b[0] - a[0])
                    + (point[1] - a[1]) * (b[1] - a[1])
                ) / ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) <= 1.0 + 1.0e-7
                for a, b in zip(SCREEN_POLYGON, SCREEN_POLYGON[1:] + SCREEN_POLYGON[:1])
            )
        }

        for overhang in (0.0, 0.1, 0.25, 0.5, 2.0):
            with self.subTest(overhang=overhang):
                expanded = _offset_polygon(SCREEN_POLYGON, overhang)
                out_vertices, out_faces, out_sources = geometry.extend_roof_mesh_eaves(
                    vertices, faces, sources, SCREEN_POLYGON, expanded,
                    overhang, pitch_tan,
                )
                self.assertEqual(len(out_vertices), len(vertices))
                self.assertEqual(len(out_faces), len(faces))
                self.assertEqual(out_sources, sources)
                geometry._validate_face_planarity(out_vertices, out_faces, 1.0e-5)
                geometry._validate_roof_mesh_topology(
                    out_vertices, out_faces, expanded, 1.0e-5
                )
                out_internal = {
                    tuple(round(value, 7) for value in point)
                    for point in out_vertices
                    if not any(
                        abs(_cross(_sub(b, a), (point[0] - a[0], point[1] - a[1]))) < 1.0e-6
                        and -1.0e-7 <= (
                            (point[0] - a[0]) * (b[0] - a[0])
                            + (point[1] - a[1]) * (b[1] - a[1])
                        ) / ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) <= 1.0 + 1.0e-7
                        for a, b in zip(expanded, expanded[1:] + expanded[:1])
                    )
                }
                self.assertEqual(out_internal, base_internal)
                # The original eave loop lies on the same roof planes at z=0.
                for face, source_id in zip(out_faces, out_sources):
                    source_ids = (source_id if isinstance(source_id, (tuple, list))
                                  else (source_id,))
                    pa, pb, pc = geometry.roof_face_plane(out_vertices, face)
                    for edge_id in source_ids:
                        a = SCREEN_POLYGON[edge_id]
                        b = SCREEN_POLYGON[(edge_id + 1) % len(SCREEN_POLYGON)]
                        midpoint = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
                        self.assertAlmostEqual(
                            pa * midpoint[0] + pb * midpoint[1] + pc, 0.0, places=5
                        )

                seams = geometry.extract_roof_seams(
                    out_vertices, out_faces, out_sources, SCREEN_POLYGON
                )
                ridge_vertices, ridge_faces = geometry.build_inset_seam_profile_mesh(
                    out_vertices, out_faces, seams, "RIDGE", 0.18,
                    (0.0, 0.0, 0.01), outline=expanded,
                )
                self.assertTrue(ridge_faces)
                self.assertTrue(all(v == 2 for v in _edge_use_counts(ridge_faces).values()))
                valley_vertices, valley_faces = geometry.build_inset_seam_profile_mesh(
                    out_vertices, out_faces, seams, "VALLEY", 0.24,
                    (0.0, 0.0, 0.01), outline=expanded,
                )
                if valley_faces:
                    self.assertTrue(
                        all(v == 2 for v in _edge_use_counts(valley_faces).values())
                    )
                    _assert_directed_edges_are_opposed(self, valley_faces)
                    _assert_vertex_links_are_cycles(self, len(valley_vertices), valley_faces)

    def test_reported_corrected_vertex_is_stable(self):
        vertices, faces, _ = geometry.build_roof_mesh(
            SCREEN_POLYGON, math.tan(math.radians(35.0))
        )
        matching = [
            point for point in vertices
            if abs(point[0] - 924.5) < 1.0e-6 and abs(point[1] + 656.5) < 1.0e-6
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual((len(vertices), len(faces)), (21, 11))
        edge_faces = collections.defaultdict(list)
        for face_index, face in enumerate(faces):
            for a, b in zip(face, face[1:] + face[:1]):
                edge_faces[tuple(sorted((a, b)))].append(face_index)
        for edge, adjacent in edge_faces.items():
            if len(adjacent) == 2:
                normal_a = geometry._unit_face_normal(vertices, faces[adjacent[0]])
                normal_b = geometry._unit_face_normal(vertices, faces[adjacent[1]])
                self.assertLess(
                    geometry._dot3(normal_a, normal_b), 1.0 - 1.0e-10,
                    f"coplanar internal edge {edge} was not dissolved",
                )

    def test_ridge_end_clipping_remains_closed(self):
        vertices, faces, sources = geometry.build_roof_mesh(
            SCREEN_POLYGON, math.tan(math.radians(35.0))
        )
        seams = geometry.extract_roof_seams(vertices, faces, sources, SCREEN_POLYGON)
        for options in ({}, {"end_setback": 0.1}, {"end_overhang": 0.1},
                        {"end_setback": 0.05, "end_overhang": 0.1}):
            with self.subTest(options=options):
                ridge_vertices, ridge_faces = geometry.build_inset_seam_profile_mesh(
                    vertices, faces, seams, "RIDGE", 0.18, (0.0, 0.0, 0.01),
                    outline=SCREEN_POLYGON, **options,
                )
                self.assertTrue(ridge_faces)
                self.assertTrue(all(v == 2 for v in _edge_use_counts(ridge_faces).values()))
                components, reached = _component_count(len(ridge_vertices), ridge_faces)
                self.assertGreaterEqual(components, 1)
                self.assertEqual(reached, len(ridge_vertices))

    def test_profile_shells_on_basic_roof_shapes(self):
        polygons = {
            "square": [(0, 0), (4, 0), (4, 4), (0, 4)],
            "rectangle": [(0, 0), (6, 0), (6, 3), (0, 3)],
            "L": [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)],
            "U": [(0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)],
            "oblique_L": [(0, 0), (4, 0), (4.5, 1), (1.4, 1.3), (1, 4), (0, 4)],
        }
        for name, polygon in polygons.items():
            roof_vertices, roof_faces, sources = geometry.build_roof_mesh(
                polygon, math.tan(math.radians(30.0))
            )
            seams = geometry.extract_roof_seams(roof_vertices, roof_faces, sources, polygon)
            for kind in ("RIDGE", "VALLEY"):
                with self.subTest(name=name, kind=kind):
                    profile_vertices, profile_faces = geometry.build_inset_seam_profile_mesh(
                        roof_vertices, roof_faces, seams, kind, 0.18,
                        (0.0, 0.0, 0.01), outline=polygon,
                    )
                    if not profile_faces:
                        continue
                    self.assertTrue(
                        all(value == 2 for value in _edge_use_counts(profile_faces).values())
                    )
                    _assert_vertex_links_are_cycles(self, len(profile_vertices), profile_faces)

    def test_basic_low_poly_roof_counts_remain_unchanged(self):
        polygons = {
            "square": [(0, 0), (4, 0), (4, 4), (0, 4)],
            "rectangle": [(0, 0), (6, 0), (6, 3), (0, 3)],
            "L": [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)],
            "U": [(0, 0), (4, 0), (4, 4), (3, 4), (3, 1), (1, 1), (1, 4), (0, 4)],
            "oblique_L": [(0, 0), (4, 0), (4.5, 1), (1.4, 1.3), (1, 4), (0, 4)],
        }
        expected = {
            "square": (5, 4), "rectangle": (6, 4), "L": (9, 6),
            "U": (12, 8), "oblique_L": (10, 6),
        }
        for name, polygon in polygons.items():
            with self.subTest(name=name):
                roof_vertices, roof_faces, _ = geometry.build_roof_mesh(
                    polygon, math.tan(math.radians(30.0))
                )
                self.assertEqual((len(roof_vertices), len(roof_faces)), expected[name])

    def test_coplanar_roof_faces_are_dissolved(self):
        vertices = [
            (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (2.0, 0.0, 1.0),
            (0.0, 1.0, 1.0), (1.0, 1.0, 1.0), (2.0, 1.0, 1.0),
        ]
        faces = [(0, 1, 4, 3), (1, 2, 5, 4)]
        merged_v, merged_f, merged_sources = geometry._merge_coplanar_roof_faces(
            vertices, faces, [0, 1], 2.0
        )
        self.assertEqual(len(merged_f), 1)
        self.assertEqual(len(merged_v), 4)
        self.assertEqual(set(merged_sources[0]), {0, 1})
        self.assertEqual(len(merged_f[0]), 4)

    def test_coplanar_shared_edge_never_becomes_a_seam(self):
        vertices = [
            (0.0, 0.0, 1.0), (1.0, 0.0, 1.0),
            (1.0, 1.0, 1.0), (0.0, 1.0, 1.0),
        ]
        faces = [(0, 1, 2), (0, 2, 3)]
        seams = geometry.extract_roof_seams(vertices, faces, [0, 1],
                                            [(0, 0), (1, 0), (1, 1), (0, 1)])
        self.assertEqual(seams, [])

    def test_signed_endpoint_offset_matches_legacy_pair(self):
        vertices, faces, sources = geometry.build_roof_mesh(
            SCREEN_POLYGON, math.tan(math.radians(35.0))
        )
        seams = geometry.extract_roof_seams(vertices, faces, sources, SCREEN_POLYGON)
        for signed, legacy in ((0.15, {"end_overhang": 0.15}),
                               (-0.12, {"end_setback": 0.12}),
                               (0.05, {"end_setback": 0.03, "end_overhang": 0.08})):
            signed_mesh = geometry.build_inset_seam_profile_mesh(
                vertices, faces, seams, "RIDGE", 0.18, (0.0, 0.0, 0.01),
                outline=SCREEN_POLYGON, end_offset=signed,
            )
            legacy_mesh = geometry.build_inset_seam_profile_mesh(
                vertices, faces, seams, "RIDGE", 0.18, (0.0, 0.0, 0.01),
                outline=SCREEN_POLYGON, **legacy,
            )
            self.assertEqual(signed_mesh, legacy_mesh)

    def test_oblique_l_contours_have_stable_valid_roofs(self):
        polygons = [
            [(0, 0), (6, 0), (6, 2), (3, 3), (3, 6), (0, 6)],
            [(0, 0), (8, 0), (7, 2), (3, 3), (2, 7), (0, 7)],
            [(0, 0), (6, 0), (5, 2), (2, 4), (2, 7), (0, 7)],
            [(0, 0), (7, 0), (7, 2), (4, 4), (3, 7), (0, 7)],
            [(0, 0), (8, 0), (8, 3), (5, 4), (3, 7), (0, 7)],
            [(0, 0), (7, 0), (7, 2), (4, 3), (2, 6), (0, 6)],
            # Simultaneous edge-collapse / reflex-split case from stress testing.
            [(0.0, 0.0), (5.683121768130834, 0.0),
             (5.683121768130834, 4.5801158187951),
             (2.220575654270237, 7.048736266393137),
             (2.220575654270237, 9.935846243800594),
             (0.0, 9.935846243800594)],
            # Previously failed oblique inward-corner proportions.
            [(0, 0), (4.541731265675749, 0),
             (4.541731265675749, 5.498827805190443),
             (3.600190925091757, 8.036036753096589),
             (3.600190925091757, 11.790320394340803),
             (0, 11.790320394340803)],
        ]
        for index, polygon in enumerate(polygons):
            with self.subTest(polygon=index):
                self._assert_oblique_l_valid(polygon)

        # A deterministic spread of oblique notch angles and arm proportions.
        rng = random.Random(254)
        for index in range(64):
            width = rng.uniform(4.0, 12.0)
            height = rng.uniform(4.0, 12.0)
            notch_x = rng.uniform(width * 0.2, width * 0.8)
            lower_y = rng.uniform(height * 0.08, height * 0.5)
            upper_y = rng.uniform(max(lower_y + 0.05, height * 0.35), height * 0.82)
            polygon = [
                (0.0, 0.0), (width, 0.0), (width, lower_y),
                (notch_x, upper_y), (notch_x, height), (0.0, height),
            ]
            with self.subTest(random_polygon=index):
                self._assert_oblique_l_valid(polygon)

    def test_free_angle_mode_handles_500_affine_oblique_l_contours(self):
        """Stress the dedicated free-angle wavefront path on skewed L plans."""
        base = [
            (0.0, 0.0), (8.0, 0.0), (8.0, 2.0),
            (3.0, 2.0), (3.0, 8.0), (0.0, 8.0),
        ]
        rng = random.Random(955)
        validated = 0
        attempts = 0
        while validated < 500 and attempts < 1000:
            attempts += 1
            scale_x = rng.uniform(0.7, 1.5)
            scale_y = rng.uniform(0.7, 1.5)
            shear_x = rng.uniform(-0.8, 0.8)
            shear_y = rng.uniform(-0.8, 0.8)
            determinant = scale_x * scale_y - shear_x * shear_y
            if determinant <= 0.25:
                continue

            translate_x = rng.uniform(-3.0, 3.0)
            translate_y = rng.uniform(-3.0, 3.0)
            polygon = [
                (
                    scale_x * x + shear_x * y + translate_x,
                    shear_y * x + scale_y * y + translate_y,
                )
                for x, y in base
            ]
            with self.subTest(contour=validated):
                roof_v, roof_f, source_ids = geometry.build_roof_mesh(
                    polygon, math.tan(math.radians(30.0)), allow_oblique=True
                )
                self.assertTrue(roof_f)
                geometry._validate_face_planarity(roof_v, roof_f, 1.0e-5)
                geometry._validate_roof_mesh_topology(roof_v, roof_f, polygon, 1.0e-5)

                seams = geometry.extract_roof_seams(
                    roof_v, roof_f, source_ids, polygon
                )
                for kind in ("RIDGE", "VALLEY"):
                    profile_v, profile_f = geometry.build_inset_seam_profile_mesh(
                        roof_v, roof_f, seams, kind, 0.18,
                        (0.0, 0.0, 0.01), outline=polygon,
                    )
                    if profile_f:
                        counts = _edge_use_counts(profile_f)
                        self.assertTrue(
                            all(count == 2 for count in counts.values()),
                            f"{kind} profile is not a closed manifold shell",
                        )
                        _assert_vertex_links_are_cycles(self, len(profile_v), profile_f)
            validated += 1

        self.assertEqual(validated, 500, "Could not generate 500 valid oblique L contours")

    def test_ideal_orthogonal_l_is_stable_in_free_angle_mode(self):
        """An exact 90-degree L must use the same free-angle path as oblique plans."""
        source = [
            (0.0, 0.0), (6.0, 0.0), (6.0, 2.0),
            (2.0, 2.0), (2.0, 6.0), (0.0, 6.0),
        ]
        boundary_edges_by_case = []
        for reverse in (False, True):
            base = list(reversed(source)) if reverse else list(source)
            for shift in range(len(base)):
                polygon = base[shift:] + base[:shift]
                if geometry._poly_area_2d(polygon) < 0.0:
                    polygon.reverse()
                for pitch in (30.0, 45.0):
                    with self.subTest(reverse=reverse, shift=shift, pitch=pitch):
                        vertices, faces, sources = geometry.build_roof_mesh(
                            polygon, math.tan(math.radians(pitch)), allow_oblique=True
                        )
                        self.assertEqual(len(vertices), 9)
                        self.assertEqual(len(faces), 6)
                        geometry._validate_face_planarity(vertices, faces, 1.0e-6)
                        geometry._validate_roof_mesh_topology(
                            vertices, faces, polygon, 1.0e-6
                        )
                        seams = geometry.extract_roof_seams(
                            vertices, faces, sources, polygon
                        )
                        for kind in ("RIDGE", "VALLEY"):
                            profile_v, profile_f = geometry.build_inset_seam_profile_mesh(
                                vertices, faces, seams, kind, 0.12,
                                (0.0, 0.0, 0.01), outline=polygon,
                            )
                            if profile_f:
                                self.assertTrue(
                                    all(value == 2 for value in _edge_use_counts(profile_f).values())
                                )

    def test_exact_orthogonal_l_simultaneous_events_keep_small_facets(self):
        """Do not erase genuine tiny facets on exact 90-degree L plans.

        The first footprint combines a long limb with a sub-millimetre notch.
        Multiple wavefront collapses occur at the same distance. The projected
        route may reject its overlapping patches, but the established fallback
        must retain the small face instead of simplifying it away.
        The second footprint has nearly equal shoulder dimensions and exercises
        the local swept-patch area threshold.
        """
        contours = [
            [
                (0.0, 0.0),
                (0.1172970698005918, 0.0),
                (0.1172970698005918, 0.0005384010852618479),
                (0.0001712178185272939, 0.0005384010852618479),
                (0.0001712178185272939, 71.27819914099638),
                (0.0, 71.27819914099638),
            ],
            [
                (0.0, 0.0),
                (0.03027455076867856, 0.0),
                (0.03027455076867856, 0.004188825114160215),
                (0.004187764385368406, 0.004188825114160215),
                (0.004187764385368406, 0.019047752969839047),
                (0.0, 0.019047752969839047),
            ],
        ]
        pitch_tan = math.tan(math.radians(30.0))
        for index, polygon in enumerate(contours):
            with self.subTest(contour=index):
                # Validate the classic fallback independently on the most
                # degenerate exact-orthogonal case.
                if index == 0:
                    classic_v, classic_f, _ = geometry._build_roof_mesh_impl(
                        polygon, pitch_tan, 0.0, projected_edge_events=False
                    )
                    self.assertEqual((len(classic_v), len(classic_f)), (10, 6))

                vertices, faces, sources = geometry.build_roof_mesh(
                    polygon, pitch_tan, allow_oblique=True
                )
                self.assertEqual((len(vertices), len(faces)), (10, 6))
                geometry._validate_face_planarity(
                    vertices, faces, max(max(abs(x) for x, _y in polygon),
                                         max(abs(y) for _x, y in polygon)) * 1.0e-7
                )
                geometry._validate_roof_mesh_topology(
                    vertices, faces, polygon,
                    max(max(math.dist(polygon[i], polygon[(i + 1) % len(polygon)])
                            for i in range(len(polygon))) * 1.0e-8, 1.0e-8),
                )

    def test_existing_mesh_boundary_edges_drive_signed_profile_offsets(self):
        polygon = [
            (0.0, 0.0), (6.0, 0.0), (6.0, 2.0),
            (2.0, 2.0), (2.0, 6.0), (0.0, 6.0),
        ]
        vertices, faces, sources = geometry.build_roof_mesh(
            polygon, math.tan(math.radians(30.0)), allow_oblique=True
        )
        seams = geometry.extract_roof_seams(vertices, faces, sources, polygon)
        boundary_uses = _edge_use_counts(faces)
        boundary_edges = [
            (vertices[a], vertices[b])
            for face in faces
            for a, b in zip(face, face[1:] + face[:1])
            if boundary_uses[tuple(sorted((a, b)))] == 1
        ]
        for kind in ("RIDGE", "VALLEY"):
            with self.subTest(kind=kind):
                zero_v, zero_f = geometry.build_inset_seam_profile_mesh(
                    vertices, faces, seams, kind, 0.12, (0.0, 0.0, 0.01),
                    end_offset=0.0, boundary_edges=boundary_edges,
                )
                over_v, over_f = geometry.build_inset_seam_profile_mesh(
                    vertices, faces, seams, kind, 0.12, (0.0, 0.0, 0.01),
                    end_offset=0.2, boundary_edges=boundary_edges,
                )
                inset_v, inset_f = geometry.build_inset_seam_profile_mesh(
                    vertices, faces, seams, kind, 0.12, (0.0, 0.0, 0.01),
                    end_offset=-0.2, boundary_edges=boundary_edges,
                )
                self.assertTrue(zero_f and over_f and inset_f)
                zero_extent = (min(v[0] for v in zero_v), max(v[0] for v in zero_v),
                               min(v[1] for v in zero_v), max(v[1] for v in zero_v))
                over_extent = (min(v[0] for v in over_v), max(v[0] for v in over_v),
                               min(v[1] for v in over_v), max(v[1] for v in over_v))
                inset_extent = (min(v[0] for v in inset_v), max(v[0] for v in inset_v),
                                min(v[1] for v in inset_v), max(v[1] for v in inset_v))
                self.assertLess(over_extent[0], zero_extent[0] + 1.0e-7)
                self.assertGreater(over_extent[1], zero_extent[1] - 1.0e-7)
                self.assertGreater(inset_extent[0], zero_extent[0] - 1.0e-7)
                self.assertLess(inset_extent[1], zero_extent[1] + 1.0e-7)

    def test_free_angle_solver_handles_simple_and_curved_l_shapes(self):
        """Cover the basic L cases that regressed in the free-angle selector."""
        contours = {
            "orthogonal_L": [
                (0.0, 0.0), (6.0, 0.0), (6.0, 2.0),
                (2.0, 2.0), (2.0, 6.0), (0.0, 6.0),
            ],
            "oblique_L": [
                (0.0, 0.0), (8.0, 0.0), (8.0, 2.0),
                (3.5, 3.0), (3.0, 7.0), (0.0, 7.0),
            ],
            "curved_inner_L": [
                (0.0, 0.0), (8.0, 0.0), (8.0, 2.0), (7.8, 2.6),
                (7.2, 3.4), (6.4, 4.0), (5.4, 4.5),
                (4.0, 4.9), (3.8, 8.0), (0.0, 8.0),
            ],
            "curved_outer_L": [
                (0.0, 0.0), (8.0, 0.0), (8.3, 0.7), (8.4, 1.5),
                (8.0, 2.2), (5.1, 3.6), (3.2, 4.2),
                (3.0, 8.0), (0.0, 8.0),
            ],
        }
        for name, source in contours.items():
            for rotation in range(len(source)):
                polygon = source[rotation:] + source[:rotation]
                area = geometry._poly_area_2d(polygon)
                if area < 0.0:
                    polygon.reverse()
                for angle in (math.radians(30.0), math.radians(45.0)):
                    with self.subTest(contour=name, rotation=rotation, pitch=angle):
                        vertices, faces, sources = geometry.build_roof_mesh(
                            polygon, math.tan(angle), allow_oblique=True
                        )
                        self.assertTrue(faces)
                        geometry._validate_face_planarity(vertices, faces, 1.0e-5)
                        geometry._validate_roof_mesh_topology(
                            vertices, faces, polygon, 1.0e-5
                        )
                        seams = geometry.extract_roof_seams(
                            vertices, faces, sources, polygon
                        )
                        for kind in ("RIDGE", "VALLEY"):
                            profile_v, profile_f = geometry.build_inset_seam_profile_mesh(
                                vertices, faces, seams, kind, 0.12,
                                (0.0, 0.0, 0.01), outline=polygon,
                            )
                            if profile_f:
                                self.assertTrue(
                                    all(v == 2 for v in _edge_use_counts(profile_f).values())
                                )
                                _assert_vertex_links_are_cycles(
                                    self, len(profile_v), profile_f
                                )

    def _assert_oblique_l_valid(self, polygon):
        roof_v, roof_f, source_ids = geometry.build_roof_mesh(
            polygon, math.tan(math.radians(35.0))
        )
        self.assertTrue(roof_f)
        geometry._validate_face_planarity(roof_v, roof_f, 1.0e-5)
        geometry._validate_roof_mesh_topology(roof_v, roof_f, polygon, 1.0e-5)
        seams = geometry.extract_roof_seams(roof_v, roof_f, source_ids, polygon)
        for kind in ("RIDGE", "VALLEY"):
            prof_v, prof_f = geometry.build_inset_seam_profile_mesh(
                roof_v, roof_f, seams, kind, 0.12, (0.0, 0.0, 0.01),
                outline=polygon,
            )
            if prof_f:
                self.assertTrue(all(value == 2 for value in _edge_use_counts(prof_f).values()))
                _assert_vertex_links_are_cycles(self, len(prof_v), prof_f)




class WeightedStraightSkeletonTests(unittest.TestCase):
    def test_equal_edge_angles_match_uniform_roof(self):
        polygon = [(0.0, 0.0), (8.0, 0.0), (8.0, 5.0), (0.0, 5.0)]
        angle = math.radians(35.0)
        weighted = geometry.build_weighted_roof_mesh(polygon, [angle] * 4)
        uniform = geometry.build_roof_mesh(
            polygon, math.tan(angle), 0.0, allow_oblique=True
        )
        self.assertEqual(len(weighted[0]), len(uniform[0]))
        self.assertEqual(len(weighted[1]), len(uniform[1]))
        self.assertEqual(weighted[2], uniform[2])
        for a, b in zip(weighted[0], uniform[0]):
            self.assertAlmostEqual(a[0], b[0], places=6)
            self.assertAlmostEqual(a[1], b[1], places=6)
            self.assertAlmostEqual(a[2], b[2], places=6)

    def test_rectangular_roof_accepts_individual_angles(self):
        polygon = [(0.0, 0.0), (8.0, 0.0), (8.0, 5.0), (0.0, 5.0)]
        pitches = [math.radians(v) for v in (30.0, 38.0, 42.0, 34.0)]
        vertices, faces, sources = geometry.build_weighted_roof_mesh(polygon, pitches)
        self.assertTrue(vertices)
        self.assertTrue(faces)
        self.assertEqual(len(faces), len(sources))
        self.assertEqual(set(sources), {0, 1, 2, 3})
        self.assertTrue(all(math.isfinite(v) for p in vertices for v in p))

    def test_concave_l_roof_uses_weighted_reflex_events(self):
        polygon = [
            (0.0, 0.0), (8.0, 0.0), (8.0, 4.0),
            (4.0, 4.0), (4.0, 8.0), (0.0, 8.0),
        ]
        pitches = [math.radians(v) for v in (30, 35, 40, 32, 38, 34)]
        vertices, faces, sources = geometry.build_weighted_roof_mesh(polygon, pitches)
        self.assertTrue(vertices)
        self.assertTrue(faces)
        self.assertEqual(len(faces), len(sources))
        self.assertEqual(set(sources), set(range(6)))

    def test_concave_u_roof_uses_weighted_reflex_events(self):
        polygon = [
            (0.0, 0.0), (10.0, 0.0), (10.0, 8.0),
            (7.0, 8.0), (7.0, 3.0), (3.0, 3.0),
            (3.0, 8.0), (0.0, 8.0),
        ]
        pitches = [math.radians(v) for v in (32, 35, 38, 40, 34, 37, 31, 36)]
        vertices, faces, sources = geometry.build_weighted_roof_mesh(polygon, pitches)
        self.assertTrue(vertices)
        self.assertTrue(faces)
        self.assertEqual(len(faces), len(sources))
        self.assertEqual(set(sources), set(range(8)))

    def test_rejects_mismatched_edge_pitch_count(self):
        polygon = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
        with self.assertRaises(geometry.SkeletonError):
            geometry.build_weighted_roof_mesh(polygon, [math.radians(35.0)] * 3)

    def test_rejects_zero_edge_pitch(self):
        polygon = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
        with self.assertRaises(geometry.SkeletonError):
            geometry.build_weighted_roof_mesh(polygon, [0.0] * 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
