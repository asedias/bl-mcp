"""Procedural materials and baking. Run: uv run python tests/run_headless.py tests/test_procedural.py"""

import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

importlib.import_module("bl_bridge.procedural")
importlib.import_module("bl_bridge.render")
importlib.import_module("bl_bridge.uvpaint")
from bl_bridge import core  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="bl_proc_"))
KINDS = ["wood", "checker", "diamond", "bricks", "noise", "marble"]


def plane(name, at=(0, 0, 0)):
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=at)
    obj = bpy.context.object
    obj.name = name
    return obj


def raises(label, fn, text):
    try:
        fn()
    except ValueError as err:
        expect(label, text in str(err), str(err))
    else:
        expect(label, False, "no error")


def spread(path):
    pixels = core.read_pixels(path)[:, :, :3]
    return float(pixels.std(axis=(0, 1)).max())


def shot(name, target):
    path = work / f"{name}.png"
    call("setup_lighting", {"preset": "three_point", "target": [target]})
    call("set_camera", {"frame": [target], "azimuth": 0, "elevation": 89, "fov_deg": 20, "margin": 1.05})
    call("render_final", {"path": str(path), "engine": "cycles", "size": 96, "samples": 4})
    return path


fresh_scene()
shots = {}
for i, kind in enumerate(KINDS):
    obj = plane(f"p_{kind}", (i * 3, 0, 0))
    obj.data.uv_layers.remove(obj.data.uv_layers[0])
    r = call("procedural_material", {"names": [obj.name], "kind": kind, "scale": 1.0, "material": f"m_{kind}"})
    expect(f"{kind}: material built", bpy.data.materials["m_{}".format(kind)].node_tree is not None and len(r["nodes"]) >= 4, r)
    expect(f"{kind}: unwrapped when no UV", r["unwrapped"] == [obj.name], r)
    expect(f"{kind}: slot filled", obj.data.materials[0].name == f"m_{kind}")
    shots[kind] = shot(f"proc_{kind}", obj.name)
    expect(f"{kind}: render has variation", spread(shots[kind]) > 0.02, spread(shots[kind]))

again = call("procedural_material", {"names": ["p_wood"], "kind": "wood", "material": "m_wood", "seed": 3})
expect("same name rebuilt, not duplicated", len([m for m in bpy.data.materials if m.name.startswith("m_wood")]) == 1)
expect("no second unwrap", again["unwrapped"] == [])
raises("unknown kind", lambda: call("procedural_material", {"names": ["p_wood"], "kind": "lava"}), "kind is one of")

# bake on a box without UV, wood material, 256 px
fresh_scene()
bpy.ops.mesh.primitive_cube_add(size=0.5, location=(0, 0, 0.25))
box = bpy.context.object
box.name = "board"
call("procedural_material", {"names": ["board"], "kind": "diamond", "material": "knurl"})
engine_before = bpy.context.scene.render.engine
call("unwrap", {"names": ["board"], "method": "smart"})
# the object had a UV after the material call: remove it to test the bake fallback
box.data.uv_layers.remove(box.data.uv_layers[0])
r = call("bake_maps", {"object": "board", "size": 256, "out_dir": str(work / "bake"), "samples": 4})
expect("bake unwrapped the mesh", r["unwrapped"] is True and len(box.data.uv_layers) == 1, r)
expect("scene engine restored", bpy.context.scene.render.engine == engine_before, bpy.context.scene.render.engine)
for key, path in r["maps"].items():
    expect(f"{key} file exists", Path(path).exists(), path)
    expect(f"{key} has variation", spread(path) > 0.005 or key == "ao", spread(path))
expect("normal map carries the bump", spread(r["maps"]["normal"]) > 0.01)
expect("no flat-normal note", "note" not in r, r)
mat = box.data.materials[0]
expect("one material, rebuilt", len(box.data.materials) == 1 and mat.name == "board_baked", mat.name)
images = {n.image.name: n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"}
expect("three image nodes", len(images) == 3, list(images))
spaces = {name.split("_", 1)[1].removesuffix(".png"): n.image.colorspace_settings.name for name, n in images.items()}
expect("base colour sRGB", spaces.get("base_color") == "sRGB", spaces)
expect("normal Non-Color", spaces.get("normal") == "Non-Color", spaces)
expect("roughness Non-Color", spaces.get("roughness") == "Non-Color", spaces)
expect("normal goes through Normal Map", any(n.type == "NORMAL_MAP" for n in mat.node_tree.nodes))
expect("no procedural nodes left", not any(n.type in {"TEX_WAVE", "TEX_NOISE", "BUMP"} for n in mat.node_tree.nodes))

glb = work / "board.glb"
call("export_glb", {"path": str(glb), "names": ["board"]})
info = call("inspect_glb", {"path": str(glb)})
expect("inspect_glb lists 3 images", len(info["images"]) == 3, info)
doc = core.read_glb(str(glb))[0]
pbr = doc["materials"][0]["pbrMetallicRoughness"]
expect("glb baseColorTexture", "baseColorTexture" in pbr, pbr)
expect("glb normalTexture", "normalTexture" in doc["materials"][0], doc["materials"][0])
expect("glb has 3 images", len(doc.get("images", [])) >= 3, doc.get("images"))
shot("baked_diamond", "board")

# flat-normal note, single map, fresh material from set_material
bpy.ops.mesh.primitive_cube_add(size=0.3, location=(2, 0, 0.15))
flat = bpy.context.object
flat.name = "flat"
call("set_material", {"names": ["flat"], "color": "#3366cc"})
r = call("bake_maps", {"object": "flat", "size": 64, "maps": ["base_color", "normal"], "out_dir": str(work / "flat"), "samples": 2})
expect("flat normal reported", "flat" in r.get("note", ""), r)
expect("only requested maps", set(r["maps"]) == {"base_color", "normal"}, r)
raises("bad map name", lambda: call("bake_maps", {"object": "flat", "maps": ["metal"]}), "maps are chosen from")
bpy.ops.mesh.primitive_cube_add(size=0.3, location=(4, 0, 0.15))
bpy.context.object.name = "bare"
raises("no material", lambda: call("bake_maps", {"object": "bare", "size": 64}), "no material")

# wood bake and view
fresh_scene()
bpy.ops.mesh.primitive_plane_add(size=1.0)
bpy.context.object.name = "plank"
call("procedural_material", {"names": ["plank"], "kind": "wood", "material": "oak", "scale": 1.5})
call("bake_maps", {"object": "plank", "size": 256, "out_dir": str(work / "wood"), "samples": 4})
shot("baked_wood", "plank")
print("PNG folder:", work)

finish()
