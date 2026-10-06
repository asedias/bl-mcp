"""Materials: PBR set-up, face assignment, dedupe, glTF export. Run: uv run python tests/run_headless.py tests/test_materials.py"""

import importlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

importlib.import_module("bl_bridge.materials")
from bl_bridge import core  # noqa: E402


def box(name, at=(0, 0, 0), size=1.0):
    bpy.ops.mesh.primitive_cube_add(size=size, location=at)
    obj = bpy.context.object
    obj.name = name
    return obj


def bsdf(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def raises(label, fn, text):
    try:
        fn()
    except ValueError as err:
        expect(label, text in str(err), str(err))
    except Exception as err:  # the bridge wraps nothing: any other type is a bug
        expect(label, False, repr(err))
    else:
        expect(label, False, "no error")


fresh_scene()
work = Path(tempfile.mkdtemp(prefix="bl_mat_"))
a, b, c = box("a"), box("b", (3, 0, 0)), box("c", (6, 0, 0))

r = call("set_material", {"names": ["a"], "color": "#ff8000", "roughness": 0.3, "metallic": 0.9, "coat": 0.4, "material": "orange"})
node = bsdf(bpy.data.materials["orange"])
expect("roughness in node", abs(node.inputs["Roughness"].default_value - 0.3) < 1e-6)
expect("metallic in node", abs(node.inputs["Metallic"].default_value - 0.9) < 1e-6)
expect("coat in node", abs(node.inputs["Coat Weight"].default_value - 0.4) < 1e-6)
expect("base colour linear", abs(node.inputs["Base Color"].default_value[0] - 1.0) < 1e-4 and abs(node.inputs["Base Color"].default_value[2]) < 1e-4)
expect("slot filled", a.data.materials[0].name == "orange")
info = call("list_materials", {"name": "orange"})
expect("info colour back to hex", info["color"] == "#ff8000", info["color"])

call("set_material", {"names": ["b"], "color": [0.2, 0.4, 0.6]})
call("set_material", {"names": ["c"], "color": [0.2, 0.4, 0.6]})
expect("same params reuse one material", b.data.materials[0] == c.data.materials[0])

g = call("set_material", {"names": ["c"], "color": "#88ccff", "alpha": 0.4, "emission": {"color": "#ffff00", "strength": 3.0}, "material": "glass"})
glass = bpy.data.materials["glass"]
expect("alpha in node", abs(bsdf(glass).inputs["Alpha"].default_value - 0.4) < 1e-6)
expect("emission strength", abs(bsdf(glass).inputs["Emission Strength"].default_value - 3.0) < 1e-6)
expect("emission colour", bsdf(glass).inputs["Emission Color"].default_value[0] > 0.9)
expect("blend mode on", glass.blend_method == "BLEND", glass.blend_method)
expect("alpha response", "alpha_mode" in g)
expect("opaque material is not blended", bpy.data.materials["orange"].blend_method == "HASHED", bpy.data.materials["orange"].blend_method)

pixels = [1, 0, 0, 1] * 4
img = bpy.data.images.new("gen", 2, 2)
img.pixels = pixels
img.filepath_raw = str(work / "base.png")
img.file_format = "PNG"
img.save()
nrm = bpy.data.images.new("gen_n", 2, 2)
nrm.pixels = [0.5, 0.5, 1, 1] * 4
nrm.filepath_raw = str(work / "normal.png")
nrm.file_format = "PNG"
nrm.save()
bpy.data.images.remove(img)
bpy.data.images.remove(nrm)

while a.data.uv_layers:
    a.data.uv_layers.remove(a.data.uv_layers[0])
raises("texture without UV is refused", lambda: call("set_material", {"names": ["a"], "color": "#ffffff", "texture": str(work / "base.png")}), "unwrap")
a.data.uv_layers.new(name="UVMap")
r = call("set_material", {"names": ["a"], "color": "#ffffff", "material": "textured", "texture": str(work / "base.png"), "normal_map": str(work / "normal.png")})
tex_mat = bpy.data.materials["textured"]
images = {n.image.name: n.image for n in tex_mat.node_tree.nodes if n.type == "TEX_IMAGE"}
expect("two image nodes", len(images) == 2, list(images))
expect("normal map is Non-Color", images["normal.png"].colorspace_settings.name == "Non-Color", images["normal.png"].colorspace_settings.name)
expect("base is sRGB", images["base.png"].colorspace_settings.name == "sRGB")
expect("normal map node feeds Normal", bsdf(tex_mat).inputs["Normal"].links[0].from_node.type == "NORMAL_MAP")
expect("texture feeds Base Color", bsdf(tex_mat).inputs["Base Color"].links[0].from_node.type == "TEX_IMAGE")
raises("missing image", lambda: call("set_material", {"names": ["a"], "color": "#ffffff", "texture": str(work / "none.png")}), "not found")

bumped = call("set_material", {"names": ["b"], "color": "#808080", "material": "rough_stone", "bump": {"scale": 10, "strength": 0.2}})
expect("bump warns about glTF", "glTF" in bumped.get("warning", ""))
listing = {m["name"]: m for m in call("list_materials", {})["materials"]}
expect("list flags procedural", listing["rough_stone"]["not_exported"] and "TEX_NOISE" in listing["rough_stone"]["procedural_nodes"], listing["rough_stone"])
expect("list flags texture", listing["textured"]["texture"] and not listing["textured"]["not_exported"])
expect("list counts users", isinstance(listing["orange"]["users"], int) and listing["orange"]["color"] == "#ff8000")
raises("unknown material info", lambda: call("list_materials", {"name": "zzz"}), "No material")

fresh_scene()
wall = box("wall", size=2.0)
call("set_material", {"names": ["wall"], "color": "#222222", "material": "dark"})
spare = box("spare", (9, 0, 0))
call("set_material", {"names": ["spare"], "color": "#ff0000", "material": "red"})
r = call("assign_material_faces", {"object": "wall", "material": "red", "where": {"normal": "+Z"}})
expect("one face picked", r["faces"] == 1, r)
mesh = bpy.data.objects["wall"].data
slot = [m.name for m in mesh.materials].index("red")
expect("slot added", slot == 1, [m.name for m in mesh.materials])
tops = [p.index for p in mesh.polygons if p.material_index == slot]
expect("only the +Z face got it", len(tops) == 1 and mesh.polygons[tops[0]].normal.z > 0.9, tops)
expect("others kept", sum(1 for p in mesh.polygons if p.material_index == 0) == 5)
raises("no match", lambda: call("assign_material_faces", {"object": "wall", "material": "red", "where": {"x": [50, 60]}}), "No faces")
raises("unknown material", lambda: call("assign_material_faces", {"object": "wall", "material": "zzz"}), "No material")

fresh_scene()
parts = [box(f"p{i}", (i * 2, 0, 0)) for i in range(4)]
call("set_material", {"names": ["p0"], "color": "#336699", "material": "m_a"})
call("set_material", {"names": ["p1"], "color": "#346699", "material": "m_b"})
call("set_material", {"names": ["p2"], "color": "#ff0000", "material": "m_c"})
call("set_material", {"names": ["p3"], "color": "#346699", "material": "m_d", "metallic": 0.9})
before = {o.name: tuple(round(v, 3) for v in o.data.materials[0].diffuse_color) for o in parts}
r = call("dedupe_materials", {"tolerance": 0.01})
expect("two merged away", r["removed"] == 1 and r["materials_before"] == 4 and r["materials_after"] == 3, r)
expect("metallic one stays", "m_d" in bpy.data.materials and "m_c" in bpy.data.materials)
expect("users moved", parts[1].data.materials[0] == parts[0].data.materials[0])
expect("look kept", tuple(round(v, 2) for v in parts[1].data.materials[0].diffuse_color[:3]) == tuple(round(v, 2) for v in before["p0"][:3]))
expect("dedupe with names limits", call("dedupe_materials", {"names": ["m_c"]})["removed"] == 0)

fresh_scene()
two = box("two")
call("set_material", {"names": ["two"], "color": "#101010", "material": "x1"})
call("set_material", {"names": ["two"], "color": "#101010", "material": "x2"})
call("assign_material_faces", {"object": "two", "material": "x2", "where": {"normal": "+Z"}})
call("dedupe_materials", {"tolerance": 0.01})
expect("duplicate slots collapse", len(two.data.materials) == 1, [m.name for m in two.data.materials])
expect("faces indices valid", all(p.material_index == 0 for p in two.data.polygons))

fresh_scene()
cube = box("cube")
cube.data.uv_layers.new(name="UVMap")
img = bpy.data.images.new("g2", 2, 2)
img.pixels = [0, 1, 0, 1] * 4
img.filepath_raw = str(work / "t.png")
img.file_format = "PNG"
img.save()
nrm = bpy.data.images.new("g2n", 2, 2)
nrm.pixels = [0.5, 0.5, 1, 1] * 4
nrm.filepath_raw = str(work / "n.png")
nrm.file_format = "PNG"
nrm.save()
bpy.data.images.remove(img)
bpy.data.images.remove(nrm)
call("set_material", {"names": ["cube"], "color": "#ffffff", "material": "game", "roughness": 0.35, "metallic": 0.6, "alpha": 0.5,
                          "emission": {"color": "#00ff00", "strength": 2.0}, "texture": str(work / "t.png"), "normal_map": str(work / "n.png")})
path = work / "out.glb"
call("export_glb", {"path": str(path)})
doc, _, _ = core.read_glb(str(path))
gm = doc["materials"][0]
pbr = gm["pbrMetallicRoughness"]
expect("glb roughness", abs(pbr["roughnessFactor"] - 0.35) < 1e-3, pbr)
expect("glb metallic", abs(pbr["metallicFactor"] - 0.6) < 1e-3, pbr)
expect("glb base texture", "baseColorTexture" in pbr, pbr)
expect("glb normal texture", "normalTexture" in gm, gm)
expect("glb alpha mode", gm.get("alphaMode") == "BLEND", gm.get("alphaMode"))
expect("glb emissive", "emissiveFactor" in gm and gm["emissiveFactor"][1] > 0.9, gm.get("emissiveFactor"))
expect("glb emissive strength ext", "KHR_materials_emissive_strength" in gm.get("extensions", {}), gm.get("extensions"))
expect("inspect sees two images", len(call("inspect_glb", {"path": str(path)})["images"]) == 2)

fresh_scene()
solid = box("solid")
call("set_material", {"names": ["solid"], "color": "#445566"})
call("export_glb", {"path": str(work / "solid.glb")})
solid_doc = core.read_glb(str(work / "solid.glb"))[0]
expect("glb opaque has no BLEND", solid_doc["materials"][0].get("alphaMode", "OPAQUE") == "OPAQUE", solid_doc["materials"][0])

call("create_primitive", {"kind": "sphere", "name": "glass_ball", "size": [0.2, 0.2, 0.2], "at": [4, 0, 0.1]})
glass = call("set_material", {"names": ["glass_ball"], "color": "#ffffff", "roughness": 0.05, "transmission": 1.0})
expect("transmission is reported", "note_transmission" in glass and glass["material"].endswith("_t1"), glass)
card = call("list_materials", {"name": glass["material"]})
expect("the material card shows transmission", card["transmission"] == 1.0, card)
call("export_glb", {"path": str(work / "glass.glb"), "names": ["glass_ball"]})
expect("transmission reaches glTF", b"KHR_materials_transmission" in (work / "glass.glb").read_bytes())


finish()
