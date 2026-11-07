# RoofForge 0.2.0-alpha.9 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**UI fix commit:** `5d751ced47ea72736bf7eabe7d9bc0c326ad23a9`  
**Versioned package commit:** pending alpha.9 package metadata commit  
**PR:** [#6 — WIP RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6), open and draft.  
**Alpha.9 artifact / SHA-256:** pending versioned package CI.  
**Important:** `main` and `develop` must remain unchanged.

## User report and verified cause

The user reported that the alpha.8 Show controls were not visible. Inspection of the actual downloaded inner alpha.8 ZIP confirmed this report:
- `addon/operators/select_edge.py` was included and imported/registered.
- `addon/ui/panel.py` in the ZIP was the unchanged old version: each Pitch row rendered the label and Pitch property only; no Show operator button.
- The earlier smoke test exercised the operator directly but did not assert that the UI panel actually exposed it.
- Therefore the previous alpha.8 release statement that the button was visible was incorrect. Do not direct user to alpha.8 for this feature.

## Alpha.9 correction

The source `addon/ui/panel.py` now visibly adds, in every Pitch row:

- `row.operator("roof_forge.select_slope_edge", text="Show", icon="EDGESEL")`
- passes `item.edge_index` to the operator
- leaves the Pitch property in the same row.

The Blender smoke test has been strengthened to assert:
1. the source-edge operator is registered;
2. the registered RoofForge sidebar panel exists;
3. the panel `draw()` bytecode constants include `roof_forge.select_slope_edge`;
4. the panel `draw()` bytecode constants include the visible label `Show`;
5. existing operator execution tests select the correct edge for wire and face contours and do not modify source coordinates/topology.

This is intentionally a package-level regression gate: a green test run must fail if the UI code is missing even when the operator itself still works.

## Existing operator behaviour

- Each Pitch row's Show button selects exactly its assigned source boundary edge.
- From Object Mode it enters Edit Mode; from Edit Mode it changes the highlighted edge.
- Uses the same deterministic boundary walk as source contour and Pitch preparation.
- Works with wire-only contours and face-mesh outer boundaries.
- Does not change source topology or coordinates.
- Native temporary Edit Mode selection only; no persistent colored overlay or pitch map yet.

## Existing geometry and UX retained

- One outward-offset source contour then full roof rebuild; no appended eave strips/caps.
- Individual per-edge pitch values, new fields default to 30°.
- Thickness default 1 cm, cm input.
- Live Update delay 0–1000 ms, default 0 ms; thickness-only cache; last-valid-mesh rollback.
- One simple boundary loop, max 64 edges.
- L/U flat-Z offset roof cases covered, subject to weighted-wavefront limitations.
- Arbitrary concave mixed-height XYZ is not guaranteed.
- Delete/recreate and source geometry preservation remain covered.

## CI / artifact status

Alpha.8 had fully green CI but its panel source was missing the control. That alpha.8 artifact must not be reused for the Show milestone.

Alpha.9 must pass:
- Python 3.11 and 3.13;
- Blender 5.0.1 smoke including the new panel-content assertions and edge selection tests;
- clean extension ZIP build;
- official Blender 5.0.1 Extension Validator.

Record final alpha.9 push/PR run IDs, artifact ID and inner ZIP SHA-256 only after downloading and inspecting the produced ZIP. Specifically inspect the packaged `addon/ui/panel.py` and verify it contains `text="Show"` and `roof_forge.select_slope_edge`.

## User QA after alpha.9 is verified

1. Install alpha.9 (not alpha.8) after removing previous RoofForge versions.
2. Prepare a source wire contour and verify each Pitch row has a visible Show button.
3. Click Show on Edge 03; verify exactly that edge is selected in Edit Mode.
4. Click another Show; selection must move to the new edge.
5. Repeat for a face mesh.
6. Generate the roof and ensure source contour coordinates/topology remain unchanged.

## Repository rules

- Continue only on `feature/0.2.0-arbitrary-contours-live-pitch`.
- Keep PR #6 draft; do not merge to develop or tag stable 0.2.0.
- Do not claim alpha.9 is ready until package contents have been inspected.
