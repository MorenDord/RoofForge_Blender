# RoofForge

Procedural roof generation for Blender 5.0+, aimed at environment artists and game-ready asset workflows.

> **Current test build: 0.3.22.** This is an early user-test build, not a finished 1.0 release. With an overhang, the original contour remains the underside/support line while the same edge planes continue beyond it. Per-slope Pitch arrows snap a slope to an exact shared vertex formed by neighbouring roof planes. The roof plan is now vector-only and redraws directly in the N-panel.

## Project documents

- Technical specification: `docs/SPECIFICATION.md`
- Architecture: `docs/ARCHITECTURE.md`
- Development roadmap: `docs/ROADMAP.md`
- 0.2.0 plan: `docs/PLAN_0.2.0_RU.md`
- Session handoff / restart instructions: `docs/SESSION_HANDOFF.md`

## 0.2.0 alpha features

- Select a mesh object; no vertex or edge selection is needed.
- Automatically read one closed outer boundary from a wire contour or the boundary of a surface mesh.
- Show a top-view numbered roof-facet plan generated from actual roof geometry. Each number maps directly to the corresponding per-edge Pitch field. The GPU preview uses antialiased polylines, contrast-aware line/text colours and area-weighted label anchors; coplanar seams are omitted.
- Generate and update a separate closed roof shell.
- Debounced Live Update for per-edge pitch, thickness and overhang changes. The vector plan geometry is cached from the latest successful roof build and redrawn directly by Blender's GPU handler.
- Cache validated roof surfaces so thickness-only edits skip the wavefront / plane-envelope rebuild.
- **Source-anchored eaves:** convex contours continue to use the original 3D support-plane envelope. Concave flat-eave L/U contours now use the weighted wavefront roof plus one exact coplanar overhang strip per source edge. With **Converge corners** enabled (required for concave contours), adjacent strips meet at one shared outer corner while each strip remains on its source slope plane. The source eave line remains fixed.
- The shell thickness is added upward from the support surface when overhang is enabled. The lower/underside surface therefore remains on the original contour while the roof extends outward beyond it.
- Coplanar and practically coplanar internal edges are dissolved from the generated Blender mesh (up to 0.05° and 10 ppm of mesh span), including degree-two vertices and loose points left by loop-cut partitions. The pass repeats until no new planar neighbours remain. Planar patches collapse to clean N-gons; straight shell walls become larger quads/N-gons. Clear ridges, valleys, silhouette corners and the outer boundary remain.
- Per-slope Pitch arrows find vertices formed by the other roof planes, solve the exact target angle, then verify a shared vertex in the rebuilt roof before changing the field.
- Length controls are displayed in centimeters; default shell thickness is 1 cm. Before the first roof build, **Initial Pitch** sets the value copied to every contour edge (default 30°); individual Pitch values can then be edited independently.
- The first **Create / Update Roof** click reads the active contour and automatically creates the Pitch fields. No separate Load / Refresh Slope Angles action is required.
- If the generated roof is deleted, Create / Update can recreate it from the stored source. Edit the source contour in Edit Mode, return to Object Mode and press Create / Update to rebuild from the edited boundary.
- No separate Validate Roof or Default Pitch field; invalid geometry is diagnosed during Create / Update.
- Configurable Live Update debounce from 0 to 1000 ms, default 0 ms (geometry still executes on Blender's main thread).
- Keep the last valid roof mesh if a requested live rebuild fails.
- Stop automatic updating if the source object or generated roof object is renamed.
- Preserve source mesh coordinates and the source object's world transform.
- Store face attributes for roof component and source slope index.
- Validate the closed shell for geometric self-intersections between non-adjacent face triangles, in addition to edge/vertex manifold topology. Intersecting results are rejected before Blender mesh creation.

The top-view plan is created from the saved generated roof faces and source-slope metadata. RoofForge is vector-only: the PNG renderer, raster toggle, preview-icon cache and refresh timer are removed. Blender's `POLYLINE_UNIFORM_COLOR` shader draws antialiased edges in a collapsible **Roof Plan** section nested inside the main **RoofForge** N-panel panel. Its transparent `template_icon` slot reserves a square in Blender's normal UI flow, pushing the subsequent Pitch and settings controls down. The GPU output is clipped to that slot with a scissor rectangle, so it cannot paint over Pitch fields or the neighbouring editor. The slot dimensions now follow Blender's actual `UI_UNIT_X/Y * icon_scale` rule (estimated from the exposed UI scale), and its position follows the exact midpoint of a CENTER-aligned UI row, shared by the placeholder and GPU overlay. The bounding box is fitted with a 7.5% margin. The draw-handler is active only while the nested section is expanded and visible. Facet numbers use an area-weighted centroid across all faces belonging to a slope, with a pole-of-inaccessibility fallback for strongly concave regions. Number size and line thickness remain adjustable.

## Geometry paths and limitations

### Flat-height eaves

When every boundary vertex has the same Z height, RoofForge uses the Python weighted wavefront solver. It supports per-edge pitch and has passing CI fixtures for:
- convex and concave radial contours through 64 edges;
- concave L/U contours with selected individual-pitch profiles;
- selected multi-notch and same-time split/collapse fixtures remain experimental and are not guaranteed.

This is a tested family of cases, not a proof for every possible simple polygon. Some multi-notch simultaneous-event combinations remain a known alpha limitation and are deliberately excluded from the passing corpus. Unsupported event configurations are rejected with an error; the previous generated roof is kept during live update.

### Mixed-height 3D eaves

If boundary vertices have different Z heights, RoofForge keeps the original XYZ eave coordinates and uses the 3D support-plane envelope solver for convex footprints. Mixed-height concave footprints are disabled in 0.3.16: the generator stops before surface construction and shows a warning. Flat-height concave L/U footprints remain supported through the weighted-wavefront path.

### Other current limits

- Exactly one simple closed boundary loop is supported. Multiple disconnected loops and holes are not.
- Self-intersecting, degenerate or unsupported contours are rejected rather than silently repaired.
- 64 edges is the enforced maximum for this alpha; larger boundaries are rejected with an actionable diagnostic.
- Length inputs are centimeters and convert through the scene's `scale_length`. Apply object scale for physically consistent centimeter distances and thickness in world space.
- Nonzero overhang is supported for convex contours, including mixed-height XYZ fixtures. Positive overhang is also supported on the tested flat-eave concave L/U wavefront cases when **Converge corners** is enabled. Mixed-height concave footprints are not supported and are rejected with a warning, regardless of overhang. Offsets that close a notch or self-intersect, and unsupported weighted-wavefront event combinations remain rejected.
- Ridge/valley/hip profiles, standing seams, UVs, LOD and export automation are not included.

## RoofForge 0.3.22

- Pitch snapping no longer builds a deliberately incomplete roof with one source slope suppressed. It solves triple intersections of the remaining finite support planes analytically, then checks the candidate by rebuilding the complete production roof.
- Candidate vertices must lie inside the contour, be supported by their three finite source edges, and belong to the lower envelope of the other slopes. This avoids treating extensions of distant support planes as valid snap targets.
- The preview placeholder is a real, center-aligned `template_icon` square. Blender's own UI layout centers that anchor in the active tab body; the GPU canvas uses the same center and slot size.
- Category-tab width now uses the horizontal View2D zoom, not the vertical zoom. Blender smoke tests cover different horizontal and vertical scale factors and a real pitch-to-vertex snap.

## RoofForge 0.3.21

- The left/right Pitch controls solve the exact angle at which the selected slope plane passes through a fixed vertex formed by the other roof slopes.
- The candidate is accepted only after a full roof build confirms that the selected and neighbouring slopes share the same 3D vertex.
- Each arrow searches only in its own pitch direction; no-match and geometry errors are reported in the panel instead of silently doing nothing.

## RoofForge 0.3.17

- The vector-preview placeholder no longer uses `template_icon` or nested-layout horizontal alignment. A full-width spacer reserves its vertical space only.
- The GPU preview is centered directly at `region.width / 2`, the midpoint of the complete N-panel UI region. Debug UI bounds draws a green center axis and reports the region and canvas centers independently.
- Blender smoke checks assert that no `template_icon` remains in the panel draw code and that the GPU canvas center equals the N-panel midpoint at multiple widths.

## RoofForge 0.3.16

- Mixed-height concave XY contours are disabled in the production build and report a warning before the roof builder runs. Flat-eave concave contours and convex mixed-height contours remain available.
- The experimental concave plane-envelope module remains in the repository for isolated research/tests but is excluded from the installable extension ZIP.
- The vector preview uses a center-aligned placeholder row and centers its GPU canvas on that row at every N-panel width.
- Coplanar cleanup uses one bounded tolerance for exact and approximate surfaces: 0.05° dihedral and 10 ppm of the mesh span. Regressions cover a 0.04° seam and preserve 0.08° / 5° ridges.

## Installation and test build

Download the **outer** `roof_forge-0.3.22-blender-5.0.1.zip` artifact from the latest successful **RoofForge tests** workflow on the feature branch, extract it once, then install the inner `roof_forge-0.3.22.zip` using Preferences → Get Extensions → Install from Disk. Do not extract the inner extension ZIP.

Russian installation and QA steps are included in `INSTALL_TEST_RU.md` inside the extension package. Remove the previous RoofForge alpha before installing this one so that Blender does not load two versions.

## Development tests

From the repository root:

```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
python tests/benchmark_geometry.py --repeats 3
```

Blender 5.0.1 background smoke checks corner-converged convex eaves, positive L/U concave overhang, source-edge support alignment, vector-plan edge extraction and stable label anchors, configurable initial pitch, one-click generation, delete/recreate from a stored source, rebuild after editing the source contour, and a real pitch-to-neighbouring-vertex snap that is verified in the generated roof. Manual viewport QA is still required.

## License

GPL-3.0-or-later.


### Clean planar topology (0.3.10)

The final Blender mesh pass now dissolves both coplanar shared edges and the degree-two vertices left between two remaining edges. Any vertices that become completely isolated by that operation are removed. This eliminates redundant loop-cut segments on otherwise planar roof patches and straight eave walls while retaining edges where face planes, ridges, valleys or the silhouette genuinely change. A subdivided-prism regression must reduce to exactly 8 vertices, 12 edges and 6 quads; generated roof smoke checks reject loose or degree-two vertices.


### Near-coplanar topology cleanup (0.3.11)

The 0.3.10 exact-coplanar pass could leave narrow seams when independently solved roof facets differed by tiny numeric or angular errors. The final BMesh pass now repeats until no new eligible neighbours remain and accepts only seams within a 0.05° dihedral / 10 ppm distance window. A new Blender regression checks that a 0.04° narrow sliver disappears while a 5° ridge is preserved. This tolerance is intended for practically flat sliver facets, not as a general ridge simplifier.


### Mixed-height concave contours (0.3.12)

The 3D support-plane arrangement is still attempted first. If the exact planar arrangement fails its internal-edge / perimeter continuity check, RoofForge retries the mixed-height concave contour with the continuous finite-segment field already used as a geometry prototype. Each source edge uses its authored plane while the perpendicular foot lies on that finite edge; near endpoints, a radial transition function makes the field continuous. Those transition zones are adaptively triangulated to a height error of 0.1% of the mesh span (maximum depth 4), while edge-interior patches remain exact planar facets. The shell and boundary validators still run on the fallback result. This trades exact planar facets near reflex vertices for a valid continuous surface; it does not enable positive overhang on mixed-height concave contours.
