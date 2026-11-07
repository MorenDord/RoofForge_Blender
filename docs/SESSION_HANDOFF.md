# RoofForge 0.2.0-alpha.4 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Validated 0.1.0 baseline:** `develop` at `78f51d34f6a6c79cfa7b5b266b7d872908287b55`  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Installable code/package snapshot:** `a2b85ad189f019a1310ad46a6bfe69f94ef17361`.  
**PR:** [#6 — WIP RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6) (open, draft; wait for user QA before merge).  
**Installable build:** `roof_forge-0.2.0-alpha.4.zip`, from CI artifact `roof_forge-0.2.0-alpha.4-blender-5.0.1` (artifact ID `13553300364`).  
**Outer artifact:** [download from GitHub Actions](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42321985435/artifacts/13552943327).  
**Inner ZIP SHA-256:** `185186234319dc31dfc03c592ba3d40aded78ed5ed47d55d7f456f1d1270aa57`.  
**Latest CI:** [Push run 42321985435](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42321985435) and [PR run 42321992476](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42321992476) both passed.  
**Important:** `main` and `develop` have not been modified. Continue only on the feature branch.

## User-confirmed 0.2.0 scope

- One simple closed boundary loop, convex or concave, with up to 64 edges.
- Active mesh object only; no vertex/edge selection required.
- One independent pitch angle per boundary edge.
- Debounced live rebuild on pitch/thickness/overhang change; retain the last valid generated roof on failure. Thickness-only rebuilds reuse the cached roof surface.
- Preserve source XYZ; do not silently flatten mixed-height contours.
- Provide Eave Overhang in scene units: nonzero is supported for convex contours; concave L/U reflex corners require zero overhang.
- Keep a compact simple per-edge UI; no need for a pitch-map preview yet.

## What is now packaged in 0.2.0-alpha.4

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

## Overhang and delete/recreate additions in alpha.3

- `eave_overhang` is a horizontal distance in scene units. `core/overhang.py` extends each convex boundary facet on its authored support plane and adds convex corner join triangles; strict coverage and shell-manifold checks remain enabled.
- If the generated object has been deleted, Create / Update clears the stale pointer/name snapshot, creates a replacement in the active scene root collection, and confirms it is present in `bpy.data.objects` and `scene.objects`.
- Blender smoke explicitly deletes and re-creates the L roof from its unchanged source contour.
- Thickness-only Live Update uses the validated surface cache and rebuilds only the closed shell. `mesh.attributes` face values use bulk `foreach_set`.

## Live Update delay slider

- `live_update_delay_ms` is an integer slider from 0 to 1000 ms with 10 ms step; default 0.
- `live_update_delay_seconds(settings)` converts the setting and `schedule_live_update()` passes it as Blender timer `first_interval`.
- Zero means no intentional debounce: callback is scheduled on the next Blender timer tick, not synchronously inside the property callback. Geometry still runs on the main thread, so solver runtime remains measurable.

## Explicit alpha limitations

- This is not a claim that every possible simple polygon is already supported.
- Some 12-edge multi-notch and same-time split/collapse combinations still fail. Two dedicated tests are intentionally marked as skipped with explicit reasons; do not remove those skips unless the event resolver is fixed and the tests pass.
- Flat-height concave L/U and selected wavy L/U cases pass; arbitrary adversarial simultaneous event groups are not guaranteed.
- Mixed-height concave L/U is not a guaranteed path. The old 3D support-plane solver is retained for mixed-Z cases and may reject some contours.
- Exactly one simple boundary loop is supported; holes and multiple disconnected loops are not.
- 64 edges is the enforced maximum for this alpha. No 128-edge optimisation target.

## CI evidence for the packaged commit

Both complete workflows on head `a2b85ad189f019a1310ad46a6bfe69f94ef17361` passed:
- Python 3.11 and 3.13: 70 tests run, 2 known multi-notch limitations skipped.
- Blender 5.0.1 background smoke: registration, wire/surface boundary extraction in Object/Edit Mode with all elements deselected, concave L/U with per-edge pitch, shared miter corners with no fan faces, incompatible pitch diagnostic, configurable 0/230 ms delay, thickness-only cache, pitch rebuild, source immutability and delete/recreate.
- Clean Extension ZIP built by `tools/build_extension.py`.
- Official `blender --command extension validate` accepted the package.
- Geometry benchmark, Rust diagnostic benchmark, legacy spatial benchmark and 64-edge profile jobs passed.

This is background CI evidence. User's visual viewport QA is still required.

## User QA priority

1. Check that each overhang corner has one shared miter point, with no triangular fan or duplicate spokes.
2. Try a roof with unequal pitches on adjacent boundary edges and nonzero overhang; the add-on must explain a support-plane height discontinuity instead of emitting broken geometry.
3. Set Update delay to 0 ms and compare with 200–300 ms. Zero removes debounce; geometry calculation remains main-thread work.

After installing the ZIP, please also check:
4. A convex quadrilateral with random XYZ heights (the existing 3D route).
5. A flat-Z concave L and U with different pitch values on adjacent slopes.
6. Edit a pitch after roof creation; ensure the same roof object updates and no duplicate appears.
7. Change Thickness; ensure it updates.
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
- [Latest push CI](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42320863070)
- [Latest PR CI / installable artifact](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42320868809)
- [Implementation plan](https://github.com/MorenDord/RoofForge_Blender/blob/feature/0.2.0-arbitrary-contours-live-pitch/docs/PLAN_0.2.0_RU.md)

## Local checks
```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
blender --background --factory-startup --python tests/blender_smoke.py
python tools/build_extension.py --output-dir dist
blender --command extension validate dist/roof_forge-0.2.0-alpha.4.zip
```
