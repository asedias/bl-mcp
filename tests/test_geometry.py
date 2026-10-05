"""Geometry: transforms, rotation on create and duplicate, repair_mesh, boolean repair, size-relative tolerances, export scale."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402


def near(a, b, tol=1e-3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def raises(label, fn, text):
    try:
        fn()
    except ValueError as err:
        expect(label, text in str(err), str(err))
    else:
        expect(label, False, "no error")


def cube(name, size, at, anchor=(0.5, 0.5, 0.5)):
    return call("create_primitive", {"kind": "cube", "name": name, "size": size, "at": at, "anchor": anchor})


fresh_scene()

# rotation on create
r = call("create_primitive", {"kind": "cube", "name": "bar", "size": [1, 0.2, 0.1], "at": [0, 0, 0], "rotate_deg": [0, 0, 90]})
expect("create rotated 90 about Z swaps X and Y", near(r["size"], [0.2, 1, 0.1]), r["size"])
r = call("create_primitive", {"kind": "cylinder", "name": "barrel", "size": [0.1, 0.1, 1], "at": [5, 5, 5], "rotate_deg": [0, 90, 0]})
expect("cylinder laid along X", near(r["size"], [1, 0.1, 0.1]) and near(r["center"], [5, 5, 5]), r)
r = call("create_primitive", {"kind": "torus", "name": "ring", "size": [1, 1, 0.1], "at": [0, 0, 0], "rotate_deg": [90, 0, 0]})
expect("torus rotates", r["size"][2] > 0.9 and r["size"][1] < 0.3, r["size"])

# transform_objects
cube("p", [1, 1, 1], [0, 0, 0])
cube("child", [0.2, 0.2, 0.2], [2, 0, 0])
call("parent", {"child": "child", "to": "p"})
call("transform_objects", {"names": ["p"], "rotate_deg": [0, 0, 90], "pivot": [0, 0, 0]})
child = call("measure", {"names": ["child"]})[0]
expect("child follows the turn around the pivot", near(child["center"], [0, 2, 0]), child["center"])
call("transform_objects", {"names": ["p"], "move": [1, 2, 3], "pivot": [0, 0, 0]})
child = call("measure", {"names": ["child"]})[0]
expect("move shifts the group with its child", near(child["center"], [1, 4, 3]), child["center"])
cube("q", [1, 1, 1], [10, 0, 0])
call("transform_objects", {"names": ["q"], "scale": [2, 1, 3]})
q = call("measure", {"names": ["q"]})[0]
expect("scale about the box centre keeps the centre", near(q["size"], [2, 1, 3]) and near(q["center"], [10, 0, 0]), q)
call("transform_objects", {"names": ["q"], "scale": 0.5, "pivot": [0, 0, 0]})
q = call("measure", {"names": ["q"]})[0]
expect("uniform scale about a pivot moves the centre", near(q["center"], [5, 0, 0]) and near(q["size"], [1, 0.5, 1.5]), q)
cube("a1", [1, 1, 1], [20, 0, 0])
cube("a2", [1, 1, 1], [22, 0, 0])
call("transform_objects", {"names": ["a1", "a2"], "rotate_deg": [0, 0, 90]})
a1, a2 = call("measure", {"names": ["a1", "a2"]})
expect("two objects turn as one group about the box centre", near(a1["center"], [21, -1, 0]) and near(a2["center"], [21, 1, 0]), (a1["center"], a2["center"]))
cube("dup_src", [1, 0.2, 0.2], [30, 0, 0])
d = call("duplicate", {"name": "dup_src", "new_name": "dup_rot", "offset": [0, 5, 0], "rotate_deg": [0, 0, 90]})
expect("duplicate turns about its own centre by default", near(d["size"], [0.2, 1, 0.2]) and near(d["center"], [30, 5, 0]), d)
d = call("duplicate", {"name": "dup_src", "new_name": "dup_piv", "rotate_deg": [0, 0, 90], "pivot": [29, 0, 0]})
expect("duplicate turns about a given pivot", near(d["center"], [29, 1, 0]), d["center"])
raises("zero scale refused", lambda: call("transform_objects", {"names": ["q"], "scale": 0}), "zero")

# repair_mesh on a damaged mesh
cube("bad", [1, 1, 1], [40, 0, 0])
obj = bpy.data.objects["bad"]
bm = bmesh.new()
bm.from_mesh(obj.data)
bm.faces.ensure_lookup_table()
top = max(bm.faces, key=lambda f: f.calc_center_median().z)
bmesh.ops.delete(bm, geom=[top], context="FACES")
bm.verts.ensure_lookup_table()
corner = bm.verts[0]
bm.verts.new(corner.co)
bm.verts.new(corner.co)
bm.verts.new((0.3, 0.3, 0.3))
bm.verts.new((0.4, 0.4, 0.4))
a, b = bm.verts.new((0.1, 0.1, 0.1)), bm.verts.new((0.2, 0.1, 0.1))
bm.edges.new((a, b))
bm.to_mesh(obj.data)
bm.free()
rep = call("repair_mesh", {"object": "bad"})
expect("repair sees the damage first", rep["before"]["open_edges"] >= 4 and rep["before"]["doubles"] >= 2 and rep["before"]["junk_vertices"] >= 4, rep["before"])
expect("repair leaves a closed mesh", rep["after"]["open_edges"] == 0 and rep["after"]["doubles"] == 0 and rep["after"]["junk_vertices"] == 0, rep["after"])
chk = call("check_mesh", {"name": "bad"})
expect("check_mesh agrees after repair", chk["closed"] and chk["volume"] > 0.99, chk)

# boolean with auto repair and with a clear error
cube("openbox", [1, 1, 1], [50, 0, 0])
call("delete_faces", {"object": "openbox", "where": {"normal": "+Z"}})
cube("cutter", [0.3, 0.3, 2], [50, 0, 0])
res = call("boolean", {"a": "openbox", "b": "cutter"})
expect("boolean heals an open box and cuts", res.get("repaired") == ["openbox"] and call("check_mesh", {"name": "openbox"})["closed"], res)

call("create_primitive", {"kind": "cylinder", "name": "wide", "size": [1, 1, 1], "at": [60, 0, 0], "segments": 16})
call("delete_faces", {"object": "wide", "where": {"normal": "+Z"}})
cube("cutter2", [0.3, 0.3, 0.3], [60, 0, 0])
try:
    call("boolean", {"a": "wide", "b": "cutter2"})
    expect("boolean explains an unrepairable mesh", False, "no error")
except ValueError as err:
    message = str(err)
    expect("error names object, count, place and remedy", "wide" in message and "open or non-manifold" in message and "world box" in message and "hole_sides=0" in message, message)
res = call("boolean", {"a": "wide", "b": "cutter2", "allow_open": True})
expect("allow_open still skips the check", "repaired" not in res, res)

# small objects: a mini pistol, 3-10 cm, default settings
parts = [
    ("g_slide", [0.1, 0.02, 0.025], [100.0, 0, 0.0625]),
    ("g_barrel", [0.03, 0.012, 0.012], [100.065, 0, 0.0625]),
    ("g_grip", [0.025, 0.02, 0.06], [100.035, 0, 0.02]),
    ("g_trigger", [0.008, 0.004, 0.015], [100.0, 0, 0.0525 - 0.0075]),
]
for name, size, at in parts:
    cube(name, size, at)
names = [p[0] for p in parts]
ff = call("find_floating", {"names": names})
expect("find_floating: touching mini pistol is one group", ff["floating"] == ["none"] and ff["connected_groups"] == 1, ff)
cube("g_far", [0.02, 0.02, 0.02], [100.0, 0.0, 0.2])
ff = call("find_floating", {"names": [*names, "g_far"]})
expect("a part 10 cm away floats", ff["floating"] != ["none"] and ff["floating"][0]["parts"] == ["g_far"], ff)
call("delete", {"names": ["g_far"]})
cube("g_hang", [0.02, 0.02, 0.02], [100.0, 0.0, 0.087])
ff = call("find_floating", {"names": ["g_slide", "g_hang"]})
expect("a 2 mm gap on small parts is a tiny gap", ff["floating"] != ["none"] and ff["tiny_gaps"] != ["none"], ff)
call("delete", {"names": ["g_hang"]})

cube("g_a", [0.04, 0.04, 0.04], [101, 0, 0])
cube("g_b", [0.04, 0.04, 0.04], [101.0399, 0, 0])
cc = call("check_contacts", {"a": "g_a", "b": "g_b"})
expect("check_contacts: 0.1 mm overlap on 4 cm cubes is intersecting", cc["state"] == "intersecting", cc)
cube("g_c", [0.04, 0.04, 0.04], [101, 0.0407, 0])
cc = call("check_contacts", {"a": "g_a", "b": "g_c"})
expect("check_contacts: 0.7 mm apart on 4 cm cubes is apart", cc["state"] == "apart", cc)
cube("g_big_a", [1, 1, 1], [200, 0, 0])
cube("g_big_b", [1, 1, 1], [201.00005, 0, 0])
expect("1 m cubes keep the old threshold (0.05 mm gap is touching)", call("check_contacts", {"a": "g_big_a", "b": "g_big_b"})["state"] == "touching")

cube("g_weld", [0.05, 0.05, 0.05], [102, 0, 0])
obj = bpy.data.objects["g_weld"]
bm = bmesh.new()
bm.from_mesh(obj.data)
for v in list(bm.verts)[:2]:
    bm.verts.new(v.co + Vector((2e-5, 0, 0)))
bm.to_mesh(obj.data)
bm.free()
w = call("weld", {"object": "g_weld"})
expect("weld default merges a 0.02 mm double on a 5 cm part", w["merged_vertices"] == 2, w)

cube("g_bevel", [0.04, 0.04, 0.04], [103, 0, 0])
bv = call("bevel_edges", {"object": "g_bevel", "segments": 1})
expect("bevel default stays inside a 4 cm cube", near(bv["size"], [0.04, 0.04, 0.04], 1e-4) and bv["tris"] > 12, bv)
cube("g_inset", [0.04, 0.04, 0.04], [104, 0, 0])
ins = call("inset_faces", {"object": "g_inset", "where": {"normal": "+Z"}})
expect("inset default works on a 4 cm cube", ins["inset"] == 1 and ins["tris"] > 12, ins)
dim = call("set_dimensions", {"name": "g_inset", "x": 0.03, "y": 0.03, "z": 0.05})
expect("set_dimensions on a small part", near(dim["size"], [0.03, 0.03, 0.05], 1e-4), dim)

cube("g_body", [0.08, 0.03, 0.05], [105, 0, 0])
call("create_primitive", {"kind": "cylinder", "name": "g_hole", "size": [0.012, 0.012, 0.08], "at": [105, 0, 0], "segments": 12})
bl = call("boolean", {"a": "g_body", "b": "g_hole"})
expect("boolean difference on small parts", bl["tris"] > 12 and "g_hole" not in bpy.data.objects and call("check_mesh", {"name": "g_body"})["closed"], bl)

for name, at in (("g_l", [106.0, -0.02, 0]), ("g_r", [106.0, 0.02, 0])):
    cube(name, [0.02, 0.01, 0.03], at)
sym = call("check_symmetry", {"names": ["g_l", "g_r"], "at": 0.0, "axis": "Y"})
expect("symmetric mini parts match with the default tolerance", sym["unmatched"] == 0 and sym["tolerance"] < 0.005, sym)
call("transform_objects", {"names": ["g_r"], "move": [0, 0.003, 0]})
sym = call("check_symmetry", {"names": ["g_l", "g_r"], "axis": "Y", "at": 0.0})
expect("a 3 mm shift of 2 cm parts is caught", sym["unmatched"] > 0, sym)

# export scale
out = Path(tempfile.mkdtemp(prefix="bl_geo_")) / "mini.glb"
cube("e_part", [0.1, 0.02, 0.05], [0, 0, 0.1])
before = call("measure", {"names": ["e_part"]})[0]
call("export_glb", {"path": str(out), "names": ["e_part"], "scale": 10})
after = call("measure", {"names": ["e_part"]})[0]
expect("export scale restores the scene", before["size"] == after["size"] and before["origin"] == after["origin"] and after["scale"] == [1, 1, 1], after)
known = set(bpy.data.objects.keys())
call("import_glb", {"path": str(out)})
imported = [n for n in bpy.data.objects.keys() if n not in known]
box = max((call("measure", {"names": [n]})[0] for n in imported), key=lambda m: max(m["size"]))
expect("exported model is ten times larger", abs(max(box["size"]) - 1.0) < 1e-2, box["size"])

finish()
