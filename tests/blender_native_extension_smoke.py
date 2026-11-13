"""Verify the installed Blender Extension loads and uses all bundled Rust kernels.

Run after installing the packaged extension with:
    blender --command extension install-file -r user_default -e roof_forge-0.3.21.zip
    blender --background --python tests/blender_native_extension_smoke.py
"""
from __future__ import annotations

import importlib
import math
import sys

import bpy


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"RoofForge native Blender smoke test failed: {message}")


PACKAGE_NAME = "bl_ext.user_default.roof_forge"
package = importlib.import_module(PACKAGE_NAME)
native_bridge = importlib.import_module(f"{PACKAGE_NAME}.core.native_bridge")
wavefront = importlib.import_module(f"{PACKAGE_NAME}.core.wavefront")

ensure(native_bridge.NATIVE_BACKEND_AVAILABLE, "the bundled roof_forge_native wheel did not import")
ensure(native_bridge.NATIVE_WAVEFRONT_EVENTS_AVAILABLE, "Rust wavefront event kernel is unavailable")
ensure(native_bridge.NATIVE_WAVEFRONT_INTERVAL_AVAILABLE, "Rust interval kernel is unavailable")
ensure(native_bridge.NATIVE_VERTEX_WELD_AVAILABLE, "Rust vertex-welding kernel is unavailable")
ensure(native_bridge.NATIVE_FACE_CONFORMANCE_AVAILABLE, "Rust face-conformance kernel is unavailable")

native_module = importlib.import_module("roof_forge_native")
ensure(native_module.api_version() == 1, "unexpected Rust native API version")

edge_count = 64
points = []
for index in range(edge_count):
    angle = 2.0 * math.pi * index / edge_count
    radius = 10.0 if index % 2 == 0 else 8.6
    points.append((
        radius * math.cos(angle),
        radius * math.sin(angle),
        0.0,
    ))
pitches = [
    32.0 + 4.0 * math.sin(index * 1.371)
    + 2.5 * math.cos(index * 0.613)
    for index in range(edge_count)
]

surface = wavefront.build_wavefront_roof_surface(points, pitches)
ensure(len(surface.vertices) == 2091, f"expected 2091 vertices, got {len(surface.vertices)}")
ensure(len(surface.faces) == 2089, f"expected 2089 faces, got {len(surface.faces)}")

mesh = bpy.data.meshes.new("RoofForge_NativeSmoke_Mesh")
mesh.from_pydata(
    list(surface.vertices),
    [],
    [tuple(face) for face in surface.faces],
)
mesh.update()
ensure(len(mesh.vertices) == 2091, "Blender mesh datablock has an unexpected vertex count")
ensure(len(mesh.polygons) == 2089, "Blender mesh datablock has an unexpected face count")

obj = bpy.data.objects.new("RoofForge_NativeSmoke_Roof", mesh)
bpy.context.collection.objects.link(obj)
ensure(obj.type == "MESH", "generated Blender object is not a mesh")

print("ROOFFORGE_NATIVE_BACKEND=Rust")
print("ROOFFORGE_NATIVE_KERNELS=5/5")
print("ROOFFORGE_NATIVE_ROOF=2091 vertices, 2089 faces")
print("ROOFFORGE_NATIVE_BLENDER_SMOKE_OK")
