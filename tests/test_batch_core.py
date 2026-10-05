"""Honest answers of the base tools on a small object. Run: uv run python tests/run_headless.py tests/test_batch_core.py"""

import colorsys
import math
import os
import sys
from pathlib import Path

import bmesh
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

work = Path(os.environ.get("BL_MCP_WORK", "/tmp/bl_work_batch_core"))
out = work / "batch_core_test"
out.mkdir(parents=True, exist_ok=True)


def refused(label, method, params, message=""):
    try:
        call(method, params)
        expect(label, False)
    except ValueError as error:
        expect(label, message in str(error), str(error))


def cube(name, size, at):
    return call("create_primitive", {"kind": "cube", "name": name, "size": list(size), "at": list(at)})


def close(a, b, tol=1e-5):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def edit(name, change):
    mesh = bpy.data.objects[name].data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    change(bm)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def material(name):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def glb_normals(path):
    doc, binary, _ = handlers.read_glb(path)
    rows = []
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            accessor = doc["accessors"][prim["attributes"]["NORMAL"]]
            view = doc["bufferViews"][accessor["bufferView"]]
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            rows.append(np.frombuffer(binary, dtype=np.float32, count=accessor["count"] * 3, offset=start).reshape(-1, 3))
    return np.vstack(rows)


def axis_aligned_share(normals):
    return float((np.abs(normals).max(axis=1) > 0.999).mean())


# status: handler list, scene objects
fresh_scene()
cube("s_one", (1, 1, 1), (0, 0, 0))
cube("s_two", (1, 1, 1), (3, 0, 0))
bpy.data.objects.new("s_orphan", None)
info = call("status", {})
expect("status lists the handlers", {"status", "mirror", "export_glb"} <= set(info["handlers"]) and info["handlers"] == sorted(handlers.HANDLERS), info["handlers"][:5])
expect("status counts the objects scene_tree shows", info["objects"] == 2 == len(call("scene_tree", {}).splitlines()), info["objects"])
expect("status names objects outside the scene", info["objects_outside_scene"]["count"] == 1 and info["objects_outside_scene"]["names"] == ["s_orphan"], info)
bpy.data.objects.remove(bpy.data.objects["s_orphan"])
expect("no outside note for a plain scene", "objects_outside_scene" not in call("status", {}))

# mirror: origin
fresh_scene()
cube("grip_L", (0.02, 0.06, 0.1), (-0.05, 0.01, 0.2))
source = bpy.data.objects["grip_L"]
source.data.transform(Matrix.Translation((0.004, 0.03, -0.05)))
source.rotation_euler = (0.2, 0.1, 0.4)
source.data.materials.append(material("m_grip"))
bpy.context.view_layer.update()
before = call("measure", {"names": ["grip_L"]})[0]
twin = call("mirror", {"name": "grip_L", "axis": "X", "at": 0.01})
expect("mirror puts the origin at the mirror image of the source origin", close(twin["origin"], [0.02 - before["origin"][0], before["origin"][1], before["origin"][2]]), (before["origin"], twin["origin"]))
expect("the origin is not the box centre", not close(twin["origin"], twin["center"], 1e-3), twin)
expect("mirror flips the box", close(twin["min"], [0.02 - before["max"][0], before["min"][1], before["min"][2]], 1e-4) and close(twin["size"], before["size"], 1e-4), (before, twin))
expect("mirror keeps normals out", call("check_mesh", {"name": "grip_R"})["issues"] == ["none"], call("check_mesh", {"name": "grip_R"}))
expect("mirror keeps one slot per material", [s.material.name for s in bpy.data.objects["grip_R"].material_slots] == ["m_grip"], len(bpy.data.objects["grip_R"].material_slots))
call("mirror", {"name": "grip_L", "axis": "Z", "at": 0.0, "new_name": "grip_down"})
expect("mirror on another axis", close(call("measure", {"names": ["grip_down"]})[0]["origin"], [before["origin"][0], before["origin"][1], -before["origin"][2]]))

# delete: children keep their place
fresh_scene()
cube("barrel", (0.03, 0.2, 0.03), (0, 0.085, 0.06))
cube("sight", (0.004, 0.01, 0.006), (0, 0.17, 0.078))
cube("pin", (0.002, 0.002, 0.002), (0, 0.17, 0.082))
bpy.data.objects["barrel"].rotation_euler = (0.3, 0, 0.2)
bpy.context.view_layer.update()
bpy.data.objects["sight"].parent = bpy.data.objects["barrel"]
call("parent", {"child": "pin", "to": "sight"})
bpy.context.view_layer.update()
placed = call("measure", {"names": ["sight", "pin"]})
gone = call("delete", {"names": ["barrel"]})
after = call("measure", {"names": ["sight", "pin"]})
expect("delete of a parent leaves the child in place", close(after[0]["min"], placed[0]["min"]) and close(after[0]["max"], placed[0]["max"]), (placed[0]["min"], after[0]["min"]))
expect("the grandchild stays too", close(after[1]["center"], placed[1]["center"]) and after[1]["parent"] == "sight", after[1])
expect("delete names the unparented children", gone["removed"] == ["barrel"] and gone["unparented"] == ["sight"] and "note" in gone, gone)
cube("lone", (0.1, 0.1, 0.1), (1, 0, 0))
expect("delete without children has no note", call("delete", {"names": ["lone"]}) == {"removed": ["lone"]})
whole = call("delete", {"names": ["sight", "pin"], "with_children": True})
expect("with_children deletes the group once", whole == {"removed": ["sight", "pin"]} and not bpy.data.objects, whole)

# attach: the box that was used
fresh_scene()
cube("table", (1, 1, 0.1), (0, 0, 0.5))
cube("frame", (0.2, 0.2, 0.2), (3, 0, 3))
cube("magazine", (0.05, 0.05, 0.3), (3, 0, 2.8))
call("parent", {"child": "magazine", "to": "frame"})
joined = call("attach", {"part": "frame", "to": "table"})
used = joined["boxes_used"]
expect("attach reports the box with children", used["part"]["objects"] == ["frame", "magazine"] and abs(used["part"]["min"][2] - 0.55) < 1e-5 and abs(used["part"]["size"][2] - 0.45) < 1e-5, used)
expect("the part alone sits higher than the box used", abs(joined["min"][2] - 0.8) < 1e-5 and any("children" in n for n in joined["notes"]), joined)
expect("attach reports the target box and the move", used["to"]["objects"] == ["table"] and abs(used["to"]["max"][2] - 0.55) < 1e-5 and close(joined["moved_by"], [-3, 0, -2.1], 1e-4), joined)
alone = call("attach", {"part": "frame", "to": "table", "with_children": False})
expect("with_children=false measures the part alone", abs(alone["min"][2] - 0.55) < 1e-5 and alone["boxes_used"]["part"]["objects"] == ["frame"] and not alone["notes"], alone)
expect("the child still moves with the part", abs(call("measure", {"names": ["magazine"]})[0]["min"][2] - 0.3) < 1e-5)

# diff_since: topology and material slots
fresh_scene()
cube("d_barrel", (0.03, 0.2, 0.03), (0, 0, 0))
cube("d_still", (0.1, 0.1, 0.1), (1, 0, 0))
call("checkpoint", {"name": "d_base"})
expect("no change gives an empty diff", call("diff_since", {"name": "d_base"})["changed"] == [])
edit("d_barrel", lambda bm: bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=1, use_grid_fill=True))
diff = call("diff_since", {"name": "d_base"})
expect("a topology change shows without a size change", [c["object"] for c in diff["changed"]] == ["d_barrel"] and "size_now" not in diff["changed"][0], diff)
expect("diff_since gives the counts before and after", diff["changed"][0].get("topology") == {"verts": "8 -> 26", "edges": "12 -> 48", "faces": "6 -> 24", "tris": "12 -> 48"}, diff)
bpy.data.objects["d_still"].data.materials.append(material("m_new"))
bpy.data.objects["d_still"].location.x += 0.5
diff = call("diff_since", {"name": "d_base"})
still = next(c for c in diff["changed"] if c["object"] == "d_still")
expect("diff_since reports material slots with a move", still.get("material_slots") == {"before": [], "now": ["m_new"]} and still["moved_or_resized_by_up_to_m"] == 0.5 and "topology" not in still, still)

# checkpoints belong to the scene
expect("the scene lists its checkpoint", call("rollback", {})["checkpoints"] == ["d_base"])
fresh_scene()
expect("a fresh scene lists no foreign checkpoint", call("rollback", {})["checkpoints"] == [])
refused("rollback to a foreign checkpoint is refused", "rollback", {"name": "d_base"}, "No checkpoint 'd_base'")
refused("diff_since a foreign checkpoint is refused", "diff_since", {"name": "d_base"}, "No checkpoint 'd_base'")
expect("listing does not mark the scene", handlers.CHECKPOINT_SCOPE not in bpy.context.scene)
cube("c_part", (1, 1, 1), (0, 0, 0))
call("checkpoint", {"name": "c_mine"})
call("delete", {"names": ["c_part"]})
call("rollback", {"name": "c_mine"})
expect("rollback works inside the scene", "c_part" in bpy.data.objects)
expect("the checkpoint copy keeps the list", call("rollback", {})["checkpoints"] == ["c_mine"])

# find_floating: near follows the size of the pair
fresh_scene()
cube("p_frame", (0.03, 0.2, 0.05), (0, 0, 0.1))
cube("p_slide", (0.03, 0.25, 0.03), (0, 0.02, 0.14))
cube("p_grip", (0.03, 0.05, 0.1), (0, -0.07, 0.025))
cube("p_safety", (0.004, 0.02, 0.008), (0.027, -0.05, 0.11))
cube("p_lever", (0.004, 0.02, 0.008), (0.018, 0.05, 0.11))
pistol = ["p_frame", "p_slide", "p_grip", "p_safety", "p_lever"]
found = call("find_floating", {"names": pistol})
pairs = [(t["a"], t["b"]) for t in found["tiny_gaps"] if t != "none"]
expect("a 1 cm gap on a 27 cm prop is not a tiny gap", ("p_frame", "p_safety") not in pairs and found["floating"][0]["parts"] == ["p_safety"], found)
expect("a 1 mm gap on it is a tiny gap", pairs == [("p_frame", "p_lever")] and 0.001 < found["tiny_gaps"][0]["near"] < 0.005, found)
expect("the note states the rule", "2% of the size of the pair" in found["note"], found["note"])
wide = call("find_floating", {"names": pistol, "near": 0.03})
expect("an explicit near still works", ("p_frame", "p_safety") in [(t["a"], t["b"]) for t in wide["tiny_gaps"]] and "0.03 m" in wide["note"], wide)
cube("big_a", (1, 1, 1), (10, 0, 0.5))
cube("big_b", (1, 1, 1), (11.02, 0, 0.5))
large = call("find_floating", {"names": ["big_a", "big_b"]})
expect("a 2 cm gap between 1 m parts is a tiny gap", large["tiny_gaps"] != ["none"] and abs(large["tiny_gaps"][0]["gap"] - 0.02) < 1e-4, large)

# render_sheet: colour by object
fresh_scene()
cube("v_red", (1, 1, 1), (-1, 0, 0.5))
cube("v_blue", (1, 1, 1), (1, 0, 0.5))
cube("v_top", (1, 1, 1), (0, 0, 1.5))
bpy.data.objects["v_red"].color = (0.1, 0.2, 0.3, 1)
views = call("render_sheet", {"names": ["v_red", "v_blue", "v_top"], "views": ["front"], "size": 192, "color_by": "object"})
pixels = handlers.read_pixels(views["path"])[..., :3].reshape(-1, 3)
hsv = np.array([colorsys.rgb_to_hsv(*p) for p in pixels])
vivid = hsv[hsv[:, 1] > 0.4]
legend = views.get("legend", {})
expect("the legend has one colour per object", sorted(legend) == ["v_blue", "v_red", "v_top"] and len(set(legend.values())) == 3, legend)
for name, colour in legend.items():
    hue = colorsys.rgb_to_hsv(*[int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)])[0]
    distance = np.abs(vivid[:, 0] - hue)
    share = float((np.minimum(distance, 1 - distance) < 0.05).mean()) if len(vivid) else 0.0
    expect(f"{name} is painted in its legend colour", 0.2 < share < 0.5, (colour, share, len(vivid)))
expect("the object colours are restored", close(bpy.data.objects["v_red"].color, (0.1, 0.2, 0.3, 1)) and close(bpy.data.objects["v_blue"].color, (1, 1, 1, 1)))
plain = call("render_sheet", {"names": ["v_red"], "views": ["front"], "size": 96})
expect("colour by material has no legend", "legend" not in plain)
refused("an unknown color_by is refused", "render_sheet", {"color_by": "ids"}, "color_by")

# render_view: wire lines follow the frame
fresh_scene()
bpy.ops.mesh.primitive_grid_add(x_subdivisions=10, y_subdivisions=10, size=1)
bpy.context.object.name = "w_grid"


def wire_share(margin):
    shot = call("render_view", {"target": ["w_grid"], "mode": "wire", "fov": 0, "elevation": 90, "azimuth": 0, "margin": margin, "size": 256, "name": "w_test"})
    return float((handlers.read_pixels(shot["path"])[..., 0] > 0.5).mean())


overview, close_up = wire_share(1.0), wire_share(0.1)
expect("wire overview has thin lines", 0.08 < overview < 0.22, overview)
expect("wire close-up keeps thin lines", 0.01 < close_up < 0.06, close_up)
expect("wire leaves no copies", [o.name for o in bpy.data.objects] == ["w_grid"] and len(bpy.data.meshes) == 1)

# check_game_ready: faces without a material, empty slots, near symmetry
fresh_scene()
cube("g_barrel", (0.03, 0.2, 0.03), (0, 0, 0.1))
barrel = bpy.data.objects["g_barrel"]
edit("g_barrel", lambda bm: bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=3, use_grid_fill=True))
barrel.data.materials.append(material("m_steel"))
clean = call("check_game_ready", {"names": ["g_barrel"], "require_uv": False})
expect("a clean symmetric part is ready without warnings", clean["ready"] and clean["warnings"] == ["none"], clean)
barrel.data.materials.append(None)
barrel.data.materials.append(None)
for polygon in list(barrel.data.polygons)[:7]:
    polygon.material_index = 1
report = call("check_game_ready", {"names": ["g_barrel"], "require_uv": False})
problems = [e["problem"] for e in report["errors"] if e != "none"]
notes = [w["problem"] for w in report["warnings"] if w != "none"]
expect("faces without a material are an error with the count", f"7 of {len(barrel.data.polygons)} faces have no material" in problems and not report["ready"], report)
expect("empty slots are named", "2 empty material slots (index [1, 2])" in notes, notes)
expect("empty slots are not counted as draw calls", not any("one draw call each" in n for n in notes), notes)
for polygon in barrel.data.polygons:
    polygon.material_index = 0
barrel.data.materials.pop(index=2)
barrel.data.materials.pop(index=1)
top_side = [v for v in barrel.data.vertices if v.co.z > 0.014 and v.co.x > 0.014][:3]
for vertex in top_side:
    vertex.co.x -= 0.004
barrel.data.update()
report = call("check_game_ready", {"names": ["g_barrel"], "require_uv": False})
lopsided = [w["problem"] for w in report["warnings"] if w != "none" and "symmetric" in w["problem"]]
expect("a part broken on one side gets a symmetry warning", len(lopsided) == 1 and "but 6 of 98 vertices" in lopsided[0] and "worst error 0.004 m" in lopsided[0], report["warnings"])
expect("the symmetry warning is no error", report["ready"], report)
skipped = call("check_game_ready", {"names": ["g_barrel"], "require_uv": False, "symmetry_axis": None})
expect("symmetry_axis=None skips the note", skipped["warnings"] == ["none"], skipped)
cube("g_wedge", (0.1, 0.1, 0.1), (1, 0, 0))
edit("g_wedge", lambda bm: [setattr(v.co, "x", v.co.x * 3) for v in bm.verts if v.co.x > 0 and v.co.z > 0])
bpy.data.objects["g_wedge"].data.materials.append(material("m_steel"))
shaped = call("check_game_ready", {"names": ["g_wedge"], "require_uv": False})
expect("a part that is asymmetric by design gets no symmetry warning", shaped["warnings"] == ["none"], shaped)

# export_glb: texture size limit
fresh_scene()
texture_path = out / "tex_big.png"
noise = np.random.default_rng(1).random((256, 256, 4)).astype(np.float32)
noise[..., 3] = 1
handlers.write_pixels(texture_path, noise)
disk_bytes = texture_path.read_bytes()
bpy.ops.mesh.primitive_cube_add(size=0.2)
bpy.context.object.name = "x_box"
image = bpy.data.images.load(str(texture_path))
skin = bpy.data.materials.new("m_tex")
skin.use_nodes = True
node = skin.node_tree.nodes.new("ShaderNodeTexImage")
node.image = image
bsdf = next(n for n in skin.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
skin.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
bpy.data.objects["x_box"].data.materials.append(skin)
full = call("export_glb", {"path": str(out / "full.glb"), "names": ["x_box"]})
expect("export reports its textures", full["textures"]["count"] == 1 and full["textures"]["images"][0]["size"] == [256, 256] and full["textures"]["bytes"] == full["textures"]["images"][0]["bytes"] > 1000 and "downscaled_for_export" not in full["textures"], full)
small = call("export_glb", {"path": str(out / "small.glb"), "names": ["x_box"], "max_texture_size": 64})
expect("max_texture_size shrinks the texture in the file", small["textures"]["images"][0]["size"] == [64, 64] and small["textures"]["downscaled_for_export"] == {"tex_big.png": "256x256 -> 64x64"}, small)
expect("the smaller texture makes a smaller file", small["bytes"] < full["bytes"] / 4 and small["textures"]["bytes"] < full["textures"]["bytes"] / 4, (small["bytes"], full["bytes"]))
inspected = call("inspect_glb", {"path": str(out / "small.glb")})
expect("the file holds the small image under the same name", inspected["images"] == [{"name": full["textures"]["images"][0]["name"], "size": [64, 64]}], inspected["images"])
expect("the scene image is untouched", node.image == image and image.name == "tex_big.png" and list(image.size) == [256, 256] and [i.name for i in bpy.data.images] == ["tex_big.png"], [i.name for i in bpy.data.images])
expect("the file on disk is untouched", texture_path.read_bytes() == disk_bytes)
roomy = call("export_glb", {"path": str(out / "roomy.glb"), "names": ["x_box"], "max_texture_size": 1024})
expect("a limit above the size changes nothing", roomy["textures"]["images"][0]["size"] == [256, 256] and "downscaled_for_export" not in roomy["textures"], roomy)
refused("a zero limit is refused", "export_glb", {"path": str(out / "bad.glb"), "names": ["x_box"], "max_texture_size": 0}, "max_texture_size")
cube("x_bare", (0.1, 0.1, 0.1), (1, 0, 0))
expect("no textures gives a zero count", call("export_glb", {"path": str(out / "bare.glb"), "names": ["x_bare"]})["textures"] == {"count": 0, "bytes": 0, "images": []})

# shade: weighted normals reach the GLB
fresh_scene()
cube("n_part", (1, 1, 1), (0, 0, 0))
edit("n_part", lambda bm: bmesh.ops.bevel(bm, geom=bm.edges[:], offset=0.1, segments=1, affect="EDGES"))
call("shade", {"names": ["n_part"], "mode": "smooth"})
call("export_glb", {"path": str(out / "smooth.glb"), "names": ["n_part"]})
weighted = call("shade", {"names": ["n_part"], "mode": "smooth", "weighted_normals": True})
part = bpy.data.objects["n_part"]
expect("shade adds a weighted normal modifier that keeps sharp edges", weighted[0]["weighted_normals"] is True and [m.type for m in part.modifiers] == ["WEIGHTED_NORMAL"] and part.modifiers[0].keep_sharp, weighted)
call("shade", {"names": ["n_part"], "mode": "auto", "angle": 60, "weighted_normals": True})
expect("a second call does not stack modifiers", len(part.modifiers) == 1)
call("export_glb", {"path": str(out / "weighted.glb"), "names": ["n_part"]})
plain_share, weighted_share = axis_aligned_share(glb_normals(out / "smooth.glb")), axis_aligned_share(glb_normals(out / "weighted.glb"))
expect("plain smooth normals lean over the bevels", plain_share < 0.1, plain_share)
expect("weighted normals in the GLB follow the large faces", weighted_share > 0.95, weighted_share)
expect("the export leaves the modifier on the object", len(part.modifiers) == 1)
call("shade", {"names": ["n_part"], "mode": "smooth"})
expect("shade without the option removes the modifier", len(part.modifiers) == 0)
refused("flat with weighted normals is refused", "shade", {"names": ["n_part"], "mode": "flat", "weighted_normals": True}, "weighted_normals")

finish()
