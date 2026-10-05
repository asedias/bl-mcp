"""Mesh surgery in world terms: pick faces, vertices or edges by a condition, then extrude, inset, bevel, cut, move."""

import math

import bmesh
import bpy
import mathutils
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

from .core import *  # noqa: F401,F403
from .core import handler

DIRECTIONS = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}
WHERE_HELP = "normal ('+Z' or [x,y,z]) with angle (degrees, default 25), x/y/z ranges [min, max] on the world centre, box [[x0,y0,z0],[x1,y1,z1]], area [min, max], index [..]"


def direction_of(value):
    if isinstance(value, str):
        return Vector(DIRECTIONS[value.upper()])
    return Vector(value).normalized()


def in_range(value, rng):
    return (rng[0] is None or value >= rng[0]) and (rng[1] is None or value <= rng[1])


def point_ok(point, where):
    for axis, key in enumerate("xyz"):
        if key in where and not in_range(point[axis], where[key]):
            return False
    if "box" in where:
        lo, hi = where["box"]
        if any(point[i] < lo[i] or point[i] > hi[i] for i in range(3)):
            return False
    return True


def edit_bmesh(obj):
    if obj.type != "MESH":
        raise ValueError(f"{obj.name} is {obj.type}, not MESH")
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    return bm


def commit(bm, obj):
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    bpy.context.view_layer.update()


def pick_faces(bm, obj, where):
    where = where or {}
    matrix = obj.matrix_world
    normal_matrix = matrix.to_3x3().inverted_safe().transposed()
    wanted = direction_of(where["normal"]) if "normal" in where else None
    limit = math.cos(math.radians(where.get("angle", 25.0)))
    picked = []
    for face in bm.faces:
        if "index" in where and face.index not in where["index"]:
            continue
        if not point_ok(matrix @ face.calc_center_median(), where):
            continue
        if wanted is not None and (normal_matrix @ face.normal).normalized().dot(wanted) < limit:
            continue
        if "area" in where and not in_range(face.calc_area() * abs(matrix.determinant()) ** (2 / 3), where["area"]):
            continue
        picked.append(face)
    return picked


def pick_verts(bm, obj, where):
    where = where or {}
    matrix = obj.matrix_world
    return [v for v in bm.verts if ("index" not in where or v.index in where["index"]) and point_ok(matrix @ v.co, where)]


def pick_edges(bm, obj, where, sharp_angle=None):
    where = where or {}
    matrix = obj.matrix_world
    picked = []
    for edge in bm.edges:
        if not point_ok(matrix @ ((edge.verts[0].co + edge.verts[1].co) / 2), where):
            continue
        if sharp_angle is not None:
            if len(edge.link_faces) != 2 or edge.calc_face_angle(0.0) < math.radians(sharp_angle):
                continue
        picked.append(edge)
    return picked


def need(items, what):
    if not items:
        raise ValueError(f"No {what} match the condition. Conditions: {WHERE_HELP}")
    return items


def edge_faults(bm):
    """Counts of boundary edges and of edges with more than two faces."""
    return sum(1 for e in bm.edges if len(e.link_faces) == 1), sum(1 for e in bm.edges if len(e.link_faces) > 2)


def opened(before, after):
    return after[0] > before[0] or after[1] > before[1]


def fault_report(bm, matrix, before=(0, 0)):
    """New boundary and non-manifold edges against the counts before, with the world box of all such edges."""
    bad = [e for e in bm.edges if len(e.link_faces) == 1 or len(e.link_faces) > 2]
    after = edge_faults(bm)
    points = np.array([matrix @ v.co for e in bad for v in e.verts])
    return {
        "new_boundary_edges": max(after[0] - before[0], 0),
        "new_non_manifold_edges": max(after[1] - before[1], 0),
        "box": [rvec(points.min(axis=0)), rvec(points.max(axis=0))],
    }


def clean_limits(obj):
    """Weld distance and zero-area limit in the units of the mesh data, relative to the object size."""
    factor = size_factor([obj])
    scale = max(sum(abs(s) for s in obj.scale) / 3, 1e-9)
    return 1.5e-5 * factor / scale, 1e-9 * factor**2 / scale**2


def zero_faces(bm, tiny_area):
    return [f for f in bm.faces if f.calc_area() < tiny_area]


def doubled_verts(bm, distance):
    tree = KDTree(len(bm.verts))
    for v in bm.verts:
        tree.insert(v.co, v.index)
    tree.balance()
    return sum(1 for v in bm.verts if len(tree.find_range(v.co, distance)) > 1)


def absorb_zero_faces(bm, tiny_area):
    """Merge each zero-area face into the neighbour across its longest edge, so no hole is left."""
    for _ in range(3):
        seams = {max(f.edges, key=lambda e: e.calc_length()) for f in zero_faces(bm, tiny_area)}
        seams = [e for e in seams if len(e.link_faces) == 2]
        if not seams:
            return
        bmesh.ops.dissolve_edges(bm, edges=seams, use_verts=False)


def cleaned(bm, distance, tiny_area):
    """Weld doubled vertices and dissolve zero-area faces. Returns (mesh, counts); a step that would open the mesh is left out."""
    faults = edge_faults(bm)
    flat = len(zero_faces(bm, tiny_area))
    for weld in (True, False):
        trial = bm.copy()
        if weld:
            bmesh.ops.remove_doubles(trial, verts=trial.verts, dist=distance)
        bmesh.ops.dissolve_degenerate(trial, edges=trial.edges, dist=distance)
        absorb_zero_faces(trial, tiny_area)
        if not opened(faults, edge_faults(trial)):
            break
        trial.free()
        trial = None
    if trial is None:
        return bm, {"merged_vertices": 0, "removed_zero_faces": 0, "zero_faces_left": flat, "doubled_vertices_left": doubled_verts(bm, distance)}
    left = len(zero_faces(trial, tiny_area))
    counts = {
        "merged_vertices": len(bm.verts) - len(trial.verts),
        "removed_zero_faces": flat - left,
        "zero_faces_left": left,
        "doubled_vertices_left": 0 if weld else doubled_verts(trial, distance),
    }
    bm.free()
    return trial, counts


def cleaning_note(counts):
    return {k: v for k, v in counts.items() if v}


def summary(obj, **extra):
    info = describe(obj)
    with evaluated_mesh(obj) as (_, mesh):
        mesh.calc_loop_triangles()
        tris = len(mesh.loop_triangles)
    return {"object": obj.name, "size": info["size"], "tris": tris, **extra}


@handler
def mesh_info(object):
    obj = get_object(object)
    bm = edit_bmesh(obj)
    matrix = obj.matrix_world
    normal_matrix = matrix.to_3x3().inverted_safe().transposed()
    groups = {}
    for face in bm.faces:
        n = (normal_matrix @ face.normal).normalized()
        name = max(DIRECTIONS, key=lambda k: n.dot(Vector(DIRECTIONS[k])))
        if n.dot(Vector(DIRECTIONS[name])) < 0.9:
            name = "other"
        entry = groups.setdefault(name, {"faces": 0, "area": 0.0, "lo": Vector((1e9,) * 3), "hi": Vector((-1e9,) * 3)})
        c = matrix @ face.calc_center_median()
        entry["faces"] += 1
        entry["area"] += face.calc_area()
        entry["lo"] = Vector(min(a, b) for a, b in zip(entry["lo"], c))
        entry["hi"] = Vector(max(a, b) for a, b in zip(entry["hi"], c))
    result = {
        "object": obj.name,
        "vertices": len(bm.verts),
        "edges": len(bm.edges),
        "faces": len(bm.faces),
        "face_groups": {k: {"faces": v["faces"], "area": rnd(v["area"], 4), "centres_from": rvec(v["lo"], 3), "centres_to": rvec(v["hi"], 3)} for k, v in groups.items()},
        "conditions": WHERE_HELP,
    }
    bm.free()
    return result


@handler
def select_faces(object, where=None):
    obj = get_object(object)
    bm = edit_bmesh(obj)
    faces = pick_faces(bm, obj, where)
    matrix = obj.matrix_world
    result = {"selected": len(faces), "of": len(bm.faces)}
    if faces:
        pts = [matrix @ f.calc_center_median() for f in faces]
        result.update({
            "area": rnd(sum(f.calc_area() for f in faces), 4),
            "centres_from": rvec([min(p[i] for p in pts) for i in range(3)], 3),
            "centres_to": rvec([max(p[i] for p in pts) for i in range(3)], 3),
            "indices": [f.index for f in faces[:60]],
        })
    bm.free()
    return result


@handler
def extrude_faces(object, where=None, distance=0.0, offset=None, scale=1.0, inset=0.0):
    obj = get_object(object)
    bm = edit_bmesh(obj)
    faces = need(pick_faces(bm, obj, where), "faces")
    matrix = obj.matrix_world
    inverse = matrix.inverted_safe()
    normal_matrix = matrix.to_3x3().inverted_safe().transposed()
    centre = sum((matrix @ f.calc_center_median() for f in faces), Vector()) / len(faces)
    average = sum(((normal_matrix @ f.normal).normalized() for f in faces), Vector()).normalized()
    move = Vector(offset) if offset is not None else average * distance
    if inset:
        result = bmesh.ops.inset_region(bm, faces=faces, thickness=inset, use_even_offset=True)
        faces = [f for f in result["faces"]]
    region = bmesh.ops.extrude_face_region(bm, geom=faces)
    verts = [e for e in region["geom"] if isinstance(e, bmesh.types.BMVert)]
    for v in verts:
        world = matrix @ v.co
        world = centre + (world - centre) * scale + move
        v.co = inverse @ world
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    commit(bm, obj)
    return summary(obj, extruded=len(faces), moved=rvec(move))


@handler
def inset_faces(object, where=None, thickness=None, depth=0.0, individual=False):
    obj = get_object(object)
    if thickness is None:
        thickness = 0.02 * size_factor([obj])
    bm = edit_bmesh(obj)
    faces = need(pick_faces(bm, obj, where), "faces")
    if individual:
        bmesh.ops.inset_individual(bm, faces=faces, thickness=thickness, depth=depth)
    else:
        bmesh.ops.inset_region(bm, faces=faces, thickness=thickness, depth=depth, use_even_offset=True)
    commit(bm, obj)
    return summary(obj, inset=len(faces))


@handler
def delete_faces(object, where=None):
    obj = get_object(object)
    bm = edit_bmesh(obj)
    faces = need(pick_faces(bm, obj, where), "faces")
    count = len(faces)
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    commit(bm, obj)
    return summary(obj, deleted=count)


@handler
def subdivide_faces(object, where=None, cuts=1):
    obj = get_object(object)
    bm = edit_bmesh(obj)
    faces = need(pick_faces(bm, obj, where), "faces")
    edges = list({e for f in faces for e in f.edges})
    bmesh.ops.subdivide_edges(bm, edges=edges, cuts=cuts, use_grid_fill=True)
    commit(bm, obj)
    return summary(obj, subdivided=len(faces))


BEVEL_MEASURES = ("offset", "width", "depth")
CLAMPED_SHARE = 0.9


def edge_frame(edge):
    """Ends of an edge and, for each of its two faces, the direction in the face that points away from the edge."""
    a, b = edge.verts[0].co.copy(), edge.verts[1].co.copy()
    inward = []
    for loop in edge.link_loops:
        along = loop.link_loop_next.vert.co - loop.vert.co
        inward.append(loop.face.normal.cross(along).normalized())
    return a, b, inward


def bevel_widths(bm, sources, metric):
    """Achieved size of each bevel, measured from the new edge loops that run along the old edge on its two faces."""
    starts = np.array([e.verts[0].co for e in bm.edges])
    ends = np.array([e.verts[1].co for e in bm.edges])
    spans = ends - starts
    lengths = np.maximum(np.linalg.norm(spans, axis=1), 1e-12)
    mids = (starts + ends) / 2
    result = []
    for a, b, inward in sources:
        a, axis = np.array(a), np.array(b - a)
        length = float(np.linalg.norm(axis))
        if length < 1e-12 or len(inward) != 2:
            continue
        axis /= length
        t0, t1 = (starts - a) @ axis / length, (ends - a) @ axis / length
        overlap = np.minimum(np.maximum(t0, t1), 1) - np.maximum(np.minimum(t0, t1), 0)
        beside = (np.abs(spans @ axis) / lengths > 0.995) & (overlap > 0.1 * np.minimum(np.abs(t1 - t0), 1))
        across = (mids - a) - np.outer((mids - a) @ axis, axis)
        reach = np.linalg.norm(across, axis=1)
        sides = []
        for direction in inward:
            on_face = beside & ((reach < 1e-9) | (across @ np.array(direction) > 0.995 * reach))
            if on_face.any():
                sides.append(across[np.flatnonzero(on_face)[np.argmin(reach[on_face])]])
        if len(sides) != 2:
            continue
        chord = float(np.linalg.norm(sides[0] - sides[1]))
        if metric == "width":
            result.append(chord)
        elif metric == "depth":
            result.append(float(np.linalg.norm(np.cross(sides[0], sides[1]))) / chord if chord > 1e-12 else 0.0)
        else:
            result.append(float(np.linalg.norm(sides[0]) + np.linalg.norm(sides[1])) / 2)
    return result


@handler
def bevel_edges(object, width=None, segments=2, angle=30.0, where=None, profile=0.5, width_type="offset"):
    types = {"offset": "OFFSET", "width": "WIDTH", "depth": "DEPTH", "percent": "PERCENT", "absolute": "ABSOLUTE"}
    if width_type not in types:
        raise ValueError(f"width_type is one of {sorted(types)}")
    obj = get_object(object)
    if width is None:
        width = 0.02 * size_factor([obj])
    bm = edit_bmesh(obj)
    edges = need(pick_edges(bm, obj, where, sharp_angle=angle), "edges sharper than the angle")
    sources = [edge_frame(e) for e in edges]
    bmesh.ops.bevel(bm, geom=edges, offset=width, offset_type=types[width_type], segments=segments, profile=profile, affect="EDGES", clamp_overlap=True, loop_slide=True)
    metric = width_type if width_type in BEVEL_MEASURES else "offset"
    achieved = bevel_widths(bm, sources, metric)
    bm, counts = cleaned(bm, *clean_limits(obj))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    commit(bm, obj)
    extra = {"width": rnd(width, 6), "width_type": width_type}
    if achieved:
        extra["achieved_width"] = {"min": rnd(min(achieved), 6), "median": rnd(float(np.median(achieved)), 6), "measured_as": metric, "edges_measured": len(achieved)}
    if achieved and width_type in BEVEL_MEASURES:
        clamped = sum(1 for a in achieved if a < CLAMPED_SHARE * width)
        extra["clamped"] = clamped
        if clamped * 2 > len(achieved):
            extra["warning"] = (
                f"{clamped} of {len(achieved)} measured bevels are narrower than asked (median {rnd(float(np.median(achieved)), 6)} m, asked {rnd(width, 6)} m). "
                "Blender limits all bevels of one call to the room next to the tightest edge. Use a smaller width, or bevel the tight edges in a separate call with where."
            )
    return summary(obj, bevelled=len(edges), **extra, **cleaning_note(counts))


@handler
def bisect(object, axis="Z", at=0.0, clear=None, fill=False):
    obj = get_object(object)
    bm = edit_bmesh(obj)
    index = AXES[axis.upper()]
    normal_world = Vector([1.0 if i == index else 0.0 for i in range(3)])
    point_world = Vector([at if i == index else 0.0 for i in range(3)])
    matrix = obj.matrix_world
    point = matrix.inverted_safe() @ point_world
    normal = (matrix.to_3x3().transposed() @ normal_world).normalized()
    before = len(bm.edges)
    result = bmesh.ops.bisect_plane(
        bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces), dist=1e-5 * size_factor([obj]), plane_co=point, plane_no=normal,
        clear_inner=clear == "inner", clear_outer=clear == "outer",
    )
    if fill and clear:
        cut = [e for e in result["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
        bmesh.ops.holes_fill(bm, edges=cut, sides=0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    new_edges = len(bm.edges) - before
    commit(bm, obj)
    return summary(obj, new_edges=new_edges, cut_at=f"{axis.upper()}={at}")


def weld_trial(obj, where, distance):
    """The welded mesh (not written to the object), the merged count and whether the weld opened the mesh."""
    bm = edit_bmesh(obj)
    verts = pick_verts(bm, obj, where) if where else list(bm.verts)
    count, faults = len(bm.verts), edge_faults(bm)
    bmesh.ops.remove_doubles(bm, verts=verts, dist=distance)
    return bm, count - len(bm.verts), faults


def safe_weld_hint(obj, where, distance):
    for step in range(1, 5):
        smaller = distance / 2**step
        bm, merged, faults = weld_trial(obj, where, smaller)
        safe = not opened(faults, edge_faults(bm))
        bm.free()
        if safe and merged:
            return f" distance={smaller:.3g} keeps it closed and merges {merged} vertices."
    return ""


@handler
def weld(object, distance=None, where=None, allow_open=False):
    obj = get_object(object)
    if distance is None:
        distance = 1e-4 * size_factor([obj])
    bm, merged, faults = weld_trial(obj, where, distance)
    extra = {}
    if opened(faults, edge_faults(bm)):
        report = fault_report(bm, obj.matrix_world, faults)
        text = (
            f"weld at {distance:.3g} m opens {obj.name}: {report['new_boundary_edges']} new boundary edges and "
            f"{report['new_non_manifold_edges']} new edges with more than 2 faces inside the world box {report['box'][0]}..{report['box'][1]}. "
            "Faces narrower than the distance collapse."
        )
        if not allow_open:
            bm.free()
            raise ValueError(f"{text} Nothing was changed.{safe_weld_hint(obj, where, distance)} Pass allow_open=true to weld anyway.")
        extra = {"warning": text, **report}
    commit(bm, obj)
    return summary(obj, merged_vertices=merged, distance=rnd(distance, 7), **extra)


FALLOFFS = {
    "smooth": lambda t: 3 * t * t - 2 * t * t * t,
    "sphere": lambda t: math.sqrt(max(2 * t - t * t, 0.0)),
    "root": lambda t: math.sqrt(t),
    "sharp": lambda t: t * t,
    "inverse_square": lambda t: t * (2 - t),
    "linear": lambda t: t,
    "constant": lambda t: 1.0,
}


def region_weights(bm, obj, selected, radius, kind):
    """Weight 1 for the selected vertices, a falloff of the distance to them for the others."""
    weights = {v.index: 1.0 for v in selected}
    if radius <= 0:
        return weights
    if kind not in FALLOFFS:
        raise ValueError(f"falloff is one of {sorted(FALLOFFS)}")
    matrix = obj.matrix_world
    tree = KDTree(len(selected))
    for i, v in enumerate(selected):
        tree.insert(matrix @ v.co, i)
    tree.balance()
    for v in bm.verts:
        if v.index in weights:
            continue
        _, _, dist = tree.find(matrix @ v.co)
        if dist < radius:
            weights[v.index] = FALLOFFS[kind](1 - dist / radius)
    return weights


def world_cloud(bm, obj):
    points = np.array([obj.matrix_world @ v.co for v in bm.verts])
    tree = KDTree(len(points))
    for i, p in enumerate(points):
        tree.insert(p, i)
    tree.balance()
    return points, tree


def mirror_twins(points, tree, index):
    """Per vertex the index of its mirror twin about the box centre on the axis (None without one); also the centre and the tolerance."""
    centre = float(points[:, index].min() + points[:, index].max()) / 2
    tolerance = 1e-3 * cloud_size_factor(points)
    twins = []
    for p in points:
        mirrored = p.copy()
        mirrored[index] = 2 * centre - mirrored[index]
        _, twin, dist = tree.find(mirrored)
        twins.append(twin if dist <= tolerance else None)
    return twins, centre, tolerance


def with_mirrored(bm, obj, selected, axis):
    """The selection plus the mirror twins of its vertices; also the number added and the number without a twin."""
    if not isinstance(axis, str) or axis.upper() not in AXES:
        raise ValueError("symmetric is 'x', 'y', 'z' or null")
    twins, _, _ = mirror_twins(*world_cloud(bm, obj), AXES[axis.upper()])
    chosen = {v.index for v in selected}
    missing = sum(1 for i in chosen if twins[i] is None)
    extended = chosen | {twins[i] for i in chosen if twins[i] is not None}
    return [bm.verts[i] for i in sorted(extended)], len(extended) - len(chosen), missing


def lopsided_selection(bm, obj, selected, skip=None):
    """Warning text when the mesh is mirror-symmetric and the selection lies on both sides of the plane but is not symmetric."""
    chosen = {v.index for v in selected}
    if len(chosen) == len(bm.verts):
        return None
    points, tree = world_cloud(bm, obj)
    for name, index in AXES.items():
        if name == skip:
            continue
        twins, centre, tolerance = mirror_twins(points, tree, index)
        if None in twins:
            continue
        offsets = points[sorted(chosen), index] - centre
        unmatched = sum(1 for i in chosen if twins[i] not in chosen)
        if unmatched and offsets.max() > tolerance and offsets.min() < -tolerance:
            return (
                f"The mesh is mirror-symmetric about {name}={rnd(centre)} but the selection is not: {unmatched} of {len(chosen)} selected "
                f"vertices have no selected twin. The result is not symmetric. Roll back and pass symmetric='{name.lower()}', or check with check_symmetry."
            )
    return None


def region_of(bm, obj, where, mode):
    if mode == "vertices":
        return need(pick_verts(bm, obj, where), "vertices")
    faces = need(pick_faces(bm, obj, where), "faces")
    return list({v for f in faces for v in f.verts})


@handler
def transform_region(object, where=None, move=None, scale=None, rotate_deg=None, pivot=None, falloff=0.0, falloff_type="smooth", mode="faces", symmetric=None):
    obj = get_object(object)
    bm = edit_bmesh(obj)
    selected = region_of(bm, obj, where, mode)
    extra = {}
    if symmetric:
        selected, added, missing = with_mirrored(bm, obj, selected, symmetric)
        extra = {"mirrored_vertices": added, "without_twin": missing}
    warning = lopsided_selection(bm, obj, selected, skip=symmetric and symmetric.upper())
    if warning:
        extra["warning"] = warning
    matrix = obj.matrix_world
    inverse = matrix.inverted_safe()
    centre = Vector(pivot) if pivot is not None else sum((matrix @ v.co for v in selected), Vector()) / len(selected)
    factors = Vector(scale) if isinstance(scale, (list, tuple)) else Vector((scale if scale is not None else 1.0,) * 3)
    rotation = mathutils.Euler([math.radians(a) for a in (rotate_deg or (0, 0, 0))]).to_matrix()
    shift = Vector(move or (0, 0, 0))
    weights = region_weights(bm, obj, selected, falloff, falloff_type)
    for v in bm.verts:
        w = weights.get(v.index)
        if not w:
            continue
        world = matrix @ v.co
        local = world - centre
        moved = centre + rotation @ Vector((local.x * factors.x, local.y * factors.y, local.z * factors.z)) + shift
        v.co = inverse @ world.lerp(moved, w)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    commit(bm, obj)
    return summary(obj, vertices_moved=len(weights), selected_vertices=len(selected), **extra)
