# RoofForge

Procedural roof generation for Blender 5.0+, aimed at environment artists and game-ready asset workflows.

> **Current test build: 0.2.0-alpha.2.** This is an early user-test build, not a finished 1.0 release. It adds automatic object-boundary detection, per-edge pitch fields, a debounced live rebuild and a tested flat-eave weighted wavefront path. The geometry engine still has explicit scope limits described below.

## Project documents

- Technical specification: `docs/SPECIFICATION.md`
- Architecture: `docs/ARCHITECTURE.md`
- Development roadmap: `docs/ROADMAP.md`
- 0.2.0 plan: `docs/PLAN_0.2.0_RU.md`
- Session handoff / restart instructions: `docs/SESSION_HANDOFF.md`

## 0.2.0 alpha features

- Select a mesh object; no vertex or edge selection is needed.
- Automatically read one closed outer boundary from a wire contour or the boundary of a surface mesh.
- Show one numbered pitch field for each ordered boundary edge.
- Generate and update a separate closed roof shell.
- Debounced Live Update for per-edge pitch and thickness changes.
- Keep the last valid roof mesh if a requested live rebuild fails.
- Stop automatic updating if the source object or generated roof object is renamed.
- Preserve source mesh coordinates and the source object's world transform.
- Store face attributes for roof component and source slope index.

The angle fields are numbered in the deterministic contour traversal order. There is not yet an in-viewport edge highlight or roof-top preview diagram.

## Geometry paths and limitations

### Flat-height eaves

When every boundary vertex has the same Z height, RoofForge uses the Python weighted wavefront solver. It supports per-edge pitch and has passing CI fixtures for:
- convex and concave radial contours through 64 edges;
- concave L/U contours with wavy boundaries and individual pitches;
- selected multi-notch and same-time split/collapse fixtures remain experimental and are not guaranteed;
- selected simultaneous split/collapse and needle events.

This is a tested family of cases, not a proof for every possible simple polygon. Some multi-notch simultaneous-event combinations remain a known alpha limitation and are deliberately excluded from the passing corpus. Unsupported event configurations are rejected with an error; the previous generated roof is kept during live update.

### Mixed-height 3D eaves

If boundary vertices have different Z heights, RoofForge keeps the original XYZ coordinates and uses the existing 3D support-plane envelope solver. It does not flatten the boundary. That path is useful for supported 3D contours, but concave mixed-height contours are not yet a general guaranteed case and may be rejected by plane-continuity or coverage validation.

### Other current limits

- Exactly one simple closed boundary loop is supported. Multiple disconnected loops and holes are not.
- Self-intersecting, degenerate or unsupported contours are rejected rather than silently repaired.
- 64 edges is the enforced maximum for this alpha; larger boundaries are rejected with an actionable diagnostic.
- Non-uniform object scale can change world-space pitch. Apply object scale for predictable world-space results.
- No optional overhang/eaves generation, ridge/valley/hip profiles, standing seams, UVs, LOD or export automation.

## Installation and test build

Download the **outer** `roof_forge-0.2.0-alpha.2-blender-5.0.1.zip` artifact from the latest successful **RoofForge tests** workflow, extract it once, then install the inner `roof_forge-0.2.0-alpha.2.zip` using Preferences → Get Extensions → Install from Disk. Do not extract the inner extension ZIP.

Russian installation and QA steps are included in `INSTALL_TEST_RU.md` inside the extension package. Remove the previous RoofForge alpha before installing this one so that Blender does not load two versions.

## Development tests

From the repository root:

```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
python tests/benchmark_geometry.py --repeats 3
```

Blender 5.0.1 background smoke also checks object-boundary acquisition, per-edge pitch on a concave L contour, closed shell creation and a debounced live rebuild. Manual viewport QA is still required.

## License

GPL-3.0-or-later.
