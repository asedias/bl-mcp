"""Procedural material presets and baking of their nodes into image maps that glTF can carry."""

import contextlib
import math

import bpy
import numpy as np

from .core import *  # noqa: F401,F403
from .core import handler, parse_color
from .materials import build_surface
from .render import render_state, restore_state

BAKE_PASS = {"base_color": "DIFFUSE", "normal": "NORMAL", "roughness": "ROUGHNESS", "ao": "AO"}
# Cycles has no bake pass for metallic, and the diffuse pass of a metal is black: these inputs are baked as emission
EMIT_INPUT = {"base_color": "Base Color", "roughness": "Roughness", "metallic": "Metallic"}
ORM_PARTS = ("ao", "roughness", "metallic")
MAP_NAMES = (*EMIT_INPUT, "normal", "ao", "orm")
# kind: (color_a, color_b, roughness)
LOOK = {"worn_metal": ("#8e9094", "#0d0c0b", 0.3)}
DEFAULT_LOOK = ("#8a5a3a", "#3a2414", 0.6)


class Builder:
    """Adds nodes by type and wires them by socket name, so localized UI names never matter."""

    def __init__(self, mat):
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.used = []
        self.x = -1400
        self.size = 1.0

    def node(self, idname, label=None, **props):
        n = self.nt.nodes.new(idname)
        for key, value in props.items():
            setattr(n, key, value)
        n.location = (self.x, 0)
        self.x += 40
        self.used.append(label or n.bl_idname.replace("ShaderNode", ""))
        return n

    def link(self, src, dst, dst_name=None):
        out = src if not hasattr(src, "outputs") else src.outputs[0]
        socket = dst if not hasattr(dst, "inputs") else dst.inputs[dst_name]
        self.nt.links.new(out, socket)

    def math(self, op, a, b=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                self.nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    def ramp(self, fac, stops):
        n = self.node("ShaderNodeValToRGB")
        elements = n.color_ramp.elements
        while len(elements) < len(stops):
            elements.new(0.5)
        for el, (pos, value) in zip(elements, stops):
            el.position = pos
            el.color = (value, value, value, 1.0)
        self.nt.links.new(fac, n.inputs["Fac"])
        return n.outputs["Color"]

    def mix_colors(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="RGBA")
        by_id = {s.identifier: s for s in n.inputs}
        self.nt.links.new(fac, by_id["Factor_Float"])
        for ident, value in (("A_Color", a), ("B_Color", b)):
            if isinstance(value, (list, tuple)):
                by_id[ident].default_value = (*value, 1.0)
            else:
                self.nt.links.new(value, by_id[ident])
        return next(s for s in n.outputs if s.identifier == "Result_Color")


def coordinates(b, scale, seed, rotation=0.0, stretch=(1.0, 1.0, 1.0), space="UV"):
    """UV coordinates (stable under object scaling) through a Mapping node; the seed shifts the pattern in all three axes."""
    uv = b.node("ShaderNodeTexCoord")
    mp = b.node("ShaderNodeMapping")
    mp.inputs["Location"].default_value = (seed * 7.31, seed * 3.17, seed * 5.53)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, rotation)
    mp.inputs["Scale"].default_value = tuple(scale * s for s in stretch)
    b.nt.links.new(uv.outputs[space], mp.inputs["Vector"])
    return mp.outputs["Vector"]


def tex(b, idname, vector, **inputs):
    props = {k: inputs.pop(k) for k in list(inputs) if k.startswith("_")}
    n = b.node(idname, **{k[1:]: v for k, v in props.items()})
    b.nt.links.new(vector, n.inputs["Vector"])
    for name, value in inputs.items():
        n.inputs[name].default_value = value
    return n


def bump_into(b, bsdf, height, strength, distance=0.02):
    n = b.node("ShaderNodeBump")
    n.inputs["Strength"].default_value = strength
    n.inputs["Distance"].default_value = distance
    b.nt.links.new(height, n.inputs["Height"])
    b.nt.links.new(n.outputs["Normal"], bsdf.inputs["Normal"])
    return n


def build_wood(b, bsdf, a, c, scale, seed, p):
    """Rings from a distorted wave, fibres from noise stretched along the grain, knots from Voronoi cells."""
    stretch = p.get("grain_stretch", 6.0)
    rings_v = coordinates(b, scale, seed, stretch=(1.0, 1.0, 1.0))
    rings = tex(b, "ShaderNodeTexWave", rings_v, _wave_type="RINGS", _rings_direction="Z", _wave_profile="SAW",
                Scale=3.0, Distortion=p.get("distortion", 5.0), Detail=2.0, **{"Detail Scale": 1.5})
    fibre_v = coordinates(b, scale * 3.0, seed + 1, stretch=(1.0, stretch, 1.0))
    fibres = tex(b, "ShaderNodeTexNoise", fibre_v, Scale=14.0, Detail=4.0, Roughness=0.6)
    grain = b.math("ADD", b.math("MULTIPLY", rings.outputs["Fac"], 0.65), b.math("MULTIPLY", fibres.outputs["Fac"], 0.35))
    if p.get("knots", True):
        knot_v = coordinates(b, scale * 0.8, seed + 2)
        cells = tex(b, "ShaderNodeTexVoronoi", knot_v, Scale=1.6, Randomness=1.0)
        knot = b.ramp(cells.outputs["Distance"], [(0.0, 1.0), (0.22, 0.0)])
        grain = b.math("MAXIMUM", grain, knot)
        knot_rings = b.math("MULTIPLY", b.math("SINE", b.math("MULTIPLY", cells.outputs["Distance"], 90.0)), 0.5)
        grain = b.math("ADD", grain, b.math("MULTIPLY", knot_rings, b.math("SUBTRACT", 1.0, b.ramp(cells.outputs["Distance"], [(0.0, 0.0), (0.3, 1.0)]))), clamp=True)
    shade = b.ramp(grain, [(0.15, 0.0), (0.85, 1.0)])
    b.link(b.mix_colors(shade, a, c), bsdf.inputs["Base Color"])
    bump_into(b, bsdf, fibres.outputs["Fac"], p.get("bump_strength", 0.25))


def build_checker(b, bsdf, a, c, scale, seed, p):
    v = coordinates(b, scale * 8.0, seed)
    n = tex(b, "ShaderNodeTexChecker", v, Scale=1.0)
    n.inputs["Color1"].default_value = (*a, 1.0)
    n.inputs["Color2"].default_value = (*c, 1.0)
    b.link(n.outputs["Color"], bsdf.inputs["Base Color"])
    if p.get("bump_strength"):
        bump_into(b, bsdf, n.outputs["Fac"], p["bump_strength"])


def build_diamond(b, bsdf, a, c, scale, seed, p):
    """Knurling: two triangle-wave band sets crossed at +-45 degrees; their product is a field of pyramids."""
    height = None
    for angle in (math.radians(45), math.radians(-45)):
        v = coordinates(b, scale * 6.0, seed, rotation=angle)
        w = tex(b, "ShaderNodeTexWave", v, _wave_type="BANDS", _bands_direction="X", _wave_profile="TRI", Scale=1.0, Distortion=0.0)
        height = w.outputs["Fac"] if height is None else b.math("MULTIPLY", height, w.outputs["Fac"])
    b.link(b.mix_colors(b.ramp(height, [(0.0, 1.0), (0.6, 0.0)]), a, c), bsdf.inputs["Base Color"])
    bump_into(b, bsdf, height, p.get("bump_strength", 1.0), distance=0.01)


def build_bricks(b, bsdf, a, c, scale, seed, p):
    v = coordinates(b, scale * 2.0, seed)
    n = tex(b, "ShaderNodeTexBrick", v, Scale=1.0, **{"Mortar Size": p.get("mortar", 0.03), "Mortar Smooth": 0.1, "Bias": 0.0})
    n.inputs["Color1"].default_value = (*a, 1.0)
    n.inputs["Color2"].default_value = (*c, 1.0)
    n.inputs["Mortar"].default_value = (0.55, 0.55, 0.52, 1.0)
    b.link(n.outputs["Color"], bsdf.inputs["Base Color"])
    bump_into(b, bsdf, n.outputs["Fac"], p.get("bump_strength", 0.5))


def build_noise(b, bsdf, a, c, scale, seed, p):
    v = coordinates(b, scale * 4.0, seed)
    n = tex(b, "ShaderNodeTexNoise", v, Scale=p.get("detail_scale", 3.0), Detail=6.0, Roughness=0.55)
    b.link(b.mix_colors(b.ramp(n.outputs["Fac"], [(0.3, 0.0), (0.7, 1.0)]), a, c), bsdf.inputs["Base Color"])
    bump_into(b, bsdf, n.outputs["Fac"], p.get("bump_strength", 0.2))


def build_marble(b, bsdf, a, c, scale, seed, p):
    v = coordinates(b, scale * 1.5, seed, rotation=math.radians(30))
    w = tex(b, "ShaderNodeTexWave", v, _wave_type="BANDS", _bands_direction="X", _wave_profile="SIN",
            Scale=2.0, Distortion=p.get("distortion", 12.0), Detail=5.0, **{"Detail Scale": 1.2, "Detail Roughness": 0.7})
    veins = b.ramp(w.outputs["Fac"], [(0.35, 0.0), (0.5, 1.0), (0.65, 0.0)])
    b.link(b.mix_colors(veins, a, c), bsdf.inputs["Base Color"])
    if p.get("bump_strength"):
        bump_into(b, bsdf, w.outputs["Fac"], p["bump_strength"])


def object_noise(b, cycles, seed, detail, stretch=(1.0, 1.0, 1.0)):
    """Noise in object space: no seams between UV islands. `cycles` counts across the object, whatever its size."""
    v = coordinates(b, cycles / b.size, seed, stretch=stretch, space="Object")
    return tex(b, "ShaderNodeTexNoise", v, Scale=1.0, Detail=detail).outputs["Fac"]


def build_worn_metal(b, bsdf, a, c, scale, seed, p):
    """Dirt gathers where the AO node finds a cavity; bare metal shows where a wide Bevel normal leaves the face normal."""
    dirt, edge_wear, scratches = p.get("dirt", 0.6), p.get("edge_wear", 0.5), p.get("scratches", 0.3)
    patches = object_noise(b, 15.0 * scale, seed, 4.0)
    fine = object_noise(b, 190.0 * scale, seed + 1, 2.0)
    ao = b.node("ShaderNodeAmbientOcclusion", samples=12)
    ao.inputs["Distance"].default_value = p.get("ao_distance", 0.015 * b.size)
    cavity = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, ao.outputs["AO"], clamp=True), 1.8, clamp=True)
    grime = b.math("MULTIPLY", b.math("MULTIPLY", cavity, b.math("ADD", 0.55, b.math("MULTIPLY", fine, 0.45))), dirt, clamp=True)
    wide = b.node("ShaderNodeBevel", samples=8)
    wide.inputs["Radius"].default_value = p.get("wear_width", 0.005 * b.size)
    face = b.node("ShaderNodeNewGeometry")
    turn = b.node("ShaderNodeVectorMath", operation="DOT_PRODUCT")
    b.nt.links.new(wide.outputs["Normal"], turn.inputs[0])
    b.nt.links.new(face.outputs["True Normal"], turn.inputs[1])
    sharp = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, turn.outputs["Value"], clamp=True), 9.0, clamp=True)
    edge = b.math("MULTIPLY", b.math("MULTIPLY", sharp, b.math("ADD", 0.35, b.math("MULTIPLY", patches, 0.9)), clamp=True), edge_wear)
    lines = object_noise(b, 480.0 * scale, seed + 2, 1.0, stretch=(1.0, 0.005, 1.0))
    scratch = b.math("MULTIPLY", b.math("MULTIPLY", b.math("SUBTRACT", lines, 0.66, clamp=True), 9.0, clamp=True), b.math("MULTIPLY", patches, scratches))
    bare = [min(1.0, v * 1.5 + 0.05) for v in a]
    color = b.mix_colors(b.math("MULTIPLY", grime, 0.85), a, c)
    color = b.mix_colors(b.math("MULTIPLY", edge, 0.6), color, bare)
    b.link(b.mix_colors(b.math("MULTIPLY", scratch, 0.5), color, bare), bsdf.inputs["Base Color"])
    rough = b.math("ADD", bsdf.inputs["Roughness"].default_value, b.math("MULTIPLY", grime, 0.38))
    rough = b.math("ADD", rough, b.math("MULTIPLY", b.math("SUBTRACT", patches, 0.5), 0.16))
    rough = b.math("SUBTRACT", rough, b.math("MULTIPLY", edge, 0.2))
    b.link(b.math("ADD", rough, b.math("MULTIPLY", scratch, 0.3), clamp=True), bsdf.inputs["Roughness"])
    b.link(b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.math("MULTIPLY", grime, 0.5), clamp=True), p.get("metallic", 1.0)), bsdf.inputs["Metallic"])
    rounded = b.node("ShaderNodeBevel", samples=12)
    rounded.inputs["Radius"].default_value = p.get("bevel_radius", 0.002 * b.size)
    bump = bump_into(b, bsdf, b.math("SUBTRACT", 1.0, scratch), p.get("bump_strength", 0.3), distance=0.0002 * b.size)
    b.nt.links.new(rounded.outputs["Normal"], bump.inputs["Normal"])


BUILDERS = {"wood": build_wood, "checker": build_checker, "diamond": build_diamond, "bricks": build_bricks,
            "noise": build_noise, "marble": build_marble, "worn_metal": build_worn_metal}


def ensure_uv(obj, layer=None):
    """Returns True when it had to unwrap. Smart project is the fallback: it needs no seams and works on any mesh."""
    if obj.type != "MESH":
        raise ValueError(f"{obj.name} is {obj.type}, not MESH")
    if layer is not None:
        if layer not in obj.data.uv_layers:
            raise ValueError(f"{obj.name} has no UV layer {layer!r}; it has {[u.name for u in obj.data.uv_layers]}")
        obj.data.uv_layers.active = obj.data.uv_layers[layer]
        return False
    if obj.data.uv_layers:
        return False
    HANDLERS["unwrap"](names=[obj.name], method="smart")
    return True


@handler
def procedural_material(names, kind, color_a=None, color_b=None, scale=1.0, roughness=None, material=None, seed=0, params=None):
    if kind not in BUILDERS:
        raise ValueError(f"kind is one of {sorted(BUILDERS)}")
    color_a, color_b, roughness = (d if v is None else v for v, d in zip((color_a, color_b, roughness), LOOK.get(kind, DEFAULT_LOOK)))
    if scale <= 0:
        raise ValueError("scale must be above 0")
    params = dict(params or {})
    objects = [get_object(n) for n in names]
    unwrapped = [o.name for o in objects if ensure_uv(o)]
    label = material or f"proc_{kind}_{str(color_a).lstrip('#')}_{str(color_b).lstrip('#')}_s{scale:g}_{seed}"
    mat = bpy.data.materials.get(label) or bpy.data.materials.new(label)
    if not mat.use_nodes:
        mat.use_nodes = True
    builder = Builder(mat)
    low, high = require_bounds(objects)
    builder.size = max((high - low).length, 1e-6)
    bsdf = builder.node("ShaderNodeBsdfPrincipled")
    out = builder.node("ShaderNodeOutputMaterial")
    builder.link(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = roughness
    BUILDERS[kind](builder, bsdf, parse_color(color_a), parse_color(color_b), scale, seed, params)
    for obj in objects:
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
    return {"material": mat.name, "kind": kind, "nodes": builder.used, "objects": names, "unwrapped": unwrapped}


def new_image(name, size, data):
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, size, size, alpha=False)
    img.colorspace_settings.name = "Non-Color" if data else "sRGB"
    return img


def materials_of(obj):
    return list({m for m in obj.data.materials if m and m.node_tree})


def principled_or_none(mat):
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


@contextlib.contextmanager
def bake_targets(obj, img):
    added = []
    for mat in materials_of(obj):
        nt = mat.node_tree
        for n in nt.nodes:
            n.select = False
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.select = True
        nt.nodes.active = node
        added.append((nt, node))
    try:
        yield
    finally:
        for nt, node in added:
            nt.nodes.remove(node)


@contextlib.contextmanager
def emission_of(obj, input_name):
    """Shows one Principled input as plain emission, so an EMIT bake writes exactly that input."""
    undo = []
    for mat in materials_of(obj):
        nt = mat.node_tree
        source = principled_or_none(mat).inputs[input_name]
        output = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output)
        surface = output.inputs["Surface"]
        before = surface.links[0].from_socket if surface.is_linked else None
        emit = nt.nodes.new("ShaderNodeEmission")
        if source.is_linked:
            nt.links.new(source.links[0].from_socket, emit.inputs["Color"])
        else:
            value = source.default_value
            emit.inputs["Color"].default_value = tuple(value) if source.type == "RGBA" else (value, value, value, 1.0)
        nt.links.new(emit.outputs["Emission"], surface)
        undo.append((nt, emit, surface, before))
    try:
        yield
    finally:
        for nt, emit, surface, before in undo:
            nt.nodes.remove(emit)
            if before is not None:
                nt.links.new(before, surface)


def normal_chain_start(bsdf):
    sock = bsdf.inputs["Normal"]
    while sock.is_linked and sock.links[0].from_node.type == "BUMP":
        sock = sock.links[0].from_node.inputs["Normal"]
    return sock


@contextlib.contextmanager
def rounded_edges(obj, radius):
    """A Bevel node at the start of each normal chain: the normal bake then holds rounded edges that the mesh does not have."""
    added = []
    for mat in materials_of(obj) if radius else []:
        bsdf = principled_or_none(mat)
        sock = normal_chain_start(bsdf) if bsdf else None
        if sock is None or sock.is_linked:
            continue
        bevel = mat.node_tree.nodes.new("ShaderNodeBevel")
        bevel.samples = 12
        bevel.inputs["Radius"].default_value = radius
        mat.node_tree.links.new(bevel.outputs["Normal"], sock)
        added.append((mat.node_tree, bevel))
    try:
        yield
    finally:
        for nt, bevel in added:
            nt.nodes.remove(bevel)


@contextlib.contextmanager
def hidden_others(scene, obj):
    others = [o for o in scene.objects if o != obj and not o.hide_render and o.type in BOUNDED]
    for o in others:
        o.hide_render = True
    try:
        yield
    finally:
        for o in others:
            o.hide_render = False


@contextlib.contextmanager
def bake_scene(obj, samples):
    """Cycles bake settings and selection for one map; all of it is put back, so a job leaves the scene clean between maps."""
    scene, layer = bpy.context.scene, bpy.context.view_layer
    settings = scene.render.bake
    saved = render_state(scene) + [(settings, a, getattr(settings, a)) for a in ("target", "margin", "use_clear", "use_selected_to_active")]
    selected, active = [o for o in layer.objects if o.select_get()], layer.objects.active
    for o in selected:
        o.select_set(False)
    obj.select_set(True)
    layer.objects.active = obj
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = max(1, samples)
        scene.cycles.use_denoising = False
        settings.target = "IMAGE_TEXTURES"
        yield scene
    finally:
        restore_state(saved)
        obj.select_set(False)
        for o in selected:
            o.select_set(True)
        layer.objects.active = active


def bake_map(obj, key, size, path, margin, samples, bevel_radius, as_emission):
    img = new_image(f"{obj.name}_{key}", size, key != "base_color")
    kwargs = dict(margin=margin, use_clear=True, use_selected_to_active=False)
    with contextlib.ExitStack() as stack:
        scene = stack.enter_context(bake_scene(obj, samples))
        stack.enter_context(bake_targets(obj, img))
        if as_emission and key in EMIT_INPUT:
            stack.enter_context(emission_of(obj, EMIT_INPUT[key]))
            kwargs["type"] = "EMIT"
        else:
            kwargs["type"] = BAKE_PASS[key]
            if key != "ao":
                stack.enter_context(hidden_others(scene, obj))
        if key == "normal":
            kwargs["normal_space"] = "TANGENT"
            stack.enter_context(rounded_edges(obj, bevel_radius))
        if kwargs["type"] == "DIFFUSE":
            kwargs["pass_filter"] = {"COLOR"}
        bpy.ops.object.bake(**kwargs)
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def pack_orm(paths, target):
    red, green, blue = (read_pixels(paths[key])[:, :, 0] for key in ORM_PARTS)
    write_pixels(target, np.dstack([red, green, blue, np.ones_like(red)]))


def has_bump(obj):
    return any(n.type == "BSDF_PRINCIPLED" and n.inputs["Normal"].links
               for m in obj.data.materials if m and m.node_tree for n in m.node_tree.nodes)


def rebuild_from_images(obj, paths):
    name = f"{obj.name}_baked"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    packed = paths.get("orm")
    build_surface(mat, "#ffffff", 0.5, 0.0, 1.0, None, 0.0, 0.0, paths.get("base_color"), paths.get("normal"), None,
                  None if packed else paths.get("roughness"), None if packed else paths.get("metallic"), packed)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat


def bake_steps(obj, size, maps, folder, margin, samples, replace_material, bevel_radius, unwrapped):
    started = time.time()
    flat_normal = "normal" in maps and not has_bump(obj) and not bevel_radius
    as_emission = all(principled_or_none(m) for m in materials_of(obj))
    passes = [m for m in maps if m != "orm"]
    passes += [m for m in ORM_PARTS if "orm" in maps and m not in passes]
    files = {key: folder / f"{obj.name}_{key}.png" for key in [*passes, *maps]}
    for done, key in enumerate(passes):
        yield {"baking": key, "done": done, "of": len(passes), "size": size}
        bake_map(obj, key, size, files[key], margin, samples, bevel_radius, as_emission)
    if "orm" in maps:
        pack_orm(files, files["orm"])
        for key in [k for k in passes if k not in maps]:
            files[key].unlink()
    paths = {key: str(files[key]) for key in maps}
    result = {"object": obj.name, "size": [size, size], "maps": paths, "unwrapped": unwrapped, "samples": samples,
              "uv_layer": obj.data.uv_layers.active.name, "seconds": rnd(time.time() - started, 1)}
    if replace_material:
        result["material"] = rebuild_from_images(obj, paths).name
    if flat_normal:
        result["note"] = "The material has no bump or normal input, so the normal map is flat (0.5, 0.5, 1.0). Give bevel_radius to bake rounded edges into it."
    if "orm" in maps:
        result["note_orm"] = "orm is R occlusion, G roughness, B metallic: glTF gets it as metallicRoughnessTexture and occlusionTexture."
    elif "ao" in maps:
        result["note_ao"] = "ao alone is saved as a file only and the rebuilt material does not use it. Ask for the orm map to send occlusion to glTF."
    return result


def run_to_end(steps):
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


@handler
def bake_maps(object, size=1024, maps=("base_color", "normal", "roughness", "ao"), out_dir=None, margin=8, samples=16,
              replace_material=True, uv_layer=None, bevel_radius=None, background=False):
    obj = get_object(object)
    maps = list(dict.fromkeys(maps))
    unknown = [m for m in maps if m not in MAP_NAMES]
    if unknown or not maps:
        raise ValueError(f"maps are chosen from {sorted(MAP_NAMES)}; got {maps}")
    if not (16 <= size <= 8192):
        raise ValueError("size must be between 16 and 8192")
    if obj.type != "MESH":
        raise ValueError(f"{object} is {obj.type}, not MESH")
    if not any(obj.data.materials):
        raise ValueError(f"{object} has no material: call procedural_material or set_material first")
    if {"metallic", "orm"} & set(maps) and not all(principled_or_none(m) for m in materials_of(obj)):
        raise ValueError(f"metallic and orm need a Principled BSDF in every material of {object}")
    if bevel_radius is not None and bevel_radius <= 0:
        raise ValueError("bevel_radius must be above 0 (metres)")
    unwrapped = ensure_uv(obj, uv_layer)
    folder = Path(out_dir).expanduser() if out_dir else WORK / "bakes"
    if not folder.is_absolute():
        folder = WORK / folder
    folder.mkdir(parents=True, exist_ok=True)
    steps = bake_steps(obj, size, maps, folder, margin, samples, replace_material, bevel_radius, unwrapped)
    return steps if background else run_to_end(steps)
