"""Custom lights, post-processing through the compositor, and text as a mesh."""

import json
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from .core import *  # noqa: F401,F403
from .core import handler
from .hard import boolean_merge, remove_with_data
from .render import LIGHT_PREFIX, aim

LIGHT_KINDS = {"spot": "SPOT", "point": "POINT", "area": "AREA", "sun": "SUN"}
TEXT_FLAG = "bl_text_mesh"
POST_GROUP = "bl_post"
POST_KEY = "bl_post_state"
GLARE_TYPES = {"bloom": "Bloom", "fog_glow": "Fog Glow", "streaks": "Streaks"}
VIGNETTE_DEFAULTS = {"strength": 0.5, "softness": 0.5}
GLARE_DEFAULTS = {"type": "bloom", "threshold": 1.0, "size": 8}
COLOR_DEFAULTS = {"saturation": 1.0, "gamma": 1.0}
PLANES = {
    # plane: (rotation of the text frame, where the reader stands)
    "XY": (Matrix.Identity(3), "above (+Z)"),
    "XZ": (Matrix.Rotation(math.pi / 2, 3, "X"), "the front (-Y)"),
    "YZ": (Matrix(((0, 0, 1), (1, 0, 0), (0, 1, 0))), "the right (+X)"),
}


def light_report(obj):
    data = obj.data
    forward = obj.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    report = {
        "name": obj.name,
        "kind": data.type.lower(),
        "location": rvec(obj.matrix_world.translation, 4),
        "power": rnd(data.energy, 3),
        "color": rvec(data.color, 4),
        "preset": obj.name.startswith(LIGHT_PREFIX),
    }
    if data.type != "POINT":
        report["direction"] = rvec(forward, 4)
    if data.type == "SPOT":
        report.update(spot_size_deg=rnd(math.degrees(data.spot_size), 3), blend=rnd(data.spot_blend, 3), radius=rnd(data.shadow_soft_size, 4))
    elif data.type == "POINT":
        report["radius"] = rnd(data.shadow_soft_size, 4)
    elif data.type == "AREA":
        report["size"] = [rnd(data.size, 4), rnd(data.size_y if data.shape == "RECTANGLE" else data.size, 4)]
    else:
        report["angle_deg"] = rnd(math.degrees(data.angle), 4)
    if getattr(data, "use_temperature", False):
        report["temperature_k"] = rnd(data.temperature, 1)
    if data.use_custom_distance:
        report["cutoff_m"] = rnd(data.cutoff_distance, 3)
    return report


def first(*values):
    return next((v for v in values if v is not None), None)


def kept_settings(data):
    """The settings of an existing light, so an update keeps what the call omits."""
    if data is None:
        return {}
    kind = next((k for k, v in LIGHT_KINDS.items() if v == data.type), None)
    kept = {"kind": kind, "power_w": data.energy, "color": list(data.color), "shadow_soft": True}
    if getattr(data, "use_temperature", False):
        kept["temperature_k"] = data.temperature
    if data.use_custom_distance:
        kept["cutoff_m"] = data.cutoff_distance
    if kind == "spot":
        kept.update(spot_size_deg=math.degrees(data.spot_size), blend=data.spot_blend, radius=data.shadow_soft_size, shadow_soft=data.shadow_soft_size > 0)
    elif kind == "point":
        kept.update(radius=data.shadow_soft_size, shadow_soft=data.shadow_soft_size > 0)
    elif kind == "area":
        kept.update(size=[data.size, data.size_y])
    elif kind == "sun":
        kept["shadow_soft"] = data.angle > 0
    return kept


def light_object(name, kind):
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type != "LIGHT":
        raise ValueError(f"{name!r} is an object of type {obj.type}, not a light. Pick another name")
    if obj is not None and obj.data.type != kind:
        old = obj.data
        obj.data = bpy.data.lights.new(name, kind)
        if old.users == 0:
            bpy.data.lights.remove(old)
    if obj is None:
        obj = bpy.data.objects.new(name, bpy.data.lights.new(name, kind))
        bpy.context.scene.collection.objects.link(obj)
    obj[ADDED_LIGHT_FLAG] = True
    return obj


@handler
def add_light(kind=None, name="light", location=None, look_at=None, power_w=None, color=None, spot_size_deg=None,
              blend=None, radius=None, size=None, shadow_soft=None, temperature_k=None, cutoff_m=None):
    if name.startswith(LIGHT_PREFIX):
        raise ValueError(f"Names with the prefix {LIGHT_PREFIX!r} belong to setup_lighting and are deleted by it. Pick another name")
    existing = bpy.data.objects.get(name)
    old = existing.data if existing is not None and existing.type == "LIGHT" else None
    kept = kept_settings(old)
    kind = kind or kept.get("kind", "spot")
    if kind not in LIGHT_KINDS:
        raise ValueError(f"Unknown kind {kind!r}. Known: {sorted(LIGHT_KINDS)}")
    same_kind = kept.get("kind") == kind
    power_w = first(power_w, kept.get("power_w"), 1000.0)
    color = first(color, kept.get("color"), "#ffffff")
    spot_size_deg = first(spot_size_deg, kept.get("spot_size_deg") if same_kind else None, 45.0)
    blend = first(blend, kept.get("blend") if same_kind else None, 0.15)
    radius = first(radius, kept.get("radius") if same_kind else None, 0.05)
    size = first(size, kept.get("size") if same_kind else None)
    shadow_soft = first(shadow_soft, kept.get("shadow_soft"), True)
    temperature_k = first(temperature_k, kept.get("temperature_k"))
    cutoff_m = first(cutoff_m, kept.get("cutoff_m") if same_kind else None)
    if power_w < 0:
        raise ValueError("power_w must not be negative")
    if not 1 <= spot_size_deg <= 180:
        raise ValueError("spot_size_deg is between 1 and 180")
    if not 0 <= blend <= 1:
        raise ValueError("blend is between 0 and 1")
    if radius < 0:
        raise ValueError("radius must not be negative")
    if temperature_k is not None and not 800 <= temperature_k <= 20000:
        raise ValueError("temperature_k is between 800 and 20000")
    if cutoff_m is not None and cutoff_m <= 0:
        raise ValueError("cutoff_m must be positive")
    shape = None
    if size is not None:
        shape = [float(size), float(size)] if isinstance(size, (int, float)) else [float(v) for v in size]
        if len(shape) != 2 or min(shape) <= 0:
            raise ValueError("size is [width, height] in metres, both positive")
    if location is None and existing is None:
        location = [0, 0, 3]
    obj = light_object(name, LIGHT_KINDS[kind])
    data = obj.data
    data.color = parse_color(color)[:3] if isinstance(color, str) else list(color)[:3]
    data.energy = power_w
    if hasattr(data, "use_temperature"):
        data.use_temperature = temperature_k is not None
        if temperature_k is not None:
            data.temperature = temperature_k
    elif temperature_k is not None:
        raise ValueError("This Blender has no light temperature")
    data.use_custom_distance = cutoff_m is not None
    if cutoff_m is not None:
        data.cutoff_distance = cutoff_m
    soft = radius if shadow_soft else 0.0
    if kind == "spot":
        data.spot_size, data.spot_blend, data.shadow_soft_size = math.radians(spot_size_deg), blend, soft
    elif kind == "point":
        data.shadow_soft_size = soft
    elif kind == "area":
        w, h = shape or [1.0, 1.0]
        data.shape = "RECTANGLE" if abs(w - h) > 1e-9 else "SQUARE"
        data.size, data.size_y = w, h
    else:
        data.angle = math.radians(0.526) if shadow_soft else 0.0
    position = Vector(location) if location is not None else obj.matrix_world.translation.copy()
    if look_at is not None:
        aim(obj, position, look_at)
    else:
        obj.location = position
        if existing is None:
            obj.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
    return light_report(obj)


@handler
def list_lights():
    return [light_report(o) for o in sorted(bpy.data.objects, key=lambda o: o.name) if o.type == "LIGHT"]


def merged_setting(old, new, defaults, label):
    if new is False:
        return None
    if new is None:
        return old
    if new is True:
        new = {}
    unknown = set(new) - set(defaults)
    if unknown:
        raise ValueError(f"Unknown {label} keys {sorted(unknown)}. Known: {sorted(defaults)}")
    return {**defaults, **(old or {}), **new}


def read_post(scene):
    return json.loads(scene.get(POST_KEY, "{}"))


def check_post(state):
    vignette, glare, color = state.get("vignette"), state.get("glare"), state.get("color")
    if vignette and not (0 <= vignette["strength"] <= 1 and 0 <= vignette["softness"] <= 1):
        raise ValueError("vignette strength and softness are between 0 and 1")
    if glare:
        if glare["type"] not in GLARE_TYPES:
            raise ValueError(f"glare type is one of {sorted(GLARE_TYPES)}")
        if glare["threshold"] < 0 or not 1 <= glare["size"] <= 9:
            raise ValueError("glare threshold is 0 or more, size is 1 to 9")
    if state.get("contrast") is not None and not -1 <= state["contrast"] <= 1:
        raise ValueError("contrast is between -1 and 1")
    if color and (color["saturation"] < 0 or color["gamma"] <= 0):
        raise ValueError("saturation is 0 or more, gamma is above 0")


def post_node(tree, kind, x, y):
    node = tree.nodes.new(kind)
    node.location = (x, y)
    return node


def set_menu(socket, value):
    try:
        socket.default_value = value
    except TypeError as error:
        raise ValueError(f"Blender refused {value!r}: {error}") from error


def vignette_chain(tree, source, params, x):
    coords = post_node(tree, "CompositorNodeImageCoordinates", x, -300)
    tree.links.new(source, coords.inputs["Image"])
    centered = post_node(tree, "ShaderNodeVectorMath", x + 180, -300)
    centered.operation = "SUBTRACT"
    centered.inputs[1].default_value = (0.5, 0.5, 0)
    tree.links.new(coords.outputs["Normalized"], centered.inputs[0])
    scaled = post_node(tree, "ShaderNodeVectorMath", x + 360, -300)
    scaled.operation = "SCALE"
    scaled.inputs["Scale"].default_value = 2.0
    tree.links.new(centered.outputs["Vector"], scaled.inputs[0])
    distance = post_node(tree, "ShaderNodeVectorMath", x + 540, -300)
    distance.operation = "LENGTH"
    tree.links.new(scaled.outputs["Vector"], distance.inputs[0])
    # distance is 1 at the middle of each edge and 1.41 in the corners; full darkness is reached before the corner
    ramp = post_node(tree, "ShaderNodeMapRange", x + 720, -300)
    ramp.interpolation_type = "SMOOTHSTEP"
    ramp.clamp = True
    outer = 1.2
    inner = 1.15 - 1.0 * params["softness"] ** 0.7
    ramp.inputs["From Min"].default_value = inner
    ramp.inputs["From Max"].default_value = outer
    ramp.inputs["To Min"].default_value = 0.0
    ramp.inputs["To Max"].default_value = params["strength"]
    tree.links.new(distance.outputs["Value"], ramp.inputs["Value"])
    darken = post_node(tree, "ShaderNodeMix", x + 900, -100)
    darken.data_type = "RGBA"
    darken.blend_type = "MULTIPLY"
    darken.inputs["B"].default_value = (0, 0, 0, 1)
    tree.links.new(ramp.outputs["Result"], darken.inputs["Factor"])
    tree.links.new(source, darken.inputs["A"])
    return darken.outputs["Result"]


def build_post(scene, state):
    group = bpy.data.node_groups.get(POST_GROUP)
    if group is not None:
        bpy.data.node_groups.remove(group)
    group = bpy.data.node_groups.new(POST_GROUP, "CompositorNodeTree")
    group.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    source = post_node(group, "CompositorNodeRLayers", 0, 0)
    last, x = source.outputs["Image"], 250
    if state.get("glare"):
        glare = state["glare"]
        node = post_node(group, "CompositorNodeGlare", x, 0)
        set_menu(node.inputs["Type"], GLARE_TYPES[glare["type"]])
        node.inputs["Threshold"].default_value = glare["threshold"]
        node.inputs["Size"].default_value = glare["size"] / 9 if glare["type"] == "bloom" else glare["size"]
        group.links.new(last, node.inputs["Image"])
        last, x = node.outputs["Image"], x + 250
    if state.get("color"):
        color = state["color"]
        sat = post_node(group, "CompositorNodeHueSat", x, 0)
        sat.inputs["Saturation"].default_value = color["saturation"]
        group.links.new(last, sat.inputs["Image"])
        gamma = post_node(group, "ShaderNodeGamma", x + 250, 0)
        gamma.inputs["Gamma"].default_value = color["gamma"]
        group.links.new(sat.outputs["Image"], gamma.inputs["Color"])
        last, x = gamma.outputs["Color"], x + 500
    if state.get("contrast") is not None:
        node = post_node(group, "CompositorNodeBrightContrast", x, 0)
        node.inputs["Contrast"].default_value = state["contrast"] * 100
        group.links.new(last, node.inputs["Image"])
        last, x = node.outputs["Image"], x + 250
    if state.get("vignette"):
        last = vignette_chain(group, last, state["vignette"], x)
        x += 1100
    out = post_node(group, "NodeGroupOutput", x, 0)
    group.links.new(last, out.inputs[0])
    scene.compositing_node_group = group
    scene.render.use_compositing = True


def clear_post(scene):
    group = bpy.data.node_groups.get(POST_GROUP)
    if scene.compositing_node_group is group:
        scene.compositing_node_group = None
    if group is not None:
        bpy.data.node_groups.remove(group)


@handler
def set_post(vignette=None, glare=None, color=None, exposure=None, contrast=None, reset=False):
    scene = bpy.context.scene
    view = scene.view_settings
    state = read_post(scene)
    if reset:
        if "exposure_before" in state:
            view.exposure = state["exposure_before"]
        clear_post(scene)
        scene.pop(POST_KEY, None)
        return {"reset": True}
    foreign = scene.compositing_node_group
    if foreign is not None and foreign.name != POST_GROUP:
        raise ValueError(f"The scene already has its own compositor tree {foreign.name!r}. set_post does not replace it; clear it first")
    new = {
        "vignette": merged_setting(state.get("vignette"), vignette, VIGNETTE_DEFAULTS, "vignette"),
        "glare": merged_setting(state.get("glare"), glare, GLARE_DEFAULTS, "glare"),
        "color": merged_setting(state.get("color"), color, COLOR_DEFAULTS, "color"),
        "contrast": state.get("contrast") if contrast is None else (None if contrast is False else float(contrast)),
    }
    check_post(new)
    if exposure is not None:
        state.setdefault("exposure_before", view.exposure)
        view.exposure = float(exposure)
    state.update({k: v for k, v in new.items() if v is not None})
    for key in ("vignette", "glare", "color", "contrast"):
        if new[key] is None:
            state.pop(key, None)
    if any(v is not None for v in new.values()):
        build_post(scene, new)
    else:
        clear_post(scene)
    scene[POST_KEY] = json.dumps(state)
    return {
        "vignette": new["vignette"],
        "glare": new["glare"],
        "color": new["color"],
        "contrast": new["contrast"],
        "exposure_stops": rnd(view.exposure, 3),
        "compositor": any(v is not None for v in new.values()),
    }


def text_curve(body, font, extrude, bevel, align):
    curve = bpy.data.curves.new("bl_text_tmp", "FONT")
    curve.body = body
    curve.size = 1.0
    curve.extrude = extrude
    curve.bevel_depth = bevel
    curve.bevel_resolution = 2 if bevel else 0
    curve.align_x = align
    curve.align_y = "CENTER"
    if font is not None:
        curve.font = font
    return curve


def mesh_of_curve(curve):
    holder = bpy.data.objects.new("bl_text_tmp", curve)
    bpy.context.scene.collection.objects.link(holder)
    try:
        bpy.context.view_layer.update()
        mesh = bpy.data.meshes.new_from_object(holder.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    finally:
        bpy.data.objects.remove(holder)
        bpy.data.curves.remove(curve)
    return mesh


def load_font(path):
    if path is None:
        return None
    try:
        return bpy.data.fonts.load(str(Path(path).expanduser()), check_existing=True)
    except RuntimeError as error:
        raise ValueError(f"Cannot load the font {path!r}: {error}") from error


def cap_height(font):
    mesh = mesh_of_curve(text_curve("H", font, 0.0, 0.0, "CENTER"))
    co = np.array([v.co[:] for v in mesh.vertices])
    bpy.data.meshes.remove(mesh)
    return float(co[:, 1].max() - co[:, 1].min())


def build_text_mesh(body, size, depth, font, align, bevel):
    scale = size / cap_height(font)
    mesh = mesh_of_curve(text_curve(body, font, depth / 2 / scale, bevel / scale, align.upper()))
    if not len(mesh.vertices):
        bpy.data.meshes.remove(mesh)
        raise ValueError("The text has no outlines: the font has none of these characters (spaces only, or missing glyphs)")
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3) * scale
    lo, hi = co.min(axis=0), co.max(axis=0)
    # the back face rests on the plane; the front looks at the reader
    shift = np.array([-(lo[0] + hi[0]) / 2 if align == "center" else (-lo[0] if align == "left" else -hi[0]), -(lo[1] + hi[1]) / 2, -lo[2]])
    mesh.vertices.foreach_set("co", (co + shift).ravel())
    mesh.update()
    merge_doubles(mesh)
    return mesh


def merge_doubles(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()


def surface_hit(target, point, normal):
    box = require_bounds([target])
    reach = (box[1] - box[0]).length + (point - (box[0] + box[1]) / 2).length + 1.0
    inverse = target.matrix_world.inverted()
    start = inverse @ (point + normal * reach)
    direction = (inverse.to_3x3() @ (-normal)).normalized()
    ok, location, face_normal, _ = target.ray_cast(start, direction, distance=reach * 2)
    if not ok:
        raise ValueError(f"No surface of {target.name!r} lies on the line through `at` along the plane normal")
    world_normal = (target.matrix_world.to_3x3().inverted().transposed() @ face_normal).normalized()
    return target.matrix_world @ location, world_normal


def volume_of(obj):
    with evaluated_mesh(obj) as (_, mesh):
        bm = bmesh.new()
        bm.from_mesh(mesh)
        volume = abs(bm.calc_volume(signed=True))
        faces = len(bm.faces)
        bm.free()
    return volume, faces


@handler
def text_mesh(text, size=0.1, depth=0.01, at=None, plane="XZ", font=None, align="center", bevel=0.0, name="text",
              on_object=None, offset=0.0005, engrave=False):
    if not text or not text.strip():
        raise ValueError("text is empty")
    if plane not in PLANES:
        raise ValueError(f"Unknown plane {plane!r}. Known: {sorted(PLANES)}")
    if align not in ("center", "left", "right"):
        raise ValueError("align is center, left or right")
    if size <= 0 or depth <= 0:
        raise ValueError("size and depth must be positive")
    if bevel < 0 or bevel > depth / 2:
        raise ValueError("bevel is between 0 and depth/2")
    if engrave and on_object is None:
        raise ValueError("engrave needs on_object")
    target = get_object(on_object) if on_object is not None else None
    if target is not None and target.type != "MESH":
        raise ValueError(f"{on_object!r} is {target.type}, not a mesh")
    old = bpy.data.objects.get(name)
    if old is not None and not old.get(TEXT_FLAG):
        raise ValueError(f"{name!r} is taken by an object that is not a text_mesh result. Pick another name")
    frame, reader = PLANES[plane]
    normal = (frame @ Vector((0, 0, 1))).normalized()
    anchor = Vector(at if at is not None else (0, 0, 0))
    hit = None
    if target is not None:
        point, surface_normal = surface_hit(target, anchor, normal)
        hit = {"point": rvec(point, 5), "surface_normal": rvec(surface_normal, 4), "plane_normal": rvec(normal, 4)}
        anchor = point
    font_data = load_font(font)
    if engrave:
        cut = depth + max(0.001, depth * 0.5)
        mesh = build_text_mesh(text, size, cut, font_data, align, 0.0)
        origin = anchor - normal * depth
    else:
        mesh = build_text_mesh(text, size, depth, font_data, align, bevel)
        origin = anchor + normal * (offset if target is not None else 0.0)
    if old is not None:
        old_mesh = old.data
        bpy.data.objects.remove(old)
        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    mesh.name = name
    obj = bpy.data.objects.new(name, mesh)
    obj.matrix_world = Matrix.Translation(origin) @ frame.to_4x4()
    bpy.context.scene.collection.objects.link(obj)
    obj[TEXT_FLAG] = True
    bpy.context.view_layer.update()
    if not engrave:
        report = describe(obj)
        report.update(plane=plane, reader_stands=reader, text_size=size, depth=depth)
        if hit:
            report["surface"] = hit
        return report
    before, faces_before = volume_of(target)
    try:
        cut = boolean_merge(target, obj, "DIFFERENCE")
    except ValueError as error:
        advice = "Make the text without `engrave`, then cut it with boolean, where allow_open exists."
        raise ValueError(str(error).replace("or pass allow_open=true.", advice).replace("or pass allow_open=true to keep this result.", advice)) from None
    finally:
        remove_with_data(obj)
    after, faces_after = volume_of(target)
    return {
        **cut,
        "engraved": target.name,
        "volume_before": rnd(before, 9),
        "volume_after": rnd(after, 9),
        "removed_volume": rnd(before - after, 9),
        "faces_before": faces_before,
        "faces_after": faces_after,
        "depth": depth,
        "surface": hit,
    }
