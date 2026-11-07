# RoofForge 0.2.0-alpha.6 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Validated 0.1.0 baseline:** `develop` at `78f51d34f6a6c79cfa7b5b266b7d872908287b55`  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Installable code/package snapshot:** `0a45005bcd8196728b39dd433fff94d36d8939a0` (code/package); docs updated in following commit.  
**PR:** [#6 — WIP RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6) (open, draft; wait for user QA before merge).  
**Installable build:** `roof_forge-0.2.0-alpha.6.zip`, from CI artifact `roof_forge-0.2.0-alpha.6-blender-5.0.1` (artifact ID `13558559927`).  
**Outer artifact:** [download from GitHub Actions](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42335026739/artifacts/13558559927).  
**Inner ZIP SHA-256:** `6fbf08dff5853ff9b6a56a57b729aae01e2a8265b5e074b6e7c7e60f2eebd14a`.  
**Latest CI:** [Push run 42335026739](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42335026739) and [PR run 42335029848](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42335029848) both passed.  
**Important:** `main` and `develop` have not been modified. Continue only on the feature branch.

## User-confirmed 0.2.0 scope

- One simple closed boundary loop, convex or concave, with up to 64 edges.
- Active mesh object only; no vertex/edge selection required.
- One independent pitch angle per boundary edge.
- Live rebuild on pitch/thickness/overhang change with a 0–1000 ms delay slider (default 0); retain the last valid generated roof on failure. Thickness-only rebuilds reuse the cached roof surface.
- Preserve source XYZ; do not silently flatten mixed-height contours.
- Provide Eave Overhang in centimeters. Each edge strip stays on its source support plane; adjacent strips are welded along the exact shared 3D ridge, with a single remaining outer ridge connector. Tested convex and concave L/U contours support individual pitch; mixed-Z convex contours are also covered. Self-intersecting or collapsed offsets are rejected.
- Keep a compact simple per-edge UI; no need for a pitch-map preview yet.

## What is now packaged in 0.2.0-alpha.6

### Automatic boundary detection
- Detects one outer loop from a wire-only mesh or a face mesh with one boundary loop.
- Works in Object Mode and Edit Mode without selected vertices/edges.
- Deterministically orders the boundary; one field is created for each edge.
- Source mesh and transform remain unchanged.

### Per-edge pitch UI
- `Load / Refresh Slope Angles` creates one numeric field per boundary edge.
- Fields are labelled with deterministic contour order and vertex pair, e.g. `Edge 01 (V1→V2)`.
- Changing one pitch schedules a debounced rebuild.
- There is no in-viewport edge highlight or top-view pitch diagram yet.

### Solver routing
- If all boundary vertices have the same Z (flat-height eaves), the generator uses `build_wavefront_roof_surface()`: the custom Python weighted wavefront with per-edge pitch.
- If vertices have different Z, the generator preserves XYZ and uses the existing 3D support-plane envelope path. This path is not a guarantee for arbitrary concave mixed-height contours and rejects incompatible geometry.
- Generated result is a separate closed shell with face attributes `roof_forge_component` and `roof_forge_slope_index`.

### Live Update
- Per-edge pitch, thickness and overhang callbacks schedule a timer with user-selected 0–1000 ms debounce; default is 0 ms.
- Mesh calculation and validation occur on Blender's main thread after the timer delay. The 0 ms setting removes intentional debounce but cannot remove the geometry solver's own execution time. The surface LRU cache key is source object pointer + XYZ points + pitches + overhang; thickness is excluded.
- New mesh data is built separately; only after successful validation is it swapped into the generated object.
- On error, the last valid roof mesh remains unchanged and status is shown in the panel.
- Renaming the source object or generated roof object stops automatic updates. The already generated geometry remains in the scene.
- If topology edge count changes, the user must use `Load / Refresh Slope Angles` and verify the mapping.

## Overhang and delete/recreate additions in alpha.6

- `eave_overhang_cm` and `thickness_cm` are entered as centimeters. `centimeters_to_blender_units()` converts them using the active scene's `unit_settings.scale_length`; apply source object scale for physically consistent world-space dimensions.
- `core/overhang.py` creates one extension strip per ordered source boundary edge. Every strip vertex remains on that edge's authored support plane.
- At each corner the neighbouring strips calculate their endpoints on the actual 3D intersection ridge of the two support planes. Their overlapping ridge segment is welded by splitting the longer strip-side edge at the shorter endpoint. The remaining ridge segment is the single external corner connector. This is the fix for the protruding custom-pitch eaves in the user's screenshot.
- There are no independent miter tails, fan spokes, or vertical zero-width caps. The combined top boundary is checked for self-intersection, exact edge coverage and closed-shell manifold validity.
- Reflex/concave turns are accepted while the resulting offset boundary remains simple. L/U with individual pitches and nonzero overhang are covered by Python and Blender smoke tests. Offsets that collapse/self-intersect are rejected.
- If the generated object has been deleted, Create / Update clears the stale pointer/name snapshot, creates a replacement in the active scene root collection, and confirms it is present in `bpy.data.objects` and `scene.objects`.
- Blender smoke explicitly deletes and re-creates the L roof from its unchanged source contour.
- Thickness-only Live Update uses the validated surface cache and rebuilds only the closed shell. `mesh.attributes` face values use bulk `foreach_set`.

## Live Update delay slider

- `live_update_delay_ms` is an integer slider from 0 to 1000 ms with 10 ms step; default 0.
- `live_update_delay_seconds(settings)` converts the setting and `schedule_live_update()` passes it as Blender timer `first_interval`.
- Zero means no intentional debounce: callback is scheduled on the next Blender timer tick, not synchronously inside the property callback. Geometry still runs on the main thread, so solver runtime remains measurable.

## UI simplification and defaults

- Removed the separate Validate Roof operator from registration and the panel. Create / Update performs validation before replacing/creating the mesh.
- Removed the Default Pitch field. New per-edge pitch entries default to 30 degrees.
- Default shell thickness is 1 cm. Thickness and overhang inputs are explicitly labelled in centimeters.

## Explicit alpha limitations

- This is not a claim that every possible simple polygon is already supported.
- Some 12-edge multi-notch and same-time split/collapse combinations still fail. Two dedicated tests are intentionally marked as skipped with explicit reasons; do not remove those skips unless the event resolver is fixed and the tests pass.
- Flat-height concave L/U and selected wavy L/U cases pass; arbitrary adversarial simultaneous event groups are not guaranteed.
- Mixed-height concave L/U is not a guaranteed path. The old 3D support-plane solver is retained for mixed-Z cases and may reject some contours.
- Exactly one simple boundary loop is supported; holes and multiple disconnected loops are not.
- 64 edges is the enforced maximum for this alpha. No 128-edge optimisation target.

## CI evidence for the packaged commit

Both complete workflows on code/package commit `0a45005bcd8196728b39dd433fff94d36d8939a0` passed:
- Python 3.11 and 3.13 CI: passed.
- Blender 5.0.1 background smoke: passed.
- Clean Extension ZIP and official Extension Validator: passed.
- Geometry benchmark, Rust diagnostics, legacy spatial benchmark and 64-edge profile: passed.

This is background CI evidence. User's visual viewport QA is still required.

## User QA priority

1. Check a flat-Z convex contour with custom pitch on every edge. No strip should protrude beyond its neighbouring ridge connector.
2. Check the same with a mixed-Z convex contour.
3. Check L/U contours with individual pitches and nonzero eaves. Moderate offsets should remain continuous; a too-large offset that collapses the notch should fail cleanly and preserve the last valid roof.
4. Set Update delay to 0 ms and compare with 200–300 ms. Zero removes intentional debounce; geometry still runs on Blender's main thread.
5. Delete and re-create a roof from the same source, then change pitch and thickness; ensure the same result object updates.
8. Rename the source object, then a generated roof object; ensure Live Update stops and the mesh is preserved.
9. Try a 12-edge multi-notch contour as an intentional stress case. Failure is currently a known alpha limitation; capture the exact error and .blend rather than repairing it manually.

For each issue, record Blender version, OS, contour points/edge count, per-edge pitch, error text and a screenshot. A small .blend with the original contour is very useful.

## Repository instructions

- Continue on `feature/0.2.0-arbitrary-contours-live-pitch`.
- Keep PR #6 draft until user feedback is incorporated and known event limitations are addressed.
- Do not merge to `develop` or tag a stable 0.2.0 release yet.
- Keep tests for known failures visible as skipped/expected failures with a reason; do not delete them to get a green run.
- Keep source mesh immutable and rebuild transactionally.
- Update this handoff after the next development session.

## Useful files
- `addon/roof_build.py` — solver routing, pitch mapping, mesh serialization.
- `addon/live_update.py` — debounce, rename guard, rollback-safe mesh swap.
- `addon/properties.py` — persistent slope fields and callbacks.
- `addon/operators/generate.py` — Create / Update Roof.
- `addon/operators/prepare.py` — prepare per-edge angles.
- `addon/adapters/mesh_io.py` — automatic boundary detection.
- `core/wavefront.py` — flat-height weighted geometry solver.
- `tests/blender_smoke.py` — Blender 5 alpha smoke.
- `tests/test_wavefront_corpus.py` — multi-notch known-failure cases.

## Important links
- [PR #6](https://github.com/MorenDord/RoofForge_Blender/pull/6)
- [Latest push CI](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42335026739)
- [Latest PR CI / installable artifact](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42335029848)
- [Implementation plan](https://github.com/MorenDord/RoofForge_Blender/blob/feature/0.2.0-arbitrary-contours-live-pitch/docs/PLAN_0.2.0_RU.md)

## Local checks
```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
blender --background --factory-startup --python tests/blender_smoke.py
python tools/build_extension.py --output-dir dist
blender --command extension validate dist/roof_forge-0.2.0-alpha.6.zip
```
