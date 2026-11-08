# RoofForge 0.2.1 — Session Handoff

**Updated:** 2026-11-08  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**PR:** [#6 — WIP RoofForge 0.2.1](https://github.com/MorenDord/RoofForge_Blender/pull/6), open and draft.  
**Installable build:** `roof_forge-0.2.1.zip`, artifact `roof_forge-0.2.1-blender-5.0.1` (artifact ID `13595999237`).  
**Workflow:** [run 42429419184](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42429419184), all jobs passed on PR head `c01778aa1dd931f5761d8971ddf88f26dae759f3`.  
**Inner ZIP SHA-256:** `e9cb79d17128318e2fd2fd81d151806f0dd86b1eca4054e0f062c4b5b7a980b6`.  
**Outer artifact digest:** `53b851e926f21550db85dccebeaa05ab316b7b0f9e3dde26171e737122df3db6`.  
**Important:** main and develop remain unchanged.

## User feedback addressed

The user reported that:
1. Custom-pitch overhang remains manifold and now touches the source contour, but unequal pitch planes extended differently at an outer corner. They want one shared corner point and the same boundary point count as the no-overhang contour, with variable distances allowed.
2. Raster generation was slowing live pitch changes. They prefer direct UI line drawing but accept a frozen old image during adjustment and one refresh after releasing controls.
3. The Load / Refresh Slope Angles action and unnecessary UI explanations should be removed. First action must be Create / Update.
4. They want to delete/recreate the roof and to edit the source contour in Edit Mode, exit to Object Mode, then rebuild.
5. Version naming should use `x.y.z`: increment z for iterative alpha fixes; increment y for larger feature milestone; increment x for major release.

## 0.2.1 implementation

### Corner-converged overhang
- Added **Converge corners** toggle next to Overhang; default enabled.
- Build pitch planes through original XYZ contour edges.
- Start from the standard miter-offset corner as a target, then project each outer corner XY coordinate onto the equality line of its previous/current support planes. Compute one shared Z from both planes.
- This creates exactly one target outer corner per source vertex. Each outer boundary edge joins two corners on its associated source edge plane.
- This may result in a variable overhang distance along the perimeter; this is expected.
- Toggle off uses the previous constant-distance miter offset.
- The mode remains convex-only. Concave L/U contours build with zero overhang; positive overhang is safely rejected until a correct reflex-corner solver is implemented.

### Deferred roof-plan preview
- Panel draw only calls `get_roof_plan_icon()` to display the most recently completed icon. It does not parse the plan or run the PNG renderer.
- Generation, successful Live Update and changes to number/line style schedule a refresh using a Blender timer.
- New requests reset the timer; it renders once after 0.75 seconds of quiet.
- Previous cached image remains visible while geometry/style values are being changed.
- Raster size reduced from 512 to 384 px. White antialiased strokes, transparent background, facet-centred adaptive numbers and non-coplanar edges are retained.
- A full custom line/text drawing directly into the sidebar was not implemented; Blender's sidebar layout API does not expose a simple arbitrary 2D drawing region. Deferred cached PNG is the implemented fallback.

### Simplified UI and recovery workflow
- The first control is Create / Update Roof.
- The operator automatically reads the active contour and initialises or reconciles the ordered Pitch settings.
- Load / Refresh Slope Angles is no longer presented as a user workflow; the internal operator remains available for test/compatibility paths but is not used by the panel.
- Explanatory text, solver labels and status blocks removed from the panel.
- If the active object is a generated roof, the operator resolves the source object from metadata or saved settings.
- If the output has been deleted, the operator recovers the stored source and creates a new roof.
- Edit the source contour in Edit Mode, return to Object Mode, then click Create / Update. Current boundary coordinates are re-read and the roof is rebuilt. Pitch fields are preserved when boundary edge count remains unchanged; if count changes they are recreated.

## Key implementation files

- `core/overhang.py`: `corner_converged_overhang_contour` and optional uniform miter fallback.
- `addon/roof_build.py`: overhang option in geometry cache signature and metadata.
- `addon/properties.py`: convergence toggle; plan style changes schedule deferred preview only.
- `addon/operators/generate.py`: source resolution, missing-roof recovery, no-preparation first-click flow.
- `addon/live_update.py`: passes corner-convergence setting and schedules deferred plan refresh after successful geometry.
- `addon/ui/plan_preview.py`: delayed refresh timer/cache; panel getter never renders.
- `addon/ui/panel.py`: streamlined user workflow.
- `tests/test_overhang.py`: equal-vertex-count converged corner, plane incidence, manifold shell and uniform-offset fallback.
- `tests/blender_smoke.py`: deferred-preview/cache behaviour, first-click generate, delete/recreate, Edit Mode source edit followed by rebuild, convex corner convergence, UI.
- `blender_manifest.toml`, `.github/workflows/tests.yml`: version and artifact naming updated to `0.2.1`.

## Validation completed

Run [42429239529](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42429239529) passed all jobs:
- Pure Python geometry and preview tests on Python 3.11 and 3.13.
- Blender 5.0.1 background smoke.
- Clean extension ZIP build.
- Official Blender 5.0.1 extension validator.
- Geometry scaling benchmarks.
- Legacy spatial benchmark and solver profile.
- Rust skeleton candidate diagnostics.

Downloaded artifact `13596766321` was inspected. Outer artifact contains the installable inner ZIP and its SHA-256 sidecar. Inner ZIP has 29 files and manifest `0.2.1`. Sidecar SHA-256 was verified against downloaded inner ZIP:
`93190e63a1598966439ae332f02bcaab96ff23798884653a55cd39c95b46e8a8`.

## Manual viewport QA remains

1. Test mixed custom pitches with **Converge corners** on: neighbouring slopes should meet at one shared point at every outer corner, and boundary vertex count should equal the source contour count.
2. Toggle **Converge corners** off: previous uniform miter offset should return.
3. Move Pitch sliders while Live Update is active: geometry should respond; old plan image should remain visible, and a new image should appear once after interaction stops.
4. Resize the N-panel wider/narrower and inspect the cached image width.
5. Delete the generated roof and recreate it. Edit source contour in Edit Mode, exit, then click Create / Update.
6. Verify a concave L/U contour still creates with zero overhang and rejects nonzero overhang with a clear message.

## Repository rules

- Continue only on `feature/0.2.0-arbitrary-contours-live-pitch`.
- Keep PR #6 draft; do not merge to develop or tag a stable 0.2.0/0.2.1 release.
- Main and develop must remain unchanged.
- Next ordinary patch uses `0.2.2`; a broader feature increment uses `0.3.0`; major release uses `1.0.0`.
