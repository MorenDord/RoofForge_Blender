# RoofForge

Procedural roof generation for Blender 5.0+, aimed at environment artists and game-ready asset workflows.

> **Current test build: 0.2.5.** This is an early user-test build, not a finished 1.0 release. With an overhang, the original contour remains the underside/support line while the same edge planes continue beyond it. Adjacent pitches can be made to meet at one shared outer corner point. The facet preview is cached and refreshed only after edits settle.

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
- Debounced Live Update for per-edge pitch, thickness and overhang changes. The roof-plan image is not regenerated during these changes; it refreshes once after the last successful geometry update.
- Cache validated roof surfaces so thickness-only edits skip the wavefront / plane-envelope rebuild.
- **Source-anchored eaves:** for convex contours, the pitch planes are constructed through the original 3D source edges. The outward domain uses one outer corner per source vertex. With **Converge corners** enabled (default), each outer corner lies on both adjacent pitch planes, so slopes meet at one point; extension length may vary around the perimeter. Disable it to use the previous uniform miter offset. Concave contours still generate normally with zero overhang; nonzero overhang is rejected for concave contours.
- The shell thickness is added upward from the support surface when overhang is enabled. The lower/underside surface therefore remains on the original contour while the roof extends outward beyond it.
- Coplanar internal edges are dissolved from the generated Blender mesh, while true ridges and the outer boundary remain.
- Length controls are displayed in centimeters; default shell thickness is 1 cm and newly prepared pitches default to 30°.
- The first **Create / Update Roof** click reads the active contour and automatically creates the Pitch fields. No separate Load / Refresh Slope Angles action is required.
- If the generated roof is deleted, Create / Update can recreate it from the stored source. Edit the source contour in Edit Mode, return to Object Mode and press Create / Update to rebuild from the edited boundary.
- No separate Validate Roof or Default Pitch field; invalid geometry is diagnosed during Create / Update.
- Configurable Live Update debounce from 0 to 1000 ms, default 0 ms (geometry still executes on Blender's main thread).
- Keep the last valid roof mesh if a requested live rebuild fails.
- Stop automatic updating if the source object or generated roof object is renamed.
- Preserve source mesh coordinates and the source object's world transform.
- Store face attributes for roof component and source slope index.

The top-view plan is created from the saved generated roof faces and source-slope metadata. The Raster preview is a cached PNG refreshed by a deferred Blender timer; it remains unchanged during edits and refreshes once after the latest update settles. The experimental Vector preview is drawn directly with Blender GPU/BLF in a reserved area of the main **RoofForge** 3D Viewport N-panel tab (`UI` region), between the display controls and per-edge Pitch list. The drawing has a transparent background: only roof edges and facet numbers are painted, with no dark tile or GPU watermark. The preview heading is omitted to reduce clutter and preserve canvas alignment. It is not a separate add-on tab and does not draw over the 3D scene. In vector-only mode the PNG renderer is skipped entirely. While the N-panel is scrolled away from the top, the pinned GPU canvas is hidden to avoid covering controls. Number size and line thickness are shared by both renderers.

## Geometry paths and limitations

### Flat-height eaves

When every boundary vertex has the same Z height, RoofForge uses the Python weighted wavefront solver. It supports per-edge pitch and has passing CI fixtures for:
- convex and concave radial contours through 64 edges;
- concave L/U contours with selected individual-pitch profiles;
- selected multi-notch and same-time split/collapse fixtures remain experimental and are not guaranteed.

This is a tested family of cases, not a proof for every possible simple polygon. Some multi-notch simultaneous-event combinations remain a known alpha limitation and are deliberately excluded from the passing corpus. Unsupported event configurations are rejected with an error; the previous generated roof is kept during live update.

### Mixed-height 3D eaves

If boundary vertices have different Z heights, RoofForge keeps the original XYZ eave coordinates and uses the 3D support-plane envelope solver. With overhang, each source-edge plane still passes through its original endpoints; corner convergence computes a shared outer-corner point on the adjacent planes. Convex mixed-height fixtures are covered by CI. Concave mixed-height contours are not guaranteed and nonzero concave overhang is rejected.

### Other current limits

- Exactly one simple closed boundary loop is supported. Multiple disconnected loops and holes are not.
- Self-intersecting, degenerate or unsupported contours are rejected rather than silently repaired.
- 64 edges is the enforced maximum for this alpha; larger boundaries are rejected with an actionable diagnostic.
- Length inputs are centimeters and convert through the scene's `scale_length`. Apply object scale for physically consistent centimeter distances and thickness in world space.
- Nonzero overhang is supported for convex contours, including mixed-height XYZ fixtures. Concave L/U contours remain supported without overhang; positive overhang on concave contours is deliberately rejected until a reflex-corner transition solver is available.
- Ridge/valley/hip profiles, standing seams, UVs, LOD and export automation are not included.

## Installation and test build

Download the **outer** `roof_forge-0.2.5-blender-5.0.1.zip` artifact from the latest successful **RoofForge tests** workflow, extract it once, then install the inner `roof_forge-0.2.5.zip` using Preferences → Get Extensions → Install from Disk. Do not extract the inner extension ZIP.

Russian installation and QA steps are included in `INSTALL_TEST_RU.md` inside the extension package. Remove the previous RoofForge alpha before installing this one so that Blender does not load two versions.

## Development tests

From the repository root:

```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
python tests/benchmark_geometry.py --repeats 3
```

Blender 5.0.1 background smoke checks corner-converged convex eaves, equal boundary-vertex count, uniform-offset fallback, source-edge support alignment, concave no-overhang, deferred plan rendering, one-click generation, delete/recreate from a stored source and rebuild after editing the source contour. Manual viewport QA is still required.

## License

GPL-3.0-or-later.
