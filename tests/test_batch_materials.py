"""Material maps, slot cleanup, HDRI world, exposure, metal lighting, baking as a job.
Run: uv run python tests/run_headless.py tests/test_batch_materials.py"""

import importlib
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

for module in ("materials", "render", "procedural", "lights", "uvpaint"):
    importlib.import_module(f"bl_bridge.{module}")
from bl_bridge import core  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="bl_batch_"))


def box(name, at=(0, 0, 0), size=1.0):
    bpy.ops.mesh.primitive_cube_add(size=size, location=at)
    obj = bpy.context.object
    obj.name = name
    return obj


def ball(name, at=(0, 0, 0), radius=0.5):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=at, segments=32, ring_count=16)
    obj = bpy.context.object
    obj.name = name
    bpy.ops.object.shade_smooth()
    return obj


def raises(label, fn, text):
    try:
        fn()
    except ValueError as err:
        expect(label, text in str(err), str(err))
    except Exception as err:
        expect(label, False, repr(err))
    else:
        expect(label, False, "no error")


def flat_image(name, rgb, size=8):
    path = work / f"{name}.png"
    core.write_pixels(path, np.tile(np.array([*rgb, 1.0], dtype=np.float32), (size, size, 1)))
    return str(path)


def exported(names, label):
    path = work / f"{label}.glb"
    call("export_glb", {"path": str(path), "names": names})
    doc, binary, _ = core.read_glb(str(path))
    return doc, binary


def glb_pixel(doc, binary, texture_index, label):
    """The middle pixel of an embedded texture, read back through Blender."""
    image = doc["images"][doc["textures"][texture_index]["source"]]
    view = doc["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    path = work / f"{label}_embedded.png"
    path.write_bytes(binary[start : start + view["byteLength"]])
    pixels = core.read_pixels(path)
    return pixels[pixels.shape[0] // 2, pixels.shape[1] // 2]


def run_job(started, limit=100000):
    progress = []
    for _ in range(limit):
        handlers.advance_jobs()
        state = call("job_status", {"job": started["job"]})
        if state.get("progress") and state["progress"] not in progress:
            progress.append(state["progress"])
        if state["status"] != "running":
            return state, progress
    return state, progress


def mesh_of(name):
    return bpy.data.objects[name].data


# 1. roughness, metallic and ORM maps, tint
fresh_scene()
grey = flat_image("grey", (0.5, 0.5, 0.5))
rough = flat_image("rough", (0.25, 0.25, 0.25))
metal = flat_image("metal", (0.75, 0.75, 0.75))
orm = flat_image("orm", (0.2, 0.4, 0.9))
normal = flat_image("normal", (0.5, 0.5, 1.0))
for name in ("tinted", "split", "packed", "veil", "plain"):
    box(name).data.uv_layers.active.name = "UVMap"

r = call("set_material", {"names": ["tinted"], "color": "#804020", "texture": grey, "material": "m_tint"})
bsdf = next(n for n in bpy.data.materials["m_tint"].node_tree.nodes if n.type == "BSDF_PRINCIPLED")
mix = bsdf.inputs["Base Color"].links[0].from_node
expect("tint is a multiply on the texture", mix.type == "MIX" and mix.blend_type == "MULTIPLY", mix.type)
expect("answer tells the glTF factor", abs(r["gltf"]["baseColorFactor"][0] - core.parse_color("#804020")[0]) < 1e-3, r["gltf"])
expect("answer lists the base texture", r["gltf"]["textures"] == ["baseColorTexture"], r["gltf"])
info = call("list_materials", {"name": "m_tint"})
expect("info keeps the tint and the texture", info["color"] == "#804020" and info["texture"].endswith("grey.png"), info)
expect("tint is not a procedural node", info["procedural_nodes"] == [], info["procedural_nodes"])
doc, binary = exported(["tinted"], "tinted")
pbr = doc["materials"][0]["pbrMetallicRoughness"]
want = core.parse_color("#804020")
expect("glb baseColorFactor is the tint", all(abs(a - b) < 2e-3 for a, b in zip(pbr.get("baseColorFactor", [1, 1, 1]), want)), pbr)
expect("glb keeps the base texture under the tint", "baseColorTexture" in pbr, pbr)

r = call("set_material", {"names": ["split"], "color": "#ffffff", "roughness_map": rough, "metallic_map": metal,
                              "normal_map": normal, "material": "m_split"})
expect("answer lists the metal-rough texture", "metallicRoughnessTexture" in r["gltf"]["textures"] and r["gltf"]["roughnessFactor"] == 1.0, r["gltf"])
info = call("list_materials", {"name": "m_split"})
expect("info has both map paths", info["roughness_map"].endswith("rough.png") and info["metallic_map"].endswith("metal.png"), info)
expect("maps are not procedural", info["procedural_nodes"] == [] and call("list_materials", {})["materials"][-1]["not_exported"] is False, info)
doc, binary = exported(["split"], "split")
pbr = doc["materials"][0]["pbrMetallicRoughness"]
expect("glb metallicRoughnessTexture from two maps", "metallicRoughnessTexture" in pbr, pbr)
if "metallicRoughnessTexture" in pbr:
    pixel = glb_pixel(doc, binary, pbr["metallicRoughnessTexture"]["index"], "split")
    expect("glb G is roughness, B is metallic", abs(pixel[1] - 0.25) < 0.02 and abs(pixel[2] - 0.75) < 0.02, pixel)
expect("glb factors stay 1 with maps", pbr.get("roughnessFactor", 1) == 1 and pbr.get("metallicFactor", 1) == 1, pbr)
expect("glb normal texture", "normalTexture" in doc["materials"][0])

r = call("set_material", {"names": ["packed"], "color": "#ffffff", "orm_map": orm, "material": "m_orm"})
expect("answer lists occlusion", {"metallicRoughnessTexture", "occlusionTexture"} <= set(r["gltf"]["textures"]), r["gltf"])
expect("info has the occlusion map", call("list_materials", {"name": "m_orm"})["occlusion_map"].endswith("orm.png"))
doc, binary = exported(["packed"], "packed")
gm = doc["materials"][0]
pbr = gm["pbrMetallicRoughness"]
expect("glb ORM: metal-rough and occlusion", "metallicRoughnessTexture" in pbr and "occlusionTexture" in gm, gm)
if "metallicRoughnessTexture" in pbr and "occlusionTexture" in gm:
    expect("glb ORM is one texture", pbr["metallicRoughnessTexture"]["index"] == gm["occlusionTexture"]["index"] and len(doc["images"]) == 1, gm)
    pixel = glb_pixel(doc, binary, pbr["metallicRoughnessTexture"]["index"], "packed")
    expect("glb ORM channels", abs(pixel[0] - 0.2) < 0.02 and abs(pixel[1] - 0.4) < 0.02 and abs(pixel[2] - 0.9) < 0.02, pixel)
raises("orm with a single map refused", lambda: call("set_material", {"names": ["packed"], "color": "#ffffff", "orm_map": orm, "roughness_map": rough}), "not both")
bare = box("no_uv")
bare.data.uv_layers.remove(bare.data.uv_layers[0])
raises("maps need a UV", lambda: call("set_material", {"names": ["no_uv"], "color": "#ffffff", "roughness_map": rough}), "UV")
bpy.data.objects.remove(bare)

# 2. alpha mode
call("set_material", {"names": ["veil"], "color": "#ffffff", "alpha": 0.5, "texture": grey, "material": "m_veil"})
call("set_material", {"names": ["plain"], "color": "#445566", "material": "m_plain"})
info = call("list_materials", {"name": "m_plain"})
expect("opaque material reports OPAQUE", info["alpha_mode"] == "OPAQUE", info["alpha_mode"])
expect("render method is told apart", info["render_method"] == "DITHERED", info["render_method"])
expect("textured opaque reports OPAQUE", call("list_materials", {"name": "m_tint"})["alpha_mode"] == "OPAQUE")
expect("see-through reports BLEND", call("list_materials", {"name": "m_veil"})["alpha_mode"] == "BLEND")
doc, _ = exported(["plain", "tinted", "packed"], "opaque")
expect("glb opaque materials have no alphaMode", all("alphaMode" not in m for m in doc["materials"]), [m.get("alphaMode") for m in doc["materials"]])
doc, _ = exported(["veil"], "veil")
gm = doc["materials"][0]
expect("glb textured alpha is BLEND with the factor", gm.get("alphaMode") == "BLEND" and abs(gm["pbrMetallicRoughness"]["baseColorFactor"][3] - 0.5) < 1e-3, gm)

# 3 and 8. slot cleanup, faces without material
fresh_scene()
for name in ("tidy", "holes", "shift"):
    box(name)
call("set_material", {"names": ["tidy"], "color": "#ff0000", "material": "red"})
call("set_material", {"names": ["shift"], "color": "#00ff00", "material": "green"})
blue = bpy.data.materials.new("blue")
lost = bpy.data.materials.new("lost")
next(n for n in lost.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Roughness"].default_value = 0.1
red, green = bpy.data.materials["red"], bpy.data.materials["green"]
mesh_of("tidy").materials.append(None)
mesh_of("tidy").materials.append(blue)
mesh_of("holes").materials.append(None)
mesh_of("holes").materials.append(red)
for i, poly in enumerate(mesh_of("holes").polygons):
    poly.material_index = 0 if i < 2 else 1
mesh_of("shift").materials.append(None)
mesh_of("shift").materials.append(red)
mesh_of("shift").polygons[5].material_index = 2
listed = call("list_materials", {})
expect("list_materials counts bare faces", listed["faces_without_material"] == {"holes": 2}, listed["faces_without_material"])
expect("the card of one material counts faces per object", call("list_materials", {"name": "red"})["faces"] == {"holes": 4, "shift": 1, "tidy": 6})
r = call("dedupe_materials", {"tolerance": 0.0})
expect("empty slots removed", r["empty_slots_removed"] == 2, r)
expect("unused slots removed", r["unused_slots_removed"] == 1, r)
expect("orphans removed", r["orphans_removed"] == ["blue", "lost"] and "lost" not in bpy.data.materials, r)
expect("nothing merged", r["removed"] == 0, r)
expect("tidy has one slot", [m.name for m in mesh_of("tidy").materials] == ["red"])
expect("slot order survives the shift", [m.name for m in mesh_of("shift").materials] == ["green", "red"])
expect("faces follow their material", mesh_of("shift").polygons[5].material_index == 1 and mesh_of("shift").polygons[0].material_index == 0)
expect("empty slot with faces stays", len(mesh_of("holes").materials) == 2 and mesh_of("holes").materials[0] is None)
expect("bare faces are reported", r.get("faces_without_material") == {"holes": 2} and "assign_material_faces" in r.get("note", ""), r)
call("assign_material_faces", {"object": "holes", "material": "green", "where": {"index": [0, 1]}})
r = call("dedupe_materials", {"tolerance": 0.0})
expect("after the assignment the empty slot goes", r["empty_slots_removed"] == 1 and "faces_without_material" not in r, r)
expect("holes keeps both materials", sorted(m.name for m in mesh_of("holes").materials) == ["green", "red"])
keep = bpy.data.materials.new("keep")
r = call("dedupe_materials", {"clean_slots": False, "remove_orphans": False})
expect("cleanup can be switched off", "keep" in bpy.data.materials and r["orphans_removed"] == [], r)

# 4. HDRI world
fresh_scene()
scene = bpy.context.scene
floor = box("floor", (0, 0, -0.55), 1.0)
floor.scale = (8, 8, 0.1)
bpy.ops.object.transform_apply(scale=True)
ball("orb")
call("set_material", {"names": ["orb"], "color": "#b0b2b6", "metallic": 1.0, "roughness": 0.25, "material": "steel"})
call("set_material", {"names": ["floor"], "color": "#303030", "roughness": 0.7, "material": "ground"})
call("set_camera", {"frame": ["orb"], "azimuth": 30, "elevation": 15, "margin": 1.6})

raises("unknown HDRI lists the built-in ones", lambda: call("set_world", {"hdri": "nope"}), "interior")
w = call("set_world", {"hdri": "interior", "strength": 1.5, "rotation_deg": 90, "color": "#ff0000", "visible_to_camera": False})
expect("built-in HDRI found", w["hdri"].endswith("interior.exr") and "studio" in w["builtin_hdris"], w)
expect("world answer", w["strength"] == 1.5 and w["rotation_deg"] == 90 and w["visible_to_camera"] is False and w["color"][0] > 0.9, w)
tree = scene.world.node_tree
expect("environment texture is wired", any(n.type == "TEX_ENVIRONMENT" and n.image for n in tree.nodes))
mapping = next(n for n in tree.nodes if n.type == "MAPPING")
expect("rotation about Z", abs(mapping.inputs["Rotation"].default_value[2] - math.radians(90)) < 1e-5)
hidden = call("render_final", {"path": str(work / "hdri_hidden.png"), "engine": "cycles", "size": 96, "samples": 8, "meter": ["orb"]})
corner = core.read_pixels(hidden["path"])[-2, 2, :3]
expect("camera sees the plain colour", corner[0] > 0.9 and corner[1] < 0.1, corner)
expect("the HDRI lights the metal without lamps", hidden["object"]["median"] > 0.05 and hidden["object"]["crushed_blacks"] < 0.5, hidden["object"])
w = call("set_world", {"strength": 0.5})
expect("strength alone keeps the HDRI", w["hdri"].endswith("interior.exr") and w["strength"] == 0.5 and w["visible_to_camera"] is False, w)
w = call("set_world", {"hdri": w["hdri"], "visible_to_camera": True})
expect("HDRI by path", w["hdri"].endswith("interior.exr") and w["visible_to_camera"] is True and w["color"][0] > 0.9, w)
shown = core.read_pixels(call("render_final", {"path": str(work / "hdri_shown.png"), "engine": "cycles", "size": 96, "samples": 8})["path"])
expect("camera sees the HDRI", not (shown[-2, 2, 0] > 0.9 and shown[-2, 2, 1] < 0.1), shown[-2, 2, :3])
eevee = call("render_final", {"path": str(work / "hdri_eevee.png"), "size": 96, "samples": 8, "meter": ["orb"]})
expect("eevee also lights from the HDRI", eevee["object"]["median"] > 0.05, eevee["object"])
w = call("set_world", {"preset": "dark"})
expect("a preset makes the world plain again", w["hdri"] is None and len([n for n in scene.world.node_tree.nodes if n.type == "BACKGROUND"]) == 1, w)

# 5. exposure
call("set_world", {"hdri": "studio", "color": "#101010", "visible_to_camera": False})
scene.view_settings.exposure = 0.7
state = (scene.render.engine, scene.render.resolution_x, scene.render.film_transparent, scene.render.image_settings.file_format,
         scene.render.image_settings.color_depth, scene.view_settings.exposure, scene.view_settings.view_transform)
shots = {}
for stops in (-3.0, 0.0, 3.0):
    shots[stops] = call("render_final", {"path": str(work / f"exp_{stops:+.0f}.png"), "engine": "cycles", "size": 96, "samples": 8,
                                         "exposure": stops, "meter": ["orb"]})
expect("answer tells the exposure", shots[3.0]["exposure"] == 3.0 and shots[-3.0]["exposure"] == -3.0, shots[3.0])
expect("more stops, brighter object", shots[-3.0]["object"]["median"] < shots[0.0]["object"]["median"] < shots[3.0]["object"]["median"],
       [s["object"]["median"] for s in shots.values()])
expect("tone numbers for the frame and the object", {"median", "mean", "clipped_highlights", "crushed_blacks"} <= set(shots[0.0]["frame"]) and "object" in shots[0.0])
blown = call("render_final", {"path": str(work / "blown.png"), "engine": "cycles", "size": 96, "samples": 8, "exposure": 8.0, "meter": ["orb"]})
expect("blown frame is a number", blown["object"]["clipped_highlights"] > 0.5 and any("clipped" in w for w in blown.get("warnings", [])), blown)
black = call("render_final", {"path": str(work / "black.png"), "engine": "cycles", "size": 96, "samples": 8, "exposure": -12.0, "meter": ["orb"]})
expect("black frame is a number", black["object"]["crushed_blacks"] > 0.9 and any("black" in w for w in black.get("warnings", [])), black)
default = call("render_final", {"path": str(work / "scene_exposure.png"), "engine": "cycles", "size": 64, "samples": 4})
expect("without exposure the scene value is used", default["exposure"] == 0.7 and "object" not in default, default)

auto = {}
for label, strength in (("dim", 0.02), ("normal", 1.0), ("harsh", 30.0)):
    call("set_world", {"strength": strength})
    auto[label] = call("render_final", {"path": str(work / f"auto_{label}.png"), "engine": "cycles", "size": 96, "samples": 8,
                                        "auto_exposure": True, "meter": ["orb"]})
    got = auto[label]
    expect(f"auto exposure {label}: probe numbers", {"median", "p95", "pixels", "exposure", "expected_median"} <= set(got.get("auto_exposure", {})), got)
    expect(f"auto exposure {label}: object in a sane range", 0.15 < got["object"]["median"] < 0.75 and got["object"]["clipped_highlights"] < 0.1
           and got["object"]["crushed_blacks"] < 0.1, got["object"])
expect("dim light gets more stops than harsh light", auto["dim"]["exposure"] > auto["normal"]["exposure"] > auto["harsh"]["exposure"],
       [a["exposure"] for a in auto.values()])
expect("the probe sees the light level", auto["dim"]["auto_exposure"]["median"] < auto["harsh"]["auto_exposure"]["median"])
call("set_world", {"strength": 1.0})
whole = call("render_final", {"path": str(work / "auto_all.png"), "size": 96, "samples": 8, "auto_exposure": True})
expect("auto exposure without meter uses all geometry", "auto_exposure" in whole and "object" in whole, whole)
after = (scene.render.engine, scene.render.resolution_x, scene.render.film_transparent, scene.render.image_settings.file_format,
         scene.render.image_settings.color_depth, scene.view_settings.exposure, scene.view_settings.view_transform)
expect("scene settings restored after exposure renders", state == after, (state, after))
raises("exposure and auto_exposure together refused", lambda: call("render_final", {"path": str(work / "x.png"), "exposure": 1.0, "auto_exposure": True}), "not both")
raises("meter needs geometry", lambda: call("render_final", {"path": str(work / "x.png"), "meter": ["camera"]}), "no geometry")
scene.view_settings.exposure = 0.0

# 6. lighting preset for metal
call("set_world", {"preset": "dark"})
rig = call("setup_lighting", {"preset": "metal", "target": ["orb"]})
lights = [o for o in bpy.data.objects if o.name.startswith("bl_light_")]
expect("metal rig: a key spot and a rim", sorted(o.name for o in lights) == ["bl_light_key", "bl_light_rim"] and bpy.data.objects["bl_light_key"].data.type == "SPOT", [o.name for o in lights])
expect("metal rig sets an HDRI hidden from the camera", rig["world"]["hdri"].endswith("interior.exr") and rig["world"]["visible_to_camera"] is False, rig.get("world"))
expect("the backdrop keeps the dark colour", max(rig["world"]["color"]) < 0.05, rig["world"]["color"])
for engine in ("cycles", "eevee"):
    shot = call("render_final", {"path": str(work / f"metal_{engine}.png"), "engine": engine, "size": 128, "samples": 16, "meter": ["orb"]})
    tone = shot["object"]
    expect(f"metal preset, {engine}: neither black nor blown at exposure 0", 0.15 < tone["median"] < 0.8 and tone["clipped_highlights"] < 0.1
           and tone["crushed_blacks"] < 0.1 and "warnings" not in shot, shot)
call("setup_lighting", {"preset": "three_point", "target": ["orb"]})
expect("another preset replaces the lights and keeps the world", len([o for o in bpy.data.objects if o.name.startswith("bl_light_")]) == 3
       and call("set_world", {"strength": 1.0})["hdri"] is not None)

# 7. worn metal, bake with ORM and rounded edges, as a job
fresh_scene()
scene = bpy.context.scene
part = box("part", (0, 0, 0.1), 0.2)
notch = box("notch", (0.1, 0, 0.2), 0.08)
call("boolean", {"a": "part", "b": "notch"})
made = call("procedural_material", {"names": ["part"], "kind": "worn_metal", "color_a": "#8e9094", "color_b": "#0d0c0b", "material": "steel_worn",
                                    "params": {"dirt": 0.8, "edge_wear": 0.8}})
expect("worn_metal uses AO and Bevel nodes", {"AmbientOcclusion", "Bevel"} <= set(made["nodes"]), made["nodes"])
worn = bpy.data.materials["steel_worn"]
worn_bsdf = next(n for n in worn.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
expect("worn_metal drives colour, roughness, metallic and normal", all(worn_bsdf.inputs[k].is_linked for k in ("Base Color", "Roughness", "Metallic", "Normal")))
nodes_before = len(worn.node_tree.nodes)
bpy.ops.object.select_all(action="DESELECT")
engine_before = scene.render.engine
started = call("bake_maps", {"object": "part", "size": 128, "maps": ["base_color", "normal", "orm"], "out_dir": str(work / "bake"),
                             "samples": 4, "background": True, "replace_material": False})
expect("bake starts as a job", started.get("status") == "running" and str(started.get("job", "")).startswith("job"), started)
handlers.advance_jobs()
expect("between maps the scene is clean", scene.render.engine == engine_before and len(worn.node_tree.nodes) == nodes_before
       and not part.select_get(), (scene.render.engine, len(worn.node_tree.nodes)))
state, progress = run_job(started)
expect("the bake job finishes", state["status"] == "done", state)
expect("the job reports each map", [p["baking"] for p in progress if "baking" in p][-1] == "metallic" and progress[-1]["of"] == 5, progress)
baked = state["result"]
expect("only the asked maps are kept", set(baked["maps"]) == {"base_color", "normal", "orm"} and sorted(p.name for p in (work / "bake").iterdir())
       == ["part_base_color.png", "part_normal.png", "part_orm.png"], baked)
colour = core.read_pixels(baked["maps"]["base_color"])[..., :3]
packed = core.read_pixels(baked["maps"]["orm"])[..., :3]
inside = packed[..., 2] > 0.01
expect("base colour of a metal is not black", colour[inside].mean() > 0.15, colour[inside].mean())
expect("wear varies the colour", colour[inside].std() > 0.02, colour[inside].std())
expect("ORM: metallic in blue, roughness in green, occlusion in red", packed[inside][:, 2].mean() > 0.6 and 0.2 < packed[inside][:, 1].mean() < 0.95
       and packed[inside][:, 0].mean() > 0.5, packed[inside].mean(axis=0))
expect("ORM: dirt lowers metallic somewhere", packed[inside][:, 2].min() < packed[inside][:, 2].max() - 0.1)
expect("replace_material=false keeps the procedural one", part.data.materials[0] == worn)

baked = call("bake_maps", {"object": "part", "size": 128, "maps": ["base_color", "normal", "orm"], "out_dir": str(work / "bake"), "samples": 4})
expect("a direct call still answers at once", baked["material"] == "part_baked" and part.data.materials[0].name == "part_baked", baked)
doc, binary = exported(["part"], "part")
gm = doc["materials"][0]
expect("glb from the bake: base, normal, metal-rough, occlusion", "baseColorTexture" in gm["pbrMetallicRoughness"]
       and "metallicRoughnessTexture" in gm["pbrMetallicRoughness"] and "occlusionTexture" in gm and "normalTexture" in gm, gm)
expect("glb from the bake: three images, opaque", len(doc["images"]) == 3 and "alphaMode" not in gm, [i.get("name") for i in doc["images"]])
again = call("bake_maps", {"object": "part", "size": 64, "maps": ["base_color", "orm"], "out_dir": str(work / "bake"), "samples": 2})
expect("a second bake reuses the baked material", again["material"] == "part_baked" and "part_baked.001" not in bpy.data.materials)

edge = box("edge", (2, 0, 0), 0.2)
call("set_material", {"names": ["edge"], "color": "#8e9094", "metallic": 1.0, "roughness": 0.3, "material": "steel_flat"})
call("unwrap", {"names": ["edge"], "method": "smart"})
flat = call("bake_maps", {"object": "edge", "size": 128, "maps": ["normal", "metallic"], "out_dir": str(work / "flat"), "samples": 4, "replace_material": False})
round_ = call("bake_maps", {"object": "edge", "size": 128, "maps": ["normal"], "out_dir": str(work / "round"), "samples": 8,
                            "replace_material": False, "bevel_radius": 0.02})
flat_px, round_px = core.read_pixels(flat["maps"]["normal"]), core.read_pixels(round_["maps"]["normal"])
metal_px = core.read_pixels(flat["maps"]["metallic"])
on_uv = metal_px[..., 0] > 0.5
expect("without bevel the normal map is flat and says so", "flat" in flat.get("note", "") and flat_px[on_uv][:, :2].std() < 0.01, flat.get("note"))
expect("bevel_radius bakes rounded edges into the normal map", "note" not in round_ and round_px[on_uv][:, :2].std() > 0.03, round_px[on_uv][:, :2].std())
expect("the bevel node is removed after the bake", not any(n.type == "BEVEL" for n in bpy.data.materials["steel_flat"].node_tree.nodes))
expect("metallic map holds the metallic value", on_uv.mean() > 0.3 and metal_px[on_uv][:, 0].mean() > 0.95, metal_px[on_uv][:, 0].mean())
raises("bad bevel radius", lambda: call("bake_maps", {"object": "edge", "bevel_radius": 0}), "bevel_radius")
raises("bad map name lists orm", lambda: call("bake_maps", {"object": "edge", "maps": ["height"]}), "orm")

print("PNG folder:", work)
finish()
