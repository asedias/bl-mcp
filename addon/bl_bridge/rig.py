"""Armatures, skinning and poses from numbers: create bones, bind a mesh, check weights, pose, render a pose sheet."""

import math

import bmesh
import bpy
import mathutils
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from .core import *  # noqa: F401,F403
from .core import handler


def get_armature(name):
    obj = get_object(name)
    if obj.type != "ARMATURE":
        raise ValueError(f"{name} is {obj.type}, not ARMATURE")
    return obj


def make_active(obj):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


@handler
def create_armature(name, bones):
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    make_active(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        made = {}
        for spec in bones:
            bone = data.edit_bones.new(spec["name"])
            bone.head, bone.tail = Vector(spec["head"]), Vector(spec["tail"])
            if bone.length < 1e-6:
                raise ValueError(f"Bone {spec['name']!r} has no length")
            made[spec["name"]] = bone
        for spec in bones:
            parent = spec.get("parent")
            if parent:
                if parent not in made:
                    raise ValueError(f"Bone {spec['name']!r} has the unknown parent {parent!r}")
                made[spec["name"]].parent = made[parent]
                made[spec["name"]].use_connect = bool(spec.get("connect", False))
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    return {"armature": name, "bones": [b["name"] for b in bones]}


@handler
def list_bones(armature):
    obj = get_armature(armature)
    matrix = obj.matrix_world
    return [
        {"name": b.name, "parent": b.parent.name if b.parent else None, "head": rvec(matrix @ b.head_local, 3), "tail": rvec(matrix @ b.tail_local, 3), "length": rnd(b.length, 3)}
        for b in obj.data.bones
    ]


def segment_distance(points, a, b):
    ab = b - a
    t = np.clip(((points - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
    return np.linalg.norm(points - (a + t[:, None] * ab), axis=1)


def add_groups(mesh_obj, armature_obj, weights):
    for name in {n for v in weights for n in v}:
        if name not in mesh_obj.vertex_groups:
            mesh_obj.vertex_groups.new(name=name)
    for index, influences in enumerate(weights):
        for name, weight in influences.items():
            mesh_obj.vertex_groups[name].add([index], weight, "REPLACE")


def attach(mesh_obj, armature_obj):
    for mod in [m for m in mesh_obj.modifiers if m.type == "ARMATURE"]:
        mesh_obj.modifiers.remove(mod)
    modifier = mesh_obj.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature_obj
    mesh_obj.parent = armature_obj
    mesh_obj.matrix_parent_inverse = armature_obj.matrix_world.inverted()


@handler
def bind(meshes, armature, method="proximity", max_influences=4, falloff=2.0):
    arm = get_armature(armature)
    bones = list(arm.data.bones)
    if not bones:
        raise ValueError("The armature has no bones")
    report = []
    for name in meshes:
        obj = get_object(name)
        if obj.type != "MESH":
            raise ValueError(f"{name} is {obj.type}, not MESH")
        used = method
        if method == "auto":
            make_active(arm)
            try:
                with bpy.context.temp_override(selected_editable_objects=[obj, arm], active_object=arm, object=arm, selected_objects=[obj, arm]):
                    obj.select_set(True)
                    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
                used = "auto"
            except RuntimeError:
                used = "proximity"
        if used == "proximity":
            matrix = obj.matrix_world
            points = np.array([list(matrix @ v.co) for v in obj.data.vertices])
            heads = [arm.matrix_world @ b.head_local for b in bones]
            tails = [arm.matrix_world @ b.tail_local for b in bones]
            distances = np.stack([segment_distance(points, np.array(h), np.array(t)) for h, t in zip(heads, tails)], axis=1)
            weights = []
            for row in distances:
                nearest = np.argsort(row)[:max_influences]
                raw = 1.0 / (row[nearest] + 1e-3) ** falloff
                raw /= raw.sum()
                weights.append({bones[i].name: float(w) for i, w in zip(nearest, raw) if w > 1e-3})
            add_groups(obj, arm, weights)
            attach(obj, arm)
        report.append({"mesh": name, "method": used, "groups": len(obj.vertex_groups)})
    bpy.context.view_layer.update()
    return report


@handler
def transfer_weights(target, donor, armature=None):
    dst, src = get_object(target), get_object(donor)
    if not src.vertex_groups:
        raise ValueError(f"{donor} has no vertex groups to copy")
    tree = KDTree(len(src.data.vertices))
    for i, v in enumerate(src.data.vertices):
        tree.insert(src.matrix_world @ v.co, i)
    tree.balance()
    names = {g.index: g.name for g in src.vertex_groups}
    weights = []
    for v in dst.data.vertices:
        _, index, _ = tree.find(dst.matrix_world @ v.co)
        weights.append({names[g.group]: g.weight for g in src.data.vertices[index].groups if g.group in names and g.weight > 1e-4})
    add_groups(dst, None, weights)
    arm_obj = get_armature(armature) if armature else next((m.object for m in src.modifiers if m.type == "ARMATURE"), None)
    if arm_obj is not None:
        attach(dst, arm_obj)
    bpy.context.view_layer.update()
    return {"target": target, "copied_groups": len(dst.vertex_groups), "armature": arm_obj.name if arm_obj else None}


@handler
def check_weights(mesh, max_influences=4):
    obj = get_object(mesh)
    unweighted = over = unnormalised = 0
    for v in obj.data.vertices:
        total = sum(g.weight for g in v.groups)
        if not v.groups or total < 1e-4:
            unweighted += 1
            continue
        if len(v.groups) > max_influences:
            over += 1
        if abs(total - 1.0) > 0.01:
            unnormalised += 1
    bone_names = set()
    for m in obj.modifiers:
        if m.type == "ARMATURE" and m.object:
            bone_names |= {b.name for b in m.object.data.bones}
    orphan_groups = [g.name for g in obj.vertex_groups if bone_names and g.name not in bone_names]
    problems = []
    if unweighted:
        problems.append(f"{unweighted} vertices have no weight")
    if over:
        problems.append(f"{over} vertices have more than {max_influences} influences")
    if unnormalised:
        problems.append(f"{unnormalised} vertices do not sum to 1")
    if orphan_groups:
        problems.append(f"groups without a bone: {orphan_groups}")
    if not any(m.type == "ARMATURE" for m in obj.modifiers):
        problems.append("no Armature modifier")
    return {"mesh": mesh, "vertices": len(obj.data.vertices), "groups": len(obj.vertex_groups), "problems": problems or ["none"]}


def apply_pose(arm, pose, reset):
    if reset:
        for pb in arm.pose.bones:
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = (0, 0, 0)
            pb.location = (0, 0, 0)
            pb.scale = (1, 1, 1)
    for bone, spec in (pose or {}).items():
        if bone not in arm.pose.bones:
            raise ValueError(f"No bone {bone!r}. Bones: {[b.name for b in arm.pose.bones]}")
        pb = arm.pose.bones[bone]
        pb.rotation_mode = "XYZ"
        if isinstance(spec, dict):
            if "rot" in spec:
                pb.rotation_euler = [math.radians(a) for a in spec["rot"]]
            if "loc" in spec:
                pb.location = spec["loc"]
            if "scale" in spec:
                pb.scale = spec["scale"]
        else:
            pb.rotation_euler = [math.radians(a) for a in spec]
    bpy.context.view_layer.update()


@handler
def pose(armature, pose=None, reset=True):
    arm = get_armature(armature)
    apply_pose(arm, pose, reset)
    return {"armature": armature, "posed": sorted((pose or {}).keys())}


@handler
def pose_sheet(armature, poses, meshes=None, view="front", size=256):
    arm = get_armature(armature)
    objs = with_children(meshes) if meshes else [o for o in scene_objects() if o.type == "MESH"]
    lo, hi = require_bounds(objs)
    centre = (lo + hi) / 2
    scale = float(max(hi - lo)) * 1.5
    distance = (hi - lo).length * 2 + 1
    RENDERS.mkdir(parents=True, exist_ok=True)
    tiles = []
    saved = {pb.name: (pb.rotation_mode, tuple(pb.rotation_euler), tuple(pb.location), tuple(pb.scale)) for pb in arm.pose.bones}
    try:
        with temp_scene(objs, "material") as scene:
            configure_extra_look(scene, "clay")
            for pose_name, spec in poses.items():
                apply_pose(arm, spec, True)
                tiles.append(shoot_view(scene, view, centre, scale, distance, size, RENDERS / f"pose_{pose_name}.png")[:, :, :4])
    finally:
        for pb in arm.pose.bones:
            mode, rot, loc, scl = saved[pb.name]
            pb.rotation_mode, pb.rotation_euler, pb.location, pb.scale = mode, rot, loc, scl
        bpy.context.view_layer.update()
    sheet = np.concatenate(tiles, axis=1)
    path = RENDERS / "pose_sheet.png"
    write_pixels(path, sheet)
    return {"path": str(path), "poses": list(poses), "order": "left to right", "view": view}
