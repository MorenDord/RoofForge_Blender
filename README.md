# RoofForge

Procedural roof generation for Blender 5.0+ with a focus on reliable geometry and game-ready output.

> **Development status:** 1.0 scaffold / early alpha. The current branch is not a feature-complete roof generator. Do not use it as a production replacement for the 0.3 prototype yet.

## Project documents
- [Technical specification](docs/SPECIFICATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development roadmap](docs/ROADMAP.md)

## Install for development
1. Download or clone this repository.
2. In Blender 5.0+, install the repository folder as an extension package or package it according to Blender's Extension workflow.
3. Enable **RoofForge**.
4. Open Viewport Sidebar (`N`) → RoofForge.
5. The current scaffold exposes initial settings and a boundary-loop validation operation.

## Current implementation
- Blender extension manifest and registration scaffold.
- Pure Python 2D polygon validation and half-plane clipping primitives.
- Lower-envelope region clipping for convex domains.
- Selected closed-edge-loop reader and initial UI panel.

## Not implemented yet
- Complete 3D plane construction from mixed-height boundary points.
- Concave polygon constrained triangulation and robust region partition.
- Roof mesh assembly and closed shell.
- Interactive pitch map, live rebuild lifecycle and detach.
- Ridge/valley/hip junction solver, standing seams.
- Existing-mesh analyzer, UV/LOD/export pipeline.

## Development principles
- Source geometry is immutable.
- Build into temporary data, validate, then swap.
- Never destroy last-valid output on failed rebuild.
- Stable UUIDs identify slopes and generated parts.
- Pure geometry code must be testable outside Blender.
- Blender datablock changes happen on Blender's main thread.

## License
GPL-3.0-or-later.
