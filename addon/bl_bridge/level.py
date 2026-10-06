"""Level design from numbers: blockout from a text plan, scatter, placement, viewshed, metrics."""

import json
import math
import random

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from .core import *  # noqa: F401,F403
from .core import handler
from .core import (base_colors, build_grid, clearance_map, home_region, node_xy, save_grid_image)
from .meshops import summary

DEFAULT_LEGEND = {
    "#": {"kind": "wall"},
    ".": {"kind": "floor"},
    " ": {"kind": "void"},
    "D": {"kind": "door"},
    "C": {"kind": "cover"},
    "S": {"kind": "marker", "name": "spawn"},
    "O": {"kind": "marker", "name": "objective"},
}


def add_box(bm, lo, hi):
    ret = bmesh.ops.create_cube(bm, size=1.0)
    centre = [(a + b) / 2 for a, b in zip(lo, hi)]
    size = [b - a for a, b in zip(lo, hi)]
    matrix = Matrix.Translation(centre) @ Matrix.Diagonal((*size, 1))
    bmesh.ops.transform(bm, matrix=matrix, verts=ret["verts"])


def rectangles(cells):
    """Greedy cover of a set of (col, row) cells by rectangles: (col0, row0, cols, rows)."""
    left, found = set(cells), []
    for col, row in sorted(cells, key=lambda c: (c[1], c[0])):
        if (col, row) not in left:
            continue
        width = 1
        while (col + width, row) in left:
            width += 1
        height = 1
        while all((col + i, row + height) in left for i in range(width)):
            height += 1
        for i in range(width):
            for j in range(height):
                left.discard((col + i, row + j))
        found.append((col, row, width, height))
    return found


def mesh_from_boxes(name, boxes):
    bm = bmesh.new()
    for lo, hi in boxes:
        add_box(bm, lo, hi)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


@handler
def build_from_grid(layout, cell=1.0, wall_height=3.0, floor_thickness=0.2, origin=(0, 0, 0), legend=None, name="level", door_height=2.2, cover_height=1.1, cover_fill=0.6):
    table = {**DEFAULT_LEGEND, **(legend or {})}
    rows = len(layout)
    cells = {}
    for r, line in enumerate(layout):
        for c, char in enumerate(line):
            spec = table.get(char)
            if spec is None:
                raise ValueError(f"Unknown character {char!r} in row {r}. Known: {sorted(table)}")
            cells[(c, r)] = {**spec, "char": char}
    ox, oy, oz = origin

    def box_xy(c, r, w=1, h=1):
        x0, x1 = ox + c * cell, ox + (c + w) * cell
        y1, y0 = oy + (rows - r) * cell, oy + (rows - r - h) * cell
        return x0, x1, y0, y1

    kinds = {}
    for key, spec in cells.items():
        kinds.setdefault(spec["kind"], set()).add(key)
    floor_cells = kinds.get("floor", set()) | kinds.get("door", set()) | kinds.get("cover", set()) | kinds.get("marker", set())
    walls, floors, covers = [], [], []
    for c, r, w, h in rectangles(floor_cells):
        x0, x1, y0, y1 = box_xy(c, r, w, h)
        floors.append(((x0, y0, oz - floor_thickness), (x1, y1, oz)))
    custom_heights = {}
    for key, spec in cells.items():
        if spec["kind"] == "wall" and spec.get("height"):
            custom_heights.setdefault(spec["height"], set()).add(key)
    plain_walls = {k for k in kinds.get("wall", set()) if not cells[k].get("height")}
    for c, r, w, h in rectangles(plain_walls):
        x0, x1, y0, y1 = box_xy(c, r, w, h)
        walls.append(((x0, y0, oz), (x1, y1, oz + wall_height)))
    for height, group in custom_heights.items():
        for c, r, w, h in rectangles(group):
            x0, x1, y0, y1 = box_xy(c, r, w, h)
            walls.append(((x0, y0, oz), (x1, y1, oz + height)))
    for c, r in kinds.get("door", set()):
        x0, x1, y0, y1 = box_xy(c, r)
        walls.append(((x0, y0, oz + door_height), (x1, y1, oz + wall_height)))
    for c, r in kinds.get("cover", set()):
        x0, x1, y0, y1 = box_xy(c, r)
        inset = cell * (1 - cover_fill) / 2
        height = cells[(c, r)].get("height", cover_height)
        covers.append(((x0 + inset, y0 + inset, oz), (x1 - inset, y1 - inset, oz + height)))
    made = []
    for suffix, boxes in (("floor", floors), ("walls", walls), ("cover", covers)):
        if boxes:
            obj = new_mesh_object(f"{name}_{suffix}", mesh_from_boxes(f"{name}_{suffix}", boxes))
            made.append(obj.name)
    markers = {}
    for (c, r), spec in sorted(cells.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if spec["kind"] == "marker":
            x0, x1, y0, y1 = box_xy(c, r)
            index = markers.get(spec["name"], 0)
            markers[spec["name"]] = index + 1
            empty = bpy.data.objects.new(f"{name}_{spec['name']}_{index + 1}", None)
            empty.empty_display_type = "SINGLE_ARROW"
            empty.location = ((x0 + x1) / 2, (y0 + y1) / 2, oz)
            bpy.context.collection.objects.link(empty)
            made.append(empty.name)
    bpy.context.view_layer.update()
    return {
        "created": made,
        "grid": f"{max(len(l) for l in layout)}x{rows} cells of {cell} m, row 0 is the top (+Y), column 0 is the left (+X to the right)",
        "floor_boxes": len(floors),
        "wall_boxes": len(walls),
        "markers": markers,
        "legend": {k: v["kind"] for k, v in table.items()},
    }


def pick_surface(surface):
    return {o.name for o in with_children(surface)}


@handler
def place_on(object, surface, at=None, yaw_deg=None):
    obj = get_object(object)
    targets = pick_surface(surface)
    cast = make_caster()
    lo, hi = require_bounds(group_of(obj))
    x, y = (at[0], at[1]) if at else ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2)
    top = max(require_bounds([o])[1].z for o in with_children(surface)) + 1
    z = top
    for _ in range(8):
        hit = cast((x, y, z), (0, 0, -1), z - -1e4)
        if hit is None:
            raise ValueError(f"Nothing under ({rnd(x, 2)}, {rnd(y, 2)}) on {surface}")
        if hit[2].name in targets or any(p in targets for p in ancestry(hit[2])):
            break
        z = hit[0].z - 1e-3
    else:
        raise ValueError("The surface is covered by other objects at that point")
    if yaw_deg is not None:
        obj.rotation_euler.z = math.radians(yaw_deg)
        bpy.context.view_layer.update()
        lo, hi = require_bounds(group_of(obj))
    move_world(obj, Vector((x - (lo.x + hi.x) / 2, y - (lo.y + hi.y) / 2, hit[0].z - lo.z)))
    return describe(obj)


@handler
def scatter(source, surface, count, seed=0, area=None, min_distance=0.0, align_to_normal=False, scale_range=(1.0, 1.0), yaw_random=True, max_slope_deg=90.0, linked=True, name=None, weights=None):
    names = [source] if isinstance(source, str) else list(source)
    sources = [get_object(n) for n in names]
    if weights is not None and len(weights) != len(sources):
        raise ValueError("Give one weight per source")
    rng = random.Random(seed)
    targets = pick_surface(surface)
    boxes = [require_bounds([o]) for o in with_children(surface)]
    lo_x = min(b[0].x for b in boxes) if area is None else area[0]
    lo_y = min(b[0].y for b in boxes) if area is None else area[1]
    hi_x = max(b[1].x for b in boxes) if area is None else area[2]
    hi_y = max(b[1].y for b in boxes) if area is None else area[3]
    top = max(b[1].z for b in boxes) + 1
    cast = make_caster()
    cos_slope = math.cos(math.radians(max_slope_deg))
    placed, made, rejected = [], [], {"too_close": 0, "not_on_surface": 0, "too_steep": 0}
    per_source = {n: 0 for n in names}
    for _ in range(count * 30):
        if len(placed) >= count:
            break
        x, y = rng.uniform(lo_x, hi_x), rng.uniform(lo_y, hi_y)
        if min_distance and any((x - px) ** 2 + (y - py) ** 2 < min_distance ** 2 for px, py in placed):
            rejected["too_close"] += 1
            continue
        hit = cast((x, y, top), (0, 0, -1), top + 1e4)
        if hit is None or hit[2].name not in targets:
            rejected["not_on_surface"] += 1
            continue
        if hit[1].z < cos_slope:
            rejected["too_steep"] += 1
            continue
        src = rng.choices(sources, weights=weights)[0] if len(sources) > 1 else sources[0]
        copy = src.copy()
        if src.data is not None and not linked:
            copy.data = src.data.copy()
        copy.name = f"{name or src.name}_{len(placed) + 1:03d}"
        bpy.context.collection.objects.link(copy)
        if align_to_normal:
            copy.rotation_euler = hit[1].to_track_quat("Z", "Y").to_euler()
        if yaw_random:
            copy.rotation_euler.rotate_axis("Z", rng.uniform(0, 2 * math.pi))
        factor = rng.uniform(*scale_range)
        copy.scale = [s * factor for s in src.scale]
        bpy.context.view_layer.update()
        box_lo, box_hi = require_bounds([copy])
        move_world(copy, Vector((x - (box_lo.x + box_hi.x) / 2, y - (box_lo.y + box_hi.y) / 2, hit[0].z - box_lo.z)))
        placed.append((x, y))
        made.append(copy.name)
        per_source[src.name] += 1
    if not placed:
        raise ValueError(f"Nothing could be placed. Rejections: {rejected}. Check the surface, the area and max_slope_deg")
    result = {"placed": len(placed), "requested": count, "rejected_tries": rejected, "per_source": per_source, "first": made[:20], "seed": seed}
    if len(placed) < count:
        result["note"] = "fewer than requested: the area is too small for min_distance, or most tries missed the surface"
    return result


@handler
def viewshed(point, names=None, eye_height=1.6, target_height=1.0, cell=None, max_range=60.0, agent_height=1.8, agent_radius=0.3, max_step=0.35, max_slope_deg=45.0, max_levels=3):
    grid = build_grid(names, cell, agent_height, agent_radius, max_step, max_slope_deg, max_levels)
    cell = grid["cell"]
    home = home_region(grid, point)
    cast = grid["cast"]
    eye = Vector(point) + Vector((0, 0, eye_height))
    visible, hidden, far = [], [], 0.0
    for key in grid["regions"][home]:
        x, y = node_xy(grid, key)
        target = Vector((x, y, grid["nodes"][key] + target_height))
        offset = target - eye
        dist = offset.length
        if dist > max_range:
            hidden.append(key)
            continue
        hit = cast(eye, offset, max(dist - 0.05, 0.01))
        (hidden if hit else visible).append(key)
        if not hit:
            far = max(far, dist)
    colors = base_colors(grid, home)
    colors[:, :, :3] *= 0.4
    for key in hidden:
        colors[key[1], key[0]] = (0.15, 0.25, 0.7, 1)
    for key in visible:
        colors[key[1], key[0]] = (0.3, 0.95, 0.4, 1)
    path, px = save_grid_image(grid, colors, "viewshed.png")
    area = cell * cell
    total = max(len(visible) + len(hidden), 1)
    return {
        "image": str(path),
        "legend": "bright green seen from the point, blue walkable but hidden, dark not reachable. +Y is up.",
        "visible_area_m2": rnd(len(visible) * area, 2),
        "hidden_area_m2": rnd(len(hidden) * area, 2),
        "visible_share": rnd(len(visible) / total, 3),
        "farthest_visible_m": rnd(far, 2),
        "eye": rvec(eye, 2),
    }


def components(mask):
    nx, ny = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    found = []
    for i in range(nx):
        for j in range(ny):
            if not mask[i, j] or seen[i, j]:
                continue
            stack, members = [(i, j)], []
            seen[i, j] = True
            while stack:
                a, b = stack.pop()
                members.append((a, b))
                for da in (-1, 0, 1):
                    for db in (-1, 0, 1):
                        x, y = a + da, b + db
                        if 0 <= x < nx and 0 <= y < ny and mask[x, y] and not seen[x, y]:
                            seen[x, y] = True
                            stack.append((x, y))
            found.append(members)
    return found


@handler
def check_passages(names=None, min_door=1.0, min_corridor=2.0, door_length=1.5, cell=None, agent_height=1.8, agent_radius=0.3, max_step=0.35, max_slope_deg=45.0, max_levels=3, start=None):
    grid = build_grid(names, cell, agent_height, agent_radius, max_step, max_slope_deg, max_levels)
    cell = grid["cell"]
    home = home_region(grid, start)
    dist = clearance_map(grid, home)
    free = dist > 0
    padded = np.pad(dist, 1)
    ridge = free.copy()
    for da in (-1, 0, 1):
        for db in (-1, 0, 1):
            if (da, db) != (0, 0):
                shifted = padded[1 + da : 1 + da + dist.shape[0], 1 + db : 1 + db + dist.shape[1]]
                ridge &= dist >= shifted
    width = (2 * dist - 1) * cell + 2 * agent_radius
    tight = ridge & (width < max(min_corridor, min_door))
    spots = []
    for members in components(tight):
        widths = [width[a, b] for a, b in members]
        lowest = members[int(np.argmin(widths))]
        length = len(members) * cell
        kind = "doorway" if length <= door_length else "corridor"
        limit = min_door if kind == "doorway" else min_corridor
        x, y = grid["lo"].x + (lowest[0] + 0.5) * cell, grid["lo"].y + (lowest[1] + 0.5) * cell
        spots.append({"kind": kind, "min_width_m": rnd(min(widths), 2), "length_m": rnd(length, 2), "at": rvec((x, y), 2), "limit_m": limit, "violation": bool(min(widths) < limit - 1e-6)})
    spots.sort(key=lambda s: s["min_width_m"])
    colors = base_colors(grid, home)
    for a, b in zip(*np.where(tight)):
        colors[b, a] = (1.0, 0.6, 0.1, 1)
    for s in spots:
        if s["violation"]:
            i, j = int((s["at"][0] - grid["lo"].x) / cell), int((s["at"][1] - grid["lo"].y) / cell)
            colors[max(j - 1, 0) : j + 2, max(i - 1, 0) : i + 2] = (1.0, 0.1, 0.1, 1)
    path, _ = save_grid_image(grid, colors, "metrics.png")
    return {
        "image": str(path),
        "legend": "orange = tight route centre line (narrower than min_corridor), red = violation, green = reachable floor. +Y is up.",
        "violations": [s for s in spots if s["violation"]] or ["none"],
        "tight_spots": spots[:12],
        "narrowest_m": rnd(float(width[ridge].min()), 2) if ridge.any() else None,
        "note": f"width is the free width including the agent radius; doorway means a tight run up to {door_length} m long",
    }


@handler
def save_spec(name, checks):
    store = json.loads(bpy.context.scene.get("bl_specs", "{}"))
    store[name] = checks
    bpy.context.scene["bl_specs"] = json.dumps(store)
    return {"saved": name, "checks": len(checks), "stored_in": "the scene (saved with the .blend)"}


@handler
def run_spec(name=None):
    store = json.loads(bpy.context.scene.get("bl_specs", "{}"))
    if name is None:
        return {"specs": {key: len(checks) for key, checks in store.items()}, "note": "Nothing was run. Pass the name of a spec to run it."}
    if name not in store:
        raise ValueError(f"No spec {name!r}. Known: {sorted(store)}")
    return HANDLERS["assert_spec"](store[name])

