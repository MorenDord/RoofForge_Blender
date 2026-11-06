# RoofForge 1.0 — Session Handoff

**Updated:** 2026-11-06  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Working branch:** `develop`  
**Do not modify:** `main`  
**Latest full code/test/package snapshot:** `c0f2305883dfd315b7f5e18e53486330fc767e09`  
**Latest verified CI:** https://github.com/MorenDord/RoofForge_Blender/actions/runs/42272132994  
**CI result:** 61 pure-Python tests passed on Python 3.11 and 3.13; Blender 5.0.1 background smoke passed in Object Mode and Edit Mode; the official Blender extension ZIP validator passed. Manual GUI installation/visual QA remains pending.

**Installable alpha build:** `roof_forge-0.1.0.zip`  
**GitHub Actions artifact:** `roof_forge-0.1.0-blender-5.0.1` (artifact ID `13529896467`, expires 2026-12-06)  
**Package SHA256:** `5c45681f4f8dc0d90e9440c097d0b5e38ce11f19cc2ae423e7a130b6485ff620`  
The package contains 22 files: manifest, extension entry point, addon/core Python modules and the Russian installation guide. It excludes tests, developer docs and legacy 2.8.4 archives.

## Start here after reconnect

1. Read this file first.
2. Read `docs/ROADMAP.md` for current priorities.
3. Read `docs/SPECIFICATION.md` for product requirements and acceptance criteria.
4. Read `docs/ARCHITECTURE.md` for modules and data flow.
5. Read `docs/CONCAVE_GEOMETRY.md` for the weighted wavefront implementation and known event limitations.
6. Inspect https://github.com/MorenDord/RoofForge_Blender/issues/3.
7. Check the latest branch commits and GitHub Actions result before editing.

## Current implementation state

### Production Blender path (unchanged)
- `core/geometry.py`: polygon predicates, clipping, ear clipping and plane primitives.
- `core/planes.py`: pitch-constrained plane per ordered 3D boundary edge.
- `core/envelope.py`: convex lower-envelope path; the restricted concave arrangement remains experimental and rejects internal open edges.
- `core/mesh.py`: welded upper-surface mesh, projected coverage and source-boundary continuity checks.
- `core/shell.py`: closed shell with thickness extruded along roof-local global `-Z`.
- `core/validation.py`: edge incidence, face winding, connected components and cyclic vertex-link validation.
- Blender operator still creates a closed shell using the existing plane/envelope path. It does **not** call the wavefront alpha yet.
- Blender 5.0.1 background smoke passed from the checkout: idempotent register/unregister; selected-boundary acquisition in Object Mode and Edit Mode; Validate and Create Roof Shell; output face attributes; source geometry and world transform remain unchanged. The extension ZIP also passes Blender's official manifest/package validation.
- No interactive Preferences → Install from Disk GUI session or artist visual QA has yet been performed. The user-facing alpha package is ready for that check.

### Experimental distance-field comparator
- `core/distance_field.py` creates continuous closed L/U comparison meshes.
- Its radial endpoint transitions are approximated; it is not the exact planar-facet solution and is not used by the Blender operator.

### Weighted wavefront alpha
File: `core/wavefront.py`

Implemented:
- One inward moving line per boundary edge; positive speed is `cot(pitch)`.
- Explicit `base_height` support: event time is absolute local Z; flat eaves may be above or below Z=0.
- Moving-line intersections and vertex velocities.
- Edge-collapse and finite-live-segment reflex split candidates, with endpoint-hit distinction.
- Deterministic event priority queue; same-time event batching; lazy stale-event invalidation by edge and loop generations.
- `apply_split_event`: validates a strict interior hit, splits one target edge into two new instances preserving source-edge identity, and returns two validated child loops.
- Global multi-loop event state; all live loops advance to the globally earliest event.
- Per-source-edge swept facet fragments and skeleton vertex trajectories.
- Restricted cross-needle resolver for one or multiple reflex endpoint-hit groups, only when the remaining finite fronts pair as opposite, endpoint-matching finite segments at the event height. Opposing speeds may differ.
- Transactional resolver for exactly one strict split plus one edge-collapse on the same loop at the same event time. It splits the target front, revalidates the collapsing segment from adjacent support-line intersections, terminates one child from the independently checked split/collapse points when they lie on both coincident fronts, and reschedules the surviving child.
- Ordinary two-edge needle termination now checks the finite segment endpoints, not only the coincident infinite support lines. Partial overlap is rejected unless handled by the constrained compound split/collapse case.
- Surface assembly retains valid small swept facets down to the vertex-weld precision threshold; the solid-shell validator still rejects faces below its scale-aware minimum-area threshold.
- T-junction conformance: inserts shared 3D vertices into earlier facet edges when later split events subdivide them.
- `run_weighted_wavefront` and `build_wavefront_roof_surface`: trace, weld, verify source planes, projected coverage and source-boundary continuity.

### Verified end-to-end fixtures
- Rectangle: point and needle terminal events.
- V-notch: one split; equal pitches and one asymmetric per-edge pitch set.
- L contour: equal-pitch and specifically constrained asymmetric cross-needle terminal events; clockwise/reversed contour also passes.
- U contour: equal-pitch and specifically constrained asymmetric multi-needle events with three terminal skeleton arcs.
- Nonzero constant eave elevation.
- The assembled RoofSurface for rectangle, V-notch, equal/asymmetric L/U, and the two constrained asymmetric L split/collapse fixtures produces shells that pass edge/vertex manifold validation.
- A sub-tolerance sliver test confirms the surface retains the real facet but shell creation rejects it with `ZERO_AREA_FACE`; no manifold validator tolerance has been weakened.
- Latest CI: 61/61 tests on Python 3.11 and 3.13, including unequal-/near-equal-speed fixtures, event-order diagnostics, two compound split/collapse cases, partial-overlap rejection and sub-tolerance shell rejection.

## Known limitations — do not overstate support

- Wavefront supports **constant-Z eaves only**. Mixed-height eaves need a separate generalized 3D formulation.
- L/U have been verified for the listed equal-pitch and specifically constrained asymmetric fixtures. This is not arbitrary mixed-pitch L/U support.
- The ordinary cross-needle resolver accepts unequal opposing speeds only when complete finite segments coincide endpoint-to-endpoint at the same event height. A constrained same-loop batch of exactly one strict split plus one edge collapse is also supported; the split point and collapse point delimit the terminal partial segment. Generic partial overlaps, multiple overlap intervals and arbitrary surviving tails remain unsupported.
- The compound event is not a general simultaneous-event resolver. It does not yet support multiple splits, additional collapses in the same batch or higher-order vertex collisions. Two asymmetric L fixtures now verify distinct-time continuation in both orders: the later batch occurs beyond the queue batching tolerance, references the live child-loop generation and only active edge instances. Do not generalize this evidence to arbitrary topologies.
- The surface assembler retains narrow fragments, but the final shell validator rejects any face below its scale-aware area threshold. Very narrow sliver fixtures are therefore explicitly rejected rather than silently simplified.
- Multiple independent split events on one loop, nested split sequences and higher-order vertex collisions are not generally resolved.
- Geometric self-intersection checking is not implemented yet.
- The wavefront alpha is **not connected to the Blender operator**. Its pure-Python event fixtures do not enable concave generation in the UI. Do not route user-facing roof creation through it yet.
- Per-edge pitch fields, numbered pitch map, overhang, live update, detach/relink, ridge/valley/hip profiles, seams, UV, LOD and export tools are not part of the 0.1.0 alpha. The Blender UI applies one pitch to all selected boundary edges.
- The 0.1.0 alpha is smoke-tested on Blender 5.0.1 Linux background only. It has not yet been visually QA-tested in the user's Blender installation or tested on Windows/macOS.

## Exact next development task

**Get manual feedback on the 0.1.0 alpha before expanding the solver.**

1. Ask the user to install the inner `roof_forge-0.1.0.zip` from the GitHub Actions artifact in Blender 5.0+ (extract the downloaded outer artifact ZIP once; do not extract the inner extension ZIP).
2. First test a simple rectangle in Edit Mode: Validate → Create Roof Shell. Confirm the RoofForge N-panel appears, a separate object is created, the source remains unchanged and shell thickness points along local -Z.
3. Repeat boundary selection in Object Mode. Then test one convex trapezoid/pentagon.
4. Collect Blender exact version, OS, contour geometry, settings, screenshots and any Console errors. Reproduce failures in `tests/blender_smoke.py` or a new fixture before changing geometry.
5. Do not present L/U as a supported Blender feature: the weighted wavefront is still disconnected from the generator. Do not implement more arbitrary event classes until the user validates the actual UI workflow or identifies geometry priorities.
6. After feedback, fix installation/UI/operator issues, add regression tests, issue a new test package version and rerun Blender 5.0.1 smoke + extension validation.

The 0.1.0 alpha is deliberately limited: one selected closed XY contour, one global pitch value, validation, and separate closed shell.

## Main project documents

- `docs/SPECIFICATION.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `docs/CONCAVE_GEOMETRY.md`
- `docs/SESSION_HANDOFF.md`

Issue: https://github.com/MorenDord/RoofForge_Blender/issues/3

## Test command

From repository root:

```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
```

## Required working rules

- Work only in `develop`; do not merge to `main`.
- Read current GitHub files rather than relying on chat history.
- Keep pure geometry code independent of `bpy`.
- Keep source geometry immutable.
- Build and validate temporary Blender output before committing datablocks.
- Never remove boundary-continuity, facet-planarity or manifold checks to make a fixture pass.
- Update this `SESSION_HANDOFF.md` at the end of every development session with tested branch snapshot, CI link/result, progress, blockers and exact next task.
- Do not claim Blender 5.0 runtime compatibility until tested directly inside Blender 5.0.
