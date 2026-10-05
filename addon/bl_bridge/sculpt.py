"""Numeric sculpting: brushes with an explicit place, radius, falloff and amount, plus deformers."""

import math

import bmesh
import bpy
import mathutils
import numpy as np
from mathutils import Vector

from .core import *  # noqa: F401,F403
from .core import handler
from .meshops import FALLOFFS, commit, edit_bmesh, region_of, region_weights, summary


def brush_weights(bm, obj, at, radius, falloff, where, mode, spread):
    """Weights per vertex index: a sphere brush at `at`, or the picked region with a falloff of `spread` metres."""
    if at is not None:
        if radius is None or radius <= 0:
            raise ValueError("Give a positive radius with `at`")
        if falloff not in FALLOFFS:
            raise ValueError(f"falloff is one of {sorted(FALLOFFS)}")
        matrix = obj.matrix_world
        centre = Vector(at)
        weights = {}
        for v in bm.verts:
            dist = (matrix @ v.co - centre).length
            if dist < radius:
                weights[v.index] = FALLOFFS[falloff](1 - dist / radius)
        if not weights:
            raise ValueError("No vertices inside the brush: check `at` and `radius`")
        return weights
    selected = region_of(bm, obj, where, mode)
    return region_weights(bm, obj, selected, spread, falloff)


def vertex_normal_world(v, normal_matrix):
    return (normal_matrix @ v.normal).normalized()


def grab(bm, obj, weights, move=None, **_):
    if move is None:
        raise ValueError("grab needs `move` [x, y, z] in metres")
    matrix, inverse = obj.matrix_world, obj.matrix_world.inverted_safe()
    shift = Vector(move)
    for v in bm.verts:
        if v.index in weights:
            v.co = inverse @ (matrix @ v.co + shift * weights[v.index])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return {}


def inflate(bm, obj, weights, amount=None, **_):
    if amount is None:
        raise ValueError("inflate needs `amount` in metres")
    matrix, inverse = obj.matrix_world, obj.matrix_world.inverted_safe()
    normal_matrix = matrix.to_3x3().inverted_safe().transposed()
    bm.normal_update()
    for v in bm.verts:
        if v.index in weights:
            v.co = inverse @ (matrix @ v.co + vertex_normal_world(v, normal_matrix) * amount * weights[v.index])
    return {}


def smooth(bm, obj, weights, iterations=2, factor=0.5, keep_boundary=True, **_):
    for _ in range(iterations):
        targets = {}
        for v in bm.verts:
            w = weights.get(v.index)
            if not w or (keep_boundary and any(len(e.link_faces) < 2 for e in v.link_edges)) or not v.link_edges:
                continue
            average = sum((e.other_vert(v).co for e in v.link_edges), Vector()) / len(v.link_edges)
            targets[v.index] = v.co.lerp(average, factor * w)
        for index, co in targets.items():
            bm.verts[index].co = co
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return {}


def flatten(bm, obj, weights, strength=None, **_):
    strength = 1.0 if strength is None else strength
    matrix, inverse = obj.matrix_world, obj.matrix_world.inverted_safe()
    normal_matrix = matrix.to_3x3().inverted_safe().transposed()
    bm.normal_update()
    members = [bm.verts[i] for i in weights]
    centre = sum((matrix @ v.co for v in members), Vector()) / len(members)
    normal = sum((vertex_normal_world(v, normal_matrix) * weights[v.index] for v in members), Vector()).normalized()
    for v in members:
        world = matrix @ v.co
        flat = world - normal * (world - centre).dot(normal)
        v.co = inverse @ world.lerp(flat, min(1.0, strength * weights[v.index]))
    return {"plane_normal": rvec(normal, 3)}


def pinch(bm, obj, weights, strength=None, at=None, **_):
    strength = 0.5 if strength is None else strength
    matrix, inverse = obj.matrix_world, obj.matrix_world.inverted_safe()
    normal_matrix = matrix.to_3x3().inverted_safe().transposed()
    bm.normal_update()
    members = [bm.verts[i] for i in weights]
    centre = Vector(at) if at is not None else sum((matrix @ v.co for v in members), Vector()) / len(members)
    normal = sum((vertex_normal_world(v, normal_matrix) for v in members), Vector()).normalized()
    for v in members:
        world = matrix @ v.co
        offset = world - centre
        flat = offset - normal * offset.dot(normal)
        v.co = inverse @ (world - flat * min(1.0, strength * weights[v.index]))
    return {}


SCULPT_OPS = {"grab": grab, "inflate": inflate, "smooth": smooth, "flatten": flatten, "pinch": pinch}


@handler
def sculpt(object, op, at=None, radius=None, where=None, mode="faces", spread=0.0, falloff="smooth", move=None, amount=None,
           strength=None, iterations=2, factor=0.5, keep_boundary=True):
    if op not in SCULPT_OPS:
        raise ValueError(f"op is one of {sorted(SCULPT_OPS)}")
    obj = get_object(object)
    bm = edit_bmesh(obj)
    if op == "smooth" and at is None and where is None:
        weights = {v.index: 1.0 for v in bm.verts}
    else:
        weights = brush_weights(bm, obj, at, radius, falloff, where, mode, spread)
    extra = SCULPT_OPS[op](bm, obj, weights, move=move, amount=amount, strength=strength, at=at, iterations=iterations,
                           factor=factor, keep_boundary=keep_boundary)
    commit(bm, obj)
    return summary(obj, op=op, vertices_moved=len(weights), **extra)


@handler
def deform(object, kind, amount, axis="Z", origin=None, limits=(0.0, 1.0), lock_x=False, lock_y=False):
    kinds = {"bend": "BEND", "twist": "TWIST", "taper": "TAPER", "stretch": "STRETCH"}
    if kind not in kinds:
        raise ValueError(f"kind is one of {sorted(kinds)}")
    obj = get_object(object)
    modifier = obj.modifiers.new("deform", "SIMPLE_DEFORM")
    modifier.deform_method = kinds[kind]
    modifier.deform_axis = axis.upper()
    if kind in ("bend", "twist"):
        modifier.angle = math.radians(amount)
    else:
        modifier.factor = amount
    modifier.limits = tuple(limits)
    modifier.lock_x, modifier.lock_y = lock_x, lock_y
    empty = None
    if origin is not None:
        empty = bpy.data.objects.new("bl_origin", None)
        bpy.context.collection.objects.link(empty)
        empty.location = origin
        modifier.origin = empty
    try:
        bake_modifiers(obj)
    finally:
        if empty is not None:
            bpy.data.objects.remove(empty)
    bpy.context.view_layer.update()
    return summary(obj, deform=f"{kind} {amount} about {axis.upper()}")


@handler
def shrinkwrap(object, target, method="nearest_surface", offset=0.0, axis=None, direction="both"):
    methods = {"nearest_surface": "NEAREST_SURFACEPOINT", "project": "PROJECT", "nearest_vertex": "NEAREST_VERTEX"}
    if method not in methods:
        raise ValueError(f"method is one of {sorted(methods)}")
    obj = get_object(object)
    modifier = obj.modifiers.new("wrap", "SHRINKWRAP")
    modifier.target = get_object(target)
    modifier.wrap_method = methods[method]
    modifier.offset = offset
    if method == "project":
        modifier.use_project_x = axis in ("X", "x")
        modifier.use_project_y = axis in ("Y", "y")
        modifier.use_project_z = axis in ("Z", "z", None)
        modifier.use_negative_direction = direction in ("both", "negative")
        modifier.use_positive_direction = direction in ("both", "positive")
    bake_modifiers(obj)
    bpy.context.view_layer.update()
    return summary(obj, wrapped_on=target)


@handler
def remesh(object, voxel_size=0.05, smooth_shading=True):
    obj = get_object(object)
    lo, hi = require_bounds([obj])
    if min(hi - lo) < voxel_size:
        raise ValueError("Remesh needs a solid with thickness: the thinnest side is below one voxel. Use solidify first or a smaller voxel_size.")
    modifier = obj.modifiers.new("remesh", "REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = voxel_size
    bake_modifiers(obj)
    for polygon in obj.data.polygons:
        polygon.use_smooth = smooth_shading
    bpy.context.view_layer.update()
    return summary(obj, voxel_size=voxel_size)


@handler
def blob(name, points, radii, resolution=0.05, threshold=0.6):
    if len(points) != len(radii):
        raise ValueError("Give one radius per point")
    ball = bpy.data.metaballs.new(name)
    ball.resolution = resolution
    ball.threshold = threshold
    for point, radius in zip(points, radii):
        element = ball.elements.new()
        element.co = Vector(point)
        element.radius = radius
    holder = bpy.data.objects.new(name + "_meta", ball)
    bpy.context.collection.objects.link(holder)
    bpy.context.view_layer.update()
    mesh = bpy.data.meshes.new_from_object(holder.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(holder)
    bpy.data.metaballs.remove(ball)
    if not len(mesh.vertices):
        raise ValueError("The blob is empty: raise the radii or lower `threshold`")
    result = new_mesh_object(name, mesh)
    for polygon in result.data.polygons:
        polygon.use_smooth = True
    return summary(result, points=len(points))
