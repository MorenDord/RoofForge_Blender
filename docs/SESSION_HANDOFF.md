# RoofForge 0.2.0-alpha.10 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Base UI reference:** `main` commit `63d7952e0ee9c7aa62b4ed4efe40716a7641a2e0`, manifest 2.9.2  
**PR:** [#6 — WIP RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6), open and draft.  
**Alpha.10 artifact / SHA-256:** pending versioned package CI.  
**Important:** `main` and `develop` must remain unchanged.

## User request

The user said editing Pitch values through Edit Mode was inconvenient and requested the UI from main branch RoofForge 2.9.2, plus an audit of other useful features.

## What was found in main 2.9.2

Main points at audit time:
- Branch main commit `63d7952e0ee9c7aa62b4ed4efe40716a7641a2e0`.
- Package folder `RoofForge_2.9.2_weighted-endpoint-fix`.
- Manifest version `2.9.2`.
- The monolithic add-on includes a numbered top-view roof plan, per-edge pitch fields, plan-label sizing, interactive update-rate throttle, ridge/valley profile meshes and standing seam generation.

## Alpha.10 UI changes

The Edit Mode Show button workflow is removed from the registered operators/UI. Each Pitch row is now identified from a schematic plan:
- White background, black contour and simple black edge numbers.
- Labels run in the same deterministic order as source contour and Pitch settings.
- Number on an edge maps directly to the Pitch field with the same index.
- Diagram scales to the available N-panel width.
- `Number size` is independent of geometry settings and changes only label rendering.
- The preview image is cached by contour + label-size signature, stored as a temporary PNG for Blender PreviewCollection, and cleaned up on unregister.
- Renderer is pure Python in `core/plan_preview.py`; it does not call the roof solver or Blender API.
- Ordered outline is stored in `scene.roof_forge.outline_preview_json` after Prepare, Generate and successful Live Update. It is persistent in the .blend scene settings.
- Panel drawing reads cached outline and only builds/reuses the preview image; it does not execute roof geometry.
- Existing per-edge numeric Pitch fields remain directly editable below the plan.

## Implementation files

- `core/plan_preview.py`: pure monochrome PNG contour renderer.
- `addon/ui/plan_preview.py`: Blender PreviewCollection + temporary file cache lifecycle.
- `addon/properties.py`: `outline_preview_json`, `plan_label_scale`.
- `addon/operators/prepare.py`: stores the ordered contour when Pitch settings are loaded/refreshed.
- `addon/operators/generate.py` / `addon/live_update.py`: refresh saved preview contour as roofs rebuild.
- `addon/ui/panel.py`: plan schematic and direct Pitch fields; no Edit Mode Show button.
- `addon/registration.py`: releases preview resources on unregister.
- `tests/test_plan_preview.py`: PNG format, B/W pixel, label-size, two-digit number, L/U, invalid contour tests.
- `tests/blender_smoke.py`: checks plan panel registration, icon creation and Number size control.

## Additional useful features audited in 2.9.2

1. Interactive update-rate cap 1–60 Hz, with expensive profiles/seams deferred until the user stops dragging. Potentially useful but not copied yet because the current 0 ms debounce UX must be preserved until measured.
2. Separate ridge and valley profile meshes extracted from actual roof face adjacency. Candidate next milestone after adapting it to current `RoofSurface` and face source IDs.
3. Standing-seam layout generator with panel width, seam height/base width and end offsets. Candidate later feature; not safe to import without porting against current generated facets and shell thickness.
4. Persistent source-surface/profile metadata on generated roof objects, useful for rebuilds after file save/reopen. Candidate architecture improvement.
5. Old solver, overhang strip builder, mesh extrusion and monolithic property group were deliberately not copied; they are incompatible with the current alpha API and would risk bringing back older geometry limitations.

## Validation required for alpha.10

- Pure Python tests: 3.11 and 3.13.
- Blender 5.0.1 smoke: visible top-plan UI references, PreviewCollection icon creation, label-size change, scene-persisted ordered outline; previous roof smoke still passes.
- Clean Extension ZIP and official Blender Extension Validator.
- Download exact alpha.10 artifact and inspect manifest + panel module contents before release.

## User QA

1. Remove previous RoofForge alpha, install alpha.10.
2. Prepare a rectangle, L or U contour.
3. Confirm a top-view plan appears above the Pitch fields.
4. Confirm each number lies by its matching source edge and matches same-numbered Pitch row.
5. Change Number size: only labels should resize; geometry/Pitch should not change.
6. Change Pitch values directly in rows; no Edit Mode selection should be required.
7. Try two-digit edge numbers on an 11–16 edge contour.

## Repository rules

- Continue only on `feature/0.2.0-arbitrary-contours-live-pitch`.
- Keep PR #6 draft; do not merge to develop or tag stable 0.2.0.
- User viewport QA remains separate from CI.
