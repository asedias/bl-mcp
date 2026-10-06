"""Hard-surface and repeat tools: boolean, combine, arrays, solidify, lathe, sweep."""

import math

import bmesh
import bpy
import mathutils
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

from .core import *  # noqa: F401,F403
from .core import handler
from .meshops import absorb_zero_faces, clean_limits, cleaned, cleaning_note, edge_faults, fault_report, summary


def merged_mesh(objs, name):
    """One mesh in world space from several mesh objects (materials are kept)."""
    bm = bmesh.new()
    materials = []
    for obj in objs:
        with evaluated_mesh(obj) as (ev, mesh):
            part = bmesh.new()
            part.from_mesh(mesh)
            bmesh.ops.transform(part, matrix=ev.matrix_world, verts=part.verts)
            if ev.matrix_world.determinant() < 0:
                bmesh.ops.reverse_faces(part, faces=part.faces)
            slots = [s.material for s in obj.material_slots]
            for face in part.faces:
                material = slots[face.material_index] if face.material_index < len(slots) else None
                if material not in materials:
                    materials.append(material)
                face.material_index = materials.index(material)
            temp = bpy.data.meshes.new("bl_part")
            part.to_mesh(temp)
            part.free()
        bm.from_mesh(temp)
        bpy.data.meshes.remove(temp)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for material in materials:
        mesh.materials.append(material)
    return mesh


@handler
def combine(names, name=None, delete_sources=True):
    objs = [get_object(n) for n in names]
    if any(o.type != "MESH" for o in objs):
        raise ValueError("Only meshes can be combined")
    result_name = name or names[0]
    mesh = merged_mesh(objs, result_name + "_merged")
    if delete_sources:
        for obj in objs:
            data = obj.data
            bpy.data.objects.remove(obj)
            if data.users == 0:
                bpy.data.meshes.remove(data)
    result = new_mesh_object(result_name, mesh)
    return summary(result, combined=len(objs))


def open_edges(obj):
    count, _ = open_edge_report(obj)
    return count


def open_edge_report(obj):
    """Count of edges without exactly two faces, and their world box [min, max] (None when there are none)."""
    bm = bmesh.new()
    with evaluated_mesh(obj) as (ev, mesh):
        bm.from_mesh(mesh)
        matrix = ev.matrix_world.copy()
    bad = [e for e in bm.edges if len(e.link_faces) != 2]
    box = None
    if bad:
        points = np.array([matrix @ v.co for e in bad for v in e.verts])
        box = [rvec(points.min(axis=0)), rvec(points.max(axis=0))]
    bm.free()
    return len(bad), box


def mesh_health(bm, tolerance, tiny_area):
    tree = KDTree(len(bm.verts))
    for v in bm.verts:
        tree.insert(v.co, v.index)
    tree.balance()
    return {
        "open_edges": sum(1 for e in bm.edges if len(e.link_faces) == 1),
        "non_manifold_edges": sum(1 for e in bm.edges if len(e.link_faces) > 2),
        "doubles": sum(1 for v in bm.verts if len(tree.find_range(v.co, tolerance)) > 1),
        "zero_faces": sum(1 for f in bm.faces if f.calc_area() < tiny_area),
        "junk_vertices": sum(1 for v in bm.verts if not v.link_faces),
    }


def drop_empty_slots(mesh):
    """Remove material slots without a material; their faces move to the first slot that is left."""
    keep = [i for i, material in enumerate(mesh.materials) if material is not None]
    removed = len(mesh.materials) - len(keep)
    if not removed:
        return 0
    indices = np.zeros(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", indices)
    remap = np.zeros(max(len(mesh.materials), int(indices.max(initial=0)) + 1), dtype=np.int32)
    remap[keep] = np.arange(len(keep))
    materials = [mesh.materials[i] for i in keep]
    mesh.materials.clear()
    for material in materials:
        mesh.materials.append(material)
    mesh.polygons.foreach_set("material_index", remap[indices])
    return removed


@handler
def repair_mesh(object, weld=None, fill_holes=True, hole_sides=8, remove_loose=True, dissolve_degenerate=True, recalc_normals=True, remove_empty_slots=True):
    obj = get_object(object)
    if obj.type != "MESH":
        raise ValueError(f"{object} is {obj.type}, not MESH")
    factor = size_factor([obj])
    distance = 1e-4 * factor if weld is None else weld
    scale = max(sum(abs(s) for s in obj.scale) / 3, 1e-9)
    local_distance = distance / scale
    tiny_area = 1e-9 * factor**2 / scale**2
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before = mesh_health(bm, local_distance, tiny_area)
    removed = {"doubled_vertices": 0, "zero_area_faces": 0, "loose_edges": 0, "loose_vertices": 0}
    if distance > 0:
        count = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=local_distance)
        removed["doubled_vertices"] = count - len(bm.verts)
    if dissolve_degenerate:
        bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=max(local_distance, 1e-9))
        absorb_zero_faces(bm, tiny_area)
        flat = [f for f in bm.faces if f.calc_area() < tiny_area]
        if flat:
            bmesh.ops.delete(bm, geom=flat, context="FACES")
    if remove_loose:
        wire = [e for e in bm.edges if not e.link_faces]
        bmesh.ops.delete(bm, geom=wire, context="EDGES")
        single = [v for v in bm.verts if not v.link_edges]
        bmesh.ops.delete(bm, geom=single, context="VERTS")
        removed.update(loose_edges=len(wire), loose_vertices=len(single))
    if fill_holes:
        boundary = [e for e in bm.edges if len(e.link_faces) == 1]
        if boundary:
            bmesh.ops.holes_fill(bm, edges=boundary, sides=hole_sides)
    if recalc_normals and bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.verts.ensure_lookup_table()
    after = mesh_health(bm, local_distance, tiny_area)
    if dissolve_degenerate:
        removed["zero_area_faces"] = max(before["zero_faces"] - after["zero_faces"], 0)
    bm.to_mesh(obj.data)
    obj.data.update()
    bm.free()
    removed["empty_material_slots"] = drop_empty_slots(obj.data) if remove_empty_slots else 0
    bpy.context.view_layer.update()
    return {"object": obj.name, "weld_distance": rnd(distance, 6), "removed": removed, "before": before, "after": after, **summary(obj)}


@handler
def transform_objects(names, move=None, rotate_deg=None, scale=None, pivot=None):
    objs = [get_object(n) for n in names]
    if not objs:
        raise ValueError("Give at least one object name")
    for label, value in (("move", move), ("rotate_deg", rotate_deg), ("pivot", pivot)):
        if value is not None and len(value) != 3:
            raise ValueError(f"{label} is [x, y, z]")
    if isinstance(scale, (list, tuple)) and len(scale) != 3:
        raise ValueError("scale is a number or [x, y, z]")
    transform_world(objs, move=move, rotate_deg=rotate_deg, scale=scale, pivot=pivot)
    return [describe(o) for o in objs]


def keep_children_in_place(obj, change):
    worlds = [(child, child.matrix_world.copy()) for child in obj.children]
    change()
    bpy.context.view_layer.update()
    for child, world in worlds:
        child.matrix_world = world
    bpy.context.view_layer.update()


def move_origin(obj, point):
    """Put the origin at a world point; the geometry and the children stay where they are in the world."""
    shift = obj.matrix_world.inverted_safe() @ Vector(point)
    data = obj.data
    if data is not None and not hasattr(data, "transform"):
        raise ValueError(f"{obj.name} is {obj.type}: its origin cannot be moved without moving the object")
    if data is not None and data.users > 1:
        data = obj.data = data.copy()

    def change():
        if obj.type == "MESH":
            data.transform(Matrix.Translation(-shift), shape_keys=True)
        elif data is not None:
            data.transform(Matrix.Translation(-shift))
        obj.matrix_world = obj.matrix_world @ Matrix.Translation(shift)

    keep_children_in_place(obj, change)


@handler
def set_origin(names, at=None, anchor=None):
    objs = [get_object(n) for n in names]
    if not objs:
        raise ValueError("Give at least one object name")
    if (at is None) == (anchor is None):
        raise ValueError("Give either at [x, y, z] (a world point) or anchor [fx, fy, fz] (fractions of the world box of each object)")
    if len(at if at is not None else anchor) != 3:
        raise ValueError("at and anchor are [x, y, z]")
    for obj in objs:
        move_origin(obj, at if at is not None else anchor_point(require_bounds([obj]), anchor))
    return [describe(o) for o in objs]


SOLVERS = ("EXACT", "MANIFOLD", "FLOAT")
TOOL_MARK = "bl_tool_face"
JITTER = Vector((0.577, 0.471, 0.667))


def marked_tool(tool):
    """A temporary copy of the tool with baked modifiers and a mark on every face, to find the faces it makes in the result."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(tool.evaluated_get(depsgraph))
    mesh.attributes.new(TOOL_MARK, "INT", "FACE").data.foreach_set("value", [1] * len(mesh.polygons))
    copy = bpy.data.objects.new("bl_tool", mesh)
    bpy.context.collection.objects.link(copy)
    copy.matrix_world = tool.matrix_world
    bpy.context.view_layer.update()
    return copy


def remove_with_data(obj):
    data = obj.data
    bpy.data.objects.remove(obj)
    if data.users == 0:
        bpy.data.meshes.remove(data)


def evaluated_bmesh(obj):
    bm = bmesh.new()
    with evaluated_mesh(obj) as (_, mesh):
        bm.from_mesh(mesh)
    return bm


def boolean_trial(target, cutter, operation, solver):
    """The boolean result as a bmesh in the target's space; the target is not changed."""
    modifier = target.modifiers.new("bl_bool", "BOOLEAN")
    modifier.object = cutter
    modifier.operation = operation
    modifier.solver = solver
    try:
        return evaluated_bmesh(target)
    finally:
        target.modifiers.remove(modifier)


def paint_tool_faces(bm, mark, slot_count):
    """Faces made by the tool take the material index of the closest target face, walking over shared edges."""
    for face in bm.faces:
        if face.material_index >= slot_count:
            face.material_index = 0
    pending = {f for f in bm.faces if f[mark]}
    while pending:
        ring = {}
        for face in pending:
            near = [n.material_index for e in face.edges for n in e.link_faces if n not in pending]
            if near:
                ring[face] = max(set(near), key=near.count)
        if not ring:
            for face in pending:
                face.material_index = 0
            return
        for face, index in ring.items():
            face.material_index = index
        pending -= ring.keys()


def boolean_attempts(target, cutter, operation, solver, closed):
    """Yields (bmesh, answer fields, cleaning counts) for the asked solver, then the other solvers, then the same with a shifted tool."""
    known = [i.identifier for i in bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items]
    # MANIFOLD gives the target back unchanged when an input is open, and that looks like a clean result.
    order = [s for s in dict.fromkeys((solver, *SOLVERS)) if s in known and (closed or s != "MANIFOLD")]
    limits = clean_limits(target)
    home = cutter.matrix_world.copy()
    for shift in (0.0, 0.5e-5 * size_factor([target])):
        cutter.matrix_world = Matrix.Translation(JITTER * shift) @ home
        bpy.context.view_layer.update()
        for name in order:
            bm, counts = cleaned(boolean_trial(target, cutter, operation, name), *limits)
            yield bm, {"solver": name, **({"tool_shift_m": rnd(shift, 8)} if shift else {})}, counts


def boolean_merge(target, tool, operation, solver="EXACT", allow_open=False, repair=True):
    """Checked and cleaned boolean on `target` (the tool is kept); returns the fields for the answer."""
    if target.type != "MESH" or tool.type != "MESH":
        raise ValueError("Boolean needs two meshes")
    if solver not in SOLVERS:
        raise ValueError(f"solver is one of {list(SOLVERS)}")
    repaired = []
    closed = True
    for obj in (target, tool):
        issue, box = open_edge_report(obj)
        if issue and repair and not allow_open:
            repair_mesh(obj.name)
            repaired.append(obj.name)
            issue, box = open_edge_report(obj)
        if issue and not allow_open:
            tried = " Automatic repair was tried and did not close it." if repair else ""
            raise ValueError(
                f"{obj.name} has {issue} open or non-manifold edges inside the world box {box[0]}..{box[1]}: "
                f"Boolean is only reliable on closed meshes.{tried} Run repair_mesh with hole_sides=0 (fills holes of any size), "
                "close the hole by hand (bisect with fill, extrude), remove edges shared by three faces, or pass allow_open=true."
            )
        closed = closed and not issue
    start = evaluated_bmesh(target)
    faults = edge_faults(start)
    start.free()
    had_uv = bool(target.data.uv_layers)
    cutter = marked_tool(tool)
    best, tried, volume = None, [], None
    try:
        for bm, label, counts in boolean_attempts(target, cutter, operation, solver, closed):
            tried.append(label["solver"] + (" with a shifted tool" if "tool_shift_m" in label else ""))
            volume = bm.calc_volume() if volume is None else volume
            # FLOAT can return a closed mesh of the wrong shape.
            if abs(bm.calc_volume() - volume) > 1e-3 * abs(volume):
                bm.free()
                continue
            after = edge_faults(bm)
            excess = max(after[0] - faults[0], 0) + max(after[1] - faults[1], 0)
            score = (excess, counts["zero_faces_left"] + counts["doubled_vertices_left"])
            if best is None or score < best[0]:
                if best:
                    best[1].free()
                best = (score, bm, label, counts)
            else:
                bm.free()
            if best[0] == (0, 0):
                break
    finally:
        remove_with_data(cutter)
    (excess, _), bm, label, counts = best
    if not bm.faces:
        bm.free()
        raise ValueError("The result is empty: the objects do not overlap the way the operation needs")
    extra = {**label, **cleaning_note(counts)}
    if counts["doubled_vertices_left"]:
        extra["note"] = "Doubled vertices are left where parts touch along an edge or at a point: a weld there makes edges with more than 2 faces."
    if repaired:
        extra["repaired"] = repaired
    if excess:
        report = fault_report(bm, target.matrix_world, faults)
        text = (
            f"boolean {operation.lower()} leaves {report['new_boundary_edges']} new boundary edges and {report['new_non_manifold_edges']} new edges with more than "
            f"2 faces on {target.name} inside the world box {report['box'][0]}..{report['box'][1]}. Tried: {', '.join(tried)}."
        )
        if not allow_open:
            bm.free()
            raise ValueError(
                f"{text} Nothing was changed. Faces or edges of {tool.name} lie on faces or edges of {target.name} there: move or resize "
                f"{tool.name} so that it crosses the surface with a clear margin, or pass allow_open=true to keep this result."
            )
        extra.update(warning=text, **report)
    mark = bm.faces.layers.int.get(TOOL_MARK)
    if mark is not None:
        if target.material_slots:
            paint_tool_faces(bm, mark, len(target.material_slots))
        bm.faces.layers.int.remove(mark)
    target.modifiers.clear()
    if target.data.users > 1:
        target.data = target.data.copy()
    bm.to_mesh(target.data)
    # A tool with a UV map leaves the target an all-zero UV layer; unwrap tools would then take it for a real one.
    if not had_uv:
        for layer in list(target.data.uv_layers):
            target.data.uv_layers.remove(layer)
    target.data.update()
    bm.free()
    empty = drop_empty_slots(target.data)
    if empty:
        extra["removed_empty_slots"] = empty
    bpy.context.view_layer.update()
    return extra


@handler
def boolean(a, b, operation="difference", keep_tool=False, solver="EXACT", allow_open=False, repair=True):
    ops = {"union": "UNION", "difference": "DIFFERENCE", "intersect": "INTERSECT"}
    if operation not in ops:
        raise ValueError(f"operation is one of {sorted(ops)}")
    target, tool = get_object(a), get_object(b)
    extra = boolean_merge(target, tool, ops[operation], solver, allow_open, repair)
    if not keep_tool:
        remove_with_data(tool)
        bpy.context.view_layer.update()
    return summary(target, operation=operation, **extra)


def copies_merged(source, transforms, name, delete_source):
    parts = []
    for matrix in transforms:
        copy = source.copy()
        copy.data = source.data.copy()
        bpy.context.collection.objects.link(copy)
        copy.matrix_world = matrix @ source.matrix_world
        parts.append(copy)
    bpy.context.view_layer.update()
    mesh = merged_mesh(parts, name + "_merged")
    for part in parts:
        data = part.data
        bpy.data.objects.remove(part)
        bpy.data.meshes.remove(data)
    if delete_source:
        data = source.data
        bpy.data.objects.remove(source)
        if data.users == 0:
            bpy.data.meshes.remove(data)
    return new_mesh_object(name, mesh)


@handler
def array(object, count, offset, name=None, keep_source=False):
    source = get_object(object)
    if count < 2:
        raise ValueError("count is at least 2")
    transforms = [Matrix.Translation(Vector(offset) * i) for i in range(count)]
    result = copies_merged(source, transforms, name or object, not keep_source)
    return summary(result, copies=count)


@handler
def radial_array(object, count, axis="Z", center=(0, 0, 0), angle=360.0, name=None, keep_source=False):
    source = get_object(object)
    if count < 2:
        raise ValueError("count is at least 2")
    axis_vec = Vector([1.0 if i == AXES[axis.upper()] else 0.0 for i in range(3)])
    steps = count if abs(angle) >= 360 else count - 1
    transforms = []
    for i in range(count):
        turn = Matrix.Rotation(math.radians(angle) * i / steps, 4, axis_vec)
        transforms.append(Matrix.Translation(center) @ turn @ Matrix.Translation(-Vector(center)))
    result = copies_merged(source, transforms, name or object, not keep_source)
    return summary(result, copies=count)


@handler
def solidify(object, thickness, offset=-1.0, even=True):
    obj = get_object(object)
    if any(abs(v - 1) > 1e-4 for v in obj.scale):
        bake_transform(obj, "scale")
    modifier = obj.modifiers.new("solid", "SOLIDIFY")
    modifier.thickness = thickness
    modifier.offset = offset
    modifier.use_even_offset = even
    bake_modifiers(obj)
    bpy.context.view_layer.update()
    return summary(obj, thickness=thickness)


@handler
def lathe(name, profile, axis="Z", segments=24, angle=360.0, at=(0, 0, 0), cap=False, close=False):
    if close and list(profile[0]) != list(profile[-1]):
        profile = [*profile, profile[0]]
    if len(profile) < 2:
        raise ValueError("A profile needs at least 2 points [radius, height]")
    plane = {"Z": lambda r, h: (r, 0.0, h), "X": lambda r, h: (h, r, 0.0), "Y": lambda r, h: (r, h, 0.0)}[axis.upper()]
    axis_vec = {"Z": (0, 0, 1), "X": (1, 0, 0), "Y": (0, 1, 0)}[axis.upper()]
    bm = bmesh.new()
    verts = [bm.verts.new(plane(r, h)) for r, h in profile]
    edges = [bm.edges.new((a, b)) for a, b in zip(verts, verts[1:])]
    full = abs(angle) >= 360
    bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=axis_vec, dvec=(0, 0, 0), angle=math.radians(angle), steps=segments, use_merge=full, use_duplicate=False)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    if cap and full:
        boundary = [e for e in bm.edges if len(e.link_faces) == 1]
        if boundary:
            bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    result = new_mesh_object(name, mesh)
    move_world(result, Vector(at))
    return describe(result)


def arc_points(arc):
    """World points of an arc in a plane; angles count from the first axis of the plane, counter-clockwise."""
    missing = [k for k in ("center", "radius") if k not in arc]
    if missing:
        raise ValueError(f"arc needs {missing}: {{center, radius, plane ('XZ', 'XY' or 'YZ'), start_deg, end_deg, points}}")
    plane = str(arc.get("plane", "XZ")).upper()
    planes = {"XY": ((1, 0, 0), (0, 1, 0)), "XZ": ((1, 0, 0), (0, 0, 1)), "YZ": ((0, 1, 0), (0, 0, 1))}
    if plane not in planes:
        raise ValueError("arc plane is XY, XZ or YZ")
    u, v = (Vector(a) for a in planes[plane])
    start, end = float(arc.get("start_deg", 0)), float(arc.get("end_deg", 180))
    count = max(3, int(arc.get("points", 24)))
    centre, r = Vector(arc["center"]), float(arc["radius"])
    return [centre + r * (math.cos(math.radians(start + (end - start) * i / (count - 1))) * u + math.sin(math.radians(start + (end - start) * i / (count - 1))) * v) for i in range(count)]


@handler
def sweep(name, path=None, radius=0.05, radii=None, sides=8, profile=None, closed=False, caps=True, up=(0, 0, 1), arc=None):
    if arc is not None:
        path = [list(p) for p in arc_points(arc)]
    if not path or len(path) < 2:
        raise ValueError("Give a path of at least 2 points, or an arc")
    pts = [Vector(p) for p in path]
    sizes = list(radii) if radii else [radius] * len(pts)
    if len(sizes) != len(pts):
        raise ValueError("Give one radius per path point, or one radius for all")
    shape = [tuple(p) for p in profile] if profile else [(math.cos(2 * math.pi * i / sides), math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    tangents = []
    for i in range(len(pts)):
        before = pts[i] - pts[i - 1] if (i > 0 or closed) else pts[1] - pts[0]
        after = pts[(i + 1) % len(pts)] - pts[i] if (i < len(pts) - 1 or closed) else pts[-1] - pts[-2]
        tangents.append((before.normalized() + after.normalized()).normalized() if before.length and after.length else (after or before).normalized())
    normal = Vector(up)
    if abs(normal.dot(tangents[0])) > 0.99:
        normal = Vector((1, 0, 0)) if abs(tangents[0].x) < 0.9 else Vector((0, 1, 0))
    bm = bmesh.new()
    rings = []
    for point, tangent, size in zip(pts, tangents, sizes):
        normal = (normal - tangent * normal.dot(tangent)).normalized()
        binormal = tangent.cross(normal)
        rings.append([bm.verts.new(point + binormal * a * size + normal * b * size) for a, b in shape])
    n = len(shape)
    last = len(rings) if closed else len(rings) - 1
    for i in range(last):
        low, high = rings[i], rings[(i + 1) % len(rings)]
        for k in range(n):
            bm.faces.new((low[k], low[(k + 1) % n], high[(k + 1) % n], high[k]))
    if caps and not closed:
        bm.faces.new(reversed(rings[0]))
        bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return describe(new_mesh_object(name, mesh))


@handler
def decimate(object, ratio=None, target_tris=None, mode="collapse", angle=5.0):
    obj = get_object(object)
    if obj.type != "MESH":
        raise ValueError(f"{object} is {obj.type}, not MESH")

    def tris():
        with evaluated_mesh(obj) as (_, mesh):
            mesh.calc_loop_triangles()
            return len(mesh.loop_triangles)

    before = tris()
    modifier = obj.modifiers.new("decimate", "DECIMATE")
    if mode == "planar":
        modifier.decimate_type = "DISSOLVE"
        modifier.angle_limit = math.radians(angle)
    elif mode == "collapse":
        modifier.decimate_type = "COLLAPSE"
        if target_tris is not None:
            ratio = min(1.0, target_tris / max(before, 1))
        if ratio is None:
            raise ValueError("Give ratio or target_tris")
        modifier.ratio = ratio
    else:
        raise ValueError("mode is collapse or planar")
    bake_modifiers(obj)
    bpy.context.view_layer.update()
    return summary(obj, tris_before=before, tris_after=tris())
