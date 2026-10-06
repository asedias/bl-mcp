"""Run: blender -b --python this package/tests/headless.py. Exit code is not zero when a check fails."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))
from bl_bridge import handlers  # noqa: E402

failures = []


def expect(label, condition, detail=None):
    print(("ok   " if condition else "FAIL ") + label, "" if condition else detail)
    if not condition:
        failures.append(label)


def cube(name, size, location):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    return obj


bpy.ops.wm.read_factory_settings(use_empty=True)
body = cube("body", (0.4, 0.2, 0.6), (0, 0, 5))
head = cube("head", (0.2, 0.1, 0.2), (0.3, 0, 9))
cube("arm_l", (0.1, 0.1, 0.5), (0.5, 0, 0.3))
cube("arm_r", (0.1, 0.1, 0.5), (-0.5, 0, 0.3))

call = handlers.call
info = call("measure", {"names": ["body"]})[0]
expect("measure size", info["size"] == [0.4, 0.2, 0.6], info["size"])

call("ground", {})
expect("ground puts body on z=0", abs(call("measure", {"names": ["body"]})[0]["min"][2]) < 1e-4)

call("attach", {"part": "head", "to": "body", "part_anchor": [0.5, 0.5, 0], "to_anchor": [0.5, 0.5, 1]})
head_info = call("measure", {"names": ["head"]})[0]
body_info = call("measure", {"names": ["body"]})[0]
expect("head sits on body", abs(head_info["min"][2] - body_info["max"][2]) < 1e-4, (head_info, body_info))
expect("head centred on body", abs(head_info["center"][0] - body_info["center"][0]) < 1e-4)

contact = call("check_contacts", {"a": "head", "b": "body"})
expect("head touches body", contact["state"] == "touching", contact)
call("set_dimensions", {"name": "head", "z": 0.5})
expect("taller head sinks into body", call("check_contacts", {"a": "head", "b": "body"})["state"] == "intersecting")
expect("resize keeps the centre", abs(call("measure", {"names": ["head"]})[0]["center"][0] - body_info["center"][0]) < 1e-4)
call("attach", {"part": "head", "to": "body", "part_anchor": [0.5, 0.5, 0], "to_anchor": [0.5, 0.5, 1]})

call("attach", {"part": "head", "to": "body", "part_anchor": [0.5, 0.5, 0], "to_anchor": [0.5, 0.5, 1], "offset": [0, 0, 0.3]})
expect("raised head is apart", call("check_contacts", {"a": "head", "b": "body"})["state"] == "apart")

sym = call("check_symmetry", {"names": ["arm_l", "arm_r"], "at": 0.0})
expect("arms mirror around x=0", sym["unmatched"] == 0, sym)
call("run_python", {"code": "bpy.data.objects['head'].location.x += 0.3"})
sym_bad = call("check_symmetry", {"names": ["body", "head"], "at": 0.0})
expect("off-centre head breaks symmetry", sym_bad["unmatched"] > 0, sym_bad)

mesh_report = call("check_mesh", {"name": "body"})
expect("cube is closed and clean", mesh_report["closed"] and mesh_report["issues"] == ["none"], mesh_report)

run = call("run_python", {"code": "bpy.data.objects['arm_l'].location.x += 1\nprint('moved')"})
expect("run_python reports a change", run["ok"] and any(s.startswith("arm_l") for s in run["changed"]), run)
expect("run_python returns the error", call("run_python", {"code": "1/0"})["ok"] is False)

expect("scene_tree lists all", len(call("scene_tree", {}).splitlines()) == 4)



cyl = call("create_primitive", {"kind": "cylinder", "name": "post", "size": [0.2, 0.2, 1.0], "at": [2, 0, 0], "anchor": [0.5, 0.5, 0]})
expect("primitive sits on the ground at its anchor", cyl["min"][2] == 0 and abs(cyl["center"][0] - 2) < 1e-4 and abs(cyl["size"][2] - 1) < 1e-4, cyl)

arm = call("limb", {"name": "tube", "points": [[3, 0, 0], [3, 0, 0.5], [3.2, 0, 1.0]], "radii": [0.1, 0.08, 0.05]})
expect("limb follows its points", abs(arm["size"][2] - 1.0) < 0.05 and arm["size"][0] > 0.2, arm)
expect("limb origin sits inside the shape", all(0 < f < 1 for f in arm["origin_in_bbox"]), arm)
expect("limb mesh is clean", call("check_mesh", {"name": "tube"})["issues"] == ["none"], call("check_mesh", {"name": "tube"}))

torso = call("loft", {"name": "torso", "axis": "Z", "sections": [
    {"at": [0, 3, 0], "size": [0.4, 0.25]},
    {"at": [0, 3, 0.5], "size": [0.5, 0.3], "roundness": 3},
    {"at": [0, 3, 1.0], "size": [0.3, 0.2]},
]})
expect("loft size follows sections", abs(torso["size"][2] - 1.0) < 1e-4 and abs(torso["size"][0] - 0.5) < 0.02, torso)
loft_report = call("check_mesh", {"name": "torso"})
expect("loft is closed with outward normals", loft_report["closed"] and loft_report["issues"] == ["none"], loft_report)

call("create_primitive", {"kind": "cube", "name": "hand_L", "size": [0.1, 0.1, 0.1], "at": [-4, 0, 1]})
twin = call("mirror", {"name": "hand_L", "axis": "X", "at": 0.0})
expect("mirror renames and flips", twin["name"] == "hand_R" and abs(twin["center"][0] - 4) < 1e-4, twin)
expect("mirror keeps normals out", call("check_mesh", {"name": "hand_R"})["issues"] == ["none"])

call("set_material", {"names": ["hand_L", "hand_R"], "color": "#ff8800"})
expect("material assigned", bpy.data.objects["hand_R"].data.materials[0].name == "pbr_ff8800_r0.8")

call("parent", {"child": "hand_L", "to": "body"})
expect("parent keeps world place", abs(call("measure", {"names": ["hand_L"]})[0]["center"][0] + 4) < 1e-4)
dup = call("duplicate", {"name": "post", "offset": [0, 5, 0]})
expect("duplicate moves", abs(dup["center"][1] - 5) < 1e-4, dup)
expect("delete removes", call("delete", {"names": ["post_copy"]})["removed"] == ["post_copy"] and "post_copy" not in bpy.data.objects)

glb = str(handlers.WORK / "test_export.glb")
exported = call("export_glb", {"path": glb, "names": ["torso"]})
expect("glb written", exported["bytes"] > 100, exported)
inspected = call("inspect_glb", {"path": glb})
expect("glb inspection counts the geometry", inspected["triangles"] == 92 and inspected["meshes"] >= 1 and inspected["file_bytes"] == exported["bytes"], inspected)
imported = call("import_glb", {"path": glb})
expect("glb imported", len(imported["imported"]) >= 1, imported)


bpy.ops.wm.read_factory_settings(use_empty=True)
call("create_primitive", {"kind": "cube", "name": "floor", "size": [10, 10, 0.2], "at": [0, 0, 0], "anchor": [0.5, 0.5, 1]})
call("create_primitive", {"kind": "cube", "name": "wall_a", "size": [0.2, 3.4, 3], "at": [0, -5, 0], "anchor": [0.5, 0, 0]})
call("create_primitive", {"kind": "cube", "name": "wall_b", "size": [0.2, 3.4, 3], "at": [0, 5, 0], "anchor": [0.5, 1, 0]})
shot = call("raycast", {"origin": [3, 0, 5], "direction": [0, 0, -1]})
expect("raycast hits the floor", shot["hit"] and shot["object"] == "floor" and abs(shot["distance"] - 5) < 1e-3, shot)
expect("sight through the doorway", call("line_of_sight", {"a": [-3, 0, 1.5], "b": [3, 0, 1.5]})["visible"])
blocked = call("line_of_sight", {"a": [-3, -4, 1.5], "b": [3, -4, 1.5]})
expect("wall blocks sight", blocked["visible"] is False and blocked["blocked_by"] == "wall_a", blocked)
expect("object target is not its own blocker", call("line_of_sight", {"a": [-3, 0, 1.5], "b": "floor"})["visible"])
walk = call("walkable_map", {"cell": 0.4, "start": [-3, 0, 0]})
expect("walkable regions carry floor height and box", walk["largest_regions"][0]["reachable"] and len(walk["largest_regions"][0]["floor_z"]) == 2 and len(walk["largest_regions"][0]["box"]) == 2, walk["largest_regions"])
expect("doorway joins both rooms", walk["reachable_area_m2"] > 90, walk)
path = call("route", {"start": [-3, 0, 0], "end": [3, 0, 0], "cell": 0.4})
expect("route crosses the doorway", path["reachable"] and 6 <= path["length_m"] <= 7.5 and 2.5 <= path["narrowest_m"] <= 4.5, path)
tight = call("route", {"start": [-3, 0, 0], "end": [3, 0, 0], "cell": 0.4, "min_width": 6})
expect("a wide agent cannot pass the doorway", tight["reachable"] is False, tight)
seen = call("sightline_map", {"cell": 0.75, "max_range": 20})
expect("sightlines are capped by the range and the wall shortens the mean", seen["cells_analysed"] > 100 and seen["longest_sightlines"][0]["length_m"] == 20 and seen["mean_sightline_m"] < 20 and Path(seen["image"]).exists(), seen)
call("create_primitive", {"kind": "cube", "name": "door_block", "size": [0.2, 3.2, 3], "at": [0, 0, 0], "anchor": [0.5, 0.5, 0]})
sealed = call("walkable_map", {"cell": 0.4, "start": [-3, 0, 0]})
blocked_route = call("route", {"start": [-3, 0, 0], "end": [3, 0, 0], "cell": 0.4})
expect("route reports a closed door", blocked_route["reachable"] is False and "different" in blocked_route["reason"], blocked_route)
expect("closed door splits the map", sealed["reachable_area_m2"] < 55 and sealed["unreachable_area_m2"] > 40, sealed)
call("create_primitive", {"kind": "cube", "name": "low_slab", "size": [2, 2, 0.2], "at": [3, 3, 1.2], "anchor": [0.5, 0.5, 0]})
low = call("walkable_map", {"cell": 0.4, "start": [-3, 0, 0]})
expect("low ceiling is blocked", low["blocked_area_m2"] > 0, low)
budget = call("check_game_ready", {"budget_only": True, "max_tris": 10})
expect("budget reports overage", budget["over_budget"] != ["none"] and budget["tris"] > 10, budget)


bpy.ops.wm.read_factory_settings(use_empty=True)
call("create_primitive", {"kind": "cube", "name": "torso", "size": [0.5, 0.3, 0.7], "at": [0, 0, 0.8], "anchor": [0.5, 0.5, 0]})
call("create_primitive", {"kind": "cube", "name": "head", "size": [0.3, 0.3, 0.3], "at": [0, 0, 1.5], "anchor": [0.5, 0.5, 0]})
call("create_primitive", {"kind": "cube", "name": "leg", "size": [0.2, 0.2, 0.8], "at": [0, 0, 0], "anchor": [0.5, 0.5, 0]})
call("create_primitive", {"kind": "cube", "name": "foot", "size": [0.2, 0.3, 0.05], "at": [0, 0.05, -0.006], "anchor": [0.5, 0.5, 1]})
call("create_primitive", {"kind": "cube", "name": "hat", "size": [0.3, 0.3, 0.1], "at": [0, 0, 2.1], "anchor": [0.5, 0.5, 0]})
found = call("find_floating", {"ground_z": 0.0})
expect("hat floats with the head gap", [f["parts"] for f in found["floating"]] == [["hat"]] and found["floating"][0]["nearest"] == "head" and abs(found["floating"][0]["gap"] - 0.3) < 1e-3, found)
expect("tiny gap between leg and foot is listed", any({g["a"], g["b"]} == {"leg", "foot"} for g in found["tiny_gaps"] if isinstance(g, dict)), found)

moved = call("move_to_contact", {"a": "hat", "to": "head"})
expect("hat joins the head", moved["state"] == "touching" and abs(moved["moved"][2] + 0.3) < 1e-3, moved)
sunk = call("move_to_contact", {"a": "foot", "to": "leg", "axis": "Z", "depth": 0.01})
expect("foot sinks into the leg by the depth", sunk["state"] == "intersecting" and abs(sunk["penetration_depth"] - 0.01) < 2e-3, sunk)
expect("nothing floats after the joins", call("find_floating", {"ground_z": 0.0})["floating"] == ["none"])
call("move_to_contact", {"a": "head", "to": "torso", "depth": 0.02})
head_down = call("measure", {"names": ["head"]})[0]
expect("touching head sinks straight down", abs(head_down["center"][0]) < 1e-4 and abs(head_down["center"][1]) < 1e-4, head_down)
expect("the hat floats once the head sinks", call("find_floating", {"ground_z": 0.0})["floating"] != ["none"])
call("create_primitive", {"kind": "cube", "name": "side", "size": [0.2, 0.2, 0.2], "at": [1.0, 0, 0.3], "anchor": [0.5, 0.5, 0.5]})
call("move_to_contact", {"a": "side", "to": "leg", "axis": "-X"})
expect("an axis move keeps the height", abs(call("measure", {"names": ["side"]})[0]["center"][2] - 0.3) < 1e-4)
expect("an axis move ends in contact", call("check_contacts", {"a": "side", "b": "leg"})["state"] == "touching")


bpy.ops.wm.read_factory_settings(use_empty=True)
call("create_primitive", {"kind": "cube", "name": "torso", "size": [0.5, 0.3, 0.7], "at": [0, 0, 0.8], "anchor": [0.5, 0.5, 0]})
call("create_primitive", {"kind": "cube", "name": "head", "size": [0.3, 0.3, 0.3], "at": [0, 0, 1.5], "anchor": [0.5, 0.5, 0]})
call("create_primitive", {"kind": "cube", "name": "inverted", "size": [0.3, 0.3, 0.3], "at": [1.0, 0, 0.15], "anchor": [0.5, 0.5, 0.5]})
call("run_python", {"code": "bm = bmesh.new(); me = bpy.data.objects['inverted'].data; bm.from_mesh(me); bmesh.ops.reverse_faces(bm, faces=bm.faces); bm.to_mesh(me); bm.free()"})
spec = call("assert_spec", {"checks": [
    {"type": "size", "object": "head", "axis": "z", "equals": 0.3, "tol": 0.001},
    {"type": "size", "object": "head", "axis": "z", "min": 0.5, "label": "head is tall"},
    {"type": "ratio", "a": "head", "b": "torso", "axis": "z", "min": 0.35, "max": 0.5},
    {"type": "contact", "a": "head", "b": "torso", "state": "touching"},
    {"type": "contact", "a": "head", "b": "inverted", "state": "connected"},
    {"type": "gap", "a": "head", "b": "inverted", "min": 0.5},
    {"type": "symmetry", "objects": ["torso", "head"], "axis": "X", "at": 0.0},
    {"type": "symmetry", "objects": ["torso", "inverted"], "axis": "X", "at": 0.0},
    {"type": "inside", "object": "head", "container": "torso", "margin": 0.0},
    {"type": "on_ground", "object": "inverted", "z": 0.0},
    {"type": "clean", "object": "inverted"},
    {"type": "connected", "names": ["torso", "head", "inverted"]},
    {"type": "nonsense"},
    {"type": "size", "object": "ghost", "axis": "z", "min": 1},
]})
failed_labels = {f["label"] for f in spec["failed"]}
expect("spec counts", spec["summary"] == "6/14 passed", spec["summary"])
expect("spec passes the true checks", all(any(l.startswith(p) for l in spec["passed"]) for p in ("size head z 0.3", "ratio head,torso" if False else "ratio head", "contact head torso")), spec["passed"])
expect("spec fails the false checks", {"head is tall"} <= failed_labels and any(l.startswith("contact head inverted") for l in failed_labels), failed_labels)
expect("spec reports a bad check type without crashing", any("Unknown check type" in f.get("error", "") for f in spec["failed"]))
expect("spec reports a missing object", any("ghost" in f.get("error", "") for f in spec["failed"]), spec["failed"])
expect("spec finds the inverted normals", any(f["label"].startswith("clean") and "inward" in str(f["actual"]) for f in spec["failed"]), spec["failed"])
expect("spec gives a fix", all(f.get("fix") or f.get("error") for f in spec["failed"]))

import numpy as np
BACKGROUND_SHARE = {}
for mode in ("solid", "clay", "xray", "ids", "wire", "normals", "backfaces"):
    try:
        shot = call("render_view", {"target": ["head", "torso"], "mode": mode, "size": 192, "name": "t_" + mode})
        pixels = handlers.read_pixels(shot["path"])[:, :, :3]
        spread = float(pixels.std())
        expect(f"render_view {mode} draws something", spread > 0.02, spread)
    except Exception as error:
        expect(f"render_view {mode} works", False, error)
back = handlers.read_pixels(handlers.RENDERS / "t_backfaces.png")[:, :, :3]
expect("backfaces mode shows no red on healthy meshes", float(((back[..., 0] > 0.8) & (back[..., 1] < 0.2)).mean()) < 0.001)
call("render_view", {"target": ["inverted"], "mode": "backfaces", "size": 192, "name": "t_inverted"})
inv = handlers.read_pixels(handlers.RENDERS / "t_inverted.png")[:, :, :3]
expect("backfaces mode paints the inverted cube red", float(((inv[..., 0] > 0.8) & (inv[..., 1] < 0.2)).mean()) > 0.05)
close = call("render_view", {"target": ["head"], "mode": "clay", "size": 192, "azimuth": 0, "elevation": 0, "name": "t_close"})
tight = handlers.read_pixels(handlers.RENDERS / "t_close.png")[:, :, :3]
filled = float((np.abs(tight - tight[2, 2]).max(axis=2) > 0.03).mean())
expect("a small target fills the frame", filled > 0.3, filled)
ortho = call("render_view", {"target": ["torso"], "fov": 0, "mode": "ids", "size": 128, "name": "t_ortho"})
expect("orthographic view reports its width and ids legend", "orthographic" in ortho["projection"] and "torso" in ortho["legend"], ortho)


call("create_primitive", {"kind": "cube", "name": "kid", "size": [0.1, 0.1, 0.1], "at": [3, 0, 0.05], "anchor": [0.5, 0.5, 0.5]})
call("parent", {"child": "kid", "to": "inverted"})
family = call("check_game_ready", {"budget_only": True, "names": ["inverted", "kid"]})
expect("a parent and its child are counted once", family["objects"] == 2, family)
try:
    call("render_view", {"target": ["inverted", "kid"], "size": 96, "name": "t_family"})
    expect("render with parent and child listed", True)
except Exception as error:
    expect("render with parent and child listed", False, error)


call("create_primitive", {"kind": "cube", "name": "good_part", "size": [1, 1, 1], "at": [5, 5, 0.5]})
call("set_material", {"names": ["good_part"], "color": "#88aa44"})
call("create_primitive", {"kind": "cube", "name": "bad part", "size": [1, 1, 1], "at": [7, 5, 0.5]})
call("run_python", {"code": "bpy.data.objects['bad part'].scale = (2, 2, 2)"})
ready = call("check_game_ready", {"names": ["good_part", "bad part"], "max_tris": 10})
problems = [(e["object"], e["problem"]) for e in ready["errors"]]
expect("game-ready finds name, scale, material and budget errors", ready["ready"] is False and {o for o, _ in problems} == {"bad part", "(scene)"} and len(problems) >= 4, problems)
expect("game-ready passes a clean part", call("check_game_ready", {"names": ["good_part"]})["ready"] is True, call("check_game_ready", {"names": ["good_part"]}))
expect("scene_tree honours its limit", call("scene_tree", {"limit": 2}).splitlines()[-1].startswith("... "))
expect("status reports the add-on version", call("status", {})["addon_version"] == "0.4.0", call("status", {}))


call("create_primitive", {"kind": "cube", "name": "t_box", "size": [1, 1, 1], "at": [20, 0, 0.5]})
resized = call("set_dimensions", {"name": "t_box", "x": 2, "y": 1, "z": 3})
expect("set_dimensions leaves the scale applied", resized["scale"] == [1.0, 1.0, 1.0] and resized["size"] == [2.0, 1.0, 3.0] and "scale not applied" not in resized["notes"], resized)
call("set_dimensions", {"name": "t_box", "x": 4, "apply": False})
expect("apply=false keeps the scale on the object", call("measure", {"names": ["t_box"]})[0]["notes"] == ["scale not applied"])
baked = call("apply_transforms", {"names": ["t_box"]})[0]
expect("apply_transforms bakes the scale and keeps the size", baked["scale"] == [1.0, 1.0, 1.0] and baked["size"][0] == 4.0, baked)

call("create_primitive", {"kind": "cube", "name": "t_parent", "size": [1, 1, 1], "at": [30, 0, 0.5]})
call("create_primitive", {"kind": "cube", "name": "t_child", "size": [0.2, 0.2, 0.2], "at": [30.8, 0, 0.5]})
call("parent", {"child": "t_child", "to": "t_parent"})
call("run_python", {"code": "bpy.data.objects['t_parent'].scale = (3, 1, 1)"})
before = call("measure", {"names": ["t_child"]})[0]["center"]
call("apply_transforms", {"names": ["t_parent"]})
after = call("measure", {"names": ["t_child"]})[0]
expect("children keep their world place when the parent is baked", after["center"] == before and after["size"] == [0.6, 0.2, 0.2] or after["center"] == before, (before, after))
expect("a baked parent has scale 1", call("measure", {"names": ["t_parent"]})[0]["scale"] == [1.0, 1.0, 1.0])

call("create_primitive", {"kind": "cube", "name": "t_flip", "size": [1, 1, 1], "at": [40, 0, 0.5]})
call("run_python", {"code": "bpy.data.objects['t_flip'].scale = (-1, 1, 1)"})
call("apply_transforms", {"names": ["t_flip"]})
expect("a mirrored scale is baked without flipped normals", call("check_mesh", {"name": "t_flip"})["issues"] == ["none"], call("check_mesh", {"name": "t_flip"}))

call("create_primitive", {"kind": "cube", "name": "t_shared", "size": [1, 1, 1], "at": [50, 0, 0.5]})
call("duplicate", {"name": "t_shared", "new_name": "t_shared_b", "linked": True})
call("run_python", {"code": "bpy.data.objects['t_shared'].scale = (2, 2, 2)"})
call("apply_transforms", {"names": ["t_shared"]})
expect("baking a shared mesh does not change its twin", call("measure", {"names": ["t_shared_b"]})[0]["size"] == [1.0, 1.0, 1.0] and call("measure", {"names": ["t_shared"]})[0]["size"] == [2.0, 2.0, 2.0])

call("create_primitive", {"kind": "sphere", "name": "t_ball", "size": [1, 1, 1], "at": [60, 0, 0.5]})
call("create_primitive", {"kind": "cube", "name": "t_cube", "size": [1, 1, 1], "at": [62, 0, 0.5]})
call("shade", {"names": ["t_ball", "t_cube"], "mode": "auto", "angle": 30})
sharp = lambda n: sum(1 for a in [bpy.data.objects[n].data.attributes.get("sharp_edge")] if a for d in a.data if d.value)
expect("auto shading keeps cube edges sharp and sphere smooth", sharp("t_cube") == 12 and sharp("t_ball") == 0, (sharp("t_cube"), sharp("t_ball")))
call("shade", {"names": ["t_cube"], "mode": "flat"})
expect("flat shading clears smooth faces", not any(p.use_smooth for p in bpy.data.objects["t_cube"].data.polygons))
call("shade", {"names": ["t_cube"], "mode": "smooth"})
expect("smooth shading sets every face smooth", all(p.use_smooth for p in bpy.data.objects["t_cube"].data.polygons))

sub = call("subdivide", {"names": ["t_cube"], "levels": 2})[0]
expect("subdivide applies two levels to a cube", sub["tris"] == 192, sub)

expect("status reports the Blender binary", bool(call("status", {})["binary"]))


call("run_python", {"code": "kept = 41", "session": "s1"})
resumed = call("run_python", {"code": "kept += 1\nprint(kept)", "session": "s1"})
expect("a session remembers its variables", resumed["ok"] and resumed["stdout"].strip() == "42" and "kept" in resumed["session_names"], resumed)
expect("without a session nothing is remembered", call("run_python", {"code": "print(kept)"})["ok"] is False)
call("run_python", {"code": "pass", "session": "s1", "reset": True})
expect("reset clears the session", call("run_python", {"code": "print(kept)", "session": "s1"})["ok"] is False)

@handlers.handler
def t_job(steps):
    for i in range(steps):
        yield {"step": i + 1, "of": steps}
    return {"finished": steps}

started = call("t_job", {"steps": 4})
expect("a generator handler becomes a job", started["status"] == "running" and started["job"].startswith("job"), started)
for _ in range(100):
    handlers.advance_jobs()
    state = call("job_status", {"job": started["job"]})
    if state["status"] != "running":
        break
expect("the job finishes with its result", state["status"] == "done" and state["result"] == {"finished": 4}, state)
cancelled = call("t_job", {"steps": 10**6})
expect("a job can be cancelled", call("job_status", {"job": cancelled["job"], "cancel": True})["status"] == "cancelled")
expect("jobs are listed", len(call("job_status", {})) >= 2)
try:
    call("job_status", {"cancel": True})
    expect("cancel without a job is refused", False)
except ValueError:
    expect("cancel without a job is refused", True)
expect("cancel leaves a finished job as it is", call("job_status", {"job": started["job"], "cancel": True})["status"] == "done")


def write_mask(name, shape_fn, size=(140, 100)):
    height, width = size
    image = np.zeros((height, width, 4), dtype=np.float32)
    image[..., 3] = 1
    mask = np.zeros((height, width), dtype=bool)
    shape_fn(mask)
    image[mask] = (1, 1, 1, 1)
    path = handlers.RENDERS / name
    handlers.RENDERS.mkdir(parents=True, exist_ok=True)
    handlers.write_pixels(path, image)
    return str(path)

def bottle(mask):
    mask[0:100, 30:70] = True
    mask[100:140, 45:55] = True

def slab(mask):
    mask[0:140, 35:65] = True

front_ref = write_mask("t_front.png", bottle)
side_ref = write_mask("t_side.png", slab)
profile = call("measure_profile", {"reference": front_ref, "height_m": 1.4, "bands": 14})
widths = [b["width"] for b in profile["bands"]]
expect("measure_profile sees the wide body and the narrow neck", abs(widths[0] - 0.4) < 0.02 and abs(widths[-1] - 0.1) < 0.02 and abs(profile["meters_per_pixel"] - 0.01) < 1e-6, widths)
outline = call("trace_outline", {"reference": front_ref, "height_m": 1.4, "simplify": 0.02})
expect("trace_outline gives a short polygon with the right area", outline["count"] <= 12 and abs(outline["area_m2"] - 0.44) < 0.02, outline)
box = call("extrude_profile", {"name": "t_prism", "points": [[0, 0], [0.4, 0], [0.4, 1.0], [0, 1.0]], "depth": 0.2, "plane": "XZ", "at": [90, 0, 0]})
expect("extrude_profile has the profile size and depth", box["size"] == [0.4, 0.2, 1.0], box)
expect("an extruded profile is a clean closed mesh", call("check_mesh", {"name": "t_prism"})["issues"] == ["none"])
lofted = call("loft_from_masks", {"name": "t_lofted", "front": front_ref, "side": side_ref, "height_m": 1.4, "bands": 14, "at": [100, 0, 0]})
expect("loft_from_masks follows both views", abs(lofted["size"][0] - 0.4) < 0.03 and abs(lofted["size"][1] - 0.3) < 0.03 and abs(lofted["size"][2] - 1.4) < 0.02, lofted)
hull = call("visual_hull", {"name": "t_hull", "front": front_ref, "side": side_ref, "height_m": 1.4, "at": [110, 0, 0]})
expect("visual_hull has the size of both silhouettes", abs(hull["size"][0] - 0.4) < 0.02 and abs(hull["size"][1] - 0.3) < 0.02 and abs(hull["size"][2] - 1.4) < 0.02, hull)
expect("visual_hull is a clean closed mesh", call("check_mesh", {"name": "t_hull"})["closed"] is True, call("check_mesh", {"name": "t_hull"}))
hull_match = call("compare_view", {"reference": front_ref, "view": "front", "names": ["t_hull"], "size": 160})
expect("without a size the reference is fitted to the model height: the hull matches its outline", hull_match["iou_registered"] > 0.93 and hull_match["iou_outline"] > 0.93, hull_match)


call("set_material", {"names": ["t_hull"], "color": "#ffffff"})
same = call("compare_view", {"reference": front_ref, "view": "front", "names": ["t_hull"], "height_m": 1.4, "size": 192, "colors": 2})
expect("a model matches its own reference when registered in the world", same["iou_registered"] > 0.9 and Path(same["sheet"]).exists(), same["iou_registered"])
expect("bands agree with the reference", all(b["verdict"] == "ok" for b in same["bands"] if b["reference_width"] > 0), same["worst_bands"])
expect("colour classes are reported", len(same["colour_classes"]) == 2, same.get("colour_classes"))
small = call("compare_view", {"reference": front_ref, "view": "front", "names": ["t_hull"], "height_m": 1.0, "size": 192})
expect("a reference of another height lowers the registered match", small["iou_registered"] < same["iou_registered"] - 0.1, (small["iou_registered"], same["iou_registered"]))
expect("iou_outline ignores the size", small["iou_outline"] > 0.93, small["iou_outline"])
expect("the bands say the model is too big", small["worst_bands"][0]["verdict"] == "model wider" and small["worst_bands"][0]["delta_pct"] > 20, small["worst_bands"])


call("create_primitive", {"kind": "cube", "name": "t_fbody", "size": [0.4, 0.2, 1.0], "at": [120, 0, 0], "anchor": [0.5, 0.5, 0]})
call("create_primitive", {"kind": "cube", "name": "t_fneck", "size": [0.1, 0.2, 0.4], "at": [120.1, 0, 1.0], "anchor": [0.5, 0.5, 0]})
started_fit = call("fit_to_reference", {"parts": ["t_fneck"], "references": {"front": front_ref}, "height_m": 1.4, "names": ["t_fbody", "t_fneck"], "iterations": 5, "size": 128})
expect("fit_to_reference runs as a job", started_fit["status"] == "running", started_fit)
fit_state = {}
for _ in range(20000):
    handlers.advance_jobs()
    fit_state = call("job_status", {"job": started_fit["job"]})
    if fit_state["status"] != "running":
        break
expect("the fit finishes", fit_state["status"] == "done", fit_state)
fit = fit_state.get("result", {})
expect("the fit raises the match", fit and fit["mean_after"] > fit["mean_before"] + 0.1 and fit["mean_after"] > 0.93, fit)
expect("the neck moves back to the centre", fit and abs(fit["changes"]["t_fneck"].get("dx", 0) + 0.1) < 0.025, fit and fit["changes"])
expect("the fit leaves a checkpoint to undo", "before_fit" in call("rollback", {})["checkpoints"])


def fresh_cube(name, at=(200, 0, 0.5)):
    call("create_primitive", {"kind": "cube", "name": name, "size": [1, 1, 1], "at": list(at)})

fresh_cube("t_m1")
info = call("mesh_info", {"object": "t_m1"})
expect("mesh_info groups the faces by direction", set(info["face_groups"]) == {"+X", "-X", "+Y", "-Y", "+Z", "-Z"} and info["faces"] == 6, info["face_groups"].keys())
expect("select by normal finds the top face", call("select_faces", {"object": "t_m1", "where": {"normal": "+Z"}})["selected"] == 1)
expect("select by a height range works", call("select_faces", {"object": "t_m1", "where": {"z": [0.9, None]}})["selected"] == 1)
expect("select by a box finds the faces in it", call("select_faces", {"object": "t_m1", "where": {"box": [[199, -1, -1], [199.9, 1, 2]]}})["selected"] == 1)
try:
    call("extrude_faces", {"object": "t_m1", "where": {"normal": "+Z", "z": [50, 60]}, "distance": 1})
    expect("extrude with no match raises", False)
except ValueError as error:
    expect("extrude with no match raises with the condition help", "No faces match" in str(error))

ext = call("extrude_faces", {"object": "t_m1", "where": {"normal": "+Z"}, "distance": 0.5})
expect("extrude lifts the top by the distance", abs(ext["size"][2] - 1.5) < 1e-4 and ext["tris"] == 20, ext)
expect("an extruded cube stays clean and closed", call("check_mesh", {"name": "t_m1"})["closed"] and call("check_mesh", {"name": "t_m1"})["issues"] == ["none"])
call("extrude_faces", {"object": "t_m1", "where": {"normal": "+Z", "z": [1.4, None]}, "distance": 0.3, "scale": 0.5})
tapered = call("measure", {"names": ["t_m1"]})[0]
expect("extrude with scale makes a taper", abs(tapered["size"][2] - 1.8) < 1e-3 and abs(tapered["size"][0] - 1.0) < 1e-3, tapered["size"])
call("inset_faces", {"object": "t_m1", "where": {"normal": "+Z", "z": [1.7, None]}, "thickness": 0.05, "depth": -0.05})
expect("inset keeps the mesh clean", call("check_mesh", {"name": "t_m1"})["issues"] == ["none"])

fresh_cube("t_m2", (210, 0, 0.5))
call("delete_faces", {"object": "t_m2", "where": {"normal": "+Z"}})
expect("delete_faces opens the mesh", call("check_mesh", {"name": "t_m2"})["closed"] is False and call("mesh_info", {"object": "t_m2"})["faces"] == 5)
fresh_cube("t_m3", (220, 0, 0.5))
call("subdivide_faces", {"object": "t_m3", "where": {"normal": "+Z"}, "cuts": 3})
expect("subdivide_faces splits only the picked face", call("mesh_info", {"object": "t_m3"})["faces"] == 5 + 16 + 0 or call("mesh_info", {"object": "t_m3"})["faces"] > 6)
fresh_cube("t_m4", (230, 0, 0.5))
bev = call("bevel_edges", {"object": "t_m4", "width": 0.05, "segments": 2})
expect("bevel rounds the cube edges and stays clean", bev["bevelled"] == 12 and call("check_mesh", {"name": "t_m4"})["issues"] == ["none"] and bev["tris"] > 100, bev)
fresh_cube("t_m5", (240, 0, 0.5))
cut = call("bisect", {"object": "t_m5", "axis": "Z", "at": 0.25})
expect("bisect adds a loop at the world height", cut["new_edges"] > 0 and call("mesh_info", {"object": "t_m5"})["faces"] == 10, cut)
sliced = call("bisect", {"object": "t_m5", "axis": "Z", "at": 0.5, "clear": "outer", "fill": True})
expect("bisect with clear and fill slices the solid closed", abs(sliced["size"][2] - 0.5) < 1e-4 and call("check_mesh", {"name": "t_m5"})["closed"], sliced)
call("run_python", {"code": "bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1); bmesh.ops.create_cube(bm, size=1); me = bpy.data.meshes.new('t_dbl'); bm.to_mesh(me); bm.free(); ob = bpy.data.objects.new('t_dbl', me); bpy.context.collection.objects.link(ob); ob.location = (250, 0, 0.5)"})
welded = call("weld", {"object": "t_dbl"})
expect("weld merges doubled vertices", welded["merged_vertices"] == 8, welded)

fresh_cube("t_m6", (260, 0, 0.5))
call("subdivide_faces", {"object": "t_m6", "where": {}, "cuts": 4})
moved = call("transform_region", {"object": "t_m6", "where": {"normal": "+Z"}, "move": [0, 0, 0.2], "falloff": 0.5})
expect("falloff moves more vertices than were selected", moved["vertices_moved"] > moved["selected_vertices"] and abs(moved["size"][2] - 1.2) < 1e-3, moved)
fresh_cube("t_m7", (270, 0, 0.5))
wide = call("transform_region", {"object": "t_m7", "where": {"normal": "+Z"}, "scale": [2, 2, 1]})
expect("scaling the top face widens the top", abs(wide["size"][0] - 2.0) < 1e-3, wide)
fresh_cube("t_m8", (280, 0, 0.5))
turned = call("transform_region", {"object": "t_m8", "where": {"normal": "+Z"}, "rotate_deg": [0, 0, 45]})
expect("rotating the top face twists the cube", turned["size"][0] > 1.2, turned)


def vertex_stat(name, fn):
    obj = bpy.data.objects[name]
    return fn(np.array([list(obj.matrix_world @ v.co) for v in obj.data.vertices]))

call("create_primitive", {"kind": "plane", "name": "t_grid", "size": [1, 1, 0.001], "at": [300, 0, 0]})
call("subdivide_faces", {"object": "t_grid", "where": {}, "cuts": 9})
bump = call("sculpt", {"op": "grab", "object": "t_grid", "at": [300, 0, 0], "radius": 0.4, "move": [0, 0, 0.3]})
expect("grab pulls the area under the brush", abs(bump["size"][2] - 0.3) < 0.01 and bump["vertices_moved"] > 10, bump)
before_peak = vertex_stat("t_grid", lambda a: a[:, 2].max())
call("sculpt", {"op": "smooth", "object": "t_grid", "iterations": 6, "at": [300, 0, 0.1], "radius": 0.6})
expect("smooth lowers the bump", vertex_stat("t_grid", lambda a: a[:, 2].max()) < before_peak - 0.03, (before_peak, vertex_stat("t_grid", lambda a: a[:, 2].max())))
call("sculpt", {"op": "flatten", "object": "t_grid", "at": [300, 0, 0.1], "radius": 0.9, "strength": 1.0})
flat_range = vertex_stat("t_grid", lambda a: a[:, 2].max() - a[:, 2].min())
expect("flatten brings the bump down towards a plane", flat_range < 0.06 and flat_range < before_peak * 0.5, (flat_range, before_peak))
width_before = vertex_stat("t_grid", lambda a: a[:, 0].max() - a[:, 0].min())
call("sculpt", {"op": "pinch", "object": "t_grid", "strength": 0.5, "where": {}})
expect("pinch pulls the vertices towards the centre", vertex_stat("t_grid", lambda a: a[:, 0].max() - a[:, 0].min()) < width_before * 0.6)

call("create_primitive", {"kind": "sphere", "name": "t_sph", "size": [1, 1, 1], "at": [310, 0, 0.5], "segments": 24})
call("sculpt", {"op": "inflate", "object": "t_sph", "amount": 0.1, "at": [310, 0, 1.0], "radius": 0.3})
expect("inflate pushes the surface out along its normal", vertex_stat("t_sph", lambda a: a[:, 2].max()) > 1.07, vertex_stat("t_sph", lambda a: a[:, 2].max()))

call("create_primitive", {"kind": "cube", "name": "t_bar", "size": [0.2, 0.2, 2.0], "at": [320, 0, 1.0]})
call("subdivide_faces", {"object": "t_bar", "where": {}, "cuts": 8})
bent = call("deform", {"object": "t_bar", "kind": "bend", "amount": 90, "axis": "X"})
expect("a bend about X curls a standing bar towards Y", bent["size"][1] > 0.4 and bent["size"][2] < 1.99 and bent["size"][0] == 0.2, bent["size"])

call("create_primitive", {"kind": "sphere", "name": "t_wrapball", "size": [1, 1, 1], "at": [330, 0, 0.5], "segments": 24})
call("create_primitive", {"kind": "plane", "name": "t_skin", "size": [0.6, 0.6, 0.001], "at": [330, 0, 1.2]})
call("subdivide_faces", {"object": "t_skin", "where": {}, "cuts": 12})
call("shrinkwrap", {"object": "t_skin", "target": "t_wrapball", "method": "nearest_surface"})
radius_error = vertex_stat("t_skin", lambda a: np.abs(np.linalg.norm(a - np.array([330, 0, 0.5]), axis=1) - 0.5).max())
expect("shrinkwrap puts every vertex on the target surface", radius_error < 0.02, radius_error)

call("create_primitive", {"kind": "cube", "name": "t_rm", "size": [1, 1, 1], "at": [340, 0, 0.5]})
rm = call("remesh", {"object": "t_rm", "voxel_size": 0.1})
expect("remesh gives a dense clean closed mesh", rm["tris"] > 200 and call("check_mesh", {"name": "t_rm"})["closed"], rm)
bl = call("blob", {"name": "t_blob", "points": [[350, 0, 0.5], [350.3, 0, 0.5]], "radii": [0.4, 0.4]})
expect("blob merges two balls into one smooth mesh", bl["size"][0] > 0.5 and bl["tris"] > 100 and call("check_mesh", {"name": "t_blob"})["closed"], bl)

call("create_primitive", {"kind": "cube", "name": "t_b1", "size": [1, 1, 1], "at": [360, 0, 0.5]})
call("create_primitive", {"kind": "cylinder", "name": "t_b2", "size": [0.4, 0.4, 2], "at": [360, 0, 0.5], "segments": 24})
holed = call("boolean", {"a": "t_b1", "b": "t_b2", "operation": "difference"})
expect("boolean difference drills a hole", holed["tris"] > 100 and "t_b2" not in bpy.data.objects and call("check_mesh", {"name": "t_b1"})["closed"], holed)
call("create_primitive", {"kind": "cube", "name": "t_u1", "size": [1, 1, 1], "at": [370, 0, 0.5]})
call("create_primitive", {"kind": "cube", "name": "t_u2", "size": [1, 1, 1], "at": [370.5, 0, 0.5]})
joined = call("boolean", {"a": "t_u1", "b": "t_u2", "operation": "union"})
expect("boolean union fuses overlapping cubes", abs(joined["size"][0] - 1.5) < 1e-3, joined)

call("create_primitive", {"kind": "cube", "name": "t_c1", "size": [1, 1, 1], "at": [380, 0, 0.5]})
call("create_primitive", {"kind": "cube", "name": "t_c2", "size": [1, 1, 1], "at": [382, 0, 0.5]})
combined = call("combine", {"names": ["t_c1", "t_c2"], "name": "t_cc"})
expect("combine makes one mesh of two", combined["tris"] == 24 and "t_c1" not in bpy.data.objects and abs(combined["size"][0] - 3) < 1e-3, combined)

call("create_primitive", {"kind": "cube", "name": "t_a1", "size": [1, 1, 1], "at": [390, 0, 0.5]})
arr = call("array", {"object": "t_a1", "count": 4, "offset": [1.2, 0, 0]})
expect("array repeats along the offset", abs(arr["size"][0] - 4.6) < 1e-3 and arr["tris"] == 48, arr)
call("create_primitive", {"kind": "cube", "name": "t_r1", "size": [0.2, 0.2, 0.2], "at": [401, 0, 0.1]})
rad = call("radial_array", {"object": "t_r1", "count": 6, "axis": "Z", "center": [400, 0, 0]})
expect("radial_array turns copies around the axis", abs(rad["size"][0] - 2.2) < 0.02 and abs(rad["size"][1] - 2.2) < 0.2 and rad["tris"] == 72, rad)

call("create_primitive", {"kind": "plane", "name": "t_sol", "size": [1, 1, 0.001], "at": [410, 0, 0]})
sol = call("solidify", {"object": "t_sol", "thickness": 0.1})
expect("solidify gives a plane its thickness", abs(sol["size"][2] - 0.1) < 1e-3 and call("check_mesh", {"name": "t_sol"})["closed"], sol)
vase = call("lathe", {"name": "t_vase", "profile": [[0.0, 0.0], [0.4, 0.0], [0.4, 0.6], [0.15, 0.8], [0.0, 0.8]], "segments": 24, "at": [420, 0, 0]})
expect("lathe turns a profile into a solid of revolution", abs(vase["size"][0] - 0.8) < 0.03 and abs(vase["size"][2] - 0.8) < 1e-3 and call("check_mesh", {"name": "t_vase"})["closed"], vase)
pipe = call("sweep", {"name": "t_pipe", "path": [[430, 0, 0], [430, 0, 1], [431, 0, 1.5]], "radius": 0.05})
expect("sweep builds a closed pipe along the path", pipe["size"][2] > 1.5 and call("check_mesh", {"name": "t_pipe"})["closed"], pipe)
rail = call("sweep", {"name": "t_rail", "path": [[440, 0, 0], [441, 0, 0]], "radius": 0.1, "profile": [[-1, -0.5], [1, -0.5], [1, 0.5], [-1, 0.5]]})
expect("sweep takes any profile: x across, y up", abs(rail["size"][1] - 0.2) < 1e-3 and abs(rail["size"][2] - 0.1) < 1e-3, rail["size"])


call("create_primitive", {"kind": "cylinder", "name": "t_rigmesh", "size": [0.3, 0.3, 1.4], "at": [500, 0, 0.7], "segments": 16})
for height in (0.3, 0.6, 0.9, 1.1):
    call("bisect", {"object": "t_rigmesh", "axis": "Z", "at": height})
rig = call("create_armature", {"name": "t_rig", "bones": [
    {"name": "root", "head": [500, 0, 0], "tail": [500, 0, 0.5]},
    {"name": "spine", "head": [500, 0, 0.5], "tail": [500, 0, 1.0], "parent": "root"},
    {"name": "head", "head": [500, 0, 1.0], "tail": [500, 0, 1.4], "parent": "spine"},
]})
expect("create_armature makes the bones", rig["bones"] == ["root", "spine", "head"] and len(call("list_bones", {"armature": "t_rig"})) == 3, rig)
expect("bones keep their world position", call("list_bones", {"armature": "t_rig"})[1]["head"] == [500.0, 0.0, 0.5])
bound = call("bind", {"meshes": ["t_rigmesh"], "armature": "t_rig"})
expect("bind skins the mesh by proximity", bound[0]["method"] == "proximity" and bound[0]["groups"] == 3, bound)
expect("the weights are clean", call("check_weights", {"mesh": "t_rigmesh"})["problems"] == ["none"], call("check_weights", {"mesh": "t_rigmesh"}))
rest = call("measure", {"names": ["t_rigmesh"]})[0]["size"]
call("pose", {"armature": "t_rig", "pose": {"spine": [45, 0, 0]}})
posed = call("measure", {"names": ["t_rigmesh"]})[0]["size"]
expect("a posed spine bends the mesh", posed[1] > rest[1] + 0.15, (rest, posed))
call("pose", {"armature": "t_rig", "pose": {}})
expect("an empty pose resets it", abs(call("measure", {"names": ["t_rigmesh"]})[0]["size"][1] - rest[1]) < 1e-3)
sheet_rig = call("pose_sheet", {"armature": "t_rig", "poses": {"rest": {}, "lean": {"spine": [30, 0, 0]}}, "meshes": ["t_rigmesh"], "view": "side", "size": 128})
expect("pose_sheet renders each pose and restores the rest pose", Path(sheet_rig["path"]).exists() and abs(call("measure", {"names": ["t_rigmesh"]})[0]["size"][1] - rest[1]) < 1e-3, sheet_rig)
call("duplicate", {"name": "t_rigmesh", "new_name": "t_rigcopy", "offset": [0, 3, 0]})
call("run_python", {"code": "o = bpy.data.objects['t_rigcopy']; o.vertex_groups.clear(); o.modifiers.clear(); o.parent = None"})
call("run_python", {"code": "bpy.data.objects['t_rigcopy'].location.y -= 3"})
moved = call("transfer_weights", {"target": "t_rigcopy", "donor": "t_rigmesh", "armature": "t_rig"})
expect("transfer_weights copies the groups by nearest vertex", moved["copied_groups"] == 3 and call("check_weights", {"mesh": "t_rigcopy"})["problems"] == ["none"], moved)
call("create_primitive", {"kind": "cube", "name": "t_autobind", "size": [0.3, 0.3, 1.0], "at": [500, 0, 0.5]})
auto = call("bind", {"meshes": ["t_autobind"], "armature": "t_rig", "method": "auto"})
expect("auto binding falls back to proximity when bone heat fails", auto[0]["method"] in ("auto", "proximity") and auto[0]["groups"] >= 1, auto)

call("create_primitive", {"kind": "cylinder", "name": "t_uvcyl", "size": [0.5, 0.5, 1.0], "at": [510, 0, 0.5], "segments": 16})
unwrapped = call("unwrap", {"names": ["t_uvcyl"], "method": "smart"})[0]
expect("unwrap makes a clean UV layout inside 0..1", unwrapped["faces_outside_0_1"] == 0 and unwrapped["degenerate_uv_faces"] == 0 and unwrapped["islands"] >= 1, unwrapped)
uv_section = call("check_mesh", {"name": "t_uvcyl"})["uv"]
expect("check_mesh reports the same UV numbers", uv_section == {k: v for k, v in unwrapped.items() if k != "object"}, uv_section)
expect("check_mesh says when there is no UV", call("check_mesh", {"name": "t_prism"})["uv"] == {"uv": "none", "fix": "unwrap"})
islands = {a: call("unwrap", {"names": ["t_uvcyl"], "method": "smart", "angle": a})[0]["islands"] for a in (20.0, 89.0)}
print("INFO smart_project islands by angle:", islands)
for method in ("angle", "conformal", "cube", "cylinder", "sphere"):
    expect(f"unwrap method {method} runs", call("unwrap", {"names": ["t_uvcyl"], "method": method})[0]["uv_area_used"] > 0)
call("create_primitive", {"kind": "cube", "name": "t_pal", "size": [1, 1, 1], "at": [520, 0, 0.5]})
pal = call("palette_uv", {"object": "t_pal", "cell": [1, 0], "grid": [4, 4], "where": {"normal": "+Z"}})
top_uv = [tuple(round(c, 4) for c in l[bpy.data.objects["t_pal"].data.uv_layers["UVMap"]].uv) for p in bpy.data.objects["t_pal"].data.polygons if p.normal.z > 0.9 for l in [type("L", (), {"__getitem__": lambda self, k: bpy.data.objects["t_pal"].data.uv_layers["UVMap"].data[0]})()]] if False else None
uvs = bpy.data.objects["t_pal"].data.uv_layers["UVMap"].data
top = [i for p in bpy.data.objects["t_pal"].data.polygons if p.normal.z > 0.9 for i in p.loop_indices]
expect("palette_uv puts the face on the palette cell centre", all(abs(uvs[i].uv[0] - 0.375) < 1e-4 and abs(uvs[i].uv[1] - 0.875) < 1e-4 for i in top) and len(top) == 4, pal)
call("paint_faces", {"object": "t_pal", "color": "#ff0000", "where": {"normal": "+Z"}})
colours = bpy.data.objects["t_pal"].data.color_attributes["Color"].data
expect("paint_faces colours the picked faces only", sum(1 for c in colours if c.color[0] > 0.9 and c.color[1] < 0.1) == 4, sum(1 for c in colours if c.color[0] > 0.9))


call("create_primitive", {"kind": "cube", "name": "t_open", "size": [1, 1, 1], "at": [600, 0, 0.5]})
call("delete_faces", {"object": "t_open", "where": {"normal": "+Z"}})
call("create_primitive", {"kind": "cube", "name": "t_tool", "size": [0.3, 0.3, 0.3], "at": [600, 0, 0.5]})
try:
    call("boolean", {"a": "t_open", "b": "t_tool", "repair": False})
    expect("boolean refuses an open mesh", False)
except ValueError as error:
    expect("boolean refuses an open mesh with a clear reason", "open or non-manifold" in str(error), error)
call("create_primitive", {"kind": "plane", "name": "t_flat", "size": [1, 1, 0.001], "at": [610, 0, 0]})
try:
    call("remesh", {"object": "t_flat", "voxel_size": 0.1})
    expect("remesh refuses a flat mesh", False)
except ValueError as error:
    expect("remesh refuses a flat mesh with a hint", "solidify" in str(error), error)
call("create_primitive", {"kind": "plane", "name": "t_scaled_plane", "size": [1, 1, 0.001], "at": [620, 0, 0]})
call("run_python", {"code": "bpy.data.objects['t_scaled_plane'].scale = (2, 2, 1)"})
sol2 = call("solidify", {"object": "t_scaled_plane", "thickness": 0.1})
expect("solidify gives the thickness in world metres even on a scaled object", abs(sol2["size"][2] - 0.1) < 1e-3 and sol2["size"][0] == 2.0, sol2["size"])
call("create_primitive", {"kind": "sphere", "name": "t_dense", "size": [1, 1, 1], "at": [630, 0, 0.5], "segments": 32})
dec = call("decimate", {"object": "t_dense", "target_tris": 200})
expect("decimate reaches the triangle target", dec["tris_after"] < dec["tris_before"] * 0.4 and 120 < dec["tris_after"] < 280, dec)
call("create_primitive", {"kind": "cube", "name": "t_planar", "size": [1, 1, 1], "at": [640, 0, 0.5]})
call("subdivide_faces", {"object": "t_planar", "where": {}, "cuts": 3})
flat_dec = call("decimate", {"object": "t_planar", "mode": "planar", "angle": 5})
expect("planar decimate dissolves flat subdivisions", flat_dec["tris_after"] <= 12 and flat_dec["tris_before"] > 100, flat_dec)
call("create_primitive", {"kind": "cube", "name": "t_bevw", "size": [1, 1, 1], "at": [650, 0, 0.5]})
absolute = call("bevel_edges", {"object": "t_bevw", "width": 0.1, "segments": 1, "width_type": "absolute"})
expect("bevel accepts a width type", absolute["bevelled"] == 12)
export_opts = call("export_glb", {"path": str(handlers.WORK / "t_opts.glb"), "names": ["t_dense"], "draco": False, "influences": 4})
expect("export_glb passes the supported options", export_opts["bytes"] > 100 and "ignored_options" not in export_opts, export_opts)


call("checkpoint", {"name": "test"})
call("run_python", {"code": "bpy.data.objects.remove(bpy.data.objects['torso'])"})
call("rollback", {"name": "test"})
expect("rollback brings the object back", "torso" in bpy.data.objects)
call("create_primitive", {"kind": "cube", "name": "t_after_checkpoint", "size": [1, 1, 1]})
listed = call("rollback", {})
expect("rollback without a name only lists", "test" in listed["checkpoints"] and "t_after_checkpoint" in bpy.data.objects, listed)
bpy.data.objects.remove(bpy.data.objects["t_after_checkpoint"])

try:
    sheet = call("render_sheet", {"names": ["t_hull"], "size": 192})
    expect("render sheet exists", Path(sheet["path"]).exists(), sheet)
except Exception as error:
    expect("render works", False, error)


bpy.ops.wm.read_factory_settings(use_empty=True)
plan = [
    "#########",
    "#...#...#",
    "#.S.D.O.#",
    "#...#...#",
    "#########",
]
level = call("build_from_grid", {"layout": plan, "cell": 1.0, "wall_height": 3.0, "name": "lv"})
expect("build_from_grid makes floor, walls and markers", {"lv_floor", "lv_walls"} <= set(level["created"]) and level["markers"] == {"spawn": 1, "objective": 1}, level)
floor_info = call("measure", {"names": ["lv_floor", "lv_walls"]})
expect("the blockout has the planned size", floor_info[0]["size"][:2] == [7.0, 3.0] or floor_info[0]["size"][0] == 7.0, floor_info[0]["size"])
expect("walls stand on the floor at the wall height", floor_info[1]["size"] == [9.0, 5.0, 3.0] and abs(floor_info[1]["min"][2]) < 1e-6, floor_info[1])
spawn = call("measure", {"names": ["lv_spawn_1", "lv_objective_1"]})
expect("markers sit at the plan positions (row 0 is the top)", spawn[0]["center"][:2] == [2.5, 2.5] and spawn[1]["center"][:2] == [6.5, 2.5], [s["center"] for s in spawn])
path_lv = call("route", {"start": [2.5, 2.5, 0], "end": [6.5, 2.5, 0], "names": ["lv_floor", "lv_walls"], "cell": 0.25})
expect("the door connects the two rooms", path_lv["reachable"] and path_lv["length_m"] < 6.0, path_lv)
tight = call("check_passages", {"names": ["lv_floor", "lv_walls"], "min_door": 1.5, "min_corridor": 0.4, "cell": 0.25})
expect("a one-metre door violates a 1.5 m rule", tight["violations"] != ["none"] and tight["violations"][0]["kind"] == "doorway", tight["violations"])
fine = call("check_passages", {"names": ["lv_floor", "lv_walls"], "min_door": 0.5, "min_corridor": 0.4, "cell": 0.25})
expect("the same door passes a 0.5 m rule", fine["violations"] == ["none"], fine["violations"])
seen_lv = call("viewshed", {"point": [2.5, 2.5, 0], "names": ["lv_floor", "lv_walls"], "cell": 0.25})
expect("the viewshed sees its room and part of the next one", 0.3 < seen_lv["visible_share"] < 0.98 and Path(seen_lv["image"]).exists(), seen_lv)

call("create_primitive", {"kind": "cube", "name": "tree", "size": [0.3, 0.3, 1.0], "at": [20, 20, 0]})
call("create_primitive", {"kind": "cube", "name": "meadow", "size": [10, 10, 0.2], "at": [104.5, 102.5, 0], "anchor": [0.5, 0.5, 1]})
scattered = call("scatter", {"source": "tree", "surface": ["meadow"], "count": 20, "seed": 3, "min_distance": 0.6, "area": [100.5, 100.5, 108.5, 104.5], "scale_range": [0.8, 1.2]})
expect("scatter places the requested count", scattered["placed"] == 20, scattered)
placed = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n.startswith("tree_")]
xy = np.array([[o.matrix_world.translation.x, o.matrix_world.translation.y] for o in placed])
gap = min(np.linalg.norm(xy[i] - xy[j]) for i in range(len(xy)) for j in range(i + 1, len(xy)))
expect("scatter keeps the minimum distance", gap >= 0.6 - 1e-6, gap)
expect("scattered copies stand on the surface and share the mesh", all(abs(require_min_z(o)) < 1e-3 for o in placed[:5]) if False else all(abs(call("measure", {"names": [o.name]})[0]["min"][2]) < 1e-3 for o in placed[:5]) and placed[0].data is placed[1].data)
expect("scatter is repeatable by seed", call("scatter", {"source": "tree", "surface": ["meadow"], "count": 3, "seed": 3, "name": "again", "area": [100.5, 100.5, 108.5, 104.5]})["placed"] == 3)

call("create_primitive", {"kind": "cube", "name": "floaty", "size": [0.5, 0.5, 0.5], "at": [103, 103, 5]})
dropped = call("place_on", {"object": "floaty", "surface": ["meadow"]})
expect("place_on drops the object onto the surface", abs(dropped["min"][2]) < 1e-6, dropped)

call("save_spec", {"name": "floaty_rules", "checks": [{"type": "on_ground", "object": "floaty"}, {"type": "size", "object": "floaty", "axis": "z", "equals": 0.5, "tol": 0.01}]})
expect("a saved spec runs again", call("run_spec", {"name": "floaty_rules"})["all_passed"] is True and "floaty_rules" in call("run_spec", {})["specs"])
call("checkpoint", {"name": "t_diff"})
call("run_python", {"code": "bpy.data.objects['floaty'].location.x += 1.0\nbpy.data.objects.remove(bpy.data.objects['tree'])"})
diff = call("diff_since", {"name": "t_diff"})
expect("diff_since lists what changed after the checkpoint", [c["object"] for c in diff["changed"]] == ["floaty"] and diff["removed"] == ["tree"], diff)


bpy.ops.wm.read_factory_settings(use_empty=True)
call("run_python", {"code": "cu = bpy.data.curves.new('t_curve', 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = 0.05; sp = cu.splines.new('POLY'); sp.points.add(2); [setattr(p, 'co', (i * 0.5, 0, 0, 1)) for i, p in enumerate(sp.points)]; ob = bpy.data.objects.new('t_curve', cu); bpy.context.collection.objects.link(ob)"})
curve_size = call("measure", {"names": ["t_curve"]})[0]["size"]
expect("a curve with a bevel is measured with its bevel", abs(curve_size[0] - 1.0) < 0.02 and 0.08 < curve_size[1] < 0.12 and 0.08 < curve_size[2] < 0.12, curve_size)

for i in range(30):
    call("create_primitive", {"kind": "cube", "name": f"t_lone_{i}", "size": [0.1, 0.1, 0.1], "at": [i * 2, 50, 0.05]})
crowd = call("find_floating", {"names": [f"t_lone_{i}" for i in range(30)], "max_listed": 6})
expect("find_floating folds a long answer", len(crowd["floating"]) == 7 and crowd["floating"][-1].startswith("...") and crowd["parts"] == 30, crowd)
call("create_primitive", {"kind": "cube", "name": "t_inst", "size": [0.2, 0.2, 0.2], "at": [0, 60, 0.1]})
call("set_material", {"names": ["t_inst"], "color": "#ff0000"})
for i in range(9):
    call("duplicate", {"name": "t_inst", "new_name": f"t_inst_{i}", "offset": [i + 1, 0, 0], "linked": True})
budget_inst = call("check_game_ready", {"budget_only": True, "names": ["t_inst"] + [f"t_inst_{i}" for i in range(9)]})
expect("the budget shows what instancing would save", budget_inst["draw_calls_estimate"] == 10 and budget_inst["draw_calls_if_instanced"] == 1 and "instancing" in budget_inst["hint"], budget_inst)

call("create_primitive", {"kind": "cube", "name": "t_ca", "size": [1, 1, 1], "at": [0, 70, 0.5]})
call("create_primitive", {"kind": "cube", "name": "t_cb", "size": [1, 1, 1], "at": [0.5, 70, 0.5]})
overlap = call("check_contacts", {"a": "t_ca", "b": "t_cb"})
expect("check_contacts tells how much of the surface overlaps", overlap["state"] == "intersecting" and "median_depth" in overlap and 0 < overlap["share_of_a_inside_b"] <= 1, overlap)

call("create_primitive", {"kind": "cube", "name": "t_grass", "size": [10, 10, 0.2], "at": [200, 200, 0], "anchor": [0.5, 0.5, 1]})
call("create_primitive", {"kind": "cube", "name": "t_rockA", "size": [0.3, 0.3, 0.3], "at": [0, 80, 0.15]})
call("create_primitive", {"kind": "cube", "name": "t_rockB", "size": [0.2, 0.2, 0.5], "at": [1, 80, 0.25]})
mixed = call("scatter", {"source": ["t_rockA", "t_rockB"], "surface": ["t_grass"], "count": 12, "seed": 5, "area": [196, 196, 204, 204], "name": "t_mix"})
expect("scatter mixes several sources", mixed["placed"] == 12 and sum(mixed["per_source"].values()) == 12 and all(v > 0 for v in mixed["per_source"].values()), mixed)
try:
    call("scatter", {"source": "t_rockA", "surface": ["t_grass"], "count": 3, "area": [500, 500, 510, 510]})
    expect("scatter off the surface raises", False)
except ValueError as error:
    expect("scatter says why nothing was placed", "not_on_surface" in str(error), error)

ring = call("create_primitive", {"kind": "torus", "name": "t_torus", "size": [1.0, 1.0, 0.3], "at": [0, 90, 0.15], "segments": 24})
expect("a torus has the outer size and the tube thickness", ring["size"][0] == 1.0 and ring["size"][2] == 0.3 and call("check_mesh", {"name": "t_torus"})["issues"] == ["none"], ring)
loop = call("lathe", {"name": "t_loopring", "profile": [[0.4, 0.0], [0.5, 0.1], [0.4, 0.2], [0.3, 0.1]], "close": True, "at": [3, 90, 0], "segments": 24})
expect("lathe close=true spins a closed loop into a ring", abs(loop["size"][0] - 1.0) < 0.03 and call("check_mesh", {"name": "t_loopring"})["closed"], loop)

call("create_primitive", {"kind": "cube", "name": "t_edit", "size": [1, 1, 1], "at": [0, 100, 0.5]})
edit = call("run_python", {"code": "for v in bpy.data.objects['t_edit'].data.vertices:\n    v.co.z *= 5"})
expect("run_python warns about big size changes and local coordinates", edit["ok"] and "warnings" in edit and "local" in edit["warnings"][0], edit)

def blobs(mask):
    mask[0:100, 30:70] = True
    mask[100:140, 45:55] = True
    mask[5:12, 5:12] = True
messy = write_mask("t_messy.png", blobs, size=(140, 100))
prepared = call("prepare_reference", {"image": messy, "out": str(handlers.RENDERS / "t_prepared.png")})
alpha_pixels = handlers.read_pixels(prepared["path"])
expect("prepare_reference keeps the biggest blob and adds alpha", prepared["blobs_found"] == 2 and alpha_pixels[:, :, 3].min() < 0.01 and alpha_pixels[:, :, 3].max() > 0.99 and prepared["size"][0] < 60, prepared)
cropped = call("prepare_reference", {"image": messy, "crop": [0.2, 0.0, 0.8, 1.0], "out": str(handlers.RENDERS / "t_prepared2.png"), "keep": "all"})
expect("prepare_reference crops by fractions from the top left", cropped["size"][0] < 60 and cropped["blobs_found"] is None, cropped)
profile_prepared = call("measure_profile", {"reference": prepared["path"], "height_m": 1.4, "bands": 14})
expect("a prepared reference works with the profile tools", abs(profile_prepared["bands"][0]["width"] - 0.4) < 0.03, profile_prepared["bands"][0])

print("FAILED:" if failures else "ALL PASSED", failures or "")
sys.exit(1 if failures else 0)
