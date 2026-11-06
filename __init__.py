"""RoofForge Blender extension package."""
from .addon.registration import register, unregister

bl_info = {
    "name": "RoofForge",
    "author": "MorenDord",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > RoofForge",
    "description": "Procedural roof generation and game-ready preparation",
    "category": "Add Mesh",
}

if __name__ == "__main__":
    register()
