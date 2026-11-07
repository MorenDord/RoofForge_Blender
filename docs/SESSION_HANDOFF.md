# RoofForge 0.2.0-alpha.1 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Validated 0.1.0 baseline:** `develop` at `78f51d34f6a6c79cfa7b5b266b7d872908287b55`  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Installable code/package snapshot:** `1f677f7509f6f61c94b10370468691cadd001e2d` (latest commits after this snapshot are documentation/PR metadata only).  
**PR:** [#6 — WIP RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6) (open, draft; wait for user QA before merge).  
**Installable build:** `roof_forge-0.2.0-alpha.1.zip`, from CI artifact `roof_forge-0.2.0-alpha.1-blender-5.0.1` (artifact ID `13551363130`).  
**Outer artifact:** [download from GitHub Actions](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42317734486/artifacts/13551363130).  
**Inner ZIP SHA-256:** `3a068a9f25fc84bcb3835d8005ec02f0062b9e8c3a3746f6b51d33f5f6de9afb`.  
**Latest CI:** [Push run 42317727266](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42317727266) and [PR run 42317734486](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42317734486) both passed on the package snapshot.  
**Important:** `main` and `develop` have not been modified. Continue only on the feature branch.

## User-confirmed 0.2.0 scope

- One simple closed boundary loop, convex or concave, with up to 64 edges.
- Active mesh object only; no vertex/edge selection required.
- One independent pitch angle per boundary edge.
- Debounced live rebuild on pitch/thickness change; retain the last valid generated roof on failure.
- Preserve source XYZ; do not silently flatten mixed-height contours.
- Remove optional eaves/overhang controls and generation.
- Keep a compact simple per-edge UI; no need for a pitch-map preview yet.

## What is now packaged in 0.2.0-alpha.1

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
- Per-edge pitch and thickness callbacks schedule a timer with approximately 0.3 s debounce.
- Mesh calculation and validation occur on Blender's main thread after the debounce.
- New mesh data is built separately; only after successful validation is it swapped into the generated object.
- On error, the last valid roof mesh remains unchanged and status is shown in the panel.
- Renaming the source object or generated roof object stops automatic updates. The already generated geometry remains in the scene.
- If topology edge count changes, the user must use `Load / Refresh Slope Angles` and verify the mapping.

## Explicit alpha limitations

- This is not a claim that every possible simple polygon is already supported.
- Some 12-edge multi-notch and same-time split/collapse combinations still fail. Two dedicated tests are intentionally marked as skipped with explicit reasons; do not remove those skips unless the event resolver is fixed and the tests pass.
- Flat-height concave L/U and selected wavy L/U cases pass; arbitrary adversarial simultaneous event groups are not guaranteed.
- Mixed-height concave L/U is not a guaranteed path. The old 3D support-plane solver is retained for mixed-Z cases and may reject some contours.
- Exactly one simple boundary loop is supported; holes and multiple disconnected loops are not.
- 64 edges is the target maximum for this milestone. No 128-edge optimisation target.

## CI evidence for the packaged commit

Both complete workflows on head `1f677f...` passed:
- Python 3.11 and 3.13: 70 tests run, 2 known multi-notch limitations skipped.
- Blender 5.0.1 background smoke: registration, wire/surface boundary extraction in Object/Edit Mode with all elements deselected, concave L with six individual pitch values, closed shell, Live Update pitch rebuild, source immutability.
- Clean Extension ZIP built by `tools/build_extension.py`.
- Official `blender --command extension validate` accepted the package.
- Geometry benchmark, Rust diagnostic benchmark, legacy spatial benchmark and 64-edge profile jobs passed.

This is background CI evidence. User's visual viewport QA is still required.

## User QA priority

After installing the ZIP, please check:
1. A convex quadrilateral with random XYZ heights (the existing 3D route).
2. A flat-Z concave L and U with different pitch values on adjacent slopes.
3. Edit a pitch after roof creation; ensure the same roof object updates and no duplicate appears.
4. Change Thickness; ensure it updates.
5. Rename the source object, then a generated roof object; ensure Live Update stops and the mesh is preserved.
6. Try a 12-edge multi-notch contour as an intentional stress case. Failure is currently a known alpha limitation; capture the exact error and .blend rather than repairing it manually.

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
- [Latest push CI](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42317727266)
- [Latest PR CI / installable artifact](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42317734486)
- [Implementation plan](https://github.com/MorenDord/RoofForge_Blender/blob/feature/0.2.0-arbitrary-contours-live-pitch/docs/PLAN_0.2.0_RU.md)

## Local checks
```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
blender --background --factory-startup --python tests/blender_smoke.py
python tools/build_extension.py --output-dir dist
blender --command extension validate dist/roof_forge-0.2.0-alpha.1.zip
```
