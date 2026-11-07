# RoofForge

Procedural roof generation for Blender 5.0+, aimed at environment artists and game-ready asset workflows.

> **Current test build: 0.2.0-alpha.11.** This is an early user-test build, not a finished 1.0 release. With an overhang, the original contour remains the underside/support line while the same edge planes continue beyond it. The preview shows the actual roof facets with white antialiased lines and centered numbers on a transparent background.

## Project documents

- Technical specification: `docs/SPECIFICATION.md`
- Architecture: `docs/ARCHITECTURE.md`
- Development roadmap: `docs/ROADMAP.md`
- 0.2.0 plan: `docs/PLAN_0.2.0_RU.md`
- Session handoff / restart instructions: `docs/SESSION_HANDOFF.md`

## 0.2.0 alpha features

- Select a mesh object; no vertex or edge selection is needed.
- Automatically read one closed outer boundary from a wire contour or the boundary of a surface mesh.
- Show a top-view numbered roof-facet plan generated from actual roof geometry. Each number is centered inside its slope and maps directly to the corresponding per-edge Pitch field. White graphics use a transparent background; coplanar seams are omitted.
- Generate and update a separate closed roof shell.
- Debounced Live Update for per-edge pitch, thickness and overhang changes.
- Cache validated roof surfaces so thickness-only edits skip the wavefront / plane-envelope rebuild.
- **Source-anchored eaves:** the pitch planes are constructed through the original 3D source edges. The outward offset contour extends the XY build domain only; it does not move or re-anchor the support planes.
- The shell thickness is added upward from the support surface when overhang is enabled. The lower/underside surface therefore remains on the original contour while the roof extends outward beyond it.
- Coplanar internal edges are dissolved from the generated Blender mesh, while true ridges and the outer boundary remain.
- Length controls are displayed in centimeters; default shell thickness is 1 cm and newly prepared pitches default to 30°.
- No separate Validate Roof or Default Pitch field; invalid geometry is diagnosed during Create / Update.
- Configurable Live Update debounce from 0 to 1000 ms, default 0 ms (geometry still executes on Blender's main thread).
- Keep the last valid roof mesh if a requested live rebuild fails.
- Stop automatic updating if the source object or generated roof object is renamed.
- Preserve source mesh coordinates and the source object's world transform.
- Store face attributes for roof component and source slope index.

The top-view plan is created from the saved generated roof faces and source-slope metadata; it does not run the roof solver while the panel is drawing. Labels are placed in the largest visible facet of each slope and reduced to fit available clearance. Number size and line thickness are separate controls, and the square preview scales to the available sidebar width.

## Geometry paths and limitations

### Flat-height eaves

When every boundary vertex has the same Z height, RoofForge uses the Python weighted wavefront solver. It supports per-edge pitch and has passing CI fixtures for:
- convex and concave radial contours through 64 edges;
- concave L/U contours with selected individual-pitch profiles;
- selected multi-notch and same-time split/collapse fixtures remain experimental and are not guaranteed.

This is a tested family of cases, not a proof for every possible simple polygon. Some multi-notch simultaneous-event combinations remain a known alpha limitation and are deliberately excluded from the passing corpus. Unsupported event configurations are rejected with an error; the previous generated roof is kept during live update.

### Mixed-height 3D eaves

If boundary vertices have different Z heights, RoofForge keeps the original relative XYZ contour elevations and uses the existing 3D support-plane envelope solver. The offset contour preserves the Z value of each corresponding source vertex. The roof is then recalculated from that new XYZ boundary. This path is covered by convex mixed-height fixtures; concave mixed-height contours are not yet a general guaranteed case and may be rejected by plane-continuity or coverage validation.

### Other current limits

- Exactly one simple closed boundary loop is supported. Multiple disconnected loops and holes are not.
- Self-intersecting, degenerate or unsupported contours are rejected rather than silently repaired.
- 64 edges is the enforced maximum for this alpha; larger boundaries are rejected with an actionable diagnostic.
- Length inputs are centimeters and convert through the scene's `scale_length`. Apply object scale for physically consistent centimeter distances and thickness in world space.
- Nonzero overhang is covered for convex contours and tested concave L/U contours with individual edge pitches. Mixed-height convex XYZ contours are also covered. Arbitrary multi-notch event combinations and arbitrary concave mixed-height XYZ are not yet guaranteed.
- Ridge/valley/hip profiles, standing seams, UVs, LOD and export automation are not included.

## Installation and test build

Download the **outer** `roof_forge-0.2.0-alpha.11-blender-5.0.1.zip` artifact from the latest successful **RoofForge tests** workflow, extract it once, then install the inner `roof_forge-0.2.0-alpha.11.zip` using Preferences → Get Extensions → Install from Disk. Do not extract the inner extension ZIP.

Russian installation and QA steps are included in `INSTALL_TEST_RU.md` inside the extension package. Remove the previous RoofForge alpha before installing this one so that Blender does not load two versions.

## Development tests

From the repository root:

```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
python tests/benchmark_geometry.py --repeats 3
```

Blender 5.0.1 background smoke checks offset-contour rebuilds for flat variable-pitch convex eaves, concave L/U eaves with nonzero overhang, mixed-height XYZ convex eaves, invalid oversized offsets, centimeter conversion, 30° pitch and 1 cm thickness defaults, the simplified UI, numbered contour-plan preview and edge-to-Pitch mapping, thickness-only cache and delete/recreate. Manual viewport QA is still required.

## License

GPL-3.0-or-later.
