# RoofForge 1.0 — Concave Roof Geometry Research

**Status:** Research and implementation decision record  
**Updated:** 2026-11-06  
**Branch:** `develop`

## 1. Problem statement

The current plane arrangement is not a correct general solution for concave roof footprints.

Two tempting alternatives were tested and rejected as the main algorithm:

1. **Global lower envelope of all infinite edge planes.** This is continuous as a scalar function, but a plane belonging to a remote boundary edge can undercut an unrelated concave/convex eave. The generated surface then no longer preserves the authored perimeter height.
2. **Restrict each plane to the inward halfspace of its source edge.** This preserves more local boundary ownership, but the active plane set changes at supporting-line arrangements. The local lower envelopes can jump across these artificial boundaries and create internal single-use edges.

The mesh validator correctly rejects those results. Do not remove or weaken this guard.

## 2. Target production algorithm: weighted straight skeleton / wavefront roof

A straight skeleton is produced by moving polygon edges inward in parallel and tracing the moving vertices. The wavefront changes topology at events:
- **Edge event:** an active wavefront edge collapses and its adjacent edges become neighbours.
- **Split event:** a reflex wavefront vertex reaches a non-adjacent active edge and splits a wavefront loop.
- **Parallel-edge / needle event:** opposing wavefront edges coincide; the common segment contributes to the skeleton and must not be discarded.
- **Simultaneous vertex event:** several adjacent vertices reach one point at the same time; process the coincident chain as one topological event or a deterministic equivalent.

The 3D roof is the lifted wavefront: vertical coordinate represents propagation time, and the swept fragment of each original boundary edge forms that edge's roof face.

### 2.1 Per-edge pitch mapping

For a flat, constant-Z eave contour, define the wavefront time as roof height (z). If edge (i) has pitch (	heta_i) above horizontal, its inward plan displacement per unit height is:

[
v_i = rac{1}{\tan(\theta_i)} = \cot(\theta_i)
]

The active line for an edge moves by (v_i z) along its inward unit normal. Its swept 3D face therefore has the requested pitch. Each roof-face patch retains its source slope ID.

All speeds must remain finite and strictly inward for the first weighted solver. Zero pitch, near-zero normal rise, outward movement and ambiguous weighted events must be rejected with diagnostics.

### 2.2 Event-driven implementation

Do not use time-step simulation. Between events, every wavefront vertex is the intersection of its two adjacent moving lines and travels with constant velocity.

The solver should:
1. Keep circular wavefront loops with stable edge-instance and vertex IDs.
2. Solve the 2x2 line-velocity system for each active vertex.
3. Schedule edge-collapse events and candidate split events.
4. Process the earliest valid event and update only the affected loops/vertices.
5. Keep an event generation/version token so obsolete queued events cannot mutate the current wavefront.
6. Record each active edge fragment between consecutive event times.
7. Lift each fragment to the source edge's 3D roof plane and assemble a shared planar face graph.
8. Validate continuity, edge incidence, vertex links, face planarity, boundary preservation and absence of self-intersections before returning a roof.

An event is valid only if the hit lies on a live wavefront segment at that event time. Merely reaching an infinite supporting line is not sufficient.

### 2.3 Weighted-skeleton risk

Different pitches turn the construction into a weighted straight skeleton. The weighted case has more complex topological behaviour than the ordinary equal-speed skeleton; event choices can be ambiguous in degenerate cases and arbitrary weights do not automatically preserve every desirable property of the unweighted skeleton. RoofForge must use positive inward speeds, explicitly resolve or reject ambiguous events, and validate the resulting graph rather than assuming it is a tree.

### 2.4 Mixed-elevation eaves

The horizontal wavefront derivation above assumes the source contour lies at one Z height. If boundary vertices have different Z values along the eaves, the corresponding 3D edge planes have tangential gradient components; their horizontal-Z cross-sections are not simply parallel offsets of the original XY edges.

Therefore:
- keep the existing 3D plane builder for convex roofs where its plane-envelope model is valid;
- do not silently feed mixed-Z eaves into the flat-eave wavefront solver;
- investigate a generalized 3D event formulation or another mathematically equivalent construction before claiming concave + mixed-height eaves support.

## 2.5 Implemented wavefront alpha (2026-11-06)

`core/wavefront.py` now includes a working pure-Python global wavefront-to-surface path for a deliberately bounded fixture set:

1. **Moving lines and time:** one moving line per source boundary edge; speed is `cot(pitch)`; event time is absolute local Z, with a stored base-eave height. Negative and positive local eave elevations are valid; all eaves must share one Z.
2. **Kinematics and events:** 2x2 moving-line intersections, constant vertex velocities, edge-collapse candidates and reflex split candidates validated against finite live segments.
3. **Event queue:** one deterministic priority queue, near-simultaneous batching and stale-event invalidation using both edge generations and loop generations.
4. **Topology changes:** a strict interior split creates two child loops and two edge instances that preserve the target's source-slope identity. The global state machine advances all active loops to the earliest queued event.
5. **L/U terminal nodes:** a restricted cross-needle resolver handles one or more reflex vertices hitting adjacent target-edge endpoints in the same event batch, provided every remaining finite wavefront segment pairs with an opposite coincident segment at the event height. The finite segments must match endpoint-to-endpoint, but their speeds may differ; the supporting lines only need to coincide at that instant. Those segment pairs become skeleton arcs.
6. **Facet collection and assembly:** every active source edge produces swept planar fragments between event heights; moving vertices produce skeleton arcs. The assembler welds 3D points, checks each fragment against its original plane, inserts intermediate vertices along T-junction edges, validates projected coverage and requires every open upper-surface edge to match the original perimeter.
7. **Solid shell:** the resulting `RoofSurface` passes through the existing roof-shell builder and edge/vertex manifold validator for fixtures whose smallest faces exceed the validator's scale-aware area tolerance.
8. **Constrained compound event:** one strict interior split coincident with one edge collapse on the same loop is applied transactionally. The split target is divided first; the collapse is revalidated from adjacent support lines. If the collapsing child reduces to two opposite coincident fronts, the finite terminal arc is defined by independently revalidated split and collapse event points, and the other child is rescheduled.
9. **Finite needle validation:** an ordinary two-front terminal state must match finite segment endpoints in reverse order. Coincident infinite support lines alone are insufficient; unhandled partial overlaps raise `PARTIAL_OVERLAP_NEEDLE_UNRESOLVED`.

### Verified fixtures
- Rectangle: point and needle terminal events.
- V-notch: one reflex split; both equal pitches and one asymmetric per-edge pitch set.
- L contour: one cross-needle terminal node with equal pitches and with deliberately unequal opposing speeds; also tested with reversed contour winding.
- Two constrained asymmetric L cases: one strict split and one edge collapse in the same event batch, with opposite split targets for the two speed configurations; both continue the surviving child and assemble into manifold shells.
- A sub-tolerance sliver regression: the upper surface retains the narrow facet, while closed-shell validation rejects the resulting below-tolerance face rather than suppressing geometry or relaxing the validator.
- U contour: two endpoint-hit groups and three terminal needle arcs, with equal pitches and with three deliberately unequal-speed opposing pairs.
- Nonzero constant eave elevation (the split edge copies must preserve their base height).
- Closed shell with roof-local global `-Z` thickness.

Latest pure-Python CI: **61 tests passed on Python 3.11 and 3.13**: https://github.com/MorenDord/RoofForge_Blender/actions/runs/42264904390.

### Known limitations
- This is not a general solution for every simple concave polygon. The same-loop compound resolver currently accepts exactly one strict split plus one edge collapse in the same event batch; it is not a generic resolver for arbitrary mixed event sets.
- The two verified asymmetric L compound fixtures cover a constrained partial terminal overlap: the split and collapse event positions define a terminal segment shared by the two coincident opposing fronts, while the remaining child continues. Generic partial overlaps with arbitrary endpoints, multiple overlap intervals or surviving tails are still unsupported and must be rejected.
- When event times are distinct, the global queue advances to the earlier candidate and schedules new candidates after topology mutation; however, the broader family of near-simultaneous event orderings is not yet covered by end-to-end adversarial fixtures. Candidate-order diagnostics alone are not proof of general support.
- A geometrically nonzero but sub-tolerance sliver may fail the closed-shell face-area gate. The solver retains the source facet; the shell validator intentionally rejects such output. No validator tolerance has been relaxed.
- Mixed-height eaves are not supported by this 2D wavefront formulation.
- The code is not connected to the Blender generation operator and has not been runtime-tested inside Blender 5.0.

## 3. Experimental comparison path

`core/distance_field.py` contains a deliberately separate prototype:
- evaluates finite edge-segment distance features;
- uses each edge's pitch over its edge-interior projection region;
- uses radial endpoint transition patches outside the finite segment;
- takes the continuous lower envelope of those feature functions;
- uniformly refines a triangulated domain to approximate the transition regions;
- checks sampled boundary preservation and the same outer-boundary/manifold conditions.

This path is useful as a visual/technical comparator and produces closed L/U test meshes for flat eaves and mixed pitches. It is **not** the production solution because the corner transition patches are approximated and are not all exact source-edge planes. Do not replace the straight-skeleton target with this prototype without an explicit product decision.

## 4. Required regression fixtures

- Rectangle: equal pitch, unequal positive pitch, width/height ratio causing parallel-edge collision.
- L and U footprints: equal pitch and mixed positive pitch.
- Concave notch / narrow neck: split event, multiple split candidates and event ordering.
- Reflex vertex hitting the endpoint of a wavefront segment (must not be treated as an interior split).
- Two or more simultaneous edge events.
- Parallel opposing wavefront edges / needle resolution.
- Near-parallel adjacent support lines and nearly zero edge lengths.
- Different boundary Z heights: verify current solver rejects unsupported cases or routes to a separately validated generalized method.
- CW and CCW boundary winding: output must be identical up to stable slope-ID mapping.

For each fixture assert:
- projected domain coverage;
- every internal roof edge has two incident faces;
- every perimeter edge lies on the source contour and the complete perimeter is covered;
- shared 3D nodes agree within scale-aware tolerance;
- each source-edge face is planar and satisfies its pitch where required;
- closed shell is edge- and vertex-manifold;
- output is deterministic within documented tolerances.

## 5. External references

- Biedl et al., *Weighted straight skeletons in the plane* (2015): https://pmc.ncbi.nlm.nih.gov/articles/PMC4235777/
- CGAL, *2D Straight Skeleton and Polygon Offsetting*: https://doc.cgal.org/latest/Straight_skeleton_2/index.html
- Algorithm overview and event handling notes (implementation reference, not code to vendor): https://github.com/lizelive/straight-skeleton/blob/main/docs/ALGORITHM.md

## 6. Exit condition

Concave roof support is not complete until the weighted wavefront solver produces exact planar edge faces and passes every topology/geometry regression fixture above. The distance-field prototype alone does not satisfy this gate.
