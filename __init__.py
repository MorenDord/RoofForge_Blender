"""RoofForge Blender extension package."""
from .addon.registration import register, unregister

bl_info = {
    "name": "RoofForge",
    "author": "MorenDord",
    "version": (0, 3, 1),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > RoofForge",
    "description": "Procedural roof shell generator",
    "category": "Add Mesh",
}

if __name__ == "__main__":
    register()
