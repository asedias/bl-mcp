"""Builds a small oil lantern through the handlers and writes the README pictures into docs/img.

Run: "$(uv run bl-mcp-find-blender)" -b --factory-startup --python tests/readme_images.py
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("BL_MCP_WORK", str(Path(tempfile.gettempdir()) / "bl_mcp_readme"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
DEMO = OUT.parent / "demo"
TEX = DEMO / "tex"
LIMIT = 400_000
METAL = ["lamp_base", "lamp_cap", "lamp_ribs", "lamp_handle", "lamp_pivot_L", "lamp_pivot_R", "lamp_knob"]
PROP = [*METAL, "lamp_glass", "lamp_flame"]
TANK_WIDTH = 0.17
BACKDROP = "#242426"


def shrink(path):
    while path.stat().st_size > LIMIT:
        image = bpy.data.images.load(str(path))
        image.scale(round(image.size[0] * 0.85), round(image.size[1] * 0.85))
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
    print(f"{path.name}: {path.stat().st_size // 1024} KB")


def copy_image(source, name):
    target = OUT / name
    target.write_bytes(Path(source).read_bytes())
    shrink(target)


def text_of(result):
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def arc(radius, center_z, steps=24):
    return [[radius * math.cos(math.radians(a)), 0, center_z + radius * math.sin(math.radians(a))] for a in [180 - 180 * i / steps for i in range(steps + 1)]]


fresh_scene()
call("lathe", {"name": "lamp_base", "segments": 48, "cap": True, "profile": [
    [0, 0], [0.075, 0], [0.085, 0.012], [0.085, 0.055], [0.075, 0.07], [0.05, 0.078], [0.05, 0.088], [0.04, 0.088], [0.04, 0.1], [0.018, 0.1], [0.018, 0.118], [0, 0.118],
]})
call("lathe", {"name": "lamp_glass", "segments": 48, "profile": [[0.038, 0.1], [0.05, 0.125], [0.054, 0.16], [0.05, 0.195], [0.04, 0.215], [0.036, 0.222]]})
call("solidify", {"object": "lamp_glass", "thickness": 0.0025})
call("lathe", {"name": "lamp_flame", "segments": 24, "cap": True, "profile": [[0, 0.118], [0.008, 0.121], [0.012, 0.136], [0.007, 0.158], [0, 0.172]]})
call("lathe", {"name": "lamp_cap", "segments": 48, "cap": True, "profile": [[0, 0.218], [0.07, 0.218], [0.07, 0.228], [0.03, 0.255], [0.022, 0.262], [0, 0.262]]})
call("bevel_edges", {"object": "lamp_cap", "width": 0.0015, "segments": 2})
call("create_primitive", {"kind": "cube", "name": "lamp_vent", "size": [0.03, 0.01, 0.012], "at": [0.05, 0, 0.238]})
call("radial_array", {"object": "lamp_vent", "count": 8, "axis": "Z"})
vents = call("boolean", {"a": "lamp_cap", "b": "lamp_vent", "operation": "difference"})
r = 0.08 * math.cos(math.radians(45))
call("sweep", {"name": "lamp_rib", "radius": 0.0035, "sides": 12, "path": [[r, r, 0.062], [r * 1.03, r * 1.03, 0.1], [r * 0.98, r * 0.98, 0.2], [r * 0.85, r * 0.85, 0.222]]})
call("radial_array", {"object": "lamp_rib", "count": 4, "axis": "Z", "name": "lamp_ribs"})
call("sweep", {"name": "lamp_handle", "radius": 0.004, "sides": 12, "path": arc(0.074, 0.223)})
call("create_primitive", {"kind": "sphere", "name": "lamp_pivot_L", "size": [0.014, 0.014, 0.014], "at": [-0.073, 0, 0.223], "segments": 16})
call("mirror", {"name": "lamp_pivot_L", "axis": "X", "at": 0})
call("create_primitive", {"kind": "cylinder", "name": "lamp_knob", "size": [0.02, 0.02, 0.014], "at": [-0.09, 0, 0.045], "segments": 24, "rotate_deg": [0, 90, 0]})
base_bevel = call("bevel_edges", {"object": "lamp_base", "width": 0.002, "segments": 2})
call("bevel_edges", {"object": "lamp_knob", "width": 0.0015, "segments": 2})
engraved = call("text_mesh", {"text": "No.7", "size": 0.016, "depth": 0.002, "at": [0, -0.085, 0.034], "plane": "XZ", "on_object": "lamp_base", "engrave": True})
print(text_of(engraved))
call("shade", {"names": PROP, "mode": "auto", "angle": 50, "weighted_normals": True})
call("shade", {"names": ["lamp_cap"], "mode": "auto", "angle": 25, "weighted_normals": True})
call("unwrap", {"names": PROP, "method": "smart"})

call("set_material", {"names": METAL, "color": "#9a7a48", "material": "lamp_brass", "metallic": 1.0, "roughness": 0.3})
call("set_material", {"names": ["lamp_glass"], "color": "#f4f8fa", "roughness": 0.05, "alpha": 0.1, "coat": 0.5})
call("set_material", {"names": ["lamp_flame"], "color": "#ffb347", "roughness": 0.5, "emission": {"color": "#ffb347", "strength": 4}})
floating = call("find_floating", {"names": PROP, "ground_z": 0.0})
print(text_of(floating))
expect("no part floats", floating["floating"] == ["none"], floating["floating"])
for a, b in [("lamp_pivot_L", "lamp_cap"), ("lamp_pivot_R", "lamp_cap"), ("lamp_handle", "lamp_pivot_L"), ("lamp_ribs", "lamp_base"), ("lamp_ribs", "lamp_cap")]:
    contact = call("check_contacts", {"a": a, "b": b})
    expect(f"{a} meets {b}", contact["state"] != "apart", contact)
if failures:
    finish()
spec = call("assert_spec", {"checks": [
    {"type": "on_ground", "object": "lamp_base"},
    {"type": "contact", "a": "lamp_glass", "b": "lamp_base", "state": "connected"},
    {"type": "contact", "a": "lamp_cap", "b": "lamp_ribs", "state": "connected"},
    {"type": "inside", "object": "lamp_flame", "container": "lamp_glass"},
    {"type": "symmetry", "objects": ["lamp_cap", "lamp_ribs", "lamp_handle", "lamp_pivot_L", "lamp_pivot_R", "lamp_glass"], "axis": "X", "at": 0},
    {"type": "connected", "names": PROP, "ground_z": 0.0},
]})
print(text_of(spec))
print(text_of(call("check_game_ready", {"names": PROP, "max_tris": 20000, "budget_only": True})))

answers = [
    ("measure", {"names": ["lamp_base", "lamp_glass"]}, call("measure", {"names": ["lamp_base", "lamp_glass"]})),
    ("check_mesh", {"name": "lamp_base"}, call("check_mesh", {"name": "lamp_base"})),
    ("bevel_edges", {"object": "lamp_base", "width": 0.002, "segments": 2}, base_bevel),
    ("boolean", {"a": "lamp_cap", "b": "lamp_vent", "operation": "difference"}, vents),
    ("find_floating", {"names": PROP, "ground_z": 0.0}, floating),
]
(OUT / "answers.txt").write_text("".join(f"--- {tool} {json.dumps(args)}\n{text_of(result)}\n\n" for tool, args, result in answers))

HEIGHT = call("measure", {"names": ["lamp_handle"]})[0]["max"][2]
sheet = call("render_sheet", {"names": PROP, "size": 384})
copy_image(sheet["path"], "sheet.png")

reference = call("render_view", {"target": PROP, "azimuth": 0, "elevation": 0, "fov": 0, "mode": "ids", "size": 768, "name": "lamp_front_ids"})
call("set_dimensions", {"name": "lamp_base", "x": TANK_WIDTH * 1.15, "y": TANK_WIDTH * 1.15, "anchor": [0.5, 0.5, 0]})
compared = call("compare_view", {"reference": reference["path"], "view": "front", "names": PROP, "height_m": HEIGHT, "size": 400, "bands": 12, "out": str(OUT / "compare.png")})
shrink(OUT / "compare.png")
keep = ("view", "iou_registered", "iou_outline", "reference_size_m", "model_size_m", "worst_bands")
trimmed = {key: compared[key] for key in keep}
trimmed["inner_detail"] = {key: compared["inner_detail"][key] for key in ("edge_agreement", "reference_edges_matched", "model_edges_matched")}
(OUT / "compare.json").write_text(json.dumps(trimmed, indent=2) + "\n")
print(json.dumps(trimmed, indent=2))
call("set_dimensions", {"name": "lamp_base", "x": TANK_WIDTH, "y": TANK_WIDTH, "anchor": [0.5, 0.5, 0]})

call("procedural_material", {"names": METAL, "kind": "worn_metal", "material": "lamp_brass", "color_a": "#9a7a48", "color_b": "#1a1410", "scale": 3.0, "params": {"dirt": 0.7, "edge_wear": 0.6}})
call("combine", {"names": METAL, "name": "lamp_metal"})
call("unwrap", {"names": ["lamp_metal"], "method": "smart"})
call("shade", {"names": ["lamp_metal"], "mode": "auto", "angle": 25, "weighted_normals": True})
baked = call("bake_maps", {"object": "lamp_metal", "size": 1024, "maps": ["base_color", "normal", "orm"], "bevel_radius": 0.0015, "samples": 16, "out_dir": str(TEX)})
print(text_of(baked))

call("create_primitive", {"kind": "plane", "name": "backdrop_floor", "size": [40, 40, 1], "at": [0, 0, 0]})
call("set_material", {"names": ["backdrop_floor"], "color": BACKDROP, "roughness": 0.8})
call("set_world", {"color": BACKDROP, "hdri": "interior", "strength": 1.0, "visible_to_camera": False})
call("add_light", {"kind": "spot", "name": "key", "location": [0.9, -0.8, 1.1], "look_at": [0, 0, 0.17], "power_w": 160, "spot_size_deg": 120, "blend": 0.9, "radius": 0.15})
call("add_light", {"kind": "spot", "name": "rim", "location": [-0.7, 0.9, 0.8], "look_at": [0, 0, 0.17], "power_w": 120, "color": "#dce6ff", "spot_size_deg": 100, "blend": 0.9, "radius": 0.1})
call("add_light", {"kind": "area", "name": "fill", "location": [-1.3, -0.9, 0.5], "look_at": [0, 0, 0.17], "power_w": 30, "size": 1.0})
call("add_light", {"kind": "point", "name": "flame_glow", "location": [0, 0, 0.14], "power_w": 3, "color": "#ffa040", "radius": 0.01})
call("set_post", {"glare": {"type": "bloom", "threshold": 3.0, "size": 5}, "vignette": {"strength": 0.35, "softness": 0.6}})
bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = 1200, 760
call("set_camera", {"frame": ["lamp_metal", "lamp_glass"], "azimuth": -30, "elevation": 24, "fov_deg": 26, "margin": 1.1})
final = call("render_final", {"path": str(OUT / "final.png"), "engine": "cycles", "size": [1200, 760], "samples": 128, "auto_exposure": True})
print(text_of(final))
shrink(OUT / "final.png")

for image in bpy.data.images:
    if image.filepath.endswith(".exr"):
        image.pack()
    elif Path(bpy.path.abspath(image.filepath)).parent == TEX:
        image.filepath = f"//tex/{Path(image.filepath).name}"
call("set_post", {"exposure": final["exposure"]})
bpy.context.scene.render.engine = "CYCLES"
bpy.context.scene.cycles.samples = 128
saved = call("save_blend", {"path": str(DEMO / "lantern.blend")})
(DEMO / "lantern.blend1").unlink(missing_ok=True)
print(text_of(saved))

print("files:", sorted(p.name for p in OUT.iterdir()))
finish()
