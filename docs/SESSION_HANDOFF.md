# RoofForge 0.3.12 — Session Handoff

**Updated:** 2026-11-12  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**PR:** [#6 — RoofForge 0.3.12 mixed-height concave continuity](https://github.com/MorenDord/RoofForge_Blender/pull/6), open and draft.  
**Validated branch head:** `bbc09d86ce9550bac1aa157b4a4a54969612f81a`.  
**Workflow:** [run 43195693341](https://github.com/MorenDord/RoofForge_Blender/actions/runs/43195693341), all 7 jobs passed. Blender 5.0.1 smoke markers, including the mixed-height concave fallback regression, and official extension validation succeeded.  
**Installable artifact:** `roof_forge-0.3.12-blender-5.0.1` (artifact ID `13933385871`).  
**Outer artifact SHA-256:** `041f53b5180c00f3ea59eefa0a336d0fe1d3d477d0b1f3b34514650863e027f4`.  
**Inner ZIP SHA-256:** `09e55e713c55c7abb1b3a6a9625cfd12cb779f5c631ad67848019bbb300b89a4`.  
**Important:** main and develop remain unchanged. Manual inspection in Blender's viewport is still required on the user's complex production contour.

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


## RoofForge 0.3.4 — isolate and clip the vector preview slot

- User feedback on 0.3.3: the preview remained slightly right-shifted and GPU drawing overlapped several fields below.
- Split the former monolithic panel into three ordered root panels in the same **RoofForge** N-panel tab: **RoofForge** (Create / Update), **Roof Plan** (vector visibility, square anchor and drawing style), and **Pitch & Settings** (initial pitch or per-edge Pitch plus common roof settings).
- The square `template_icon(0)` anchor now belongs to the dedicated Roof Plan panel, so it pushes the subsequent Pitch & Settings panel down in normal Blender layout flow.
- GPU canvas coordinates compensate for the 12 px right scrollbar gutter, centring the plan on the usable content area rather than the entire UI region.
- The drawing canvas has an 8 px inset inside the reserved slot and is clipped with `gpu.state.scissor_set` / `scissor_test_set`; antialiased lines and labels cannot paint outside the slot into Pitch controls or the adjacent editor.
- Added smoke assertions for panel ordering, anchor ownership, content-centre alignment, width-responsive scaling and scissor clipping. CI still cannot certify exact visual alignment in an interactive Blender window; manual viewport QA remains necessary.
- Version: 0.3.4. PR #6 remains open and draft; do not merge.


### 0.3.4 layout refinement — nested panel instead of sibling panels

The initial 0.3.4 draft split the UI into three sibling panels. This was superseded before packaging because a separate collapsible panel could leave a stale GPU draw-handler visible when collapsed. The final design keeps a single root `ROOFFORGE_PT_panel` and uses `UILayout.panel("roof_forge_plan_preview", ...)` for a collapsible Roof Plan subsection. The draw-handler visibility is tracked per UI region through `set_preview_slot_visible`; it draws only when the nested section body is present, Show preview is enabled, and the panel is not scrolled away. The reserved `template_icon(0)` square remains in normal layout flow before Pitch rows. The canvas is clipped to the square and compensated for the sidebar scrollbar gutter. The nested heading and its Show preview body row retain the two-row layout, so the vertical anchor top offset remains 126 logical px. Smoke tests verify visibility state, panel structure, clipping, bounding-box centring and width-dependent scaling. Manual Blender UI QA remains required.


## RoofForge 0.3.5 — UI bounds diagnostics

- Added an opt-in **Debug UI bounds** overlay to the nested Roof Plan section.
- The overlay draws the full UI Region, the visible View2D rectangle derived through `View2D.view_to_region(..., clip=False)`, the current estimated template-icon slot and the GPU viewport mapped through `Region.x/y`. Text labels expose their pixel dimensions and origins.
- Corrected scissor coordinates: the template slot is calculated in region-local POST_PIXEL coordinates, while `gpu.state.scissor_set` operates in active-framebuffer pixel coordinates. The scissor rectangle is now translated by the active `gpu.state.viewport_get()` origin.
- Added smoke coverage for View2D bounds conversion and framebuffer scissor translation.
- Version: 0.3.5. The debug overlay is off by default. It is a measurement aid, not proof of final panel-item alignment.
- Request a screenshot with the full RoofForge sidebar and Debug UI bounds enabled before replacing the remaining estimated template-icon slot position.


## RoofForge 0.3.6 — correct template_icon dimensions and panel alignment

- Root cause found from Blender's `interface_template_icon.cc`: `template_icon()` allocates `UI_UNIT_X * icon_scale` by `UI_UNIT_Y * icon_scale`; both UI units are `U.widget_unit`. The previous vector code incorrectly treated the unrelated divisor `32` as the physical pixel size, so the GPU square was larger than the real layout item.
- GPU slot size is now estimated as `round(20 * system.ui_scale) * icon_scale`. Blender does not expose `U.widget_unit` directly in Python; the public UI scale is used as its documented approximation. This is much closer than assuming 32 px per unit.
- Horizontal alignment no longer recentres the square in the entire UI Region or subtracts a guessed scrollbar gutter. It starts at the panel's internal left margin (`0.4 * widget_unit)).
- Vertical anchoring is expressed in four UI units for the root panel heading, Create button, nested Roof Plan heading and Show preview row, rather than the old 126 logical-pixel offset.
- The debug overlay now treats `gpu.state.viewport_get()` as local active-framebuffer coordinates. `Region.x/y` remain window-space and are no longer subtracted from the local GPU viewport. It prints the estimated widget unit and actual `template_icon` slot size, and exposes why View2D mapping is unavailable instead of hiding the exception.
- Version: 0.3.6. CI must pass before distributing the package. Manual visual QA remains user-confirmed; the UI-unit estimate may still differ slightly with Blender's wide-line/DPI settings.


### 0.3.6 validation and package

- PR head: `79958504cfc08fe9dcb8127722599781ebc77d0d`.
- CI run [42538925796](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42538925796): all seven jobs passed, including Python 3.11/3.13, Blender 5.0.1 smoke, clean extension ZIP, official extension validator and all benchmark jobs.
- Artifact: `roof_forge-0.3.6-blender-5.0.1`, ID `13639953240`.
- Outer artifact digest: `4371e6b4a6b230057803be0da1d0955d264200d2f0914a637c0e90cf70d1e5e4`.
- Inner installable ZIP: `roof_forge-0.3.6.zip`, 29 files, manifest version `0.3.6`, ZIP integrity check passed.
- Inner ZIP SHA-256 independently matched its sidecar: `93516d4f3473bb786b9da2a667d5896d403828ffe6e9a0302ebd5c7405d581f5`.


## RoofForge 0.3.7 — copyable preview diagnostics

- Added a **Copy debug text** button below the **Debug UI bounds** toggle.
- The draw handler continuously caches a per-UI-region diagnostic snapshot. The operator `roof_forge.copy_preview_debug` writes the latest snapshot to `context.window_manager.clipboard`.
- Replaced direct `View2D.cur` access with the public Blender 5.0 API methods `region_to_view(x, y)` and `view_to_region(x, y, clip=False)`. Blender's RNA wrapper does not expose the internal `cur` field; the copied message now reports view-space corners and their pixel round-trip, or the explicit mapping error.
- The text snapshot includes Blender version, Region size and window-space origin, GPU viewport in local framebuffer coordinates, UI scale, estimated widget unit, `template_icon` scale and estimated slot/draw rectangles.
- Background Blender smoke covers public View2D mapping, copy operator registration and clipboard string output via a test context.
- Version: 0.3.7. Clipboard interaction still needs a quick check in an interactive Blender window; the background smoke tests exercise the operator's clipboard assignment with a mock window manager.


### 0.3.7 validation and package

- PR head tested: `1245a15aaa03adbf43baaf214af26263c94dbb50`.
- CI run [42581930937](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42581930937): all seven jobs passed — Python 3.11/3.13, Blender 5.0.1 background smoke, clean ZIP build, official extension validator and benchmark jobs.
- PR-triggered duplicate run [42581936661](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42581936661) was also started; push run 42581930937 completed successfully.
- Artifact: `roof_forge-0.3.7-blender-5.0.1`, ID `13658120077`.
- Outer artifact digest: `41ac36a47344d8919cf39269ca048d28b669f4a82f8fd39a8ccc9002531d56d5`.
- Inner installable ZIP: `roof_forge-0.3.7.zip`, 30 files, manifest version `0.3.7`; ZIP integrity check passed and the copy operator source is included.
- Inner ZIP SHA-256 (matches the included sidecar and independently computed): `5f160e329f2f6c1c77ba3a14bdf9b7c4276d4395b2397b76dda3dac38a8390f0`.
- The tested source no longer references `View2D.cur`; scroll-state tracking uses the public `region_to_view()` mapping with a per-region top baseline.


## RoofForge 0.3.8 — positive overhang for concave flat-eave contours

- Convex source-anchored overhang remains on the established plane-envelope path.
- Concave contours with one common eave Z use the tested weighted-wavefront roof as their base surface. A single offset corner per source vertex is projected to the intersection of its adjacent pitch planes. Every original boundary edge is extended by a planar quad strip on that edge's own pitch plane; the strips replace the source boundary and share one outer corner.
- The assembled upper surface is checked for exact projected ring area, strip-to-edge mapping, source-plane membership, expanded-boundary coverage and edge incidence. The normal shell builder then checks the closed shell for manifold topology.
- **Converge corners** is required for positive concave overhang. Mixed-height concave eaves are explicitly rejected. Offsets that self-intersect, close an L/U notch, or fail wavefront event validation are rejected rather than repaired.
- Added pure-Python regression fixtures for L and U shapes, asymmetric L pitch, reversed winding with preserved edge-pitch mapping, flat-eave enforcement, convergence requirement, and an over-wide U offset. Blender background smoke also exercises positive L and U overhang through the actual Generate operator.
- Version: 0.3.8. The weighted-wavefront solver is still a bounded alpha, not a guarantee for every simple concave polygon. Do not describe arbitrary concave contours or mixed-height concave eaves as supported.


## RoofForge 0.3.9 — geometric self-intersection validation

- Added a pure-Python triangle intersection test for coplanar and non-coplanar triangles.
- An X-axis sweep and 3D AABB overlap tests reject most candidate pairs before the narrow-phase intersection check.
- RoofForge-generated roof faces are planar convex cells and are fan-triangulated. Pairs from the same face and pairs of faces sharing a mesh vertex are excluded to avoid reporting expected manifold adjacency.
- `validate_closed_mesh()` emits `SELF_INTERSECTION` with both one-based face numbers. `build_roof_shell()` raises `GeometryInputError` when detected, which reaches the Blender Generate operator and preserves the last valid roof.
- Added regressions for a connected self-crossing bipyramid, overlapping/separate closed components, coplanar/non-coplanar triangle intersection, and valid rectangle plus concave L/U roof shells.
- Local 8/16/32/64-edge wavefront check produced no false positives; 64-edge shell validation took approximately 8.3 seconds in this Python runtime, so performance remains something to monitor.
- Version 0.3.9. This is an additional guard for non-adjacent face pairs, not a mathematical proof against every pathological configuration.


## RoofForge 0.3.10 — remove redundant loop-cut remnants

- The final BMesh cleanup now calls `bmesh.ops.dissolve_edges(..., use_verts=True)` for edges whose two linked faces lie on the same plane. This removes degree-two vertices remaining between two edges after planar faces merge.
- Loose edges/vertices left inside a merged planar patch are explicitly deleted.
- Real plane breaks, ridges, valleys, silhouette corners and non-coplanar wall transitions are preserved because only shared coplanar edges enter the dissolve operation.
- Blender smoke validates a subdivided cuboid collapsing to exactly 8 vertices, 12 edges and 6 quads, and asserts generated closed shells have no loose or degree-two vertices and no shared coplanar interior edges.
- Version: 0.3.10. Visual/manual Blender inspection is still required for the user's complex production contours.


## RoofForge 0.3.11 — near-coplanar seam cleanup

- The final BMesh pass now accepts only practically coplanar neighbouring faces: dihedral angle <= 0.05 degrees and the smaller adjacent face must lie within 1e-5 of the mesh span from the larger face's plane.
- Dissolution is iterative; after one merge creates new neighbours, the mesh is checked again until no eligible seam remains.
- A Blender smoke regression creates a narrow 0.04-degree sliver and requires it to dissolve. A second 5-degree ridge fixture must retain its shared edge.
- The existing subdivided-prism regression still requires 8 vertices, 12 edges and 6 quads.
- This does not collapse significant pitch transitions or promise full quad retopology. It only removes narrow near-flat seams within the stated tolerance.


## RoofForge 0.3.12 — mixed-height concave support-plane continuity

- Root cause: the non-flat concave 3D path split the contour by infinite inward supporting lines, then removed a candidate slope on the opposite side of each line. Where such a line crossed the polygon interior, the active plane set could change discontinuously and leave a single-use internal edge.
- Investigation: finite projection-only activation still leaves a discontinuity where a remote segment enters/leaves its candidate interval; a T-junction conformity pass alone does not close it.
- Production fallback: try the exact plane arrangement first. If it fails with an internal open edge or boundary coverage mismatch, retry with `build_distance_field_roof_surface()`, whose min of finite segment plane/radial endpoint features is continuous. Only corner-transition zones are adaptively triangulated; edge-interior zones remain on authored planes.
- Convex mixed-height roofs and flat-eave weighted-wavefront roofs keep their existing paths.
- Added an L-shaped mixed-Z regression with per-edge pitches; it must enter the continuous fallback, assemble complete projected coverage and pass closed-shell validation.
- The fallback's bounded approximation is recorded in `RoofSurface.approximation_error` / `refinement_depth`; Blender mesh metadata retains upward-facing transition patches as roof component faces even when they do not belong to one source plane.
- Positive overhang on mixed-height concave contours remains unsupported.
