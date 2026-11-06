# RoofForge 1.0 — Concave Roof Geometry Research

**Status:** Research/implementation decision record  
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
