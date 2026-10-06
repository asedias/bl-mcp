"""Camera, lights, world, render, save. Run: uv run python tests/run_headless.py tests/test_render.py"""

import importlib
import os
import sys
from pathlib import Path

from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

importlib.import_module("bl_bridge.render")


def box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    return obj


def forward_of(name):
    return bpy.data.objects[name].matrix_world.to_quaternion() @ Vector((0, 0, -1))


def project_corners(cam, obj):
    scene = bpy.context.scene
    from bpy_extras.object_utils import world_to_camera_view

    return [world_to_camera_view(scene, cam, obj.matrix_world @ Vector(c)) for c in obj.bound_box]


work = Path(os.environ.get("BL_MCP_WORK", "/tmp/bl_work_render"))
out = work / "render_test"
out.mkdir(parents=True, exist_ok=True)

fresh_scene()
a = box("a", (1.0, 0.5, 2.0), (0, 0, 1))
b = box("b", (0.6, 0.6, 0.6), (3, 1, 0.3))
bpy.context.scene.world = None

# camera: explicit aim
info = call("set_camera", {"location": [4, -6, 3], "look_at": [0, 0, 1]})
want = (Vector((0, 0, 1)) - Vector((4, -6, 3))).normalized()
expect("camera looks at target", forward_of("camera").dot(want) > 0.9999, forward_of("camera"))
expect("camera becomes active", bpy.context.scene.camera.name == "camera")
call("set_camera", {"name": "side", "location": [0, -5, 1], "look_at": [0, 0, 1], "make_active": False})
expect("make_active=False keeps camera", bpy.context.scene.camera.name == "camera")
call("set_camera", {"look_at": [0, 0, 0]})
expect("update keeps location", (bpy.data.objects["camera"].location - Vector((4, -6, 3))).length < 1e-5)
expect("update re-aims", forward_of("camera").dot((Vector((0, 0, 0)) - Vector((4, -6, 3))).normalized()) > 0.9999)
call("set_camera", {"name": "side", "location": [0, -5, 1], "look_at": [0, 0, 1], "roll_deg": 90})
up = bpy.data.objects["side"].matrix_world.to_quaternion() @ Vector((0, 1, 0))
expect("roll tilts the camera", abs(up.z) < 0.01, up)
try:
    call("set_camera", {"name": "a", "location": [1, 1, 1], "look_at": [0, 0, 0]})
    expect("camera name clash is refused", False)
except ValueError:
    expect("camera name clash is refused", True)

# frame mode
for az, el in ((0, 20), (135, 40), (270, 70)):
    call("set_camera", {"name": "fit", "frame": ["a", "b"], "azimuth": az, "elevation": el, "fov_deg": 35})
    cam = bpy.data.objects["fit"]
    pts = [p for o in (a, b) for p in project_corners(cam, o)]
    inside = all(0 <= p.x <= 1 and 0 <= p.y <= 1 and p.z > 0 for p in pts)
    spread = max(max(p.x for p in pts) - min(p.x for p in pts), max(p.y for p in pts) - min(p.y for p in pts))
    expect(f"frame fits az={az} el={el}", inside and spread > 0.4, spread)
call("set_camera", {"name": "fit", "frame": ["a", "b"], "fov_deg": 0})
cam = bpy.data.objects["fit"]
pts = [p for o in (a, b) for p in project_corners(cam, o)]
expect("ortho frame fits", cam.data.type == "ORTHO" and all(0 <= p.x <= 1 and 0 <= p.y <= 1 for p in pts))
for bad in ({"azimuth": 10}, {}):
    try:
        call("set_camera", {"name": "fresh", **bad})
        expect(f"bad set_camera {bad} refused", False)
    except ValueError:
        expect(f"bad set_camera {bad} refused", True)

# lighting
before_cameras = bpy.context.scene.camera
for preset, count in (("three_point", 3), ("sun", 1), ("soft_studio", 4), ("night", 2)):
    call("setup_lighting", {"preset": preset})
    lights = [o for o in bpy.data.objects if o.name.startswith("bl_light_")]
    expect(f"lights {preset}", len(lights) == count, len(lights))
call("setup_lighting", {"preset": "three_point", "target": ["a"], "color": "#ffeedd"})
call("setup_lighting", {"preset": "three_point", "target": ["a"]})
expect("no duplicate lights", len([o for o in bpy.data.objects if o.name.startswith("bl_light_")]) == 3)
expect("no orphan light data", len(bpy.data.lights) == 3, len(bpy.data.lights))
key = bpy.data.objects["bl_light_key"]
aimed = (key.matrix_world.to_quaternion() @ Vector((0, 0, -1))).dot((Vector((0, 0, 1)) - key.location).normalized())
expect("key light aims at target", aimed > 0.999, aimed)
expect("lighting leaves scene camera", bpy.context.scene.camera is before_cameras)
try:
    call("setup_lighting", {"preset": "nope"})
    expect("unknown preset refused", False)
except ValueError:
    expect("unknown preset refused", True)

# world
call("set_world", {"preset": "studio_grey"})
bg = next(n for n in bpy.context.scene.world.node_tree.nodes if n.type == "BACKGROUND")
expect("world preset", abs(bg.inputs["Color"].default_value[0] - 0.18) < 1e-3)
call("set_world", {"color": "#ff0000", "strength": 2.0})
bg = next(n for n in bpy.context.scene.world.node_tree.nodes if n.type == "BACKGROUND")
expect("world colour and strength", bg.inputs["Color"].default_value[0] > 0.9 and bg.inputs["Strength"].default_value == 2.0)
call("set_world", {"preset": "studio_grey"})

# render
scene = bpy.context.scene
call("set_camera", {"frame": ["a", "b"], "azimuth": 30, "elevation": 25})
snapshot = (scene.render.engine, scene.render.resolution_x, scene.render.resolution_y, scene.render.filepath,
            scene.render.film_transparent, scene.render.image_settings.file_format, scene.camera)
result = call("render_final", {"path": str(out / "eevee.png"), "size": 160, "samples": 8})
pixels = handlers.read_pixels(result["path"])
expect("eevee PNG size", pixels.shape[:2] == (160, 160), pixels.shape)
expect("eevee has pixel spread", pixels[..., :3].std() > 0.02, pixels[..., :3].std())
expect("render result fields", {"path", "size", "seconds", "engine"} <= set(result), result)
after = (scene.render.engine, scene.render.resolution_x, scene.render.resolution_y, scene.render.filepath,
         scene.render.film_transparent, scene.render.image_settings.file_format, scene.camera)
expect("scene settings restored", snapshot == after, (snapshot, after))

result = call("render_final", {"path": str(out / "cycles.png"), "engine": "cycles", "size": [128, 96], "samples": 8})
pixels = handlers.read_pixels(result["path"])
expect("cycles non-square size", pixels.shape[:2] == (96, 128), pixels.shape)
expect("cycles has pixel spread", pixels[..., :3].std() > 0.02)
expect("cycles engine name", result["engine"] == "CYCLES")

result = call("render_final", {"path": str(out / "wb.png"), "engine": "workbench", "size": 96})
expect("workbench renders", handlers.read_pixels(result["path"])[..., :3].std() > 0.02)

call("set_world", {"preset": "studio_grey", "transparent": True})
result = call("render_final", {"path": str(out / "alpha.png"), "size": 128, "samples": 8, "transparent": True})
alpha = handlers.read_pixels(result["path"])[..., 3]
expect("transparent has alpha < 1", alpha.min() < 0.01 and alpha.max() > 0.99, (alpha.min(), alpha.max()))
call("set_world", {"preset": "studio_grey", "transparent": False})

for bad in ({"engine": "nope"}, {"file_format": "XYZ"}, {"size": 0}):
    try:
        call("render_final", {"path": str(out / "bad.png"), **bad})
        expect(f"bad render args {bad} refused", False)
    except ValueError:
        expect(f"bad render args {bad} refused", True)
expect("failed render keeps settings", scene.render.engine == snapshot[0])

# save
before_path = bpy.data.filepath
saved = call("save_blend", {"path": str(out / "copy")})
expect("save_blend writes file", Path(saved["path"]).exists() and Path(saved["path"]).suffix == ".blend" and Path(saved["path"]).stat().st_size > 0)
expect("save_blend keeps current file", bpy.data.filepath == before_path, bpy.data.filepath)
call("save_blend", {"path": str(out / "current.blend"), "make_current": True})
expect("make_current renames", bpy.data.filepath.endswith("current.blend"))

# render_view from a standing point: the wall in front fills the picture, the box behind it does not show
box("wall_front", (6.0, 0.3, 3.0), (0, 2, 1.5))
box("behind", (1.0, 1.0, 1.0), (0, 6, 0.5))
seen = call("render_view", {"eye": [0, -1, 1.6], "look_at": [0, 6, 1.6], "fov": 60, "mode": "ids", "size": 128, "name": "eye_view", "isolate": False})
expect("a view from a point reports the camera at that point", [round(v, 2) for v in seen["camera_at"]] == [0.0, -1.0, 1.6], seen["camera_at"])
pixels = handlers.read_pixels(seen["path"])
colours = {tuple((pixels[y, x, :3] * 255).astype(int) // 32) for y in range(0, 128, 8) for x in range(0, 128, 8)}
expect("the wall in front hides the box behind", len(colours) <= 3, len(colours))
refused = False
try:
    call("render_view", {"eye": [0, -1, 1.6], "size": 64})
except ValueError:
    refused = True
expect("eye without look_at is refused", refused)
call("delete", {"names": ["wall_front", "behind"]})


finish()
