"""UV maps and flat colour painting for stylised, palette-textured games."""

import math

import bpy

from .core import *  # noqa: F401,F403
from .core import handler
from .meshops import commit, edit_bmesh, need, pick_faces, summary


def in_edit_mode(obj, action):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        bpy.ops.mesh.select_all(action="SELECT")
        action()
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")


@handler
def unwrap(names, method="smart", angle=66.0, margin=0.02, pack=True):
    methods = {
        "smart": lambda: bpy.ops.uv.smart_project(angle_limit=math.radians(angle), island_margin=margin),
        "angle": lambda: bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=margin),
        "conformal": lambda: bpy.ops.uv.unwrap(method="CONFORMAL", margin=margin),
        "cube": lambda: bpy.ops.uv.cube_project(),
        "cylinder": lambda: bpy.ops.uv.cylinder_project(),
        "sphere": lambda: bpy.ops.uv.sphere_project(),
    }
    if method not in methods:
        raise ValueError(f"method is one of {sorted(methods)}")
    report = []
    for name in names:
        obj = get_object(name)
        if obj.type != "MESH":
            raise ValueError(f"{name} is {obj.type}, not MESH")

        def run():
            methods[method]()
            if pack:
                bpy.ops.uv.pack_islands(margin=margin)

        in_edit_mode(obj, run)
        report.append({"object": name, **uv_report(obj)})
    return report


@handler
def paint_faces(object, color, where=None, attribute="Color"):
    from .core import parse_color

    obj = get_object(object)
    bm = edit_bmesh(obj)
    faces = need(pick_faces(bm, obj, where), "faces")
    layer = bm.loops.layers.float_color.get(attribute) or bm.loops.layers.float_color.new(attribute)
    rgb = parse_color(color)
    for face in faces:
        for loop in face.loops:
            loop[layer] = (*rgb, 1.0)
    commit(bm, obj)
    return summary(obj, painted=len(faces), attribute=attribute)


@handler
def palette_uv(object, cell, grid=(4, 4), where=None, uv_layer="UVMap"):
    obj = get_object(object)
    bm = edit_bmesh(obj)
    faces = need(pick_faces(bm, obj, where), "faces")
    layer = bm.loops.layers.uv.get(uv_layer) or bm.loops.layers.uv.new(uv_layer)
    columns, rows = grid
    u = (cell[0] + 0.5) / columns
    v = 1.0 - (cell[1] + 0.5) / rows
    for face in faces:
        for loop in face.loops:
            loop[layer].uv = (u, v)
    commit(bm, obj)
    return summary(obj, faces_set=len(faces), uv=[round(u, 4), round(v, 4)], note="row 0 is the top row of the palette image")
