# RoofForge 0.2.0-alpha.11 — Session Handoff

**Updated:** 2026-11-08  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Base UI reference:** `main` commit `63d7952e0ee9c7aa62b4ed4efe40716a7641a2e0`, manifest 2.9.2  
**PR:** [#6 — WIP RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6), open and draft.  
**Installable build:** `roof_forge-0.2.0-alpha.11.zip`, from artifact `roof_forge-0.2.0-alpha.11-blender-5.0.1` (artifact ID `13592915106`).  
**Workflow:** [run 42418098836](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42418098836), all jobs passed.  
**Inner ZIP SHA-256:** `bb76a87621c3e27edfabcbcc3f2c478341f628c825eb4a08f0a1f7a15a970748`.  
**Artifact ZIP SHA-256:** `9d7cf6579eb62f118594ea93e4293ae95c8a9500610cf8f45f931e150d026d76`.  
**Important:** `main` and `develop` remain unchanged.

## User request

The user reported that the eave overhang moved the roof edges and caused the lower surface to miss the original contour. The requested behavior is to keep the underside/support surface exactly on the original roof/eave contour.

The user also asked to replace the contour-only preview with actual roof facet graphics: white lines and numbers, transparent background, internal non-coplanar edges, no coplanar seams, antialiasing, adjustable line width, numbers centered and auto-sized inside facets, and width-responsive preview.

## Alpha.11 geometry changes

- For a **convex contour with a positive overhang**, support planes are built through the original 3D boundary edges. The expanded XY domain extends those same planes without re-anchoring them to shifted contour edges.
- The support/underside surface remains at the original contour. Shell thickness is extruded upward from it.
- Coplanar internal edges are dissolved from the actual Blender mesh through BMesh; face component/slope metadata is rebuilt after topology changes.
- Concave overhang (L/U) is **not supported in this alpha**. The add-on now returns a clear `OVERHANG_CONCAVE_UNSUPPORTED` diagnostic rather than risking a disconnected or invalid roof. Concave L/U contours continue to generate normally with zero overhang. A proper reflex-corner/valley transition solver is future work.

## Alpha.11 roof-facet plan UI

- The plan is derived from generated roof vertices, faces, slope IDs and plane data, not from a guessed outline.
- Outer boundary and real non-coplanar ridge edges are drawn; coplanar internal edges are omitted.
- White antialiased lines and labels on transparent RGBA background.
- Labels are placed in the largest face region belonging to a slope and centered using a pole-of-inaccessibility approximation; glyph size is reduced to fit local line clearance.
- Separate `Number size` and `Line thickness` controls.
- Preview image scale grows with the available N-panel width.
- Preview data is persisted after Generate / Live Update; drawing the panel does not rerun the roof solver.

## Implementation files

- `core/plan_preview.py`: actual roof facet topology conversion, coplanar-edge filtering, transparent antialiased PNG renderer and centered/auto-fit numbers.
- `addon/ui/plan_preview.py`: Blender PreviewCollection and temporary PNG lifecycle.
- `addon/properties.py`: saved roof plan JSON and rendering controls.
- `addon/operators/generate.py` / `addon/live_update.py`: refresh saved plan data on successful generation/rebuild.
- `addon/roof_build.py`: source-anchored convex overhang, upward shell, coplanar BMesh dissolve and face metadata rebuild.
- `core/overhang.py`, `core/mesh.py`, `core/envelope.py`, `core/planes.py`, `core/shell.py`: overhang support construction, active roof envelope, source-plane checks and shell extrusion.
- `addon/ui/panel.py`: full-width roof facet plan and independent rendering controls.
- `tests/test_plan_preview.py`: transparent/white pixels, antialiasing, ridge vs coplanar edge behavior, line/number size, two-digit IDs, concave diagrams.
- `tests/test_overhang.py`: convex support edge alignment, mixed-Z contour, upward thickness, safe concave rejection, clockwise offset and input validation.
- `tests/blender_smoke.py`: Blender 5.0.1 UI, plan rendering/cache, metadata after dissolve, actual overhang support edge alignment and concave no-overhang behavior.
- `.github/workflows/tests.yml`: build, validate and artifact names are bumped to alpha.11.

## Validation completed

Run [42418098836](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42418098836) passed all jobs:
- Pure Python tests on 3.11 and 3.13.
- Blender 5.0.1 background smoke.
- Clean extension ZIP build.
- Official Blender 5.0.1 extension validator.
- Geometry scaling benchmarks.
- Legacy spatial benchmark and solver profile.
- Rust skeleton candidate diagnostics.

Artifact archive ID `13592915106` was downloaded and inspected. It contains outer artifact files:
- `roof_forge-0.2.0-alpha.11.zip`
- `roof_forge-0.2.0-alpha.11.zip.sha256`

The inner ZIP manifest identifies `0.2.0-alpha.11`; archive contains 29 files including the new renderer, UI wrapper, geometry and shell modules. SHA-256 was checked against the provided sidecar.

## User viewport QA still needed

1. Install alpha.11 in Blender 5.0+.
2. Generate a convex roof with overhang and check that the underside/support surface remains on the original contour while thickness builds upward.
3. Try a mixed-Z convex contour with overhang and check the same alignment.
4. Resize the N-panel narrower and wider; verify the roof plan fills the available width.
5. Check the white transparent lines/labels on the current Blender theme, antialiasing and readability; verify number positions across facets of different widths.
6. Check that real ridges remain visible, coplanar seams are absent from both plan and roof mesh.
7. Verify concave L/U contours with overhang 0; a positive overhang should be rejected with a clear message in this alpha.

## Repository rules

- Continue only on `feature/0.2.0-arbitrary-contours-live-pitch`.
- Keep PR #6 draft; do not merge to develop or tag stable 0.2.0.
- Main and develop must remain unchanged.
- User viewport QA remains separate from CI.
