# RoofForge 1.0 — Session Handoff

**Updated:** 2026-11-06  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Working branch:** `develop`  
**Do not modify:** `main`  
**Last tested code commit:** `8cdebc285ded06e5a7067de372fd5e61d0895d90`  
**Last verified CI run:** https://github.com/MorenDord/RoofForge_Blender/actions/runs/42247157224  
**Last verified tests:** 37 passed on Python 3.11 and 3.13. Blender 5.0 runtime has not been tested.

## Start here

1. Read this file first.
2. Read `docs/ROADMAP.md` for current priorities.
3. Read `docs/SPECIFICATION.md` for product requirements and acceptance criteria.
4. Read `docs/ARCHITECTURE.md` for package boundaries and data flow.
5. Read `docs/CONCAVE_GEOMETRY.md` for the algorithm decision, current wavefront code and degeneracy notes.
6. Inspect https://github.com/MorenDord/RoofForge_Blender/issues/3.
7. Check the latest branch commits and GitHub Actions result before editing.

## Current implementation state

### Production Blender path
- `core/geometry.py`: polygon predicates, clipping, ear clipping and plane primitives.
- `core/planes.py`: one pitch-constrained plane per ordered 3D boundary edge.
- `core/envelope.py`: convex lower-envelope operations; restricted concave arrangement is experimental and rejected when it produces internal open edges.
- `core/mesh.py`: welded upper-surface mesh, projected coverage and source-boundary continuity checks.
- `core/shell.py`: closed shell with thickness extruded along roof-local global `-Z`.
- `core/validation.py`: edge incidence, face winding, connected components and cyclic vertex-link validation.
- Blender operator creates a closed shell from one selected closed edge loop. Verified production geometry remains the rectangle fixture.
- **Do not route experimental wavefront or distance-field output through the Blender operator yet.**

### Experimental comparator
- `core/distance_field.py` builds continuous closed L/U comparison meshes with individual pitches.
- Endpoint transition patches are approximated. This is not the exact planar-facet production solution.

### Weighted wavefront code — current slice
File: `core/wavefront.py`

Implemented:
- `build_moving_lines`: constant-Z boundary requirement; edge speed `cot(pitch)`.
- Moving-line intersection and constant vertex velocity.
- Edge-collapse candidate calculation.
- Convex-contour simulation with lifted facet fragments, rectangle needle and simultaneous point handling.
- `find_split_candidates`: reflex vertex hitting a live finite target segment; distinguishes interior split from endpoint hit.
- `WavefrontEventQueue`: deterministic event ordering, near-simultaneous batching, lazy stale-event removal by edge and loop generation.
- `apply_split_event`: revalidates an interior split; replaces one target edge with two edge instances retaining the same source-edge identity; returns two child loops and checks their orientation/simplicity.
- V-notch regression fixture verifies a genuine non-parallel split into two valid loops.

Known limitation:
- This is **not yet a complete concave wavefront simulator**. There is no global state machine that advances multiple loops together, processes collapse and split events from one shared queue, collects all roof facets, records every skeleton arc and builds a complete manifold roof mesh.
- Some L-shaped examples create a parallel opposing-edge coincidence at the same instant as a reflex hit. That is a needle/parallel-edge degeneracy, not a normal split. `apply_split_event` correctly rejects it; the global simulator must resolve it explicitly or report a blocking diagnostic.
- The first 2D wavefront formulation supports constant-Z eaves only. Mixed-height eaves require a separate generalized 3D formulation.

## Exact next development task

Implement a global multi-loop event-driven wavefront state machine in `core/wavefront.py`.

Suggested sequence:
1. Define a mutable simulation-state wrapper containing current time, active loops, active moving edge instances, next stable edge/loop IDs, generation tokens, facet fragments and skeleton arcs.
2. Build one shared event queue from collapse and split candidates across **all** active loops.
3. Pop the globally earliest event batch and advance every active loop to that same time.
4. Record each active source-edge segment swept between the previous time and the event time as a lifted 3D facet fragment; verify each fragment remains on its source edge plane.
5. Process an isolated edge collapse by removing its edge and updating the loop generation. Detect two-edge needle termination and point termination.
6. Process a strict split using `apply_split_event`, replace the parent loop with its two child loops, and invalidate all queued events from the previous loop generation.
7. For near-simultaneous or overlapping event batches, implement deterministic combined handling only when mathematically justified; otherwise return explicit diagnostics. Do not silently process ambiguous events sequentially.
8. Preserve source-edge identity on duplicated target edge instances so later facet assembly can map them back to original roof slopes.
9. Add end-to-end fixtures: V-notch one split, nested/multiple splits, collapse after split, L parallel-needle degeneracy, U contour, CW/CCW winding, unequal positive pitches.
10. Only after the global trace is stable, implement shared-node/facet assembly and verify exact planarity, pitch, boundary coverage, edge/vertex manifold and self-intersection conditions.

Do not connect the new multi-loop solver to the Blender operator until these tests pass.

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
- Never remove the boundary-continuity or manifold checks to make a fixture pass.
- Update this `SESSION_HANDOFF.md` at the end of every development session with latest tested commit, CI link/result, progress, blockers and exact next task.
- Do not claim Blender 5.0 runtime compatibility until tested directly inside Blender 5.0.
