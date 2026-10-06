"""Small-part defects: boolean materials, cleaning and result check, honest bevel, lopsided selection, set_origin, weld that opens, repair counts.

Run: uv run python tests/run_headless.py tests/test_batch_mesh.py
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

import bmesh  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

hard = importlib.import_module("bl_bridge.hard")


def near(a, b, tol=1e-5):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def refused(label, method, params, text):
    try:
        result = call(method, params)
    except ValueError as err:
        expect(label, text in str(err), str(err))
        return str(err)
    expect(label, False, result)
    return ""


def cube(name, size, at, anchor=(0.5, 0.5, 0.5), rotate_deg=None):
    call("create_primitive", {"kind": "cube", "name": name, "size": size, "at": at, "anchor": anchor, "rotate_deg": rotate_deg})
    return bpy.data.objects[name]


def cylinder(name, size, at, rotate_deg=None, segments=16):
    call("create_primitive", {"kind": "cylinder", "name": name, "size": size, "at": at, "segments": segments, "rotate_deg": rotate_deg})
    return bpy.data.objects[name]


def issues(name):
    return [i for i in call("check_mesh", {"name": name})["issues"] if i != "none"]


def material(name):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def slots(obj):
    return [s.material.name if s.material else None for s in obj.material_slots]


def face_materials(obj):
    names = slots(obj)
    return {names[p.material_index] if p.material_index < len(names) else "out of range" for p in obj.data.polygons}


def raw_boolean(a, b, operation):
    target = bpy.data.objects[a]
    modifier = target.modifiers.new("raw", "BOOLEAN")
    modifier.object, modifier.operation, modifier.solver = bpy.data.objects[b], operation, "EXACT"
    handlers.bake_modifiers(target)
    return issues(a)


def world_box(obj):
    points = [obj.matrix_world @ v.co for v in obj.data.vertices]
    return [min(p[i] for p in points) for i in range(3)] + [max(p[i] for p in points) for i in range(3)]


fresh_scene()

# boolean: materials
body = cube("m_body", [0.03, 0.02, 0.02], [0, 0, 0])
body.data.materials.append(material("steel"))
tool = cylinder("m_tool", [0.008, 0.008, 0.05], [0, 0, 0])
tool.data.materials.append(material("red"))
res = call("boolean", {"a": "m_body", "b": "m_tool"})
expect("cutter material does not leak into the target", slots(body) == ["steel"] and face_materials(body) == {"steel"}, (slots(body), face_materials(body)))
expect("boolean names the solver", res.get("solver") == "EXACT", res)

body = cube("m_two", [0.04, 0.02, 0.02], [1, 0, 0])
body.data.materials.append(material("steel"))
body.data.materials.append(material("wood"))
for polygon in body.data.polygons:
    polygon.material_index = 1 if polygon.center.x > 0.019 else 0
cylinder("m_bare", [0.006, 0.006, 0.02], [1.02, 0, 0], rotate_deg=[0, 90, 0])
before = len(body.data.polygons)
call("boolean", {"a": "m_two", "b": "m_bare"})
names = slots(body)
wall = [names[p.material_index] for p in body.data.polygons if abs(p.normal.x) < 0.5 and abs((body.matrix_world @ p.center).x - 1.015) < 0.006 and p.area < 1e-4]
expect("cutter without material adds no empty slot", names == ["steel", "wood"] and face_materials(body) <= {"steel", "wood"}, (names, face_materials(body)))
expect("faces made by the cutter take the material of the face they cut", len(body.data.polygons) > before and wall and set(wall) == {"wood"}, wall)

bare = cube("m_none", [0.03, 0.02, 0.02], [2, 0, 0])
tool = cylinder("m_red", [0.008, 0.008, 0.05], [2, 0, 0])
tool.data.materials.append(material("red"))
call("boolean", {"a": "m_none", "b": "m_red"})
expect("target without material stays without slots", slots(bare) == [], slots(bare))

holed = cube("m_empty", [0.03, 0.02, 0.02], [3, 0, 0])
holed.data.materials.append(None)
holed.data.materials.append(material("steel"))
for polygon in holed.data.polygons:
    polygon.material_index = polygon.index % 2
cylinder("m_cut", [0.008, 0.008, 0.05], [3, 0, 0])
res = call("boolean", {"a": "m_empty", "b": "m_cut"})
expect("boolean removes an empty slot and leaves no face without material", slots(holed) == ["steel"] and face_materials(holed) == {"steel"} and res.get("removed_empty_slots") == 1, (slots(holed), res))

kept = cube("m_keep", [0.03, 0.02, 0.02], [4, 0, 0])
keeper = cube("m_keeper", [0.01, 0.01, 0.05], [4, 0, 0])
keeper.data.materials.append(material("red"))
call("boolean", {"a": "m_keep", "b": "m_keeper", "keep_tool": True})
expect("a kept tool is not changed", "m_keeper" in bpy.data.objects and slots(keeper) == ["red"] and len(keeper.data.polygons) == 6 and "bl_tool" not in bpy.data.objects)

# boolean: coplanar union is cleaned
HULL = [[0.03, 0.03], [0.015, 0.056], [-0.0075, 0.043], [-0.01, 0.03], [-0.01, 0.0127], [0.01, 0.0127]]


def coplanar(prefix):
    call("extrude_profile", {"name": prefix + "hull", "points": HULL, "depth": 0.028, "plane": "XZ"})
    cube(prefix + "block", [0.05, 0.05, 0.05], [-0.01, 0, 0.0127], anchor=(0, 0.5, 0))


coplanar("raw_")
dirty = raw_boolean("raw_hull", "raw_block", "UNION")
expect("reproduction: a raw coplanar union leaves zero-area faces and doubled vertices", any("zero-area" in i for i in dirty) and any("share a place" in i for i in dirty), dirty)
coplanar("c_")
res = call("boolean", {"a": "c_hull", "b": "c_block", "operation": "union"})
expect("coplanar union comes out clean", issues("c_hull") == [] and res.get("merged_vertices", 0) > 0 and res.get("removed_zero_faces", 0) > 0, (res, issues("c_hull")))

# boolean: intersect of a hull with a cube whose face passes through a hull vertex
PISTOL = [[0.01, 0.03], [0.0115, 0.0396], [0.0052, 0.0595], [-0.01, 0.0473], [-0.0141, 0.0351], [-0.0282, 0.0197], [-0.0075, 0.017], [0.0017, 0.0202], [0.0115, 0.0204]]


def hull_and_cube(prefix):
    call("extrude_profile", {"name": prefix + "hull", "points": PISTOL, "depth": 0.028, "plane": "XZ"})
    cube(prefix + "block", [0.05, 0.05, 0.05], [0.01, 0, 0.0197], anchor=(0, 0.5, 0))


hull_and_cube("raw2_")
dirty = raw_boolean("raw2_hull", "raw2_block", "INTERSECT")
expect("reproduction: a raw intersect silently leaves a non-manifold edge", any("more than 2 faces" in i for i in dirty), dirty)
hull_and_cube("i_")
res = call("boolean", {"a": "i_hull", "b": "i_block", "operation": "intersect"})
check = call("check_mesh", {"name": "i_hull"})
expect("intersect through a hull vertex gives a closed result", check["closed"] and not any("zero-area" in i for i in check["issues"]) and "solver" in res, (res, check))
cube("i_next", [0.004, 0.01, 0.004], [0.011, 0, 0.035])
res = call("boolean", {"a": "i_hull", "b": "i_next", "operation": "union"})
expect("the next boolean accepts that result", call("check_mesh", {"name": "i_hull"})["closed"], res)

# boolean: a cut that touches along an edge; EXACT alone gives an edge with 4 faces
TOUCH = [[0.03, 0.03], [0.0141, 0.0441], [0.0, 0.045], [-0.0141, 0.0441], [-0.02, 0.03], [-0.0141, 0.0159], [0.0, 0.0], [0.0212, 0.0088]]


def touching(prefix):
    call("extrude_profile", {"name": prefix + "hull", "points": TOUCH, "depth": 0.028, "plane": "XZ"})
    cube(prefix + "block", [0.0141, 0.028, 0.0291], [-0.0141, 0, 0.0159], anchor=(0, 0.5, 0))
    return bpy.data.objects[prefix + "hull"]


touching("raw3_")
dirty = raw_boolean("raw3_hull", "raw3_block", "DIFFERENCE")
expect("reproduction: raw EXACT leaves an edge with more than 2 faces", any("more than 2 faces" in i for i in dirty), dirty)
hull = touching("t_")
res = call("boolean", {"a": "t_hull", "b": "t_block"})
check = call("check_mesh", {"name": "t_hull"})
expect("another solver gives a closed result and the answer names it", check["closed"] and res.get("solver") in ("MANIFOLD", "FLOAT"), (res, check))
expect("doubled vertices that cannot be welded are reported", res.get("doubled_vertices_left", 0) > 0 and "note" in res, res)

attempts = hard.boolean_attempts
hard.boolean_attempts = lambda *args: (item for item in list(attempts(*args))[:1])
hull = touching("f_")
faces = len(hull.data.polygons)
message = refused("boolean refuses a result with new non-manifold edges", "boolean", {"a": "f_hull", "b": "f_block"}, "new edges with more than")
expect("the refusal gives the count, the world box and the solvers tried", "1 new edges with more than 2 faces" in message and "world box [" in message and "EXACT" in message, message)
expect("the refusal changes nothing", len(hull.data.polygons) == faces and "f_block" in bpy.data.objects and "bl_tool" not in bpy.data.objects and not hull.modifiers)
res = call("boolean", {"a": "f_hull", "b": "f_block", "allow_open": True})
expect("allow_open keeps the result and warns with counts and box", "warning" in res and res.get("new_non_manifold_edges") == 1 and len(res.get("box", [])) == 2, res)
hard.boolean_attempts = attempts

# boolean: a new cut that overlaps an old cut on a sloped face
cylinder("o_barrel", [0.02, 0.02, 0.15], [5, 0, 0], rotate_deg=[90, 0, 0])
cube("o_wedge", [0.06, 0.2, 0.03], [5, 0, 0.022], rotate_deg=[20, 0, 0])
call("boolean", {"a": "o_barrel", "b": "o_wedge"})
cylinder("o_port", [0.0056, 0.0056, 0.04], [5, 0, 0.01])
call("boolean", {"a": "o_barrel", "b": "o_port"})
call("duplicate", {"name": "o_barrel", "new_name": "o_raw"})
cylinder("o_raw_cut", [0.0056, 0.0056, 0.0105], [5.0036, 0, 0.012])
dirty = raw_boolean("o_raw", "o_raw_cut", "DIFFERENCE")
expect("reproduction: a raw overlapping cut leaves a zero-area face", any("zero-area" in i for i in dirty), dirty)
cylinder("o_cut", [0.0056, 0.0056, 0.0105], [5.0036, 0, 0.012])
res = call("boolean", {"a": "o_barrel", "b": "o_cut"})
expect("overlapping cuts on a slope come out clean and closed", issues("o_barrel") == [] and call("check_mesh", {"name": "o_barrel"})["closed"] and res.get("removed_zero_faces") == 1, (res, issues("o_barrel")))
refused("boolean refuses an unknown solver", "boolean", {"a": "o_barrel", "b": "o_raw", "solver": "FAST"}, "solver is one of")

# bevel_edges: the answer tells the achieved width
cube("b_fit", [0.05, 0.02, 0.01], [6, 0, 0])
res = call("bevel_edges", {"object": "b_fit", "width": 0.002, "segments": 2})
expect("bevel that fits reports the asked width as achieved", res["width"] == 0.002 and near([res["achieved_width"]["min"], res["achieved_width"]["median"]], [0.002, 0.002], 1e-6) and res["clamped"] == 0 and "warning" not in res, res)
cube("b_tight", [0.05, 0.02, 0.01], [7, 0, 0])
res = call("bevel_edges", {"object": "b_tight", "width": 0.02, "segments": 2})
expect("bevel larger than fits reports the clamped width", res["width"] == 0.02 and near([res["achieved_width"]["median"]], [0.005], 1e-5) and res["clamped"] == 12 and "warning" in res, res)
expect("clamped bevel leaves no doubled vertices or zero-area faces", issues("b_tight") == [] and res.get("merged_vertices", 0) > 0, (res, issues("b_tight")))
for kind in ("width", "depth"):
    cube("b_kind", [0.05, 0.02, 0.01], [8, 0, 0])
    res = call("bevel_edges", {"object": "b_kind", "width": 0.002, "segments": 3, "width_type": kind})
    expect(f"bevel measures the {kind} type in its own terms", near([res["achieved_width"]["min"]], [0.002], 1e-6) and res["achieved_width"]["measured_as"] == kind and res["clamped"] == 0, res)
    call("delete", {"names": ["b_kind"]})
cube("b_percent", [0.05, 0.02, 0.01], [8, 0, 0])
res = call("bevel_edges", {"object": "b_percent", "width": 20, "segments": 1, "width_type": "percent"})
expect("percent bevel gives metres and no clamped count", res["achieved_width"]["measured_as"] == "offset" and 0.001 < res["achieved_width"]["min"] < 0.011 and "clamped" not in res, res)

barrel = cylinder("b_barrel", [0.02, 0.02, 0.15], [9, 0, 0], rotate_deg=[90, 0, 0])
for i in range(6):
    cube("b_slot", [0.03, 0.002, 0.004], [9, -0.06 + i * 0.006, 0.009])
    call("boolean", {"a": "b_barrel", "b": "b_slot"})
res = call("bevel_edges", {"object": "b_barrel", "width": 0.0005, "segments": 2})
expect("many bevels clamped near zero give a warning", res["clamped"] > res["bevelled"] / 2 and res["achieved_width"]["median"] < 0.0001 and "warning" in res, res)
expect("the barrel is clean after the clamped bevels", issues("b_barrel") == [], issues("b_barrel"))

# transform_region: lopsided selection on a symmetric mesh
TOP = {"normal": "+Z", "z": [0.009, None]}


def bar(name, x):
    cube(name, [0.02, 0.15, 0.02], [x, 0, 0])
    call("subdivide_faces", {"object": name, "cuts": 3})
    return bpy.data.objects[name]


bar("s_bar", 10)
res = call("transform_region", {"object": "s_bar", "where": {**TOP, "x": [9.994, None]}, "scale": [0.5, 1, 1]})
expect("lopsided selection on a symmetric mesh warns with axis and count", "X=10" in res.get("warning", "") and "5 of 20" in res["warning"], res)
expect("the lopsided edit did break the symmetry", call("check_symmetry", {"names": ["s_bar"]})["unmatched"] > 0)
bar("s_fix", 11)
res = call("transform_region", {"object": "s_fix", "where": {**TOP, "x": [10.994, None]}, "scale": [0.5, 1, 1], "symmetric": "x"})
expect("symmetric adds the mirror twins", res.get("mirrored_vertices") == 5 and res.get("without_twin") == 0 and res["selected_vertices"] == 25 and "warning" not in res, res)
expect("the symmetric edit keeps the symmetry", call("check_symmetry", {"names": ["s_fix"]})["unmatched"] == 0)
bar("s_top", 12)
res = call("transform_region", {"object": "s_top", "where": TOP, "move": [0, 0, 0.005]})
expect("a symmetric selection gives no warning", "warning" not in res, res)
bar("s_side", 13)
res = call("transform_region", {"object": "s_side", "where": {**TOP, "x": [13.001, None]}, "move": [0.002, 0, 0]})
expect("a selection on one side of the plane gives no warning", "warning" not in res, res)
refused("symmetric refuses a wrong axis", "transform_region", {"object": "s_side", "where": TOP, "move": [0, 0, 0.001], "symmetric": "w"}, "symmetric is")

# set_origin
grip = cube("g_grip", [0.03, 0.02, 0.1], [20, 0, 0.05], rotate_deg=[0, 0, 30])
grip.scale = (1.5, 1, 1)
bpy.context.view_layer.update()
screw = cube("g_screw", [0.005, 0.005, 0.005], [20.02, 0, 0.08])
call("parent", {"child": "g_screw", "to": "g_grip"})
box_before, child_before = world_box(grip), screw.matrix_world.copy()
res = call("set_origin", {"names": ["g_grip"], "at": [20.01, 0.002, 0.03]})
expect("set_origin puts the origin at the world point", near(res[0]["origin"], [20.01, 0.002, 0.03]), res)
expect("set_origin keeps the geometry in the world", near(world_box(grip), box_before), (world_box(grip), box_before))
expect("set_origin keeps the child in the world", all(near(a, b) for a, b in zip(screw.matrix_world, child_before)))
res = call("set_origin", {"names": ["g_grip", "g_screw"], "anchor": [0.5, 0.5, 0]})
expect("set_origin on a list uses the bottom centre of each box", near(res[0]["origin_in_bbox"], [0.5, 0.5, 0], 1e-3) and near(res[1]["origin_in_bbox"], [0.5, 0.5, 0], 1e-3), res)
expect("parent and child in one call both stay in place", near(world_box(grip), box_before) and near(screw.matrix_world.translation, [20.02, 0, 0.0775]), screw.matrix_world.translation[:])
twin = call("duplicate", {"name": "g_screw", "new_name": "g_twin", "offset": [0.01, 0, 0], "linked": True})
twin_box = world_box(bpy.data.objects["g_twin"])
call("set_origin", {"names": ["g_screw"], "anchor": [0.5, 0.5, 0.5]})
expect("set_origin does not move an object that shared the mesh", near(world_box(bpy.data.objects["g_twin"]), twin_box))
bpy.ops.object.empty_add(location=(21, 0, 0))
pivot = bpy.context.object
pivot.name = "g_pivot"
leaf = cube("g_leaf", [0.01, 0.01, 0.01], [21.05, 0, 0])
call("parent", {"child": "g_leaf", "to": "g_pivot"})
call("set_origin", {"names": ["g_pivot"], "at": [21, 0, 0.5]})
expect("set_origin moves an empty and leaves its child", near(pivot.matrix_world.translation, [21, 0, 0.5]) and near(leaf.matrix_world.translation, [21.05, 0, 0]))
refused("set_origin needs one of at and anchor", "set_origin", {"names": ["g_grip"]}, "either at")
refused("set_origin refuses both at and anchor", "set_origin", {"names": ["g_grip"], "at": [0, 0, 0], "anchor": [0, 0, 0]}, "either at")

# weld that would open the mesh
finned = cube("w_body", [0.02, 0.02, 0.02], [30, 0, 0])
cube("w_fin", [0.01, 0.00002, 0.01], [30, 0, 0.012])
call("boolean", {"a": "w_body", "b": "w_fin", "operation": "union"})
expect("the body with a thin fin is closed", issues("w_body") == [], issues("w_body"))
count = len(finned.data.vertices)
message = refused("weld refuses a distance that opens the mesh", "weld", {"object": "w_body", "distance": 3e-5}, "opens w_body")
expect("the refusal names the new edges and their box", "new boundary edges" in message and "world box [" in message and "Nothing was changed" in message, message)
expect("the refused weld changed nothing", len(finned.data.vertices) == count and issues("w_body") == [])
res = call("weld", {"object": "w_body", "distance": 3e-5, "allow_open": True})
expect("allow_open welds and reports the damage", res["merged_vertices"] > 0 and "warning" in res and res["new_boundary_edges"] + res["new_non_manifold_edges"] > 0, res)
plain = cube("w_plain", [0.02, 0.02, 0.02], [31, 0, 0])
bm = bmesh.new()
bm.from_mesh(plain.data)
bmesh.ops.split_edges(bm, edges=bm.edges)
bm.to_mesh(plain.data)
bm.free()
res = call("weld", {"object": "w_plain"})
expect("a weld that closes seams passes without warning", res["merged_vertices"] == 16 and "warning" not in res and issues("w_plain") == [], res)

# repair_mesh: counts of everything it removes
bad = cube("r_bad", [0.02, 0.02, 0.02], [32, 0, 0])
bad.data.materials.append(material("steel"))
bad.data.materials.append(None)
bm = bmesh.new()
bm.from_mesh(bad.data)
bm.faces.ensure_lookup_table()
bm.faces[0].material_index = 1
edge = bm.faces[1].edges[0]
ends = list(edge.verts)
face, far = bm.faces[1], bm.faces[3]
bmesh.utils.edge_split(edge, ends[0], 0.5)
bmesh.utils.face_split(face, ends[0], ends[1])
bmesh.ops.split_edges(bm, edges=list(far.edges))
bm.to_mesh(bad.data)
bm.free()
dirty = issues("r_bad")
expect("reproduction: the damaged cube has a zero-area face and doubled vertices", any("zero-area" in i for i in dirty) and any("share a place" in i for i in dirty), dirty)
res = call("repair_mesh", {"object": "r_bad"})
removed = res["removed"]
expect("repair_mesh reports each count", removed["doubled_vertices"] > 0 and removed["zero_area_faces"] == 1 and removed["empty_material_slots"] == 1, res)
expect("repair_mesh leaves a clean closed mesh with one material", issues("r_bad") == [] and call("check_mesh", {"name": "r_bad"})["closed"] and slots(bad) == ["steel"] and face_materials(bad) == {"steel"}, (issues("r_bad"), slots(bad)))
keep = cube("r_keep", [0.02, 0.02, 0.02], [33, 0, 0])
keep.data.materials.append(None)
res = call("repair_mesh", {"object": "r_keep", "remove_empty_slots": False})
expect("remove_empty_slots=false keeps the slot", len(keep.material_slots) == 1 and res["removed"]["empty_material_slots"] == 0, res)

# a tool with a UV map must not leave the target a fake UV layer
call("create_primitive", {"kind": "cube", "name": "uv_target", "size": [0.2, 0.2, 0.2], "at": [8, 0, 0.1]})
for layer in list(bpy.data.objects["uv_target"].data.uv_layers):
    bpy.data.objects["uv_target"].data.uv_layers.remove(layer)
call("create_primitive", {"kind": "cylinder", "name": "uv_tool", "size": [0.05, 0.05, 0.4], "at": [8, 0, 0.1]})
call("unwrap", {"names": ["uv_tool"]})
call("boolean", {"a": "uv_target", "b": "uv_tool", "operation": "difference"})
expect("boolean does not add a UV layer to a target without one", len(bpy.data.objects["uv_target"].data.uv_layers) == 0)
call("create_primitive", {"kind": "cube", "name": "uv_target2", "size": [0.2, 0.2, 0.2], "at": [9, 0, 0.1]})
call("create_primitive", {"kind": "cylinder", "name": "uv_tool2", "size": [0.05, 0.05, 0.4], "at": [9, 0, 0.1]})
call("unwrap", {"names": ["uv_target2", "uv_tool2"]})
call("boolean", {"a": "uv_target2", "b": "uv_tool2", "operation": "difference"})
expect("boolean keeps the UV layer of a target that had one", len(bpy.data.objects["uv_target2"].data.uv_layers) == 1)

bail = call("sweep", {"name": "bail", "arc": {"center": [0, 0, 0.2], "radius": 0.09, "plane": "XZ", "start_deg": 0, "end_deg": 180}, "radius": 0.005})
expect("an arc sweep spans the diameter and rises by the radius", abs(bail["size"][0] - 0.19) < 0.002 and abs(bail["size"][2] - 0.095) < 0.002 and abs(bail["max"][2] - 0.295) < 0.002, bail)


call("create_primitive", {"kind": "cube", "name": "crate_a", "size": [1, 1, 1], "at": [0, 0, 0.5]})
call("create_primitive", {"kind": "cube", "name": "crate_b", "size": [1, 1, 2], "at": [0, 0, 1]})
placed = call("transform_objects", {"place": {"crate_a": [10, 0, 0], "crate_b": [12, 3, 0.5]}})
by_name = {o["name"]: o for o in placed}
expect("place puts each object's bottom centre on its own point", by_name["crate_a"]["min"][2] == 0 and by_name["crate_a"]["center"][:2] == [10.0, 0.0] and abs(by_name["crate_b"]["min"][2] - 0.5) < 1e-6 and by_name["crate_b"]["center"][:2] == [12.0, 3.0], placed)
top = call("transform_objects", {"place": {"crate_a": [10, 0, 5]}, "anchor": [0.5, 0.5, 1]})
expect("anchor picks the point of the box", abs(top[0]["max"][2] - 5) < 1e-6, top[0])


finish()
