# RoofForge 1.0 — Session Handoff

**Updated:** 2026-11-06  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Working branch:** `develop`  
**Do not modify:** `main`  
**Latest full CI-verified project snapshot:** `5569d8311eee906283112cb9001a82f8cbab66b3`  
**Latest verified CI:** https://github.com/MorenDord/RoofForge_Blender/actions/runs/42263378860  
**CI result:** 58 pure-Python tests passed on Python 3.11 and 3.13. Blender 5.0 runtime has not been tested.

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
- T-junction conformance: inserts shared 3D vertices into earlier facet edges when later split events subdivide them.
- `run_weighted_wavefront` and `build_wavefront_roof_surface`: trace, weld, verify source planes, projected coverage and source-boundary continuity.

### Verified end-to-end fixtures
- Rectangle: point and needle terminal events.
- V-notch: one split; equal pitches and one asymmetric per-edge pitch set.
- L contour: equal-pitch and specifically constrained asymmetric cross-needle terminal events; clockwise/reversed contour also passes.
- U contour: equal-pitch and specifically constrained asymmetric multi-needle events with three terminal skeleton arcs.
- Nonzero constant eave elevation.
- The assembled RoofSurface for each listed fixture produces a shell that passes edge/vertex manifold validation.
- Latest CI: 58/58 tests on Python 3.11 and 3.13, including unequal- and near-equal-speed L/U fixtures plus event-order diagnostics.

## Known limitations — do not overstate support

- Wavefront supports **constant-Z eaves only**. Mixed-height eaves need a separate generalized 3D formulation.
- L/U have been verified for the listed equal-pitch and specifically constrained asymmetric fixtures. This is not arbitrary mixed-pitch L/U support.
- The cross-needle resolver accepts unequal opposing speeds only when complete finite segments coincide endpoint-to-endpoint at the same event height. Partial overlaps are not resolved.
- A small change in opposing speed sums can separate the endpoint hit and edge-collapse times. Candidate ordering is tested, but a mixed split/collapse batch or sequential split/collapse state update is not yet implemented.
- Multiple independent split events on one loop, nested split sequences and higher-order vertex collisions are not generally resolved.
- Geometric self-intersection checking is not implemented yet.
- The wavefront alpha is **not connected to the Blender operator** and has not been runtime-tested inside Blender 5.0. Do not route user-facing roof creation through it yet.

## Exact next development task

Resolve **weighted split/collapse event ordering and partial-overlap needles**.

1. Implement a topology update for a reflex split that is simultaneous with an edge collapse on the same loop, with full participant revalidation.
2. Implement the sequential case where a tiny speed-sum difference makes one event occur first and the other occur later; regenerate candidates after each topology change rather than batching stale candidates.
3. Add partial-overlap opposing-front events where the coincident segment endpoints do not both match; split the overlap into valid terminal arcs and continue any surviving wavefront portions where mathematically required, or reject explicitly.
4. Preserve exact source-plane facets, projected coverage, boundary-chain checks, T-junction conformance, edge/vertex manifold checks and deterministic output.
5. Then address multiple independent splits on one loop, nested split sequences and higher-order vertex collisions.
6. Keep mixed-Z eaves out of this 2D solver. Do not connect the alpha to the Blender generator until the broader geometry gate passes.

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
