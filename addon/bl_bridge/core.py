"""Core of the bridge: registry, shared helpers and the base handlers.

A handler takes keyword params and returns a str or a JSON-able value, or is a generator that yields progress and
returns the value (it then runs as a background job).
"""

import contextlib
import inspect
import io
import json
import math
import os
import struct
import tempfile
import time
import traceback
import uuid
from pathlib import Path

import bmesh
import bpy
import mathutils
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

WORK = Path(os.environ.get("BL_MCP_WORK") or Path(tempfile.gettempdir()) / "bl_mcp")
CHECKPOINTS = WORK / "checkpoints"
RENDERS = WORK / "renders"
BOUNDED = {"MESH", "CURVE", "SURFACE", "FONT", "META"}
AXES = {"X": 0, "Y": 1, "Z": 2}
VIEWS = {
    # name: (camera euler in degrees, world axes shown as (right, up))
    "front": ((90, 0, 0), (0, 2)),
    "back": ((90, 0, 180), (0, 2)),
    "side": ((90, 0, 90), (1, 2)),
    "top": ((0, 0, 0), (0, 1)),
    "iso": (None, None),
}
AXIS_COLORS = [(0.9, 0.2, 0.2), (0.2, 0.8, 0.2), (0.3, 0.4, 0.95)]

HANDLERS = {}
SESSIONS = {}
JOBS = {}
JOB_BUDGET = 0.03


def handler(fn):
    HANDLERS[fn.__name__] = fn
    return fn


class Job:
    counter = 0

    def __init__(self, method, generator):
        Job.counter += 1
        self.id = f"job{Job.counter}"
        self.method, self.generator = method, generator
        self.status, self.progress, self.result, self.error = "running", None, None, None
        self.started = time.time()

    def summary(self):
        data = {"job": self.id, "method": self.method, "status": self.status, "seconds": rnd(time.time() - self.started, 1)}
        if self.progress is not None:
            data["progress"] = self.progress
        if self.status == "done":
            data["result"] = self.result
        if self.status == "failed":
            data["error"] = self.error
        return data


def advance_jobs():
    for job in [j for j in JOBS.values() if j.status == "running"]:
        deadline = time.time() + JOB_BUDGET
        while time.time() < deadline and job.status == "running":
            try:
                job.progress = next(job.generator)
            except StopIteration as stop:
                job.status, job.result = "done", stop.value
            except Exception:
                job.status, job.error = "failed", traceback.format_exc(limit=4)
    return any(j.status == "running" for j in JOBS.values())


def call(method, params):
    if method not in HANDLERS:
        raise ValueError(f"Unknown method {method!r}. Known: {sorted(HANDLERS)}")
    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    result = HANDLERS[method](**params)
    if inspect.isgenerator(result):
        job = Job(method, result)
        JOBS[job.id] = job
        return {"job": job.id, "status": "running"}
    return result


@handler
def job_status(job=None, cancel=False):
    if job is None:
        if cancel:
            raise ValueError(f"Name the job to cancel. Known: {sorted(JOBS)}")
        return [j.summary() for j in JOBS.values()]
    if job not in JOBS:
        raise ValueError(f"No job {job!r}. Known: {sorted(JOBS)}")
    if cancel and JOBS[job].status == "running":
        JOBS[job].generator.close()
        JOBS[job].status = "cancelled"
    return JOBS[job].summary()


def rnd(value, digits=4):
    return round(float(value), digits)


def rvec(values, digits=4):
    return [rnd(v, digits) for v in values]


def get_object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"No object named {name!r}")
    return obj


def scene_objects():
    return [o for o in bpy.context.scene.objects if o.visible_get() and o.type in BOUNDED]


def group_of(obj):
    return [obj, *obj.children_recursive]


def ancestry(obj):
    names = {obj.name}
    while obj.parent:
        obj = obj.parent
        names.add(obj.name)
    return names


def with_children(names):
    seen, result = set(), []
    for name in names:
        for obj in group_of(get_object(name)):
            if obj.name not in seen:
                seen.add(obj.name)
                result.append(obj)
    return result


def depth_of(obj):
    depth = 0
    while obj.parent:
        obj, depth = obj.parent, depth + 1
    return depth


def points_of(obj, depsgraph):
    ev = obj.evaluated_get(depsgraph)
    matrix = np.array(ev.matrix_world)
    if obj.type == "MESH":
        mesh = ev.to_mesh()
        try:
            co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
            mesh.vertices.foreach_get("co", co)
        finally:
            ev.to_mesh_clear()
        co = co.reshape(-1, 3)
    elif obj.type in BOUNDED:
        co = None
        try:
            mesh = ev.to_mesh()
            try:
                if len(mesh.vertices):
                    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
                    mesh.vertices.foreach_get("co", co)
                    co = co.reshape(-1, 3)
            finally:
                ev.to_mesh_clear()
        except RuntimeError:
            pass
        if co is None:
            co = np.array([list(c) for c in ev.bound_box], dtype=np.float64)
    else:
        co = np.zeros((1, 3))
    return co @ matrix[:3, :3].T + matrix[:3, 3]


def bounds_of(objs):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    clouds = [points_of(o, depsgraph) for o in objs]
    if not clouds:
        return None
    cloud = np.vstack(clouds)
    return Vector(cloud.min(axis=0)), Vector(cloud.max(axis=0))


def require_bounds(objs):
    box = bounds_of(objs)
    if box is None:
        raise ValueError("Nothing to measure")
    return box


FULL_SIZE_DIAGONAL = 0.3


def size_factor(objs):
    """1.0 for anything at least 0.3 m across, smaller for small parts: tolerances shrink with the object."""
    box = bounds_of(list(objs))
    if box is None:
        return 1.0
    return min(1.0, max((box[1] - box[0]).length, 1e-6) / FULL_SIZE_DIAGONAL)


def cloud_size_factor(cloud):
    return min(1.0, max(float(np.linalg.norm(cloud.max(axis=0) - cloud.min(axis=0))), 1e-6) / FULL_SIZE_DIAGONAL)


def transform_world(objs, move=None, rotate_deg=None, scale=None, pivot=None):
    """Rotate (world X, Y, Z in turn), scale and move objects about a world pivot; children follow their parent."""
    roots = [o for o in objs if not (ancestry(o) - {o.name}) & {x.name for x in objs}]
    if scale is not None and not isinstance(scale, (list, tuple)):
        scale = (scale, scale, scale)
    if scale is not None and any(abs(v) < 1e-9 for v in scale):
        raise ValueError("scale must not be zero")
    angles = [math.radians(a) for a in (rotate_deg or (0, 0, 0))]
    rotation = (
        mathutils.Matrix.Rotation(angles[2], 4, "Z")
        @ mathutils.Matrix.Rotation(angles[1], 4, "Y")
        @ mathutils.Matrix.Rotation(angles[0], 4, "X")
    )
    stretch = mathutils.Matrix.Diagonal((*(scale or (1, 1, 1)), 1))
    centre = Vector(pivot) if pivot is not None else sum(require_bounds(with_children_of(objs)), Vector()) / 2
    matrix = (
        mathutils.Matrix.Translation(centre + Vector(move or (0, 0, 0)))
        @ rotation
        @ stretch
        @ mathutils.Matrix.Translation(-centre)
    )
    for obj in roots:
        obj.matrix_world = matrix @ obj.matrix_world
        bpy.context.view_layer.update()


def with_children_of(objs):
    seen, result = set(), []
    for obj in objs:
        for member in group_of(obj):
            if member.name not in seen:
                seen.add(member.name)
                result.append(member)
    return result


@contextlib.contextmanager
def evaluated_mesh(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    try:
        yield ev, mesh
    finally:
        ev.to_mesh_clear()


def describe(obj):
    lo, hi = require_bounds([obj])
    size = hi - lo
    origin = obj.matrix_world.translation
    inside = [rnd((origin[i] - lo[i]) / size[i]) if size[i] > 1e-9 else None for i in range(3)]
    notes = []
    if any(abs(s - 1) > 1e-4 for s in obj.scale):
        notes.append("scale not applied")
    if any(s < 0 for s in obj.scale):
        notes.append("negative scale")
    return {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "size": rvec(size),
        "min": rvec(lo),
        "max": rvec(hi),
        "center": rvec((lo + hi) / 2),
        "origin": rvec(origin),
        "origin_in_bbox": inside,
        "rotation_deg": rvec([math.degrees(a) for a in obj.rotation_euler], 2),
        "scale": rvec(obj.scale),
        "notes": notes,
    }


def snapshot():
    bpy.context.view_layer.update()
    state = {}
    for obj in bpy.data.objects:
        box = bounds_of([obj])
        state[obj.name] = (tuple(rvec(box[0], 3)), tuple(rvec(box[1], 3))) if box else None
    return state


def brief(obj):
    box = bounds_of([obj])
    if box is None:
        return obj.name
    lo, hi = box
    return f"{obj.name} [{obj.type}] size {rvec(hi - lo, 3)} min {rvec(lo, 3)} max {rvec(hi, 3)}"


@handler
def status():
    import sys

    package = sys.modules.get(__package__ or "")
    version = ".".join(map(str, package.bl_info["version"])) if package and hasattr(package, "bl_info") else None
    scene = bpy.context.scene
    outside = sorted(o.name for o in bpy.data.objects if o.name not in scene.objects)
    result = {
        "blender": bpy.app.version_string,
        "addon_version": version,
        "binary": bpy.app.binary_path,
        "file": bpy.data.filepath or None,
        "objects": len(scene.objects),
        "scene": scene.name,
        "unit_scale": scene.unit_settings.scale_length,
        "handlers": sorted(HANDLERS),
    }
    if outside:
        result["objects_outside_scene"] = {"count": len(outside), "names": outside[:10], "note": "in the file but not in this scene: scene_tree and the other tools do not see them"}
    return result


@handler
def run_python(code, session=None, reset=False, paths=()):
    import sys

    for path in paths:
        if path not in sys.path:
            sys.path.insert(0, path)
    base = {"bpy": bpy, "bmesh": bmesh, "mathutils": mathutils, "Vector": Vector, "np": np, "math": math}
    if session:
        if reset:
            SESSIONS.pop(session, None)
        namespace = SESSIONS.setdefault(session, {})
        namespace.update(base)
    else:
        namespace = dict(base)
    before = snapshot()
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(code, "<bl>", "exec"), namespace)
    except Exception:
        return {"ok": False, "stdout": out.getvalue(), "error": traceback.format_exc(limit=4)}
    after = snapshot()
    added = [n for n in after if n not in before]
    removed = [n for n in before if n not in after]
    changed = [n for n in after if n in before and after[n] != before[n]]
    result = {
        "ok": True,
        "stdout": out.getvalue(),
        "added": [brief(bpy.data.objects[n]) for n in added],
        "changed": [brief(bpy.data.objects[n]) for n in changed],
        "removed": removed,
    }
    warnings = []
    for n in changed:
        a, b = before[n], after[n]
        if not a or not b:
            continue
        size_a = [hi - lo for lo, hi in zip(*a)]
        size_b = [hi - lo for lo, hi in zip(*b)]
        if any(max(x, y) > 0.05 and (y > 2 * max(x, 1e-6) or y < 0.5 * x) for x, y in zip(size_a, size_b)):
            warnings.append(f"{n}: size changed from {rvec(size_a, 3)} to {rvec(size_b, 3)}. If you edited vertex coordinates: they are local to the object (world = obj.matrix_world @ v.co), and a scaled or rotated object changes them.")
    if warnings:
        result["warnings"] = warnings
    if session:
        result["session_names"] = sorted(k for k in namespace if not k.startswith("__") and k not in base)
    return result


@handler
def scene_tree(limit=200):
    lines = []
    ordered = sorted(bpy.context.scene.objects, key=lambda o: (depth_of(o), o.name))
    for obj in ordered[:limit]:
        depth = depth_of(obj)
        box = bounds_of([obj])
        tris = ""
        if obj.type == "MESH":
            with evaluated_mesh(obj) as (_, mesh):
                mesh.calc_loop_triangles()
                tris = f" tris {len(mesh.loop_triangles)}"
        geometry = f" size {rvec(box[1] - box[0], 3)} min {rvec(box[0], 3)}" if box else ""
        collection = obj.users_collection[0].name if obj.users_collection else "-"
        lines.append(f"{'  ' * depth}{obj.name} [{obj.type}] in {collection}{geometry}{tris}")
    if len(ordered) > limit:
        lines.append(f"... {len(ordered) - limit} more objects (raise `limit`)")
    return "\n".join(lines) or "empty scene"


@handler
def measure(names):
    return [describe(get_object(n)) for n in names]


def anchor_point(box, fractions):
    lo, hi = box
    return Vector(lo[i] + (hi[i] - lo[i]) * fractions[i] for i in range(3))


def move_world(obj, delta):
    matrix = obj.matrix_world.copy()
    matrix.translation += Vector(delta)
    obj.matrix_world = matrix
    bpy.context.view_layer.update()


@handler
def attach(part, to, part_anchor=(0.5, 0.5, 0), to_anchor=(0.5, 0.5, 1), offset=(0, 0, 0), with_children=True):
    moving, target = get_object(part), get_object(to)
    measured = {name: group_of(obj) if with_children else [obj] for name, obj in (("part", moving), ("to", target))}
    delta = anchor_point(require_bounds(measured["to"]), to_anchor) + Vector(offset)
    delta -= anchor_point(require_bounds(measured["part"]), part_anchor)
    move_world(moving, delta)
    result = describe(moving)
    result["moved_by"] = rvec(delta)
    result["boxes_used"] = {name: box_report(objs) for name, objs in measured.items()}
    if any(len(objs) > 1 for objs in measured.values()):
        result["notes"].append("boxes_used include the children: the anchors were taken from them, not from min and max above")
    return result


def box_report(objs):
    lo, hi = require_bounds(objs)
    return {"objects": [o.name for o in objs], "min": rvec(lo), "max": rvec(hi), "size": rvec(hi - lo)}


@handler
def ground(names=None, z=0.0):
    result = []
    for obj in [get_object(n) for n in names] if names else [o for o in scene_objects() if o.parent is None]:
        lo, _ = require_bounds(group_of(obj))
        move_world(obj, (0, 0, z - lo.z))
        result.append(brief(obj))
    return result


@handler
def set_dimensions(name, x=None, y=None, z=None, uniform=False, anchor=(0.5, 0.5, 0.5), apply=True):
    obj = get_object(name)
    wanted = [x, y, z]
    pinned = anchor_point(require_bounds(group_of(obj)), anchor)
    if uniform:
        first = next((i for i, v in enumerate(wanted) if v is not None), None)
        if first is None:
            raise ValueError("Give at least one size")
        factor = wanted[first] / obj.dimensions[first]
        obj.scale = [s * factor for s in obj.scale]
    else:
        dims = obj.dimensions.copy()
        for i, v in enumerate(wanted):
            if v is not None:
                dims[i] = v
        obj.dimensions = dims
    bpy.context.view_layer.update()
    if apply and obj.type == "MESH":
        bake_transform(obj, "scale")
    move_world(obj, pinned - anchor_point(require_bounds(group_of(obj)), anchor))
    return describe(obj)


def bake_transform(obj, mode):
    local = obj.matrix_basis
    loc, rot, scale = local.decompose()
    scale_m = mathutils.Matrix.Diagonal((*scale, 1))
    rot_m = rot.to_matrix().to_4x4()
    if mode == "scale":
        baked, rest = scale_m, ("scale",)
    elif mode == "scale_rotation":
        baked, rest = rot_m @ scale_m, ("scale", "rotation")
    else:
        baked, rest = mathutils.Matrix.Translation(loc) @ rot_m @ scale_m, ("scale", "rotation", "location")
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    children = {child: child.matrix_world.copy() for child in obj.children}
    mesh = obj.data
    mesh.transform(baked)
    if baked.determinant() < 0:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()
    if "scale" in rest:
        obj.scale = (1, 1, 1)
    if "rotation" in rest:
        obj.rotation_mode = "XYZ"
        obj.rotation_euler = (0, 0, 0)
    if "location" in rest:
        obj.location = (0, 0, 0)
    bpy.context.view_layer.update()
    for child, world in children.items():
        child.matrix_world = world
    bpy.context.view_layer.update()


@handler
def apply_transforms(names, mode="scale"):
    if mode not in {"scale", "scale_rotation", "all"}:
        raise ValueError("mode is scale, scale_rotation or all")
    result = []
    for name in names:
        obj = get_object(name)
        if obj.type != "MESH":
            raise ValueError(f"{name} is {obj.type}: only meshes can bake a transform")
        bake_transform(obj, mode)
        result.append(describe(obj))
    return result


WEIGHTED_NORMALS = "bl_weighted_normals"


@handler
def shade(names, mode="smooth", angle=30.0, weighted_normals=False):
    if mode not in {"smooth", "flat", "auto"}:
        raise ValueError("mode is smooth, flat or auto")
    if weighted_normals and mode == "flat":
        raise ValueError("weighted_normals needs mode smooth or auto: flat faces share no normals")
    sharp_limit = math.radians(angle)
    report = []
    for name in names:
        obj = get_object(name)
        if obj.type != "MESH":
            raise ValueError(f"{name} is {obj.type}, not MESH")
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        for face in bm.faces:
            face.smooth = mode != "flat"
        sharp = 0
        for edge in bm.edges:
            if mode == "auto":
                edge.smooth = not (len(edge.link_faces) == 2 and edge.calc_face_angle(0.0) > sharp_limit)
                sharp += not edge.smooth
            elif mode == "smooth":
                edge.smooth = True
        bm.to_mesh(obj.data)
        bm.free()
        previous = obj.modifiers.get(WEIGHTED_NORMALS)
        if previous:
            obj.modifiers.remove(previous)
        if weighted_normals:
            modifier = obj.modifiers.new(WEIGHTED_NORMALS, "WEIGHTED_NORMAL")
            modifier.keep_sharp = True
            modifier.weight = 100
        report.append({"name": name, "mode": mode, "sharp_edges": sharp if mode == "auto" else None, "weighted_normals": weighted_normals})
    return report


@handler
def subdivide(names, levels=1, apply=True):
    report = []
    for name in names:
        obj = get_object(name)
        if obj.type != "MESH":
            raise ValueError(f"{name} is {obj.type}, not MESH")
        modifier = obj.modifiers.new("subsurf", "SUBSURF")
        modifier.levels = modifier.render_levels = levels
        if apply:
            bake_modifiers(obj)
            for polygon in obj.data.polygons:
                polygon.use_smooth = True
        with evaluated_mesh(obj) as (_, mesh):
            mesh.calc_loop_triangles()
            report.append({"name": name, "levels": levels, "applied": apply, "tris": len(mesh.loop_triangles)})
    return report


def count_uv_islands(bm, layer):
    parent = list(range(len(bm.faces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def uv_at(face, vert):
        return next(loop[layer].uv for loop in face.loops if loop.vert == vert)

    for edge in bm.edges:
        if len(edge.link_faces) != 2:
            continue
        a, b = edge.link_faces
        if all((uv_at(a, v) - uv_at(b, v)).length < 1e-5 for v in edge.verts):
            parent[find(a.index)] = find(b.index)
    return len({find(f.index) for f in bm.faces})


def uv_report(obj):
    """Quality of the active UV map of a mesh, or the text 'none' with the fix."""
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        layer = bm.loops.layers.uv.active
        if layer is None:
            return {"uv": "none", "fix": "unwrap"}
        ratios, covered, outside, degenerate = [], 0.0, 0, 0
        for face in bm.faces:
            uvs = [loop[layer].uv.copy() for loop in face.loops]
            area_uv = 0.5 * abs(sum(a.x * b.y - b.x * a.y for a, b in zip(uvs, uvs[1:] + uvs[:1])))
            area_3d = face.calc_area()
            covered += area_uv
            if area_uv < 1e-9:
                degenerate += 1
            elif area_3d > 1e-9:
                ratios.append(area_uv / area_3d)
            if any(not (-1e-4 <= uv.x <= 1 + 1e-4 and -1e-4 <= uv.y <= 1 + 1e-4) for uv in uvs):
                outside += 1
        islands = count_uv_islands(bm, layer)
    finally:
        bm.free()
    ratios = np.array(ratios) if ratios else np.array([0.0])
    return {
        "islands": islands,
        "uv_area_used": rnd(covered, 3),
        "faces_outside_0_1": outside,
        "degenerate_uv_faces": degenerate,
        "texel_density_spread": rnd(float(ratios.max() / max(ratios.min(), 1e-12)), 2),
        "texel_density_note": "ratio of the largest to the smallest UV area per surface area; 1 is even, above 4 is stretched or uneven",
    }


@handler
def check_mesh(name, uv=True):
    obj = get_object(name)
    if obj.type != "MESH":
        raise ValueError(f"{name} is {obj.type}, not MESH")
    issues = []
    factor = size_factor([obj])
    with evaluated_mesh(obj) as (_, mesh):
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
            over = sum(1 for e in bm.edges if len(e.link_faces) > 2)
            wire = sum(1 for e in bm.edges if not e.link_faces)
            loose = sum(1 for v in bm.verts if not v.link_edges)
            degenerate = sum(1 for f in bm.faces if f.calc_area() < 1e-9 * factor**2)
            ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
            tris = sum(len(f.verts) - 2 for f in bm.faces)
            closed = boundary == 0 and over == 0 and wire == 0 and len(bm.faces) > 0
            volume = bm.calc_volume(signed=True) if closed else None
            tree = KDTree(len(bm.verts))
            for v in bm.verts:
                tree.insert(v.co, v.index)
            tree.balance()
            doubles = sum(1 for v in bm.verts if len(tree.find_range(v.co, 1e-5 * factor)) > 1)
        finally:
            bm.free()
    for label, count in [
        ("boundary edges (open holes)", boundary),
        ("edges with more than 2 faces", over),
        ("loose edges", wire),
        ("loose vertices", loose),
        ("zero-area faces", degenerate),
        ("vertices that share a place", doubles),
    ]:
        if count:
            issues.append(f"{count} {label}")
    if volume is not None and volume < 0:
        issues.append("normals point inward")
    if any(abs(s - 1) > 1e-4 for s in obj.scale):
        issues.append("scale not applied")
    return {
        "name": name,
        "tris": tris,
        "ngons": ngons,
        "closed": closed,
        "volume": rnd(volume) if volume is not None else None,
        "materials": len(obj.material_slots),
        "issues": issues or ["none"],
        **({"uv": uv_report(obj)} if uv else {}),
    }


def mirror_mismatch(cloud, index, center, tolerance):
    """Worst distance from a mirrored point to its nearest partner, and the points over the tolerance, worst first."""
    tree = KDTree(len(cloud))
    for i, p in enumerate(cloud):
        tree.insert(p, i)
    tree.balance()
    worst, unmatched = 0.0, []
    for p in cloud:
        mirror = p.copy()
        mirror[index] = 2 * center - mirror[index]
        _, _, dist = tree.find(mirror)
        worst = max(worst, dist)
        if dist > tolerance:
            unmatched.append((dist, p))
    unmatched.sort(key=lambda item: -item[0])
    return worst, unmatched


@handler
def check_symmetry(names, axis="X", at=None, tolerance=None):
    index = AXES[axis.upper()]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    cloud = np.vstack([points_of(get_object(n), depsgraph) for n in names])
    if tolerance is None:
        tolerance = 0.005 * cloud_size_factor(cloud)
    center = float(at) if at is not None else float((cloud[:, index].min() + cloud[:, index].max()) / 2)
    worst, unmatched = mirror_mismatch(cloud, index, center, tolerance)
    return {
        "axis": axis.upper(),
        "mirror_plane": rnd(center),
        "tolerance": rnd(tolerance, 6),
        "vertices": len(cloud),
        "unmatched": len(unmatched),
        "unmatched_share": rnd(len(unmatched) / len(cloud)),
        "worst_error": rnd(worst),
        "worst_points": [rvec(p) for _, p in unmatched[:5]],
    }


def has_inward_normals(mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        closed = len(bm.faces) > 0 and all(len(e.link_faces) == 2 for e in bm.edges)
        return closed and bm.calc_volume(signed=True) < 0
    finally:
        bm.free()


def world_bvh(obj):
    with evaluated_mesh(obj) as (ev, mesh):
        matrix = ev.matrix_world
        verts = [matrix @ v.co for v in mesh.vertices]
        mesh.calc_loop_triangles()
        tris = [tuple(t.vertices) for t in mesh.loop_triangles]
        if has_inward_normals(mesh) != (matrix.determinant() < 0):
            tris = [(a, c, b) for a, b, c in tris]
    centers = [(verts[a] + verts[b] + verts[c]) / 3 for a, b, c in tris]
    return BVHTree.FromPolygons(verts, tris), verts + centers


def penetration_depths(tree, verts):
    depths = []
    for v in verts:
        location, normal, _, dist = tree.find_nearest(v)
        if location is not None and dist > 1e-9 and (v - location).dot(normal) < -0.9 * dist:
            depths.append(dist)
    return depths


def penetration(tree, verts):
    return max(penetration_depths(tree, verts), default=0.0)


def closest_pair(tree_a, verts_a, tree_b, verts_b):
    best = (math.inf, None, None)
    for v in verts_a:
        location, _, _, dist = tree_b.find_nearest(v)
        if location is not None and dist < best[0]:
            best = (dist, v.copy(), location.copy())
    for v in verts_b:
        location, _, _, dist = tree_a.find_nearest(v)
        if location is not None and dist < best[0]:
            best = (dist, location.copy(), v.copy())
    return best


def pair_metrics(a, b):
    tree_a, verts_a = world_bvh(a)
    tree_b, verts_b = world_bvh(b)
    depth = max(penetration(tree_b, verts_a), penetration(tree_a, verts_b))
    gap, point_a, point_b = closest_pair(tree_a, verts_a, tree_b, verts_b)
    return depth, gap, point_a, point_b


def contact_state(depth, gap, eps=1e-4):
    return "intersecting" if depth > eps else ("touching" if gap < eps else "apart")


def pair_eps(a, b):
    return 1e-4 * size_factor([a, b])


@handler
def check_contacts(a, b):
    obj_a, obj_b = get_object(a), get_object(b)
    tree_a, verts_a = world_bvh(obj_a)
    tree_b, verts_b = world_bvh(obj_b)
    in_b = penetration_depths(tree_b, verts_a)
    in_a = penetration_depths(tree_a, verts_b)
    depth = max(in_b + in_a, default=0.0)
    gap, _, _ = closest_pair(tree_a, verts_a, tree_b, verts_b)
    eps = pair_eps(obj_a, obj_b)
    result = {"a": a, "b": b, "state": contact_state(depth, gap, eps), "penetration_depth": rnd(depth), "min_vertex_distance": rnd(gap)}
    if depth > eps:
        result["median_depth"] = rnd(float(np.median(in_b + in_a)))
        result["share_of_a_inside_b"] = rnd(len(in_b) / max(len(verts_a), 1), 3)
        result["share_of_b_inside_a"] = rnd(len(in_a) / max(len(verts_b), 1), 3)
        result["note"] = "penetration_depth is the deepest sample; median_depth and the shares tell how much of the surface overlaps"
    return result


def box_gap(box_a, box_b):
    return math.sqrt(sum(max(0.0, box_a[0][i] - box_b[1][i], box_b[0][i] - box_a[1][i]) ** 2 for i in range(3)))


NEAR_SHARE, NEAR_MAX = 0.02, 0.03


def near_gap(box_a, box_b):
    """Largest gap that still reads as a seam between two parts: a share of the size of the pair."""
    diagonal = math.sqrt(sum((max(box_a[1][i], box_b[1][i]) - min(box_a[0][i], box_b[0][i])) ** 2 for i in range(3)))
    return min(NEAR_MAX, NEAR_SHARE * diagonal)


@handler
def find_floating(names=None, touch=None, near=None, search=None, ground_z=None, max_listed=12):
    parts = [o for o in ([get_object(n) for n in names] if names else scene_objects()) if o.type == "MESH" and len(o.data.polygons)]
    boxes = {o.name: require_bounds([o]) for o in parts}
    if search is None:
        search = 1.0 * size_factor(parts) if parts else 1.0
    links, tiny, gaps = {o.name: set() for o in parts}, [], {}
    for i, a in enumerate(parts):
        for b in parts[i + 1 :]:
            if box_gap(boxes[a.name], boxes[b.name]) > search:
                continue
            depth, gap, _, _ = pair_metrics(a, b)
            gaps[(a.name, b.name)] = gap
            factor = size_factor([a, b])
            if depth > 1e-4 * factor or gap <= (touch if touch is not None else 0.001 * factor):
                links[a.name].add(b.name)
                links[b.name].add(a.name)
            elif gap <= (limit := near if near is not None else near_gap(boxes[a.name], boxes[b.name])):
                tiny.append({"a": a.name, "b": b.name, "gap": rnd(gap, 5), "near": rnd(limit, 5)})
    ground_tolerance = touch if touch is not None else 0.001 * size_factor(parts) if parts else 0.001
    grounded = {n for n, box in boxes.items() if ground_z is not None and box[0].z <= ground_z + ground_tolerance}
    groups, seen = [], set()
    for name in links:
        if name in seen:
            continue
        stack, group = [name], []
        seen.add(name)
        while stack:
            cur = stack.pop()
            group.append(cur)
            for other in links[cur] - seen:
                seen.add(other)
                stack.append(other)
        groups.append(sorted(group))
    anchored = [g for g in groups if grounded & set(g)] if grounded else []
    main = anchored or [max(groups, key=len)] if groups else []
    main_names = {n for g in main for n in g}
    floating = []
    for group in groups:
        if set(group) & main_names:
            continue
        nearest = min(
            ((gap, pair) for pair, gap in gaps.items() if (pair[0] in group) != (pair[1] in group)),
            default=None,
        )
        entry = {"parts": group}
        if nearest:
            entry["nearest"] = [n for n in nearest[1] if n not in group][0]
            entry["gap"] = rnd(nearest[0], 5)
            entry["nearest_part_of_group"] = [n for n in nearest[1] if n in group][0]
        floating.append(entry)

    def short(items, limit):
        return items if len(items) <= limit else [*items[:limit], f"... {len(items) - limit} more"]

    floating.sort(key=lambda e: -len(e["parts"]))
    tiny.sort(key=lambda t: t["gap"])
    for entry in floating:
        entry["parts"] = short(entry["parts"], 8)
    result = {
        "parts": len(parts),
        "connected_groups": len(groups),
        "main_group": short(sorted(main_names), max_listed),
        "main_group_size": len(main_names),
        "floating": short(floating, max_listed) or ["none"],
        "tiny_gaps": short(tiny, max_listed) or ["none"],
        "note": (
            f"connected means overlapping or gap <= {f'{touch} m' if touch is not None else '0.001 m (less for a pair under 0.3 m)'}; "
            f"tiny_gaps are wider gaps up to {f'{near} m' if near is not None else f'{NEAR_SHARE:.0%} of the size of the pair, at most {NEAR_MAX} m'}"
        ),
    }
    if floating:
        result["floating_groups"] = len(floating)
    if tiny:
        result["tiny_gap_count"] = len(tiny)
    return result


def axis_vector(axis):
    sign = -1 if axis.startswith("-") else 1
    return Vector([sign if i == AXES[axis.lstrip("+-").upper()] else 0 for i in range(3)])


def travel_along(direction, tree_a, verts_a, tree_b, verts_b):
    best = math.inf
    for v in verts_a:
        hit = tree_b.ray_cast(v, direction)
        if hit[0] is not None:
            best = min(best, hit[3])
    for v in verts_b:
        hit = tree_a.ray_cast(v, -direction)
        if hit[0] is not None:
            best = min(best, hit[3])
    return best


@handler
def move_to_contact(a, to, axis=None, depth=0.0):
    moving, target = get_object(a), get_object(to)
    depth_now, gap, point_a, point_b = pair_metrics(moving, target)
    eps = pair_eps(moving, target)
    if depth_now > eps:
        return {"moved": [0, 0, 0], "state": "intersecting", "penetration_depth": rnd(depth_now), "note": "already inside: nothing moved"}
    if axis:
        direction = axis_vector(axis)
        tree_a, verts_a = world_bvh(moving)
        tree_b, verts_b = world_bvh(target)
        distance = travel_along(direction, tree_a, verts_a, tree_b, verts_b)
        if math.isinf(distance):
            raise ValueError(f"{a} does not reach {to} along {axis}")
        move = direction * (distance + depth)
    else:
        direction = point_b - point_a
        if direction.length < 1e-6:
            lo_a, hi_a = require_bounds(group_of(moving))
            lo_b, hi_b = require_bounds(group_of(target))
            toward = (lo_b + hi_b) / 2 - (lo_a + hi_a) / 2
            move = toward.normalized() * depth if toward.length > 1e-9 else Vector()
        else:
            move = direction + direction.normalized() * depth
    move_world(moving, move)
    after_depth, after_gap, _, _ = pair_metrics(moving, target)
    return {
        "moved": rvec(move),
        "gap_before": rnd(gap),
        "state": contact_state(after_depth, after_gap, eps),
        "penetration_depth": rnd(after_depth),
    }


CHECKPOINT_SCOPE = "bl_mcp_checkpoints"
TOPOLOGY_COUNTS = ("verts", "edges", "faces", "tris")


def checkpoint_folder(create=False):
    """Checkpoints of the open file only. The id is a scene property, so it travels with the .blend and its checkpoint copies."""
    scope = next((s[CHECKPOINT_SCOPE] for s in bpy.data.scenes if CHECKPOINT_SCOPE in s), None)
    if scope is None and create:
        scope = bpy.context.scene[CHECKPOINT_SCOPE] = uuid.uuid4().hex[:12]
    return CHECKPOINTS / scope if scope else None


def checkpoint_file(name, suffix):
    folder = checkpoint_folder()
    path = folder / f"{name}.{suffix}" if folder else None
    if path is None or not path.exists():
        raise ValueError(f"No checkpoint {name!r} of this scene (checkpoints of other files are not shared). Known: {checkpoint_names()}")
    return path


def topology():
    state = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        with evaluated_mesh(obj) as (_, mesh):
            mesh.calc_loop_triangles()
            state[obj.name] = {
                "verts": len(mesh.vertices),
                "edges": len(mesh.edges),
                "faces": len(mesh.polygons),
                "tris": len(mesh.loop_triangles),
                "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
            }
    return state


@handler
def checkpoint(name="last"):
    folder = checkpoint_folder(create=True)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    (folder / f"{name}.json").write_text(json.dumps({"boxes": {k: v for k, v in snapshot().items() if v}, "topology": topology()}))
    return {"name": name, "path": str(path)}


@handler
def diff_since(name="last", tolerance=0.001):
    saved = json.loads(checkpoint_file(name, "json").read_text())
    then, shape_then = saved["boxes"], saved["topology"]
    now, shape_now = {k: v for k, v in snapshot().items() if v}, topology()
    changed = []
    for key in sorted(set(then) & set(now)):
        a, b = then[key], now[key]
        entry = {"object": key}
        delta = max(abs(x - y) for pair in zip(a, b) for x, y in zip(*pair))
        if delta > tolerance:
            entry.update({"moved_or_resized_by_up_to_m": rnd(delta, 3), "size_before": rvec([hi - lo for lo, hi in zip(*a)], 3), "size_now": rvec([hi - lo for lo, hi in zip(*b)], 3)})
        before, after = shape_then.get(key), shape_now.get(key)
        if before and after:
            counts = {k: f"{before[k]} -> {after[k]}" for k in TOPOLOGY_COUNTS if before[k] != after[k]}
            if counts:
                entry["topology"] = counts
            if before["materials"] != after["materials"]:
                entry["material_slots"] = {"before": before["materials"], "now": after["materials"]}
        if len(entry) > 1:
            changed.append(entry)
    return {"added": sorted(set(now) - set(then)), "removed": sorted(set(then) - set(now)), "changed": changed}


def checkpoint_names():
    folder = checkpoint_folder()
    return sorted(p.stem for p in folder.glob("*.blend")) if folder else []


@handler
def rollback(name=None):
    if name is None:
        return {"checkpoints": checkpoint_names(), "note": "Nothing was rolled back. Pass the name of a checkpoint to return to it."}
    path = checkpoint_file(name, "blend")
    original = bpy.data.filepath
    SESSIONS.clear()
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    return {
        "restored": name,
        "note": "The open file is now the checkpoint copy. Use Save As before you save.",
        "original_file": original or None,
    }


def read_pixels(path):
    image = bpy.data.images.load(str(path))
    image.colorspace_settings.name = "Non-Color"
    width, height = image.size
    flat = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(flat)
    bpy.data.images.remove(image)
    return flat.reshape(height, width, 4)


def write_pixels(path, array, alpha=False):
    height, width = array.shape[:2]
    image = bpy.data.images.new("bl_out", width, height, alpha=alpha)
    image.colorspace_settings.name = "Non-Color"
    image.pixels.foreach_set(np.ascontiguousarray(array, dtype=np.float32).ravel())
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def set_if_valid(target, attr, value):
    try:
        setattr(target, attr, value)
    except TypeError:
        pass


@contextlib.contextmanager
def temp_scene(objs, look):
    scene = bpy.data.scenes.new("bl_tmp")
    world = bpy.data.worlds.new("bl_tmp")
    world.color = (0.0, 0.0, 0.0) if look == "mask" else (0.2, 0.21, 0.23)
    scene.world = world
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    set_if_valid(scene.view_settings, "view_transform", "Standard")
    set_if_valid(scene.view_settings, "look", "None")
    shading = scene.display.shading
    shading.show_object_outline = look != "mask"
    if look == "mask":
        shading.light = "FLAT"
        shading.color_type = "SINGLE"
        shading.single_color = (1.0, 1.0, 1.0)
        scene.display.render_aa = "OFF"
    else:
        shading.light = "STUDIO"
        shading.color_type = {"material": "MATERIAL", "object": "OBJECT"}[look]
    for obj in objs:
        scene.collection.objects.link(obj)
    try:
        yield scene
    finally:
        bpy.data.scenes.remove(scene)
        bpy.data.worlds.remove(world)


def shoot_view(scene, view, center, scale, distance, size, path):
    camera_data = bpy.data.cameras.new("bl_cam")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = scale
    camera_data.clip_start = 0.01
    camera_data.clip_end = distance * 4
    camera = bpy.data.objects.new("bl_cam", camera_data)
    scene.collection.objects.link(camera)
    euler, _ = VIEWS[view]
    if euler is None:
        direction = Vector((0.55, -0.75, 0.5)).normalized()
        camera.location = center + direction * distance
        camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    else:
        rotation = mathutils.Euler([math.radians(a) for a in euler])
        camera.rotation_euler = rotation
        camera.location = center - (rotation.to_matrix() @ Vector((0, 0, -1))) * distance
    scene.camera = camera
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.filepath = str(path)
    try:
        bpy.ops.render.render(write_still=True, scene=scene.name)
    finally:
        bpy.data.objects.remove(camera)
        bpy.data.cameras.remove(camera_data)
    return read_pixels(path)


def grid_step(scale):
    return next((s for s in (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 25) if scale / s <= 14), 50)


def draw_grid(tile, view, center, scale):
    _, axes = VIEWS[view]
    if axes is None:
        return
    size = tile.shape[0]
    step = grid_step(scale)
    for screen_axis, world_axis in enumerate(axes):
        lo = center[world_axis] - scale / 2
        k = math.ceil(lo / step)
        while k * step <= lo + scale:
            px = int(round((k * step - center[world_axis]) / scale * size + size / 2))
            if 0 <= px < size:
                zero = k == 0
                color = np.array(AXIS_COLORS[world_axis]) if zero else np.ones(3)
                weight = 0.8 if zero else (0.35 if k % 5 == 0 else 0.15)
                line = tile[px, :, :3] if screen_axis == 1 else tile[:, px, :3]
                line[:] = line * (1 - weight) + color * weight
            k += 1


def view_framing(objs):
    lo, hi = require_bounds(objs)
    center = (lo + hi) / 2
    scale = max(hi - lo) * 1.2
    return center, max(scale, 0.1), (hi - lo).length * 2 + 1


@handler
def render_sheet(names=None, views=("front", "side", "top", "iso"), size=384, color_by="material"):
    if color_by not in {"material", "object"}:
        raise ValueError("color_by is material or object")
    objs = with_children(names) if names else scene_objects()
    center, scale, distance = view_framing(objs)
    RENDERS.mkdir(parents=True, exist_ok=True)
    tiles = []
    saved_colors, legend = assign_id_colors(objs) if color_by == "object" else ({}, None)
    try:
        with temp_scene(objs, color_by) as scene:
            for view in views:
                tile = shoot_view(scene, view, center, scale, distance, size, RENDERS / f"{view}.png")
                draw_grid(tile, view, center, scale)
                tiles.append(tile)
    finally:
        for obj, color in saved_colors.items():
            obj.color = color
    cols = math.ceil(math.sqrt(len(tiles)))
    rows = math.ceil(len(tiles) / cols)
    sheet = np.zeros((rows * size, cols * size, 4), dtype=np.float32)
    for i, tile in enumerate(tiles):
        row, col = divmod(i, cols)
        y = (rows - 1 - row) * size
        sheet[y : y + size, col * size : (col + 1) * size] = tile
    path = RENDERS / "sheet.png"
    write_pixels(path, sheet)
    result = {
        "path": str(path),
        "views": list(views),
        "layout": f"{cols} columns, first view top left",
        "meters_per_tile": rnd(scale),
        "grid_step_m": grid_step(scale),
        "center": rvec(center),
    }
    if legend:
        result["legend"] = legend
    return result


def mask_of(pixels, threshold):
    alpha = pixels[:, :, 3]
    if alpha.min() < 0.99:
        return alpha > 0.5
    corners = np.array([pixels[0, 0], pixels[0, -1], pixels[-1, 0], pixels[-1, -1]])[:, :3]
    background = np.median(corners, axis=0)
    return np.abs(pixels[:, :, :3] - background).max(axis=2) > threshold


def reference_mask(path, threshold):
    return mask_of(read_pixels(path), threshold)


def crop(mask):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        raise ValueError("Silhouette is empty")
    return mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def resize_nearest(mask, height, width):
    rows = (np.arange(height) * mask.shape[0] / height).astype(int)
    cols = (np.arange(width) * mask.shape[1] / width).astype(int)
    return mask[rows][:, cols]


def link_new(obj):
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


def new_mesh_object(name, mesh):
    mesh.name = name
    co = np.array([v.co[:] for v in mesh.vertices])
    center = Vector((co.min(axis=0) + co.max(axis=0)) / 2) if len(co) else Vector()
    mesh.transform(mathutils.Matrix.Translation(-center))
    obj = bpy.data.objects.new(name, mesh)
    obj.location = center
    return link_new(obj)


def bake_modifiers(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    baked = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
    old = obj.data
    obj.modifiers.clear()
    obj.data = baked
    baked.name = obj.name
    bpy.data.meshes.remove(old)


def place_at(obj, at, anchor):
    move_world(obj, Vector(at) - anchor_point(require_bounds(group_of(obj)), anchor))


@handler
def create_primitive(kind, name, size=(1, 1, 1), at=(0, 0, 0), anchor=(0.5, 0.5, 0.5), segments=16, rotate_deg=None):
    builders = {
        "cube": lambda: bpy.ops.mesh.primitive_cube_add(size=1),
        "sphere": lambda: bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, segments=segments, ring_count=max(segments // 2, 3)),
        "cylinder": lambda: bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1, vertices=segments),
        "cone": lambda: bpy.ops.mesh.primitive_cone_add(radius1=0.5, depth=1, vertices=segments),
        "plane": lambda: bpy.ops.mesh.primitive_plane_add(size=1),
    }
    if kind == "torus":
        obj = torus_object(name, size, segments)
        place_at(obj, at, anchor)
        if rotate_deg:
            transform_world([obj], rotate_deg=rotate_deg, pivot=at)
        return describe(obj)
    if kind not in builders:
        raise ValueError(f"Unknown kind {kind!r}. Known: {sorted([*builders, 'torus'])}")
    builders[kind]()
    obj = bpy.context.object
    obj.name = obj.data.name = name
    obj.data.transform(mathutils.Matrix.Diagonal((*size, 1)))
    obj.location = (0, 0, 0)
    bpy.context.view_layer.update()
    place_at(obj, at, anchor)
    if rotate_deg:
        transform_world([obj], rotate_deg=rotate_deg, pivot=at)
    return describe(obj)


def torus_object(name, size, segments):
    outer_x, outer_y, tube = size
    major, minor = max(segments, 8), max(segments // 2, 6)
    ring = (outer_x - tube) / 2
    stretch = outer_y / outer_x
    bm = bmesh.new()
    verts = []
    for i in range(major):
        u = 2 * math.pi * i / major
        row = []
        for j in range(minor):
            v = 2 * math.pi * j / minor
            radius = ring + tube / 2 * math.cos(v)
            row.append(bm.verts.new((radius * math.cos(u), radius * math.sin(u) * stretch, tube / 2 * math.sin(v))))
        verts.append(row)
    for i in range(major):
        for j in range(minor):
            bm.faces.new((verts[i][j], verts[(i + 1) % major][j], verts[(i + 1) % major][(j + 1) % minor], verts[i][(j + 1) % minor]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return new_mesh_object(name, mesh)


def skin_layer(mesh):
    if not mesh.skin_vertices:
        bpy.ops.mesh.customdata_skin_add()
    return mesh.skin_vertices[0].data


@handler
def limb(name, points, radii, sides=8, subdivisions=2, apply=True):
    if len(points) < 2:
        raise ValueError("A limb needs at least 2 points")
    if len(radii) == 1:
        radii = list(radii) * len(points)
    if len(radii) != len(points):
        raise ValueError("Give one radius per point, or one radius for all")
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(p) for p in points], [(i, i + 1) for i in range(len(points) - 1)], [])
    obj = new_mesh_object(name, mesh)
    skin = obj.modifiers.new("skin", "SKIN")
    skin.use_smooth_shade = True
    layer = skin_layer(mesh)
    for i, radius in enumerate(radii):
        layer[i].radius = (radius, radius)
    layer[0].use_root = True
    if subdivisions:
        obj.modifiers.new("subsurf", "SUBSURF").levels = subdivisions
    if apply:
        bake_modifiers(obj)
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
    return describe(obj)


def ring(center, size, plane, roundness, segments):
    a_index, b_index = plane
    points = []
    for k in range(segments):
        t = 2 * math.pi * k / segments
        c, s = math.cos(t), math.sin(t)
        a = math.copysign(abs(c) ** (2 / roundness), c) * size[0] / 2
        b = math.copysign(abs(s) ** (2 / roundness), s) * size[1] / 2
        p = list(center)
        p[a_index] += a
        p[b_index] += b
        points.append(tuple(p))
    return points


@handler
def loft(name, sections, axis="Z", segments=16, caps=True, subdivisions=0):
    planes = {"X": (1, 2), "Y": (0, 2), "Z": (0, 1)}
    if len(sections) < 2:
        raise ValueError("A loft needs at least 2 sections")
    plane = planes[axis.upper()]
    bm = bmesh.new()
    rings = []
    for section in sections:
        verts = [bm.verts.new(p) for p in ring(section["at"], section["size"], plane, section.get("roundness", 2), segments)]
        rings.append(verts)
    for lower, upper in zip(rings, rings[1:]):
        for k in range(segments):
            n = (k + 1) % segments
            bm.faces.new((lower[k], lower[n], upper[n], upper[k]))
    if caps:
        bm.faces.new(rings[0])
        bm.faces.new(reversed(rings[-1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = new_mesh_object(name, mesh)
    if subdivisions:
        obj.modifiers.new("subsurf", "SUBSURF").levels = subdivisions
        bake_modifiers(obj)
    return describe(obj)


def mirrored_name(name):
    for a, b in (("_L", "_R"), (".L", ".R"), ("Left", "Right"), ("left", "right"), ("_l", "_r")):
        for x, y in ((a, b), (b, a)):
            if x in name:
                return name.replace(x, y)
    return name + "_mirror"


@handler
def mirror(name, axis="X", at=0.0, new_name=None):
    source = get_object(name)
    if source.type != "MESH":
        raise ValueError(f"{name} is {source.type}, not MESH")
    index = AXES[axis.upper()]
    scale = [1, 1, 1, 1]
    scale[index] = -1
    plane = Vector((0, 0, 0))
    plane[index] = at
    flip = mathutils.Matrix.Translation(plane) @ mathutils.Matrix.Diagonal(scale) @ mathutils.Matrix.Translation(-plane)
    origin = flip @ source.matrix_world.translation
    mesh = source.data.copy()
    mesh.transform(mathutils.Matrix.Translation(-origin) @ flip @ source.matrix_world)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.name = new_name or mirrored_name(name)
    result = bpy.data.objects.new(mesh.name, mesh)
    result.location = origin
    link_new(result)
    for index, slot in enumerate(source.material_slots):
        if slot.link == "OBJECT":
            result.material_slots[index].link = "OBJECT"
            result.material_slots[index].material = slot.material
    return describe(result)


def parse_color(value):
    if isinstance(value, str):
        text = value.lstrip("#")
        srgb = [int(text[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return list(value)[:3]


@handler
def parent(child, to, keep_world=True):
    obj, target = get_object(child), get_object(to)
    world = obj.matrix_world.copy()
    obj.parent = target
    if keep_world:
        obj.matrix_parent_inverse = target.matrix_world.inverted()
        obj.matrix_world = world
    bpy.context.view_layer.update()
    return describe(obj)


@handler
def duplicate(name, new_name=None, offset=(0, 0, 0), linked=False, rotate_deg=None, pivot=None):
    source = get_object(name)
    copy = source.copy()
    if source.data is not None and not linked:
        copy.data = source.data.copy()
    copy.name = new_name or f"{name}_copy"
    link_new(copy)
    move_world(copy, offset)
    if rotate_deg:
        transform_world([copy], rotate_deg=rotate_deg, pivot=pivot)
    return describe(copy)


ADDED_LIGHT_FLAG = "bl_added_light"


@handler
def delete(names=None, with_children=False, prefix=None, lights=None):
    if lights not in (None, "added", "all"):
        raise ValueError("lights is 'added' (the lights made by add_light) or 'all'")
    if not names and not prefix and not lights:
        raise ValueError("Give names, a prefix or lights")
    named = [get_object(n) for n in names or []]
    if prefix:
        named += [o for o in bpy.data.objects if o.name.startswith(prefix)]
    if lights:
        named += [o for o in bpy.data.objects if o.type == "LIGHT" and (lights == "all" or o.get(ADDED_LIGHT_FLAG))]
    named = list(dict.fromkeys(named))
    targets = with_children_of(named) if with_children else named
    removed = [o.name for o in targets]
    bpy.context.view_layer.update()
    unparented = []
    for obj in targets:
        for child in obj.children:
            if child.name in removed:
                continue
            world = child.matrix_world.copy()
            child.parent = None
            child.matrix_world = world
            unparented.append(child.name)
    for obj in targets:
        light = obj.data if obj.type == "LIGHT" else None
        bpy.data.objects.remove(obj)
        if light is not None and light.users == 0:
            bpy.data.lights.remove(light)
    bpy.context.view_layer.update()
    result = {"removed": removed}
    if unparented:
        result["unparented"] = unparented
        result["note"] = "the unparented children kept their place in the world; pass with_children=true to delete them too"
    return result


def select_only(objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def image_nodes(objs):
    materials = {slot.material for obj in objs for slot in obj.material_slots if slot.material and slot.material.node_tree}
    return [n for mat in materials for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]


@contextlib.contextmanager
def downscaled_textures(objs, max_size):
    """Swaps images larger than max_size for scaled copies of the same name; on exit the originals are back."""
    nodes = image_nodes(objs) if max_size else []
    swapped, report = [], {}
    try:
        for image in {n.image for n in nodes}:
            width, height = image.size
            if max(width, height) <= max_size:
                continue
            name, factor = image.name, max_size / max(width, height)
            small = image.copy()
            small.scale(max(1, round(width * factor)), max(1, round(height * factor)))
            users = [n for n in nodes if n.image == image]
            swapped.append((image, small, name, users))
            # The exporter names the texture after the image: the copy takes the name for the time of the export.
            image.name = f"{name}.full_size"
            small.name = name
            for node in users:
                node.image = small
            report[name] = f"{width}x{height} -> {small.size[0]}x{small.size[1]}"
        yield report
    finally:
        for image, small, name, users in swapped:
            for node in users:
                node.image = image
            bpy.data.images.remove(small)
            image.name = name


def glb_textures(path, objs):
    doc, binary, _ = read_glb(path)
    scene_sizes = {Path(n.image.name).stem: list(n.image.size) for n in image_nodes(objs)}
    textures = []
    for image in doc.get("images", []):
        view = doc["bufferViews"][image["bufferView"]] if "bufferView" in image else None
        start = view.get("byteOffset", 0) if view else 0
        dims = png_size(binary[start : start + 32]) if view else None
        size = list(dims) if dims else scene_sizes.get(Path(image.get("name") or "").stem)
        textures.append({"name": image.get("name"), "size": size, "bytes": view["byteLength"] if view else None})
    return textures


@handler
def export_glb(path, names=None, apply_modifiers=True, skins=True, influences=4, animations=False, draco=False, tangents=False, scale=1.0, max_texture_size=None):
    objs = with_children(names) if names else scene_objects()
    if not objs:
        raise ValueError("Nothing to export")
    select_only(objs)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wanted = {
        "filepath": str(path), "use_selection": True, "export_format": "GLB", "export_apply": apply_modifiers,
        "export_skins": skins, "export_influence_nb": influences, "export_animations": animations,
        "export_draco_mesh_compression_enable": draco, "export_tangents": tangents, "export_yup": True,
    }
    known = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    skipped = sorted(set(wanted) - known)
    if scale <= 0:
        raise ValueError("scale must be above zero")
    if max_texture_size is not None and max_texture_size < 1:
        raise ValueError("max_texture_size is a size in pixels, 1 or more")
    roots = [o for o in objs if not (ancestry(o) - {o.name}) & {x.name for x in objs}]
    saved = {o: o.matrix_basis.copy() for o in roots}
    try:
        if scale != 1.0:
            transform_world(objs, scale=scale, pivot=(0, 0, 0))
        with downscaled_textures(objs, max_texture_size) as downscaled:
            bpy.ops.export_scene.gltf(**{k: v for k, v in wanted.items() if k in known})
            textures = glb_textures(path, objs)
    finally:
        for obj, matrix in saved.items():
            obj.matrix_basis = matrix
        bpy.context.view_layer.update()
    result = {"path": str(path), "bytes": Path(path).stat().st_size, "objects": len(objs)}
    result["textures"] = {"count": len(textures), "bytes": sum(t["bytes"] or 0 for t in textures), "images": textures}
    if downscaled:
        result["textures"]["downscaled_for_export"] = downscaled
    if scale != 1.0:
        result["scale"] = scale
    if skipped:
        result["ignored_options"] = skipped
    return result


@handler
def import_glb(path):
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=str(path))
    added = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    return {"imported": [brief(o) for o in added]}


def make_caster():
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene

    def cast(origin, direction, distance=1.0e4):
        hit, location, normal, _, obj, _ = scene.ray_cast(depsgraph, Vector(origin), Vector(direction).normalized(), distance=distance)
        return (location, normal, obj) if hit else None

    return cast


def point_of(value):
    if isinstance(value, str):
        lo, hi = require_bounds(group_of(get_object(value)))
        return (lo + hi) / 2
    return Vector(value)


@handler
def raycast(origin, direction, max_distance=1000.0):
    hit = make_caster()(origin, direction, max_distance)
    if hit is None:
        return {"hit": False}
    location, normal, obj = hit
    return {
        "hit": True,
        "object": obj.name,
        "distance": rnd((location - Vector(origin)).length),
        "point": rvec(location),
        "normal": rvec(normal),
    }


@handler
def line_of_sight(a, b):
    start, end = point_of(a), point_of(b)
    ignored = {n for n in (a, b) if isinstance(n, str)}
    cast = make_caster()
    direction = end - start
    total = direction.length
    origin = start.copy()
    for _ in range(16):
        remaining = total - (origin - start).length
        if remaining <= 1e-4:
            break
        hit = cast(origin, direction, remaining)
        if hit is None:
            break
        location, _, obj = hit
        if not ancestry(obj) & ignored:
            return {"visible": False, "blocked_by": obj.name, "at_distance": rnd((location - start).length), "point": rvec(location)}
        origin = location + direction.normalized() * 1e-3
    return {"visible": True, "distance": rnd(total)}


def floors_in_column(cast, x, y, top, bottom, cos_slope, levels):
    found, z = [], top
    for _ in range(levels * 2):
        hit = cast((x, y, z), (0, 0, -1), z - bottom + 1)
        if hit is None:
            break
        location, normal, _ = hit
        if normal.z >= cos_slope:
            found.append(location.z)
        z = location.z - 1e-3
    return found


def standable(cast, x, y, floor, agent_height, agent_radius, max_step):
    ceiling = cast((x, y, floor + 0.01), (0, 0, 1), agent_height)
    if ceiling is not None:
        return False
    probe = floor + max_step + 0.05
    return not any(cast((x, y, probe), d, agent_radius) for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)))


def label_regions(nodes, max_step):
    by_cell = {}
    for key, z in nodes.items():
        by_cell.setdefault(key[:2], []).append(key)
    label, regions = {}, []
    for key in nodes:
        if key in label:
            continue
        stack, members = [key], []
        label[key] = len(regions)
        while stack:
            cur = stack.pop()
            members.append(cur)
            i, j, _ = cur
            for ni, nj in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                for other in by_cell.get((ni, nj), ()):
                    if other not in label and abs(nodes[other] - nodes[cur]) <= max_step:
                        label[other] = len(regions)
                        stack.append(other)
        regions.append(members)
    return label, regions


def build_grid(names, cell, agent_height, agent_radius, max_step, max_slope_deg, max_levels):
    objs = with_children(names) if names else scene_objects()
    lo, hi = require_bounds(objs)
    nx, ny = math.ceil((hi.x - lo.x) / cell), math.ceil((hi.y - lo.y) / cell)
    if nx * ny > 40000:
        raise ValueError(f"{nx}x{ny} cells is too many. Raise `cell`.")
    cast = make_caster()
    cos_slope = math.cos(math.radians(max_slope_deg))
    nodes, blocked = {}, set()
    for j in range(ny):
        for i in range(nx):
            x, y = lo.x + (i + 0.5) * cell, lo.y + (j + 0.5) * cell
            for k, floor in enumerate(floors_in_column(cast, x, y, hi.z + 1, lo.z - 1, cos_slope, max_levels)):
                if standable(cast, x, y, floor, agent_height, agent_radius, max_step):
                    nodes[(i, j, k)] = floor
                else:
                    blocked.add((i, j))
    if not nodes:
        raise ValueError("No walkable floor found")
    label, regions = label_regions(nodes, max_step)
    return {"lo": lo, "hi": hi, "nx": nx, "ny": ny, "cell": cell, "nodes": nodes, "blocked": blocked,
            "label": label, "regions": regions, "cast": cast, "max_levels": max_levels, "max_step": max_step}


def nearest_node(grid, point, within=2):
    lo, cell = grid["lo"], grid["cell"]
    si, sj = int((point[0] - lo.x) / cell), int((point[1] - lo.y) / cell)
    near = [k for k in grid["nodes"] if abs(k[0] - si) <= within and abs(k[1] - sj) <= within]
    if not near:
        raise ValueError(f"{rvec(point, 2)} is not on or near a walkable cell")
    return min(near, key=lambda k: (k[0] - si) ** 2 + (k[1] - sj) ** 2 + (abs(grid["nodes"][k] - point[2]) / cell) ** 2)


def home_region(grid, start):
    """The region of `start`, else the largest one among those that touch the lowest floor level (not wall tops or roofs)."""
    if start is not None:
        return grid["label"][nearest_node(grid, start, within=2)]
    nodes, regions = grid["nodes"], grid["regions"]
    lowest = min(nodes.values())
    ground = [r for r, members in enumerate(regions) if min(nodes[k] for k in members) <= lowest + 0.6]
    return max(ground or range(len(regions)), key=lambda r: len(regions[r]))


def node_xy(grid, key):
    return grid["lo"].x + (key[0] + 0.5) * grid["cell"], grid["lo"].y + (key[1] + 0.5) * grid["cell"]


def save_grid_image(grid, colors, name):
    px = max(1, 640 // max(grid["nx"], grid["ny"]))
    image = np.repeat(np.repeat(colors, px, axis=0), px, axis=1)
    RENDERS.mkdir(parents=True, exist_ok=True)
    path = RENDERS / name
    write_pixels(path, image)
    return path, px


def base_colors(grid, home):
    colors = np.zeros((grid["ny"], grid["nx"], 4), dtype=np.float32)
    colors[:] = (0.12, 0.12, 0.14, 1)
    for key in grid["nodes"]:
        colors[key[1], key[0]] = (0.2, 0.8, 0.3, 1) if grid["label"][key] == home else (0.95, 0.8, 0.2, 1)
    for i, j in grid["blocked"]:
        if not any(grid["label"].get((i, j, k)) == home for k in range(grid["max_levels"])):
            colors[j, i] = (0.75, 0.2, 0.2, 1)
    return colors


@handler
def walkable_map(names=None, cell=0.5, agent_height=1.8, agent_radius=0.3, max_step=0.35, max_slope_deg=45.0, start=None, max_levels=3):
    grid = build_grid(names, cell, agent_height, agent_radius, max_step, max_slope_deg, max_levels)
    home = home_region(grid, start)
    path, _ = save_grid_image(grid, base_colors(grid, home), "walkable.png")
    area = cell * cell
    sizes = sorted((len(m) * area for m in grid["regions"]), reverse=True)
    return {
        "image": str(path),
        "legend": "green reachable, yellow walkable but not reachable, red blocked (solid, low ceiling or too close to a wall), dark no floor. +Y is up in the image.",
        "grid": f"{grid['nx']}x{grid['ny']} cells of {cell} m, lower-left corner at {rvec(grid['lo'][:2], 3)}",
        "reachable_area_m2": rnd(len(grid["regions"][home]) * area, 2),
        "unreachable_area_m2": rnd((len(grid["nodes"]) - len(grid["regions"][home])) * area, 2),
        "blocked_area_m2": rnd(len(grid["blocked"]) * area, 2),
        "regions": len(grid["regions"]),
        "largest_regions_m2": [rnd(v, 2) for v in sizes[:5]],
    }


def heat_color(t):
    t = max(0.0, min(1.0, t))
    return (0.15 + 0.85 * t, 0.35 + 0.4 * (1 - abs(2 * t - 1)), 0.9 * (1 - t) + 0.1, 1)


@handler
def sightline_map(names=None, cell=0.75, eye_height=1.6, rays=24, max_range=60.0, long_sightline=25.0, start=None,
                  agent_height=1.8, agent_radius=0.3, max_step=0.35, max_slope_deg=45.0, max_levels=3):
    grid = build_grid(names, cell, agent_height, agent_radius, max_step, max_slope_deg, max_levels)
    home = home_region(grid, start)
    members = grid["regions"][home]
    if len(members) * rays > 400000:
        raise ValueError(f"{len(members)} cells x {rays} rays is too slow. Raise `cell` or lower `rays`.")
    cast, directions = grid["cast"], [(math.cos(2 * math.pi * r / rays), math.sin(2 * math.pi * r / rays), 0) for r in range(rays)]
    stats = {}
    for key in members:
        x, y = node_xy(grid, key)
        origin = (x, y, grid["nodes"][key] + eye_height)
        lengths = []
        for d in directions:
            hit = cast(origin, d, max_range)
            lengths.append((hit[0] - Vector(origin)).length if hit else max_range)
        longest = max(range(rays), key=lengths.__getitem__)
        stats[key] = (sum(lengths) / rays, lengths[longest], longest)
    means = np.array([v[0] for v in stats.values()])
    scale = float(np.percentile(means, 95)) or 1.0
    colors = base_colors(grid, home)
    colors[:, :, :3] *= 0.35
    for key, (mean, _, _) in stats.items():
        colors[key[1], key[0]] = heat_color(mean / scale)
    path, _ = save_grid_image(grid, colors, "sightlines.png")
    ranked = sorted(stats.items(), key=lambda kv: -kv[1][1])
    long_cells = [k for k, v in stats.items() if v[1] >= long_sightline]
    return {
        "image": str(path),
        "legend": "blue = enclosed (short sight lines), red = exposed (long sight lines), by mean ray length; dark = not reachable. +Y is up.",
        "cells_analysed": len(stats),
        "mean_sightline_m": rnd(float(means.mean()), 2),
        "longest_sightlines": [
            {"from": rvec(node_xy(grid, k), 2), "length_m": rnd(v[1], 2), "azimuth_deg": rnd(360 * v[2] / rays, 1)} for k, v in ranked[:5]
        ],
        f"area_with_a_sightline_over_{long_sightline:g}_m_m2": rnd(len(long_cells) * cell * cell, 2),
        "note": f"{rays} rays per cell at eye height {eye_height} m, range {max_range} m",
    }


def clearance_map(grid, home):
    free = np.zeros((grid["nx"], grid["ny"]), dtype=bool)
    for key in grid["regions"][home]:
        free[key[0], key[1]] = True
    dist = np.where(free, 1e9, 0.0)
    nx, ny = free.shape
    root2 = math.sqrt(2)
    for i in range(nx):
        for j in range(ny):
            if free[i, j]:
                best = 1.0 if i in (0, nx - 1) or j in (0, ny - 1) else dist[i, j]
                for di, dj, w in ((-1, 0, 1), (0, -1, 1), (-1, -1, root2), (-1, 1, root2)):
                    a, b = i + di, j + dj
                    if 0 <= a < nx and 0 <= b < ny:
                        best = min(best, dist[a, b] + w)
                dist[i, j] = best
    for i in range(nx - 1, -1, -1):
        for j in range(ny - 1, -1, -1):
            if free[i, j]:
                best = dist[i, j]
                for di, dj, w in ((1, 0, 1), (0, 1, 1), (1, 1, root2), (1, -1, root2)):
                    a, b = i + di, j + dj
                    if 0 <= a < nx and 0 <= b < ny:
                        best = min(best, dist[a, b] + w)
                dist[i, j] = best
    return dist


@handler
def route(start, end, names=None, cell=0.5, min_width=0.0, agent_height=1.8, agent_radius=0.3, max_step=0.35, max_slope_deg=45.0, max_levels=3):
    import heapq

    grid = build_grid(names, cell, agent_height, agent_radius, max_step, max_slope_deg, max_levels)
    a, b = nearest_node(grid, start), nearest_node(grid, end)
    if grid["label"][a] != grid["label"][b]:
        return {"reachable": False, "reason": "start and end are in different walkable regions", "start_region_m2": rnd(len(grid["regions"][grid["label"][a]]) * cell * cell, 2)}
    home = grid["label"][a]
    clear = clearance_map(grid, home)
    width_of = lambda key: (2 * clear[key[0], key[1]] - 1) * cell + 2 * agent_radius
    nodes = grid["nodes"]
    by_cell = {}
    for key in grid["regions"][home]:
        by_cell.setdefault(key[:2], []).append(key)
    best, came, queue = {a: 0.0}, {}, [(0.0, a)]
    while queue:
        cost, cur = heapq.heappop(queue)
        if cur == b:
            break
        if cost > best.get(cur, math.inf):
            continue
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if (di, dj) == (0, 0):
                    continue
                for nxt in by_cell.get((cur[0] + di, cur[1] + dj), ()):
                    if abs(nodes[nxt] - nodes[cur]) > grid["max_step"] or width_of(nxt) < min_width:
                        continue
                    if di and dj and not (by_cell.get((cur[0] + di, cur[1])) and by_cell.get((cur[0], cur[1] + dj))):
                        continue
                    step = math.hypot(di, dj) * cell
                    if cost + step < best.get(nxt, math.inf):
                        best[nxt] = cost + step
                        came[nxt] = cur
                        heapq.heappush(queue, (cost + step, nxt))
    if b not in best:
        return {"reachable": False, "reason": f"no route with width >= {min_width} m", "widest_possible": "run again with a smaller min_width"}
    path = [b]
    while path[-1] != a:
        path.append(came[path[-1]])
    path.reverse()
    narrow = min(path, key=width_of)
    colors = base_colors(grid, home)
    for key in path:
        colors[key[1], key[0]] = (1, 1, 1, 1)
    colors[a[1], a[0]], colors[b[1], b[0]] = (0.2, 0.5, 1, 1), (1, 0.3, 0.9, 1)
    image, _ = save_grid_image(grid, colors, "route.png")
    step_up = [abs(nodes[q] - nodes[p]) for p, q in zip(path, path[1:])]
    waypoints = [rvec((*node_xy(grid, k), nodes[k]), 2) for k in path[:: max(1, len(path) // 12)]] + [rvec((*node_xy(grid, b), nodes[b]), 2)]
    return {
        "reachable": True,
        "length_m": rnd(best[b], 2),
        "straight_line_m": rnd(math.dist(node_xy(grid, a), node_xy(grid, b)), 2),
        "narrowest_m": rnd(width_of(narrow), 2),
        "narrowest_at": rvec((*node_xy(grid, narrow), nodes[narrow]), 2),
        "highest_step_m": rnd(max(step_up, default=0), 3),
        "waypoints": waypoints,
        "image": str(image),
        "legend": "white route, blue start, pink end; other colours as walkable_map",
        "note": "width is the free width including the agent radius on both sides",
    }


def budget_of(names=None, max_tris=None, max_objects=None, max_materials=None, max_draw_calls=None):
    """Triangles, objects, materials and draw calls of the meshes, and the limits they pass."""
    objs = with_children(names) if names else scene_objects()
    meshes = [o for o in objs if o.type == "MESH"]
    tris = 0
    for obj in meshes:
        with evaluated_mesh(obj) as (_, mesh):
            mesh.calc_loop_triangles()
            tris += len(mesh.loop_triangles)
    materials = {s.material.name for o in meshes for s in o.material_slots if s.material}
    draw_calls = sum(max(1, len(o.material_slots)) for o in meshes)
    shared = {(o.data.name, tuple(slot.material.name if slot.material else "" for slot in o.material_slots)) for o in meshes}
    instanced = len(shared)
    measured = {"tris": tris, "objects": len(meshes), "materials": len(materials), "draw_calls_estimate": draw_calls}
    limits = {"tris": max_tris, "objects": max_objects, "materials": max_materials, "draw_calls_estimate": max_draw_calls}
    verdict = [f"{k} {measured[k]} over the limit {v}" for k, v in limits.items() if v is not None and measured[k] > v]
    result = {**measured, "over_budget": verdict or ["none"], "draw_calls_if_instanced": instanced, "note": "draw_calls_estimate assumes no batching or instancing"}
    if instanced < draw_calls:
        result["hint"] = f"{len(meshes) - instanced} objects repeat a mesh with the same materials: with GPU instancing (three.js InstancedMesh) they cost {instanced} draw calls; without it, merge them with combine"
    return result


EEVEE_LOOKS = {"normals", "backfaces"}
WIRE_PIXELS = 2.0
FLAT_COLORS = {"clay": (0.75, 0.76, 0.8)}


def override_material(look):
    mat = bpy.data.materials.new("bl_override")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    geometry = nodes.new("ShaderNodeNewGeometry")
    out = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    if look == "normals":
        scaled = nodes.new("ShaderNodeVectorMath")
        scaled.operation = "MULTIPLY_ADD"
        scaled.inputs[1].default_value = (0.5, 0.5, 0.5)
        scaled.inputs[2].default_value = (0.5, 0.5, 0.5)
        links.new(geometry.outputs["Normal"], scaled.inputs[0])
        links.new(scaled.outputs[0], emission.inputs["Color"])
        links.new(emission.outputs[0], out.inputs["Surface"])
        return mat
    front = emission
    front.inputs["Color"].default_value = (0.6, 0.6, 0.6, 1)
    back = nodes.new("ShaderNodeEmission")
    back.inputs["Color"].default_value = (1, 0, 0, 1)
    mix = nodes.new("ShaderNodeMixShader")
    links.new(geometry.outputs["Backfacing"], mix.inputs[0])
    links.new(front.outputs[0], mix.inputs[1])
    links.new(back.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def configure_extra_look(scene, look):
    """Looks beyond material, object and mask: clay, xray, ids, wire, normals, backfaces."""
    shading = scene.display.shading
    shading.show_object_outline = look in {"clay", "solid"}
    if look in EEVEE_LOOKS:
        scene.render.engine = "BLENDER_EEVEE"
        set_if_valid(scene.eevee, "taa_render_samples", 1)
        scene.view_layers[0].material_override = override_material(look)
        return
    if look == "clay":
        shading.light, shading.color_type, shading.single_color = "STUDIO", "SINGLE", FLAT_COLORS["clay"]
    elif look == "xray":
        shading.light, shading.color_type = "STUDIO", "MATERIAL"
        shading.show_xray, shading.xray_alpha = True, 0.45
    elif look == "ids":
        shading.light, shading.color_type = "FLAT", "OBJECT"
        scene.display.render_aa = "OFF"
    elif look == "flat":
        shading.light, shading.color_type = "FLAT", "MATERIAL"
        scene.display.render_aa = "OFF"
    elif look == "wire":
        shading.light, shading.color_type, shading.single_color = "FLAT", "SINGLE", (0.95, 0.95, 0.95)


def hex_of(rgb):
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def assign_id_colors(objs):
    import colorsys

    saved = {o: tuple(o.color) for o in objs}
    legend = {}
    for i, obj in enumerate(sorted(objs, key=lambda o: o.name)):
        rgb = colorsys.hsv_to_rgb((i * 0.61803398875) % 1.0, 0.75, 0.95)
        obj.color = (*rgb, 1)
        legend[obj.name] = hex_of(rgb)
    return saved, legend


def wire_copies(objs, thickness):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    copies = []
    for obj in objs:
        if obj.type != "MESH":
            continue
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph))
        copy = bpy.data.objects.new(obj.name + "_wire", mesh)
        copy.matrix_world = obj.matrix_world
        modifier = copy.modifiers.new("wire", "WIREFRAME")
        modifier.thickness = thickness
        modifier.use_replace = True
        copies.append(copy)
    return copies


def drop_wire_copies(copies):
    for copy in copies:
        mesh = copy.data
        bpy.data.objects.remove(copy)
        bpy.data.meshes.remove(mesh)


def camera_fit(cloud, center, direction, fov, margin):
    offsets = cloud - np.array(center)
    toward = np.array(direction)
    basis = (-direction).to_track_quat("-Z", "Y").to_matrix()
    right, up = np.array(basis.col[0]), np.array(basis.col[1])
    reach = np.maximum(np.abs(offsets @ right), np.abs(offsets @ up))
    if fov:
        needed = reach * margin / math.tan(math.radians(fov) / 2) + offsets @ toward
        return float(needed.max()) + 0.01, None
    return float(np.linalg.norm(offsets, axis=1).max()) + 1.0, float(reach.max() * 2 * margin)


@handler
def render_view(target=None, azimuth=35.0, elevation=20.0, fov=35.0, mode="solid", size=512, isolate=True, margin=1.15, look_at=None, name="view"):
    modes = {"solid", "clay", "xray", "flat", "ids", "wire", *EEVEE_LOOKS}
    if mode not in modes:
        raise ValueError(f"Unknown mode {mode!r}. Known: {sorted(modes)}")
    framed = with_children(target) if target else scene_objects()
    shown = framed if isolate else scene_objects()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    cloud = np.vstack([points_of(o, depsgraph) for o in framed])
    center = Vector(look_at) if look_at is not None else Vector((cloud.min(axis=0) + cloud.max(axis=0)) / 2)
    el = math.radians(max(-89.5, min(89.5, elevation)))
    az = math.radians(azimuth)
    direction = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    distance, ortho_scale = camera_fit(cloud, center, direction, fov, margin)

    legend, saved_colors, copies = None, {}, []
    look = {"solid": "material"}.get(mode, mode)
    if mode == "ids":
        saved_colors, legend = assign_id_colors(shown)
    if mode == "wire":
        frame_width = ortho_scale or 2 * distance * math.tan(math.radians(fov) / 2)
        copies = wire_copies(shown, max(frame_width * WIRE_PIXELS / size, 1e-6))
        shown = copies
    RENDERS.mkdir(parents=True, exist_ok=True)
    path = RENDERS / f"{name}.png"
    camera_data = bpy.data.cameras.new("bl_cam")
    try:
        with temp_scene(shown, "mask" if look in {"wire", "ids"} else "material") as scene:
            if look != "material":
                configure_extra_look(scene, look)
            camera_data.clip_start, camera_data.clip_end = 0.01, distance * 4 + 10
            if fov:
                camera_data.type, camera_data.sensor_fit, camera_data.angle = "PERSP", "AUTO", math.radians(fov)
            else:
                camera_data.type, camera_data.ortho_scale = "ORTHO", ortho_scale
            camera = bpy.data.objects.new("bl_cam", camera_data)
            scene.collection.objects.link(camera)
            camera.location = center + direction * distance
            camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
            scene.camera = camera
            scene.render.resolution_x = scene.render.resolution_y = size
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True, scene=scene.name)
            bpy.data.objects.remove(camera)
    finally:
        bpy.data.cameras.remove(camera_data)
        for obj, color in saved_colors.items():
            obj.color = color
        drop_wire_copies(copies)
        for mat in [m for m in bpy.data.materials if m.name.startswith("bl_override") and m.users == 0]:
            bpy.data.materials.remove(mat)
    result = {
        "path": str(path),
        "mode": mode,
        "camera_at": rvec(center + direction * distance, 3),
        "looking_at": rvec(center, 3),
        "distance_m": rnd(distance, 3),
        "projection": f"perspective {fov} deg" if fov else f"orthographic, {rnd(ortho_scale, 3)} m across",
    }
    if legend:
        result["legend"] = legend
    if mode == "backfaces":
        result["legend"] = "grey front faces, red back faces (flipped normals or open shells seen from inside)"
    if mode == "normals":
        result["legend"] = "colour is the world normal: +X red, +Y green, +Z blue, negative axes darker"
    return result


SPEC_CHECKS = {}
SPEC_HINTS = {
    "size": "set_dimensions",
    "position": "attach or ground",
    "ratio": "set_dimensions on one of the two",
    "gap": "move_to_contact or attach",
    "contact": "move_to_contact (touch) or attach",
    "symmetry": "mirror one side from the other",
    "inside": "move or resize with set_dimensions",
    "on_ground": "ground",
    "clean": "check_mesh lists the defects",
    "budget": "reduce segments or merge parts",
    "connected": "find_floating names the loose parts, then move_to_contact",
}


def spec_check(fn):
    SPEC_CHECKS[fn.__name__.removeprefix("spec_")] = fn
    return fn


def judge(value, rule):
    expected = []
    ok = True
    if "equals" in rule:
        tol = rule.get("tol", 0.01)
        ok = ok and abs(value - rule["equals"]) <= tol
        expected.append(f"= {rule['equals']} +-{tol}")
    if "min" in rule:
        ok = ok and value >= rule["min"] - 1e-9
        expected.append(f">= {rule['min']}")
    if "max" in rule:
        ok = ok and value <= rule["max"] + 1e-9
        expected.append(f"<= {rule['max']}")
    if not expected:
        raise ValueError("Give equals (with tol), min or max")
    return ok, " and ".join(expected)


def axis_of(check):
    return AXES[str(check.get("axis", "z")).upper()]


@spec_check
def spec_size(c):
    obj = get_object(c["object"])
    lo, hi = require_bounds(group_of(obj) if c.get("with_children") else [obj])
    value = (hi - lo)[axis_of(c)]
    ok, expected = judge(value, c)
    return ok, rnd(value), f"size {c.get('axis', 'z')} {expected}"


@spec_check
def spec_position(c):
    lo, hi = require_bounds([get_object(c["object"])])
    which = c.get("which", "center")
    value = {"min": lo, "max": hi, "center": (lo + hi) / 2}[which][axis_of(c)]
    ok, expected = judge(value, c)
    return ok, rnd(value), f"{which} {c.get('axis', 'z')} {expected}"


@spec_check
def spec_ratio(c):
    lo_a, hi_a = require_bounds([get_object(c["a"])])
    lo_b, hi_b = require_bounds([get_object(c["b"])])
    value = (hi_a - lo_a)[axis_of(c)] / (hi_b - lo_b)[axis_of(c)]
    ok, expected = judge(value, c)
    return ok, rnd(value), f"size {c['a']} / {c['b']} along {c.get('axis', 'z')} {expected}"


@spec_check
def spec_gap(c):
    depth, gap, _, _ = pair_metrics(get_object(c["a"]), get_object(c["b"]))
    value = 0.0 if depth > 1e-4 else gap
    ok, expected = judge(value, c)
    return ok, rnd(value, 5), f"gap {expected}"


@spec_check
def spec_contact(c):
    depth, gap, _, _ = pair_metrics(get_object(c["a"]), get_object(c["b"]))
    state = contact_state(depth, gap)
    wanted = c.get("state", "connected")
    ok = state in ("touching", "intersecting") if wanted == "connected" else state == wanted
    if "max_depth" in c:
        ok = ok and depth <= c["max_depth"]
    return ok, f"{state}, depth {rnd(depth, 4)}, gap {rnd(gap, 4)}", f"{wanted}" + (f", depth <= {c['max_depth']}" if "max_depth" in c else "")


@spec_check
def spec_symmetry(c):
    result = check_symmetry(c["objects"], c.get("axis", "X"), c.get("at"), c.get("tolerance", 0.005))
    limit = c.get("max_unmatched_share", 0.0)
    return result["unmatched_share"] <= limit, f"{result['unmatched']} of {result['vertices']} unmatched, worst {result['worst_error']}", f"unmatched share <= {limit}"


@spec_check
def spec_inside(c):
    lo, hi = require_bounds([get_object(c["object"])])
    box_lo, box_hi = require_bounds([get_object(c["container"])])
    margin = c.get("margin", 0.0)
    over = [max(box_lo[i] - margin - lo[i], hi[i] - box_hi[i] - margin, 0.0) for i in range(3)]
    return max(over) <= 1e-6, f"sticks out by {rvec(over)}", f"inside {c['container']} with margin {margin}"


@spec_check
def spec_on_ground(c):
    lo, _ = require_bounds(group_of(get_object(c["object"])))
    z, tol = c.get("z", 0.0), c.get("tol", 0.005)
    return abs(lo.z - z) <= tol, rnd(lo.z), f"lowest point = {z} +-{tol}"


@spec_check
def spec_clean(c):
    issues = [i for i in check_mesh(c["object"], uv=False)["issues"] if i != "none" and not any(k in i for k in c.get("ignore", []))]
    return not issues, issues or "none", "no mesh defects"


@spec_check
def spec_budget(c):
    result = budget_of(c.get("names"), c.get("max_tris"), c.get("max_objects"), c.get("max_materials"), c.get("max_draw_calls"))
    return result["over_budget"] == ["none"], {k: result[k] for k in ("tris", "objects", "materials", "draw_calls_estimate")}, "within the limits"


@spec_check
def spec_connected(c):
    result = find_floating(c.get("names"), ground_z=c.get("ground_z"))
    return result["floating"] == ["none"], result["floating"], "no floating groups"


def spec_label(c):
    detail = [",".join(map(str, v)) if isinstance(v, list) else str(v) for k, v in c.items() if k not in {"type", "label"}]
    return c.get("label") or f"{c['type']} " + " ".join(detail)


@handler
def assert_spec(checks):
    failed, passed = [], []
    for check in checks:
        label = spec_label(check)
        try:
            if check["type"] not in SPEC_CHECKS:
                raise ValueError(f"Unknown check type {check['type']!r}. Known: {sorted(SPEC_CHECKS)}")
            ok, actual, expected = SPEC_CHECKS[check["type"]](check)
        except Exception as error:
            failed.append({"label": label, "error": str(error).strip().splitlines()[-1]})
            continue
        if ok:
            passed.append(label)
        else:
            failed.append({"label": label, "actual": actual, "expected": expected, "fix": SPEC_HINTS.get(check["type"])})
    return {"summary": f"{len(passed)}/{len(checks)} passed", "all_passed": not failed, "failed": failed, "passed": passed}


def png_size(blob):
    if blob[:8] == b"\x89PNG\r\n\x1a\n" and len(blob) >= 24:
        return struct.unpack(">II", blob[16:24])
    return None


def read_glb(path):
    data = Path(path).read_bytes()
    magic, version, length = struct.unpack("<4sII", data[:12])
    if magic != b"glTF":
        raise ValueError("Not a GLB file")
    offset, document, binary = 12, None, b""
    while offset < len(data):
        size, kind = struct.unpack("<I4s", data[offset : offset + 8])
        chunk = data[offset + 8 : offset + 8 + size]
        if kind == b"JSON":
            document = json.loads(chunk)
        elif kind == b"BIN\x00":
            binary = chunk
        offset += 8 + size
    return document, binary, len(data)


@handler
def inspect_glb(path, max_texture=2048):
    doc, binary, size = read_glb(path)
    accessors, meshes = doc.get("accessors", []), doc.get("meshes", [])
    tris = verts = 0
    warnings = []
    for mesh in meshes:
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            position = accessors[attrs["POSITION"]]["count"] if "POSITION" in attrs else 0
            verts += position
            tris += (accessors[prim["indices"]]["count"] if "indices" in prim else position) // 3
            if "NORMAL" not in attrs:
                warnings.append(f"mesh {mesh.get('name')} has no normals")
            if prim.get("material") is not None and "TEXCOORD_0" not in attrs:
                has_texture = "pbrMetallicRoughness" in doc["materials"][prim["material"]] and "baseColorTexture" in doc["materials"][prim["material"]]["pbrMetallicRoughness"]
                if has_texture:
                    warnings.append(f"mesh {mesh.get('name')} uses a texture but has no UV")
    images = []
    for image in doc.get("images", []):
        dims = None
        if "bufferView" in image:
            view = doc["bufferViews"][image["bufferView"]]
            dims = png_size(binary[view.get("byteOffset", 0) : view.get("byteOffset", 0) + 32])
        images.append({"name": image.get("name"), "size": list(dims) if dims else None})
        if dims and max(dims) > max_texture:
            warnings.append(f"texture {image.get('name')} is {dims[0]}x{dims[1]}, over {max_texture}")
        if dims and any(d & (d - 1) for d in dims):
            warnings.append(f"texture {image.get('name')} is not a power of two")
    names = [n.get("name") for n in doc.get("nodes", [])]
    duplicates = sorted({n for n in names if n and names.count(n) > 1})
    if duplicates:
        warnings.append(f"duplicate node names: {duplicates}")
    return {
        "file_bytes": size,
        "nodes": len(names),
        "meshes": len(meshes),
        "triangles": tris,
        "vertices": verts,
        "materials": len(doc.get("materials", [])),
        "images": images,
        "animations": len(doc.get("animations", [])),
        "skins": len(doc.get("skins", [])),
        "extensions_used": doc.get("extensionsUsed", []),
        "extensions_required": doc.get("extensionsRequired", []),
        "warnings": warnings or ["none"],
    }


def object_images(obj):
    found = []
    for slot in obj.material_slots:
        if slot.material and slot.material.node_tree:
            found += [n.image for n in slot.material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    return found


NEAR_SYMMETRY_SHARE = 0.1


def near_symmetry(obj, axis, depsgraph):
    """Text for a mesh that mirrors on all but a few vertices: a broken side, which a silhouette does not show."""
    cloud = points_of(obj, depsgraph)
    if not len(cloud):
        return None
    index = AXES[axis.upper()]
    lo, hi = float(cloud[:, index].min()), float(cloud[:, index].max())
    tolerance = 0.001 * cloud_size_factor(cloud)
    planes = [(lo + hi) / 2, *([0.0] if lo < 0 < hi else [])]
    (worst, unmatched), plane = min(((mirror_mismatch(cloud, index, at, tolerance), at) for at in planes), key=lambda found: len(found[0][1]))
    if not 0 < len(unmatched) < NEAR_SYMMETRY_SHARE * len(cloud):
        return None
    return (
        f"nearly symmetric about {axis.upper()} = {rnd(plane)}, but {len(unmatched)} of {len(cloud)} vertices have no mirror partner "
        f"within {rnd(tolerance, 6)} m, worst error {rnd(worst)} m near {rvec(unmatched[0][1])}"
    )


@handler
def check_game_ready(names=None, name_pattern=r"^[A-Za-z0-9_]+$", max_tris=None, max_objects=None, max_materials=None, max_draw_calls=None, max_texture=2048, require_uv=True, symmetry_axis="X", budget_only=False):
    import re

    budget = budget_of(names, max_tris, max_objects, max_materials, max_draw_calls)
    if budget_only:
        return budget
    objs = [o for o in (with_children(names) if names else scene_objects()) if o.type == "MESH"]
    errors, warnings = [], []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in objs:
        if not re.match(name_pattern, obj.name):
            errors.append({"object": obj.name, "problem": f"name does not match {name_pattern}"})
        if re.search(r"\.\d{3}$", obj.name):
            warnings.append({"object": obj.name, "problem": "name ends in a duplicate suffix (.001)"})
        if any(abs(v - 1) > 1e-4 for v in obj.scale):
            errors.append({"object": obj.name, "problem": "scale is not applied", "fix": "apply_transforms"})
        filled = [bool(s.material) for s in obj.material_slots]
        slot_of_face = np.empty(len(obj.data.polygons), dtype=np.int32)
        obj.data.polygons.foreach_get("material_index", slot_of_face)
        bare = sum(1 for i in slot_of_face if i >= len(filled) or not filled[i])
        if not any(filled):
            errors.append({"object": obj.name, "problem": "no material", "fix": "set_material"})
        elif bare:
            errors.append({"object": obj.name, "problem": f"{bare} of {len(slot_of_face)} faces have no material", "fix": "assign_material_faces"})
        if any(filled) and not all(filled):
            empty = [i for i, full in enumerate(filled) if not full]
            warnings.append({"object": obj.name, "problem": f"{len(empty)} empty material slots (index {empty})", "fix": "repair_mesh or dedupe_materials"})
        if sum(filled) > 1:
            warnings.append({"object": obj.name, "problem": f"{sum(filled)} material slots: one draw call each"})
        if symmetry_axis:
            lopsided = near_symmetry(obj, symmetry_axis, depsgraph)
            if lopsided:
                warnings.append({"object": obj.name, "problem": lopsided, "fix": "check_symmetry lists the points; rebuild one side with mirror"})
        if require_uv and not obj.data.uv_layers:
            warnings.append({"object": obj.name, "problem": "no UV map"})
        for image in object_images(obj):
            if max(image.size) > max_texture:
                errors.append({"object": obj.name, "problem": f"texture {image.name} is {image.size[0]}x{image.size[1]}, over {max_texture}"})
        report = check_mesh(obj.name, uv=False)
        for issue in report["issues"]:
            if issue == "none" or issue == "scale not applied":
                continue
            bucket = errors if any(k in issue for k in ("inward", "zero-area")) else warnings
            bucket.append({"object": obj.name, "problem": issue})
        if report["ngons"]:
            warnings.append({"object": obj.name, "problem": f"{report['ngons']} n-gons"})
    for line in budget["over_budget"]:
        if line != "none":
            errors.append({"object": "(scene)", "problem": line})
    return {
        "ready": not errors,
        "errors": errors or ["none"],
        "warnings": warnings or ["none"],
        "totals": {k: budget[k] for k in ("tris", "objects", "materials", "draw_calls_estimate")},
    }
