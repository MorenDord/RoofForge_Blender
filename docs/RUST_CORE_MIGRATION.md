# RoofForge Rust Core Migration

## Decision

RoofForge is moving toward an in-process native geometry core, not a separate
worker process. Blender remains responsible for scene access, artist controls,
preview drawing, material/UV datablocks, and writing the final Blender mesh.
The Rust crate receives plain numeric geometry and returns plain numeric
results. It must never import or depend on bpy.

Keeping the native core in Blender's process avoids IPC, mesh serialization
round-trips, process startup, and synchronization overhead on every live
rebuild. The Rust library can later be reused by a standalone application
without changing its geometry API.

## Python boundary

- Rust crate: rust/roof_forge_native.
- Python extension module: roof_forge_native, built with Maturin and PyO3.
- Python ABI: CPython stable ABI starting at 3.10 (abi3-py310), suitable for
  the Blender Python versions targeted by this project.
- The Blender adapter continues to own object transforms, mesh extraction,
  scene units, datablock creation, and transactional replacement.
- The Python geometry implementation remains a fallback until platform wheels
  are bundled and validated for Blender.

The bridge passes ordered XY/XYZ coordinates and per-edge parameters as plain
numeric arrays. Outputs use indexed vertices/faces, stable source-edge or
slope identifiers, and diagnostic codes. No Blender objects cross the API.

## First vertical slice

The first native operation is simple-polygon validation. Its Rust implementation
is checked against the Python reference for diagnostic codes, ordering,
messages, severity, and tolerance behaviour. The Python dispatcher uses the
native path for contours with at least 32 vertices when a compatible native
wheel is present; otherwise it uses the Python reference implementation.

This first operation proves the extension build, ABI, bridge, fallback, and
differential-test pipeline. It is not expected to produce a large end-to-end
roof-generation speedup by itself.

## Performance baseline and migration order

CI measurements from the current Python implementation provide these reference
cases (runner-dependent; compare like-for-like on the same runner):

- 64-edge concave weighted-wavefront surface, variable pitch: approximately
  319 ms.
- 64-edge variable-pitch wavy L/U wavefront surface: approximately 344–345 ms.
- 96-point mixed-height exact spatial L/U surface: approximately 487–500 ms.

The next Rust work should be selected from profiles of the current production
paths, not from the separate legacy solver. Priority candidates are:

1. Weighted-wavefront event scheduling, candidate generation, and moving-line
   kinematics in core/wavefront.py.
2. Exact spatial arrangement / plane intersection and face-patch assembly in
   core/exact_spatial.py.
3. Vertex welding, T-junction conformance, and topology assembly in core/mesh.py.

The existing surfer2 experiment remains a benchmark/research candidate, not
the production solver: several tested concave variable-pitch L/U cases did not
preserve projected footprint coverage or closed internal topology. It must not
replace the current solver without passing the full RoofForge geometry corpus.

## Correctness and speed gates

Every migrated operation must:

- Match the Python reference on the complete applicable regression corpus,
  including clockwise input, per-edge pitch, concave fixtures, near-degenerate
  geometry, diagnostic codes, and deterministic ordering.
- Preserve projected coverage, source-boundary continuity, face-to-slope
  metadata, manifold checks, and the current rejection behaviour for unsupported
  event classes.
- Be benchmarked independently and as part of the full roof build. Record
  median and p95 timings for the same fixtures before and after the migration.
- Be retained only when it improves measured end-to-end performance or
  provides a necessary capability without a material regression.

Do not remove the Python reference implementation until parity has remained
green across the supported Blender and Python test matrix.
