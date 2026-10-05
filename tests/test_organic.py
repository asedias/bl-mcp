"""Organic tools: noise_displace, terrain, rock, path_carve."""

import importlib
import sys
from pathlib import Path

import bmesh
import numpy as np
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402,F401,F403

importlib.import_module("bl_bridge.organic")


def world_points(name):
    obj = bpy.data.objects[name]
    return np.array([(obj.matrix_world @ v.co)[:] for v in obj.data.vertices])


def make_ico(name, radius=1.0, subdivisions=3):
    bpy.ops.mesh.primitive_ico_sphere_add(radius=radius, subdivisions=subdivisions, location=(0, 0, 0))
    obj = bpy.context.object
    obj.name = name
    return obj


def raises(method, params, fragment):
    try:
        call(method, params)
    except ValueError as error:
        return fragment in str(error)
    except Exception as error:  # handlers wrap errors differently
        return fragment in str(error)
    return False


def self_intersections(name):
    obj = bpy.data.objects[name]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    tree = BVHTree.FromBMesh(bm, epsilon=1e-6)
    bad = 0
    for a, b in tree.overlap(tree):
        if a < b and not ({v.index for v in bm.faces[a].verts} & {v.index for v in bm.faces[b].verts}):
            bad += 1
    bm.free()
    return bad


fresh_scene()

# noise_displace
make_ico("blob_a")
make_ico("blob_b")
make_ico("blob_c")
before = world_points("blob_a")
call("noise_displace", {"object": "blob_a", "amount": 0.1, "seed": 3})
call("noise_displace", {"object": "blob_b", "amount": 0.1, "seed": 3})
call("noise_displace", {"object": "blob_c", "amount": 0.1, "seed": 4})
a, b, c = world_points("blob_a"), world_points("blob_b"), world_points("blob_c")
expect("same seed gives the same vertices", np.allclose(a, b))
expect("other seed gives other vertices", not np.allclose(a, c, atol=1e-4))
shift = np.linalg.norm(a - before, axis=1)
expect("amount limits the largest shift", shift.max() <= 0.1 + 1e-6, shift.max())
expect("the displacement is not tiny", shift.max() > 0.04, shift.max())

make_ico("vec_obj")
before = world_points("vec_obj")
call("noise_displace", {"object": "vec_obj", "amount": 0.1, "mode": "vector", "seed": 1})
expect("vector mode stays within amount", np.linalg.norm(world_points("vec_obj") - before, axis=1).max() <= 0.1 + 1e-6)

make_ico("z_obj")
before = world_points("z_obj")
call("noise_displace", {"object": "z_obj", "amount": 0.1, "mode": "z"})
delta = world_points("z_obj") - before
expect("z mode moves only along z", np.abs(delta[:, :2]).max() < 1e-6 and np.abs(delta[:, 2]).max() > 0.02)

make_ico("part_obj")
before = world_points("part_obj")
call("noise_displace", {"object": "part_obj", "amount": 0.1, "where": {"z": [0.5, None]}, "spread": 0.3})
moved = np.linalg.norm(world_points("part_obj") - before, axis=1)
expect("where limits the region", moved[before[:, 2] < 0.0].max() < 1e-9 and moved[before[:, 2] > 0.6].max() > 0.01)
expect("noise_displace rejects a bad mode", raises("noise_displace", {"object": "part_obj", "amount": 0.1, "mode": "x"}, "mode"))

# terrain
call("terrain", {"name": "land", "size": [10, 8], "resolution": 0.5, "height": 2.0, "scale": 4.0, "seed": 5, "at": [3, 4, 1]})
pts = world_points("land")
expect("terrain width and depth", abs(np.ptp(pts[:, 0]) - 10) < 1e-4 and abs(np.ptp(pts[:, 1]) - 8) < 1e-4, (np.ptp(pts[:, 0]), np.ptp(pts[:, 1])))
expect("terrain height inside the range", pts[:, 2].min() >= 1 - 1e-6 and pts[:, 2].max() <= 3 + 1e-6, (pts[:, 2].min(), pts[:, 2].max()))
expect("terrain uses the height", np.ptp(pts[:, 2]) > 1.5, np.ptp(pts[:, 2]))
expect("terrain centred on at", abs(pts[:, 0].mean() - 3) < 1e-6 and abs(pts[:, 1].mean() - 4) < 1e-6)
land = bpy.data.objects["land"]
normals_up = sum(1 for p in land.data.polygons if p.normal.z > 0) == len(land.data.polygons)
expect("terrain normals point up", normals_up)
call("terrain", {"name": "land2", "size": [10, 8], "resolution": 0.5, "scale": 4.0, "seed": 5, "at": [3, 4, 1]})
expect("terrain is repeatable", np.allclose(world_points("land2"), pts))

call("terrain", {"name": "flat", "size": [20, 20], "resolution": 0.5, "height": 3.0, "flat_center": 3.0, "seed": 2})
pf = world_points("flat")
core = pf[np.hypot(pf[:, 0], pf[:, 1]) <= 3.0]
expect("flat_center is level", np.ptp(core[:, 2]) < 1e-6, np.ptp(core[:, 2]))
expect("terrain outside the centre still varies", np.ptp(pf[:, 2]) > 0.5)

call("terrain", {"name": "steps", "size": [20, 20], "resolution": 0.5, "height": 3.0, "plateau_levels": 4, "seed": 2})
levels = np.unique(np.round(world_points("steps")[:, 2], 4))
expect("plateaus give four heights", len(levels) == 4, levels)
expect("plateau heights are even", np.allclose(levels, [0, 1, 2, 3], atol=1e-3), levels)

call("terrain", {"name": "island", "size": [20, 20], "resolution": 0.5, "height": 3.0, "edge_falloff": 0.5, "seed": 2})
pi = world_points("island")
border = (np.abs(pi[:, 0]) > 9.99) | (np.abs(pi[:, 1]) > 9.99)
expect("island borders sit at zero", pi[border][:, 2].max() < 1e-6 and pi[:, 2].max() > 1.0)

call("terrain", {"name": "block", "size": [10, 10], "resolution": 0.5, "height": 2.0, "skirt": -1.0, "at": [0, 0, 0]})
report = call("check_mesh", {"name": "block"})
expect("skirt terrain is a closed solid", report["closed"] and report["issues"] == ["none"], report)
expect("skirt reaches the floor", abs(world_points("block")[:, 2].min() + 1.0) < 1e-6)
expect("skirt must lie under the terrain", raises("terrain", {"name": "bad", "size": [10, 10], "skirt": 5.0}, "skirt"))
expect("terrain vertex limit", raises("terrain", {"name": "huge", "size": [1000, 1000], "resolution": 0.5}, "limit"))

# path_carve
call("terrain", {"name": "field", "size": [20, 20], "resolution": 0.5, "height": 0.001, "scale": 4.0})
call("path_carve", {"terrain": "field", "points": [[-10, 0], [10, 0]], "width": 2.0, "depth": 0.5, "falloff": 1.0})
pc = world_points("field")
on_road = pc[np.abs(pc[:, 1]) <= 1.0]
away = pc[np.abs(pc[:, 1]) >= 2.5]
expect("path_carve lowers the road", on_road[:, 2].max() < -0.49, on_road[:, 2].max())
expect("path_carve leaves the far ground", away[:, 2].min() > -1e-9 and away[:, 2].max() < 0.01)

# rock
call("rock", {"name": "stone", "radius": 0.5, "seed": 7, "roughness": 0.3, "detail": 3, "at": [2, 1, 0.5]})
report = call("check_mesh", {"name": "stone"})
expect("rock is closed and clean", report["closed"] and report["issues"] == ["none"], report)
ps = world_points("stone")
half = max(np.ptp(ps[:, 0]), np.ptp(ps[:, 1])) / 2
expect("rock half width is the radius", abs(half - 0.5) < 0.005, half)
expect("rock sits on at", abs(ps[:, 2].min() - 0.5) < 1e-6 and abs((ps[:, 0].max() + ps[:, 0].min()) / 2 - 2) < 1e-6)
call("rock", {"name": "stone2", "radius": 0.5, "seed": 7, "at": [2, 1, 0.5]})
expect("rock is repeatable", np.allclose(world_points("stone2"), ps))
call("rock", {"name": "stone3", "radius": 0.5, "seed": 8, "at": [2, 1, 0.5]})
expect("other rock seed differs", not np.allclose(world_points("stone3"), ps, atol=1e-4))
call("rock", {"name": "flat_rock", "radius": 0.5, "flatness": 0.6, "seed": 7})
expect("flatness lowers the rock", np.ptp(world_points("flat_rock")[:, 2]) < 0.6 * np.ptp(world_points("stone")[:, 2]))
for detail in (1, 2):
    info = call("rock", {"name": f"low{detail}", "detail": detail, "facets": True})
    clean = call("check_mesh", {"name": f"low{detail}"})
    expect(f"low-poly rock detail {detail} is closed", clean["closed"] and clean["issues"] == ["none"], clean)
    expect(f"low-poly rock detail {detail} is flat shaded", all(not p.use_smooth for p in bpy.data.objects[f"low{detail}"].data.polygons))
print("tris detail 1 and 2:", call("check_mesh", {"name": "low1"})["tris"], call("check_mesh", {"name": "low2"})["tris"])
expect("rock detail is bounded", raises("rock", {"name": "x", "detail": 9}, "detail"))

# pictures
call("render_view", {"target": ["land"], "mode": "clay", "azimuth": 30, "elevation": 35, "name": "organic_terrain"})
call("render_view", {"target": ["stone", "low1", "low2"], "mode": "clay", "name": "organic_rocks"})

finish()
