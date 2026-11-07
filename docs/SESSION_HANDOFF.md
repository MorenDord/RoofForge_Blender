# RoofForge 0.2.0-alpha.7 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Validated 0.1.0 baseline:** develop at `78f51d34f6a6c79cfa7b5b266b7d872908287b55`  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Code commit:** `a56035369a8159e08de6e46819783b4476f7015d`  
**Versioned package commit:** `7730ac1b7b4caff1776c58a534cee04f40f34298`  
**PR:** [#6 — WIP RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6), open and draft.  
**Installable build:** `roof_forge-0.2.0-alpha.7.zip`, from CI artifact `roof_forge-0.2.0-alpha.7-blender-5.0.1` (artifact ID `13573556398`).  
**Outer artifact:** [download from GitHub Actions](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42370549428/artifacts/13573556398).  
**Inner ZIP SHA-256:** `38f625e999d41d0d5453b66fa93f3eb811adcfd20bd4d14ca2265b364cc77db4`.  
**Important:** `main` and `develop` are unchanged. Continue only on the feature branch.

## User-confirmed 0.2.0 scope

- One simple closed boundary loop, convex or concave, up to 64 edges.
- Active mesh object only; no vertex/edge selection required.
- One independent pitch angle per boundary edge.
- Live rebuild on pitch/thickness/overhang change with 0–1000 ms delay (default 0); retain the last valid roof on failure.
- Preserve source XYZ; do not flatten mixed-height contours.
- Eave Overhang in centimeters.
- New alpha.7 eaves are created by offsetting the source contour as one polygon and rebuilding the complete roof from this new contour. This replaces the old strip-extension/stitching algorithm.
- Compact per-edge UI; no pitch-map preview yet.

## Core change in alpha.7: one offset contour, then rebuild

Previous alpha versions first built the original roof and then tried to attach separate overhang strips around it. This created complex corner topology and still allowed protruding ends.

The alpha.7 approach is different:

1. Validate the original simple XY boundary.
2. Translate each directed source edge outward by the requested horizontal distance, preserving its direction.
3. At each source corner, intersect the previous and current translated edge lines. This produces one miter-offset vertex for the whole contour.
4. Preserve the corresponding source vertex Z at each new offset vertex.
5. Preserve vertex count/order, so pitch[i] still belongs to new edge i.
6. Run the normal roof solver from scratch on this offset 3D contour.
7. Validate the resulting single upper surface and closed thickness shell.

There is no extension of existing roof faces, no per-edge strip assembly, no corner fan, no miter cap and no post-build ridge stitching. The eaves are simply the boundary edges of the newly generated roof.

Offset invariants tested in Python:
- every new edge is parallel to its source edge;
- signed perpendicular distance is exactly the requested overhang;
- the new polygon has the same number and order of vertices;
- corresponding Z values remain unchanged;
- winding is preserved, area grows, and self-intersections/collapsed offsets are rejected.

For reflex corners the same adjacent-line intersection formula is used. This moves the inner notch offset into the notch; if the new contour self-intersects, the input is rejected before the roof solver runs.

## Solver routing and current limitations

- Flat-height boundaries use `build_wavefront_roof_surface()`, the custom Python weighted wavefront with per-edge pitch.
- Mixed-height boundaries preserve the Z values at corresponding offset vertices and use the current 3D support-plane envelope solver.
- Concave L/U flat-height contours and mixed-height convex contours are covered by smoke.
- Some weighted-wavefront simultaneous-event / multi-notch combinations remain known limitations. Arbitrary concave mixed-height XYZ is not guaranteed.
- One simple loop only; no holes or multiple loops.
- 64 edges maximum for 0.2.0. No 128-edge target.
- Offset miters longer than 50 times the requested offset, self-intersecting offsets and collapsed contours are rejected.

## Existing add-on behavior retained

- Automatic boundary detection from wire-only and face meshes, in Object/Edit Mode, with no mesh-element selection.
- Per-edge pitch list, new fields default 30°.
- Thickness default 1 cm; Thickness and Eave Overhang displayed in centimeters and converted through scene Unit Scale.
- Validate Roof and Default Pitch fields/operators removed.
- Live Update delay 0–1000 ms, default 0; last-valid mesh rollback; rename guard.
- Thickness-only update reuses cached upper surface and rebuilds shell only.
- Delete/recreate after deleting the generated roof is covered.
- Source object mesh and transform remain unchanged.
- Generated mesh has face attributes for roof component and source slope index.

## CI evidence for the versioned package commit

Push run [42370549428](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42370549428) and PR run [42370553763](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42370553763) passed on versioned package commit `7730ac1b7b4caff1776c58a534cee04f40f34298`:
- Python 3.11 and 3.13: all tests pass.
- Blender 5.0.1 background smoke: passes, including flat variable-pitch contour rebuild, concave L/U rebuild with overhang, mixed-height XYZ convex rebuild, oversized U offset rejection, cm/default/UI/live-update/cache/delete-recreate regressions.
- Clean extension ZIP built and accepted by official Blender 5.0.1 Extension Validator.
- Geometry benchmarks, legacy spatial benchmark, Rust diagnostic candidate and legacy solver profile pass.

The alpha.7 package was built by Blender 5.0.1 CI, accepted by the official Extension Validator, downloaded from GitHub Actions and checked locally against the included SHA-256 file.

## User viewport QA priority

1. Test a convex rectangle with strongly different Pitch values and a visible 25 cm eave. The entire eave must be one continuous outer contour, with no protruding pieces.
2. Test a convex contour with different source Z values. Confirm each offset vertex retains the corresponding source Z.
3. Test concave L and U contours with individual pitch values and 10–15 cm eave.
4. Check a narrow U notch with a large offset; it should produce a clear error instead of a self-intersecting roof.
5. Change pitch and thickness after creation; delete/recreate from the same original contour.
6. Check that the original contour object is unchanged.

## Repository instructions

- Continue on `feature/0.2.0-arbitrary-contours-live-pitch`.
- Keep PR #6 in draft; do not merge to develop or tag stable 0.2.0 yet.
- Preserve skipped tests for known wavefront limitations; don't delete them to get a green run.
- Update this handoff after new viewport feedback.
