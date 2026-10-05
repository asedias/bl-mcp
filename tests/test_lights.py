"""Custom lights, post-processing, text as a mesh. Run: uv run python tests/run_headless.py tests/test_lights.py"""

import importlib
import math
import os
import sys
from pathlib import Path

import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

importlib.import_module("bl_bridge.lights")

work = Path(os.environ.get("BL_MCP_WORK", "/tmp/bl_work_lights"))
out = work / "lights_test"
out.mkdir(parents=True, exist_ok=True)


def refused(label, method, params):
    try:
        call(method, params)
        expect(label, False)
    except ValueError:
        expect(label, True)


def forward_of(obj):
    return obj.matrix_world.to_quaternion() @ Vector((0, 0, -1))


def box(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    return obj


def pixels_of(path):
    return handlers.read_pixels(path)[..., :3]


fresh_scene()
scene = bpy.context.scene
scene.world = None
floor = box("floor", (6, 6, 0.1), (0, 0, -0.05))
block = box("block", (0.6, 0.6, 0.6), (0, 0, 0.3))
call("set_camera", {"location": [0, -4, 2.5], "look_at": [0, 0, 0.2]})
call("set_world", {"preset": "dark"})

# lights
spot = call("add_light", {"kind": "spot", "name": "beam", "location": [2, -2, 3], "look_at": [0, 0, 0.3], "power_w": 800,
                          "color": "#ffcc88", "spot_size_deg": 30, "blend": 0.3, "radius": 0.1})
obj = bpy.data.objects["beam"]
data = obj.data
expect("spot kind", data.type == "SPOT" and spot["kind"] == "spot")
expect("spot size", abs(math.degrees(data.spot_size) - 30) < 1e-4, data.spot_size)
expect("spot blend and radius", abs(data.spot_blend - 0.3) < 1e-5 and abs(data.shadow_soft_size - 0.1) < 1e-5)
expect("spot power", abs(data.energy - 800) < 1e-3)
expect("spot colour is linear", abs(data.color[0] - 1.0) < 1e-3 and 0.5 < data.color[1] < 0.7 and data.color[2] < 0.3, tuple(data.color))
want = (Vector((0, 0, 0.3)) - Vector((2, -2, 3))).normalized()
expect("spot looks at the target", forward_of(obj).dot(want) > 0.99999, forward_of(obj))
expect("spot reports direction", Vector(spot["direction"]).dot(want) > 0.9999)
expect("light is not a preset", not obj.name.startswith("bl_light_") and spot["preset"] is False)

call("add_light", {"kind": "spot", "name": "beam", "location": [-2, -2, 3], "look_at": [0, 0, 0.3], "power_w": 300, "spot_size_deg": 60})
expect("repeat updates, no copy", len([o for o in bpy.data.objects if o.name.startswith("beam")]) == 1)
expect("repeat updates the data", abs(bpy.data.objects["beam"].data.energy - 300) < 1e-3 and bpy.data.objects["beam"].location.x == -2)
expect("no orphan light data", len(bpy.data.lights) == 1, len(bpy.data.lights))
call("add_light", {"kind": "point", "name": "beam", "power_w": 100})
expect("kind change keeps the object", bpy.data.objects["beam"].data.type == "POINT" and len(bpy.data.lights) == 1)
expect("update without location keeps it", bpy.data.objects["beam"].location.x == -2)

area = call("add_light", {"kind": "area", "name": "panel", "location": [0, -2, 2], "look_at": [0, 0, 0], "size": [2, 0.5], "power_w": 200})
expect("area size", bpy.data.lights["panel"].shape == "RECTANGLE" and abs(bpy.data.lights["panel"].size - 2) < 1e-6 and abs(bpy.data.lights["panel"].size_y - 0.5) < 1e-6)
expect("area aims", forward_of(bpy.data.objects["panel"]).dot((Vector((0, 0, 0)) - Vector((0, -2, 2))).normalized()) > 0.9999)
sun = call("add_light", {"kind": "sun", "name": "sunny", "location": [0, 0, 5], "look_at": [1, 0, 0], "power_w": 3, "shadow_soft": False})
expect("sun strength and hard shadow", bpy.data.lights["sunny"].energy == 3 and bpy.data.lights["sunny"].angle == 0)
warm = call("add_light", {"kind": "point", "name": "warm", "location": [0, 0, 2], "temperature_k": 3000, "cutoff_m": 5})
expect("temperature set", bpy.data.lights["warm"].use_temperature and bpy.data.lights["warm"].temperature == 3000 and warm["cutoff_m"] == 5)

listed = call("list_lights", {})
expect("list_lights", {l["name"] for l in listed} == {"beam", "panel", "sunny", "warm"}, listed)
call("setup_lighting", {"preset": "sun"})
expect("setup_lighting keeps custom lights", "panel" in bpy.data.objects and "beam" in bpy.data.objects)
expect("list shows presets flagged", any(l["preset"] for l in call("list_lights", {})))
call("setup_lighting", {"preset": "sun"})
refused("prefix name refused", "add_light", {"name": "bl_light_x"})
refused("name of a mesh refused", "add_light", {"name": "block"})
refused("bad kind refused", "add_light", {"kind": "laser"})
refused("bad spot size refused", "add_light", {"spot_size_deg": 0})

removed = call("delete", {"names": ["warm"]})
expect("remove by name", "warm" not in bpy.data.objects and "warm" not in bpy.data.lights, removed)
call("delete", {"prefix": "pan"})
expect("remove by prefix", "panel" not in bpy.data.objects)
call("delete", {"lights": "added"})
expect("lights='added' takes tool lights only", "beam" not in bpy.data.objects and "sunny" not in bpy.data.objects and "bl_light_sun" in bpy.data.objects)
call("setup_lighting", {"preset": "three_point"})
call("delete", {"prefix": "bl_light_"})
expect("prefix can remove presets", not [o for o in bpy.data.objects if o.type == "LIGHT"] and not bpy.data.lights)
call("add_light", {"name": "mine"})
call("setup_lighting", {"preset": "sun"})
call("delete", {"lights": "all"})
expect("lights='all' removes every light and nothing else", not [o for o in bpy.data.objects if o.type == "LIGHT"] and "block" in bpy.data.objects)
refused("delete without a target is refused", "delete", {})
refused("an unknown lights value is refused", "delete", {"lights": "preset"})

# spot picture: dark scene, one cone
call("add_light", {"kind": "spot", "name": "stage", "location": [1.5, -2.5, 3.5], "look_at": [0, 0, 0.3], "power_w": 1500, "spot_size_deg": 28, "blend": 0.4})
spot_render = call("render_final", {"path": str(out / "spot.png"), "size": 256, "samples": 16})
spot_px = pixels_of(spot_render["path"])
centre = spot_px[100:156, 100:156].mean()
corner = spot_px[:20, :20].mean()
expect("spot lights the middle, not the corner", centre > 0.05 and centre > 4 * corner, (centre, corner))

# post-processing
call("delete", {"lights": "added"})
call("setup_lighting", {"preset": "soft_studio"})
call("set_world", {"preset": "white"})
plain = pixels_of(call("render_final", {"path": str(out / "plain.png"), "size": 192, "samples": 16})["path"])
info = call("set_post", {"vignette": {"strength": 0.9, "softness": 0.6}})
expect("set_post builds a tree", scene.compositing_node_group is not None and info["compositor"], info)
vig = pixels_of(call("render_final", {"path": str(out / "vignette.png"), "size": 192, "samples": 16})["path"])
corner_plain, corner_vig = plain[:12, :12].mean(), vig[:12, :12].mean()
mid_plain, mid_vig = plain[90:102, 90:102].mean(), vig[90:102, 90:102].mean()
expect("vignette darkens corners", corner_vig < corner_plain * 0.5, (corner_plain, corner_vig))
expect("vignette keeps the centre", abs(mid_vig - mid_plain) < 0.02 * max(mid_plain, 0.1) + 0.01, (mid_plain, mid_vig))
expect("vignette smooth in the middle of an edge", vig[:12, 90:102].mean() > corner_vig, (vig[:12, 90:102].mean(), corner_vig))
wb = pixels_of(call("render_final", {"path": str(out / "vignette_wb.png"), "engine": "workbench", "size": 128})["path"])
expect("vignette works with workbench", wb[:8, :8].mean() < wb[60:68, 60:68].mean() * 0.5 or wb[:8, :8].mean() < 0.1, (wb[:8, :8].mean(), wb[60:68, 60:68].mean()))

call("set_post", {"color": {"saturation": 0.0}})
expect("settings merge", scene.compositing_node_group is not None and call("set_post", {})["vignette"]["strength"] == 0.9)
grey = pixels_of(call("render_final", {"path": str(out / "grey.png"), "size": 96, "samples": 8})["path"])
expect("saturation 0 gives grey", np.abs(grey[..., 0] - grey[..., 2]).max() < 0.02, np.abs(grey[..., 0] - grey[..., 2]).max())
call("set_post", {"color": False})
call("set_post", {"glare": {"type": "bloom", "threshold": 0.5, "size": 6}})
glow = pixels_of(call("render_final", {"path": str(out / "glare.png"), "size": 96, "samples": 8})["path"])
expect("glare renders", glow.std() > 0.01)
for kind in ("fog_glow", "streaks"):
    call("set_post", {"glare": {"type": kind}})
    expect(f"glare {kind} renders", pixels_of(call("render_final", {"path": str(out / f"{kind}.png"), "size": 64, "samples": 4})["path"]).std() > 0.0)
call("set_post", {"glare": False})
expect("glare removed, vignette stays", call("set_post", {})["glare"] is None and call("set_post", {})["vignette"] is not None)

call("set_world", {"preset": "studio_grey", "strength": 0.3})
call("set_post", {"exposure": 1.0})
expect("exposure set on view settings", scene.view_settings.exposure == 1.0)
bright = pixels_of(call("render_final", {"path": str(out / "bright.png"), "size": 96, "samples": 8})["path"])
call("set_post", {"exposure": -1.0})
dim = pixels_of(call("render_final", {"path": str(out / "dim.png"), "size": 96, "samples": 8})["path"])
expect("exposure changes brightness", bright.mean() > dim.mean() * 1.3)
call("set_post", {"contrast": 0.8})
hard = pixels_of(call("render_final", {"path": str(out / "contrast.png"), "size": 96, "samples": 8})["path"])
expect("contrast changes pixels", np.abs(hard - dim).max() > 0.02)
refused("bad vignette key refused", "set_post", {"vignette": {"power": 1}})
refused("bad glare type refused", "set_post", {"glare": {"type": "star"}})
refused("vignette out of range refused", "set_post", {"vignette": {"strength": 2}})

after_reset = call("set_post", {"reset": True})
expect("reset clears the tree and exposure", scene.compositing_node_group is None and scene.view_settings.exposure == 0.0 and "bl_post" not in bpy.data.node_groups, after_reset)
call("set_world", {"preset": "white"})
back = pixels_of(call("render_final", {"path": str(out / "back.png"), "size": 192, "samples": 16})["path"])
expect("reset restores pixels", np.abs(back - plain).max() < 0.01, np.abs(back - plain).max())
call("set_post", {"reset": True})

# text
fresh_scene()
bpy.context.scene.world = None
height = 0.2
info = call("text_mesh", {"text": "H", "size": height, "depth": 0.02, "at": [0, 0, 1], "plane": "XZ", "name": "h"})
obj = bpy.data.objects["h"]
size = Vector(info["size"])
expect("cap height is size", abs(size.z - height) < 1e-4, size)
expect("depth along the normal", abs(size.y - 0.02) < 1e-5 and size.x < size.z, size)
expect("XZ plane centred on at", (Vector(info["center"]) - Vector((0, 0.01, 1))).length < 0.02 and abs(info["center"][0]) < 1e-4 and abs(info["center"][2] - 1) < 1e-4, info["center"])
expect("XZ front is -Y: back at at, front toward the viewer", info["min"][1] < 1e-5 and abs(info["min"][1] + 0.02) < 1e-4, info["min"])
checked = call("check_mesh", {"name": "h"})
expect("text mesh is closed", checked["closed"] and checked["issues"] == ["none"], checked)
top = call("text_mesh", {"text": "HI", "size": 0.1, "depth": 0.005, "at": [1, 1, 0], "plane": "XY", "name": "t2"})
expect("XY plane lies flat", top["size"][2] < 0.0051 and top["size"][1] > 0.099 and top["size"][0] > 0.05 and abs(top["min"][2]) < 1e-5, top["size"])
side = call("text_mesh", {"text": "HI", "size": 0.1, "depth": 0.005, "plane": "YZ", "name": "t3"})
expect("YZ plane stands on the side", side["size"][0] < 0.0051 and side["size"][2] > 0.099, side["size"])
left = call("text_mesh", {"text": "ABC", "size": 0.1, "align": "left", "name": "t4", "at": [2, 0, 0]})
right = call("text_mesh", {"text": "ABC", "size": 0.1, "align": "right", "name": "t5", "at": [2, 0, 0]})
expect("align left and right", abs(left["min"][0] - 2) < 1e-4 and abs(right["max"][0] - 2) < 1e-4, (left["min"], right["max"]))
two = call("text_mesh", {"text": "AB\nCD", "size": 0.1, "name": "t6"})
expect("two lines are taller", two["size"][2] > 0.18, two["size"])
call("text_mesh", {"text": "HI", "size": 0.1, "name": "t6"})
expect("same name replaces", len([o for o in bpy.data.objects if o.name.startswith("t6")]) == 1)
bevelled = call("text_mesh", {"text": "O", "size": 0.1, "depth": 0.02, "bevel": 0.002, "name": "b"})
expect("bevelled text is closed", call("check_mesh", {"name": "b"})["closed"])
ru = call("text_mesh", {"text": "Кто убийца", "size": 0.1, "name": "ru"})
en = call("text_mesh", {"text": "Who is it", "size": 0.1, "name": "en"})
expect("Cyrillic has outlines", ru["size"][0] > 0.4 and len(bpy.data.objects["ru"].data.vertices) > 200, (ru["size"], len(bpy.data.objects["ru"].data.vertices)))
refused("empty text refused", "text_mesh", {"text": "  "})
refused("bad plane refused", "text_mesh", {"text": "a", "plane": "ZZ"})
refused("bad font refused", "text_mesh", {"text": "a", "font": "/nope/none.ttf"})
refused("name of other object refused", "text_mesh", {"text": "a", "name": "ru_x_missing", "on_object": "nothing"})
bpy.ops.mesh.primitive_cube_add(size=1, location=(5, 5, 5))
bpy.context.object.name = "other"
refused("text name over other object refused", "text_mesh", {"text": "a", "name": "other"})

# surface placement
fresh_scene()
bpy.context.scene.world = None
slab = box("slab", (0.5, 0.2, 0.3), (0, 0, 0))
placed = call("text_mesh", {"text": "ID", "size": 0.05, "depth": 0.004, "at": [0.1, -5, 0.02], "plane": "XZ", "on_object": "slab", "offset": 0.001, "name": "decal"})
expect("decal sits on the front face", abs(placed["surface"]["point"][1] + 0.1) < 1e-4 and abs(placed["min"][1] + 0.1 + 0.001 + 0.004) < 1e-4 and abs(placed["max"][1] + 0.1 + 0.001) < 1e-4, (placed["surface"], placed["min"], placed["max"]))
expect("decal x follows at", abs(placed["center"][0] - 0.1) < 1e-4 and abs(placed["center"][2] - 0.02) < 1e-4, placed["center"])
refused("miss refused", "text_mesh", {"text": "ID", "at": [5, 0, 0], "on_object": "slab", "name": "miss"})
refused("engrave without object refused", "text_mesh", {"text": "ID", "engrave": True})

call("set_material", {"names": ["slab"], "color": "#808080", "material": "slab_grey"})
cut = call("text_mesh", {"text": "ID", "size": 0.06, "depth": 0.01, "at": [0, 0, 0], "plane": "XZ", "on_object": "slab", "engrave": True})
expect("engrave removes volume", cut["removed_volume"] > 1e-7 and cut["volume_after"] < cut["volume_before"], cut)
expect("engrave adds faces", cut["faces_after"] > cut["faces_before"], cut)
expect("engrave removes about depth x glyph area", cut["removed_volume"] < 0.06 * 0.12 * 0.01, cut["removed_volume"])
expect("engrave leaves a closed slab", call("check_mesh", {"name": "slab"})["closed"], call("check_mesh", {"name": "slab"}))
expect("engrave keeps the outer size", abs(Vector(call("describe", {"name": "slab"})["size"]).x - 0.5) < 1e-4 if "describe" in handlers.HANDLERS else True)
expect("engraved faces take the slab material and no empty slot is left", [s.material.name if s.material else None for s in slab.material_slots] == ["slab_grey"]
       and {p.material_index for p in slab.data.polygons} == {0}, [s.material for s in slab.material_slots])
expect("engrave leaves no tool object", sorted(o.name for o in bpy.data.objects) == ["decal", "slab"], [o.name for o in bpy.data.objects])

# pictures
bpy.data.objects.remove(bpy.data.objects["decal"])
call("set_world", {"preset": "studio_grey"})
call("setup_lighting", {"preset": "three_point", "target": ["slab"]})
call("text_mesh", {"text": "WHO", "size": 0.04, "depth": 0.004, "at": [0, -0.1, 0.1], "plane": "XZ", "on_object": "slab", "name": "label"})
call("set_camera", {"frame": ["slab"], "azimuth": 20, "elevation": 15})
call("render_final", {"path": str(out / "text.png"), "size": 384, "samples": 32})

finish()
