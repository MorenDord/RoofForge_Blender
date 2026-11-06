# RoofForge 1.0 — Session Handoff

**Updated:** 2026-11-06  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Working branch:** `develop`  
**Do not modify:** `main`  
**Latest branch commit:** `288131ebb210142a41a9dcd51a69f6c03d6d29b2`  
**Latest CI:** https://github.com/MorenDord/RoofForge_Blender/actions/runs/42234907845  
**CI result:** 24 tests passed on Python 3.11 and 3.13. Blender 5.0 runtime has not yet been tested.

## Start here

1. Read this file first.
2. Read `docs/ROADMAP.md` for priorities and completed work.
3. Read `docs/SPECIFICATION.md` for requirements and acceptance criteria.
4. Read `docs/ARCHITECTURE.md` for module boundaries and data flow.
5. Read `docs/CONCAVE_GEOMETRY.md` for the current concave-roof algorithm decision and research references.
6. Inspect the GitHub issue: https://github.com/MorenDord/RoofForge_Blender/issues/3
7. Check the latest commits and CI before editing.

## Current implementation state

### Production path
- `core/geometry.py`: polygon predicates, plane primitives, clipping, ear clipping.
- `core/planes.py`: one plane per 3D boundary edge with pitch/eave-grade validation.
- `core/envelope.py`: plane lower-envelope operations; its restricted concave arrangement is experimental.
- `core/mesh.py`: welded surface mesh, source-boundary chain validation and projected coverage.
- `core/shell.py`: closed shell with thickness along roof-local global `-Z`.
- `core/validation.py`: edge incidence, face winding, connected components and vertex-link validation.
- Blender operator builds a closed shell from one selected closed edge loop; the verified production fixture is a rectangle.

The current concave arrangement must reject surfaces with internal open edges. **Do not weaken or remove that guard.**

### Experimental comparator
- `core/distance_field.py` produces continuous, closed L/U comparison meshes with individual pitches.
- It uses finite segment-distance features and approximated radial endpoint transition patches.
- It is not an exact planar-per-boundary-face solution and is not wired into the production Blender operator.

## Main unresolved geometry problem

The target is a **weighted straight-skeleton / inward-wavefront solver** for concave footprints.

For constant-Z eaves, use roof height (z) as wavefront time. A boundary edge with pitch `theta_i` moves inward by:

`v_i * z`, where `v_i = cot(theta_i) = 1 / tan(theta_i)`.

Planned event types:
- edge collapse;
- reflex-vertex split against a live wavefront segment;
- parallel-edge / needle collision;
- simultaneous/coincident vertex events.

The solver should be event-driven, not time-step sampled. Use stable edge-instance and vertex IDs, a priority queue, generation tokens for stale events, and lift each swept source-edge fragment into its exact planar roof face.

**Important constraint:** this first 2D wavefront formulation assumes all contour vertices have the same Z. Concave roofs with mixed-height eaves need a separate generalized 3D formulation. Do not silently apply the flat-eave solver to them.

## Next development task

Implement the initial pure-Python `core/wavefront.py` prototype:
1. Define stable wavefront loop, edge-instance, vertex and event data structures.
2. Implement moving-line intersections and vertex velocities.
3. Implement edge-collapse events and simple reflex split events for constant-Z contours.
4. Validate that split hits lie on a live finite edge segment at event time.
5. Add deterministic handling/rejection for parallel, needle and simultaneous events.
6. Collect per-source-edge swept face fragments and lift them to 3D using event height as Z.
7. Add fixtures for rectangle, L, U, narrow notch, edge collapse, split, parallel edges and simultaneous events.
8. Do not route the production Blender operator through this prototype until face planarity, exact boundary preservation, closed-shell manifold checks and determinism all pass.

Start with equal pitch if needed to validate event topology; then implement positive per-edge speeds for individual pitch control. Any weighted event ambiguity must be explicitly resolved or rejected.

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
- Build and validate temporary output before committing Blender datablocks.
- Keep the last-valid mesh and all topology rejection checks.
- Update this `SESSION_HANDOFF.md` at the end of every development session with latest commit, CI link/result, progress, blockers and exact next task.
- Do not claim Blender 5.0 runtime compatibility until tested inside Blender 5.0.
