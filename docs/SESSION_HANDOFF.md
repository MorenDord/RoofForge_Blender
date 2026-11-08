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


## RoofForge 0.2.2 — dual plan preview experiment

- PR #6 remains open and draft; no merge. Main/develop are unchanged.
- Branch head verified for this build: `b5e3718ad0ac60d83d2e8e2b59b84f71c7a3c067`.
- Workflow run: [42455878553](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42455878553), all jobs passed.
- Artifact: `roof_forge-0.2.2-blender-5.0.1`, ID `13607413534`.
- Outer artifact SHA-256: `f039432fef0bd2b8c4fc33e0dcbe48c318ac4d6955da021a59510a4b226467d7`.
- Inner extension ZIP SHA-256: `f0d9b5ce64ce2a77cec1eeab1e607de6de80dcdeedb70361b41aab9bad72662e`.
- Extension manifest version: `0.2.2`, 30 files.
- Added independent Raster preview (PNG) and Vector overlay (Viewport) toggles. Raster defaults on; vector defaults off. Vector drawing uses a cached roof-plan representation and Blender GPU/BLF drawing; it does not invoke PNG rendering.
- Both modes can be shown together, independently disabled, or both turned off.
- Blender 5.0.1 background smoke: legacy geometry suite and vector-preview geometry/registration/toggle smoke passed. Extension validator passed.
- Manual interactive viewport QA is still required for actual GPU visual placement, resizing, readability, redraw latency, multiple View3D areas, and draw-handler cleanup.
- Positive overhang remains convex-only; concave L/U roofs are supported at zero overhang.


## RoofForge 0.2.3 — direct GPU preview in the N-panel (experimental)

- PR #6 remains open and draft; no merge. Main/develop unchanged.
- The vector draw-handler now targets SpaceView3D region type `UI` (N-panel) rather than `WINDOW` (main viewport).
- A dedicated N-panel category/tab `Roof Plan` contains the GPU canvas and its visibility/style controls. Main generation controls remain in `RoofForge`; this avoids drawing over a dynamically sized list of Pitch controls.
- The handler only draws while `region.active_panel_category == "Roof Plan"`; it is tagged for redraw on the UI regions only.
- Vector-only mode skips PNG timer scheduling and PNG rendering. Raster remains independently switchable and may be enabled together with vector.
- Canvas is centered in the UI region below a reserved control strip; manual Blender 5.0.1 visual QA is required for coordinates, panel resizing, scroll behaviour, multiple areas, redraw and cleanup.
- Version set to 0.2.3 in manifest, add-on metadata and workflow artifact name.
- Smoke asserts UI-region handler registration, dedicated panel category and that vector-only mode does not queue a PNG render.


### 0.2.3 package verification

- Branch head: `49abdbf65304ab10f2d3b5d4eab062f3fd4ad1ce`.
- CI: [workflow 42459312000](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42459312000), all seven jobs passed.
- Blender 5.0.1 smoke step passed both `tests/blender_smoke.py` and `tests/blender_vector_preview_smoke.py`; clean ZIP build and official Blender 5.0.1 extension validator passed.
- Artifact ID: `13609122113`, name `roof_forge-0.2.3-blender-5.0.1`.
- Outer artifact SHA-256: `803fb1b53fc4e1792dae092980387f8213028be58084bb3b4802c19918d5065a`.
- Inner extension ZIP SHA-256 (matches included sidecar and independently computed): `b9ba992847a5d6fb9c50484ffa7ca09fa346484103937df9b99d524cbb718e97`.
- Exact package downloaded and inspected: manifest `0.2.3`, 30 files, includes the `UI`-region draw handler, Roof Plan tab and current Russian test instructions.
- Manual visual QA is not covered by background CI and remains required.


## RoofForge 0.2.4 — vector preview integrated into the main N-panel tab

- User tested 0.2.3 and confirmed the GPU drawing worked, but the separate **Roof Plan** tab prevented simultaneous viewing and use of the **RoofForge** controls.
- Removed the standalone `ROOFFORGE_PT_vector_preview` panel and moved the drawing target to the existing `RoofForge` category.
- The main panel now reserves a blank UI-layout row for the GPU canvas between Plan display controls and the per-edge Pitch list.
- The draw handler checks the active category and hides its pinned canvas when the UI region's View2D is scrolled away from the top, avoiding overlap with lower controls.
- When Raster and Vector are both enabled, the top offset accounts for the displayed PNG icon so the GPU canvas is positioned below it.
- Version: `0.2.4` in the manifest, `bl_info` and CI package artifact name.
- New Blender background smoke checks the main category, absence of the standalone panel, vector geometry and top/scroll state helper.
- Manual viewport QA remains required: position/alignment with raster off and on, Pitch control accessibility, N-panel scrolling, width/UI-scale changes, multiple View3D areas and handler cleanup. Background smoke does not validate pixel-perfect placement.


## RoofForge 0.2.5 — transparent GPU preview cleanup

- User-provided Blender screenshot showed the same-tab preview now works but has a dark opaque square behind the plan, a `RoofForge / GPU` watermark colliding with the geometry, and a redundant `Vector plan` heading overlapping the reserved canvas area.
- Removed the opaque GPU quad entirely; the vector preview now draws only white edges and facet labels over the native Blender N-panel background.
- Removed the in-canvas watermark and the redundant `Vector plan` UI heading. Kept the blank layout row as the reserved canvas slot to preserve placement.
- Added a smoke assertion that the opaque-rectangle helper is absent.
- Bumped add-on, manifest and workflow package version to `0.2.5`.
- Manual QA still required for transparent rendering, alignment with the slot, readability across Blender themes, and panel resizing/scrolling. Background CI cannot verify rendered pixels.


## RoofForge 0.3.0 — vector-only preview and pre-create settings

- Removed raster PNG preview end-to-end: deleted `addon/ui/plan_preview.py` and `core/plan_preview.py`, removed `plan_show_raster`, preview icon cache, temporary PNG file handling and deferred PNG refresh timer.
- Added `core/roof_plan.py` containing only JSON-safe topology, visible-edge and label-anchor geometry helpers.
- Added GPU antialiasing using Blender's `POLYLINE_UNIFORM_COLOR` built-in shader with `viewportSize` and `lineWidth` uniforms.
- Replaced the largest-face label anchor with an area-weighted centroid across all faces assigned to the same source slope. Strongly concave regions fall back to a higher-resolution pole-of-inaccessibility search.
- Added exact bounding-box-centre alignment to the N-panel preview slot. Preview size is clamped to the region's actual available width/height; below a minimum width it is hidden rather than spilling into the adjacent editor.
- Vector colour is selected from the active UI theme brightness; facet labels use a contrasting text outline.
- Added `initial_pitch` (default 30°, range 1–85°). `sync_slope_settings()` copies it to every edge only when a new source/contour is initialized. Changing it later does not overwrite already-authored individual pitches.
- The main panel now shows initial pitch, thickness, overhang, corner convergence, Live Update and debounce controls before the first roof is created.
- Background tests cover removal of raster settings, no raster module references, first-build initial pitch, continuous area-centroid anchors, centred bounding boxes, narrow-panel hiding and label geometry. Actual GPU anti-aliasing and pixel placement still require manual viewport QA.
- Version bumped to `0.3.0`; PR #6 remains open and draft.


## RoofForge 0.3.1 — N-panel preview position correction

- User screenshot of 0.3.0 showed the GPU plan occupying nearly the full sidebar width and extending down into the first Pitch row.
- Calibrated the reserved UI-region anchor from 188 to 152 logical px, reduced the max canvas side from 208 to 140 logical px, and changed safe margins/minimum visible width.
- Kept the original panel order: Roof plan toggle and style controls first, reserved preview row second, Pitch list immediately below.
- The resulting canvas is smaller and vertically re-centred inside the existing preview slot; narrow-panel hiding remains in place.
- Corrected displayed facet numbers from zero-based source indices to one-based numbering matching Pitch rows (01, 02, ...).
- Added/updated Blender smoke assertions for reserved-area sizing and anchor bounds. Version 0.3.1.
- Manual interactive viewport QA is still required; screenshot calibration is a best-effort correction, not a GUI pixel-level CI test.


## RoofForge 0.3.2 — full-region centring and width-responsive scaling

- User reported the 0.3.1 preview still was not vertically centred and did not grow with sidebar width.
- Removed the guessed `_PANEL_TOP_RESERVED` and fixed `_PANEL_MAX_SIZE` layout model.
- `_compute_canvas_layout()` now centres the contour bounding box at `(region.width / 2, region.height / 2)` in the full active RoofForge UI region.
- The geometry scale is recalculated on every draw using the current available width and a height cap of 30% of the UI region. This preserves aspect ratio, grows with sidebar width while width-constrained, and prevents very tall shapes from taking over the panel.
- Added smoke coverage that verifies exact vertical/horizontal centring and monotonic scaling when the UI-region width grows from 320 to 420 px.
- Version bumped to 0.3.2. Manual interactive viewport QA remains necessary, especially to confirm that the new centre aligns with the visible sidebar in the user's Blender layout.


## RoofForge 0.3.3 — restore the former raster preview's layout behaviour for GPU vectors

- User said the 0.3.2 whole-UI-region centring became worse and asked to reproduce the raster preview's behaviour exactly.
- Retrieved the historical `core/plan_preview.py` and `addon/ui/panel.py` from the 0.2.5 package. The raster renderer used a square 384 px canvas, `margin = max(18, size * 0.075)`, scale `(size - 2 * margin) / max(span_x, span_y)`, and centred offsets `(size - span_x * scale) / 2`, `(size - span_y * scale) / 2`. The panel displayed it with `layout.template_icon(icon_id, scale=max(1, (region_width - 24) / 32))`.
- Replaced the full-region centring and 30%-height cap with this exact square-fit model. The displayed square side is `region_width - 24` px (provided it is at least 96 px), and its scale grows with the sidebar width.
- The panel now inserts an `ICON_NONE` `template_icon(0, scale=...)` immediately after the Roof plan toggle. This is a transparent UI-layout anchor only: it contains no roof image data, does not invoke a PNG renderer, and reserves the same square item size in the layout. The GPU draw-handler paints the vector plan over this slot. Number/line style controls and Pitch are laid out after the square, so they are pushed down instead of being covered by the GPU overlay.
- GPU overlay slot top is anchored 126 logical px below the top of the UI region (scaled by Blender UI scale), matching the panel's button/header/toggle rows in the current layout. Manual GUI check is still needed to validate pixel-level anchor alignment.
- Added smoke assertions for raster-equivalent square dimensions, 7.5% fit margin, centring and monotonic scaling at 320→420 px UI widths; asserts the UI panel includes a `template_icon` anchor.
- Version: 0.3.3. PR #6 remains open and draft. `main` was restored after an accidental out-of-branch write; its tree SHA matches the pre-write tree exactly. `develop` was not changed.
