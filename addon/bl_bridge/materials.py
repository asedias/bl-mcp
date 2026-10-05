"""Game materials: Principled set-ups that survive glTF export, per-face assignment, merging look-alikes."""

import bpy
import numpy as np

from .core import *  # noqa: F401,F403
from .core import handler, parse_color
from .meshops import commit, edit_bmesh, need, pick_faces

EXPORTED_NODES = {"BSDF_PRINCIPLED", "OUTPUT_MATERIAL", "TEX_IMAGE", "NORMAL_MAP", "UVMAP", "SEPARATE_COLOR"}
KEPT_NODES = {"BSDF_PRINCIPLED", "OUTPUT_MATERIAL"}
# the glTF exporter reads occlusion from a group node with this name
GLTF_OUTPUT = "glTF Material Output"
ALPHA_CLIP_MATH = {"ROUND", "LESS_THAN", "GREATER_THAN"}


def principled(mat):
    node = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.node_tree else None
    if node is None:
        raise ValueError(f"Material {mat.name} has no Principled BSDF")
    return node


def socket(node, *names):
    for name in names:
        if name in node.inputs:
            return node.inputs[name]
    raise ValueError(f"Principled BSDF has none of the inputs {names}; it has {list(node.inputs.keys())}")


def to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def hex_of(linear):
    return "#" + "".join(f"{round(max(0.0, min(1.0, to_srgb(c))) * 255):02x}" for c in linear[:3])


def exported(node):
    """True for the node patterns the glTF exporter understands: a multiply by a constant is a factor."""
    if node.type == "MIX":
        return node.data_type == "RGBA" and node.blend_type == "MULTIPLY"
    if node.type == "MATH":
        return node.operation == "MULTIPLY"
    if node.type == "GROUP":
        return node.node_tree is not None and node.node_tree.name.startswith(GLTF_OUTPUT)
    return node.type in EXPORTED_NODES


def default_name(color, roughness, metallic, alpha, emission, coat, subsurface):
    parts = [f"pbr_{hex_of(parse_color(color)).lstrip('#')}", f"r{roughness:g}"]
    if metallic:
        parts.append(f"m{metallic:g}")
    if alpha < 1:
        parts.append(f"a{alpha:g}")
    if emission:
        parts.append("e" + hex_of(parse_color(emission.get("color", "#ffffff"))).lstrip("#") + f"x{emission.get('strength', 1.0):g}")
    if coat:
        parts.append(f"c{coat:g}")
    if subsurface:
        parts.append(f"s{subsurface:g}")
    return "_".join(parts)


def clear_extras(mat):
    tree = mat.node_tree
    for node in [n for n in tree.nodes if n.type not in KEPT_NODES]:
        tree.nodes.remove(node)
    for link in list(tree.links):
        if link.to_node.type == "BSDF_PRINCIPLED":
            tree.links.remove(link)


def load_image(path, colorspace):
    from pathlib import Path

    if not Path(path).is_file():
        raise ValueError(f"Image file not found: {path}")
    image = bpy.data.images.load(str(path), check_existing=True)
    # an image Blender already holds may be stale: a new bake writes over the same file
    image.reload()
    image.colorspace_settings.name = colorspace
    return image


def image_node(tree, path, colorspace, location):
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = load_image(path, colorspace)
    node.location = location
    return node


def require_uv(names):
    missing = [n for n in names if not get_object(n).data.uv_layers]
    if missing:
        raise ValueError(f"{missing} have no UV map, so a texture cannot be placed. Run unwrap (or palette_uv) on them first")


def set_render_method(mat, alpha):
    """Only the EEVEE draw mode. glTF alphaMode comes from the Alpha input, see gltf_alpha_mode."""
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED" if alpha < 1 else "DITHERED"
    else:
        mat.blend_method = "BLEND" if alpha < 1 else "OPAQUE"


def gltf_alpha_mode(mat):
    """The alphaMode the glTF exporter derives: it reads the Alpha input and ignores the render method."""
    sock = socket(principled(mat), "Alpha")
    if not sock.is_linked:
        return "OPAQUE" if sock.default_value >= 1 else "MASK" if sock.default_value <= 0 else "BLEND"
    node = sock.links[0].from_node
    return "MASK" if node.type == "MATH" and node.operation in ALPHA_CLIP_MATH else "BLEND"


def tinted(tree, source, linear, location):
    node = tree.nodes.new("ShaderNodeMix")
    node.data_type, node.blend_type, node.location = "RGBA", "MULTIPLY", location
    inputs = {s.identifier: s for s in node.inputs}
    inputs["Factor_Float"].default_value = 1.0
    inputs["B_Color"].default_value = (*linear, 1)
    tree.links.new(source, inputs["A_Color"])
    return next(s for s in node.outputs if s.identifier == "Result_Color")


def scaled(tree, source, factor, location):
    node = tree.nodes.new("ShaderNodeMath")
    node.operation, node.location = "MULTIPLY", location
    node.inputs[1].default_value = factor
    tree.links.new(source, node.inputs[0])
    return node.outputs[0]


def channels(tree, path, location):
    tex = image_node(tree, path, "Non-Color", location)
    split = tree.nodes.new("ShaderNodeSeparateColor")
    split.location = (location[0] + 300, location[1])
    tree.links.new(tex.outputs["Color"], split.inputs["Color"])
    return split.outputs


def occlusion_input(tree):
    group = bpy.data.node_groups.get(GLTF_OUTPUT)
    if group is None:
        group = bpy.data.node_groups.new(GLTF_OUTPUT, "ShaderNodeTree")
        group.interface.new_socket("Occlusion", socket_type="NodeSocketFloat")
        group.nodes.new("NodeGroupInput")
        group.nodes.new("NodeGroupOutput")
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree, node.location = group, (0, -400)
    return node.inputs["Occlusion"]


def link_surface_maps(tree, bsdf, roughness_map, metallic_map, orm_map):
    """glTF packs roughness in G and metallic in B, so every map goes through Separate Color on those channels."""
    if orm_map:
        out = channels(tree, orm_map, (-900, 0))
        tree.links.new(out["Green"], socket(bsdf, "Roughness"))
        tree.links.new(out["Blue"], socket(bsdf, "Metallic"))
        tree.links.new(out["Red"], occlusion_input(tree))
    if roughness_map:
        tree.links.new(channels(tree, roughness_map, (-900, 0))["Green"], socket(bsdf, "Roughness"))
    if metallic_map:
        tree.links.new(channels(tree, metallic_map, (-900, 300))["Blue"], socket(bsdf, "Metallic"))


def build_surface(mat, color, roughness, metallic, alpha, emission, coat, subsurface, texture, normal_map, bump,
                  roughness_map=None, metallic_map=None, orm_map=None):
    mat.use_nodes = True
    clear_extras(mat)
    tree, bsdf = mat.node_tree, principled(mat)
    linear = parse_color(color)
    socket(bsdf, "Base Color").default_value = (*linear, 1)
    socket(bsdf, "Roughness").default_value = roughness
    socket(bsdf, "Metallic").default_value = metallic
    socket(bsdf, "Alpha").default_value = alpha
    socket(bsdf, "Coat Weight", "Clearcoat").default_value = coat
    socket(bsdf, "Subsurface Weight", "Subsurface").default_value = subsurface
    glow = emission or {}
    socket(bsdf, "Emission Color", "Emission").default_value = (*parse_color(glow.get("color", "#000000")), 1)
    socket(bsdf, "Emission Strength").default_value = glow.get("strength", 1.0) if emission else 0.0
    mat.diffuse_color = (*linear, alpha)
    set_render_method(mat, alpha)
    if texture:
        tex = image_node(tree, texture, "sRGB", (-900, 600))
        white = min(linear) >= 0.999
        tree.links.new(tex.outputs["Color"] if white else tinted(tree, tex.outputs["Color"], linear, (-300, 600)), socket(bsdf, "Base Color"))
        if alpha < 1:
            tree.links.new(scaled(tree, tex.outputs["Alpha"], alpha, (-300, 400)), socket(bsdf, "Alpha"))
    link_surface_maps(tree, bsdf, roughness_map, metallic_map, orm_map)
    normal_source = None
    if normal_map:
        tex = image_node(tree, normal_map, "Non-Color", (-900, -200))
        normal_source = tree.nodes.new("ShaderNodeNormalMap")
        normal_source.location = (-400, -200)
        tree.links.new(tex.outputs["Color"], normal_source.inputs["Color"])
    if bump:
        noise = tree.nodes.new("ShaderNodeTexNoise")
        noise.location = (-700, -500)
        noise.inputs["Scale"].default_value = bump.get("scale", 20.0)
        node = tree.nodes.new("ShaderNodeBump")
        node.location = (-400, -500)
        node.inputs["Strength"].default_value = bump.get("strength", 0.3)
        tree.links.new(noise.outputs["Fac"], node.inputs["Height"])
        if normal_source is not None:
            tree.links.new(normal_source.outputs["Normal"], node.inputs["Normal"])
        normal_source = node
    if normal_source is not None:
        tree.links.new(normal_source.outputs["Normal"], socket(bsdf, "Normal"))


def put_on_objects(mat, objs):
    for obj in objs:
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)


def gltf_summary(mat):
    """What the glTF exporter writes for this material, read back from the node tree."""
    p = params_of(mat)
    linear = socket(principled(mat), "Base Color").default_value
    textures = {
        "baseColorTexture": p["texture"],
        "metallicRoughnessTexture": p["roughness_map"] or p["metallic_map"],
        "occlusionTexture": p["occlusion_map"],
        "normalTexture": p["normal_map"],
    }
    return {
        "alphaMode": p["alpha_mode"],
        "baseColorFactor": [rnd(c, 4) for c in linear[:3]] + [p["alpha"]],
        "roughnessFactor": 1.0 if p["roughness_map"] else p["roughness"],
        "metallicFactor": 1.0 if p["metallic_map"] else p["metallic"],
        "textures": [key for key, path in textures.items() if path],
    }


@handler
def set_material(names, color, material=None, roughness=0.8, metallic=0.0, alpha=1.0, emission=None, coat=0.0,
                 subsurface=0.0, texture=None, normal_map=None, bump=None, roughness_map=None, metallic_map=None,
                 orm_map=None):
    objs = [get_object(n) for n in names]
    if any(o.type != "MESH" for o in objs):
        raise ValueError("Materials go on meshes")
    if orm_map and (roughness_map or metallic_map):
        raise ValueError("Give orm_map, or roughness_map and metallic_map, not both: orm_map already holds roughness and metallic")
    images = {"tex": texture, "nrm": normal_map, "rgh": roughness_map, "mtl": metallic_map, "orm": orm_map}
    if any(images.values()) and not all(o.data.uv_layers for o in objs):
        require_uv(names)
    label = material or default_name(color, roughness, metallic, alpha, emission, coat, subsurface)
    if any(images.values()) or bump:
        label = material or label + "_" + "_".join(k for k, v in {**images, "bump": bump}.items() if v)
    mat = bpy.data.materials.get(label) or bpy.data.materials.new(label)
    build_surface(mat, color, roughness, metallic, alpha, emission, coat, subsurface, texture, normal_map, bump,
                  roughness_map, metallic_map, orm_map)
    put_on_objects(mat, objs)
    result = {"material": label, "objects": names, "reused": mat.users > len(objs), "gltf": gltf_summary(mat)}
    if alpha < 1:
        result["alpha_mode"] = "BLEND in glTF; sorting of transparent faces is the engine's job, keep them few"
    if bump:
        result["warning"] = "bump is a procedural noise: glTF export drops it. Bake it into a normal map first, or leave it out for the game"
    if emission and emission.get("strength", 1.0) > 1:
        result["note"] = "emission strength over 1 exports as KHR_materials_emissive_strength"
    if coat or subsurface:
        result["note_extensions"] = "coat exports as KHR_materials_clearcoat; subsurface has no glTF counterpart in most engines. Both are often ignored at runtime"
    return result


def procedural_nodes(mat):
    if not mat.node_tree:
        return []
    return sorted({n.type for n in mat.node_tree.nodes if not exported(n)})


def image_behind(sock):
    """The image that feeds a socket through the exported helper nodes (factor, channel split, Normal Map)."""
    while sock is not None and sock.is_linked:
        node = sock.links[0].from_node
        if node.type == "TEX_IMAGE":
            return node.image
        if not exported(node) or node.type == "BSDF_PRINCIPLED":
            return None
        sock = next((s for s in node.inputs if s.is_linked and s.type in {"RGBA", "VALUE"}), None)
    return None


def image_of(bsdf, input_name):
    return image_behind(bsdf.inputs.get(input_name))


def occlusion_image(mat):
    for node in mat.node_tree.nodes:
        if node.type == "GROUP" and exported(node) and "Occlusion" in node.inputs:
            return image_behind(node.inputs["Occlusion"])
    return None


def faces_per_slot(mesh):
    indices = np.zeros(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", indices)
    return np.bincount(np.clip(indices, 0, max(len(mesh.materials) - 1, 0)), minlength=max(len(mesh.materials), 1))


def faces_without_material():
    bare = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not len(obj.data.polygons):
            continue
        counts = faces_per_slot(obj.data)
        missing = int(sum(n for i, n in enumerate(counts) if i >= len(obj.data.materials) or obj.data.materials[i] is None))
        if missing:
            bare[obj.name] = missing
    return bare


def faces_using(mat):
    usage = {}
    for obj in bpy.data.objects:
        if obj.type == "MESH" and mat.name in obj.data.materials:
            counts = faces_per_slot(obj.data)
            usage[obj.name] = int(sum(counts[i] for i, m in enumerate(obj.data.materials) if m == mat))
    return usage


def params_of(mat):
    bsdf = principled(mat)
    emission = socket(bsdf, "Emission Color", "Emission").default_value
    base = image_of(bsdf, "Base Color")
    normal = image_of(bsdf, "Normal")
    rough, metal, occlusion = image_of(bsdf, "Roughness"), image_of(bsdf, "Metallic"), occlusion_image(mat)
    return {
        "color": hex_of(socket(bsdf, "Base Color").default_value),
        "roughness": round(socket(bsdf, "Roughness").default_value, 4),
        "metallic": round(socket(bsdf, "Metallic").default_value, 4),
        "alpha": round(socket(bsdf, "Alpha").default_value, 4),
        "emission": {"color": hex_of(emission), "strength": round(socket(bsdf, "Emission Strength").default_value, 4)}
        if socket(bsdf, "Emission Strength").default_value > 0 and max(emission[:3]) > 0 else None,
        "coat": round(socket(bsdf, "Coat Weight", "Clearcoat").default_value, 4),
        "subsurface": round(socket(bsdf, "Subsurface Weight", "Subsurface").default_value, 4),
        "texture": base.filepath if base else None,
        "normal_map": normal.filepath if normal else None,
        "normal_map_colorspace": normal.colorspace_settings.name if normal else None,
        "roughness_map": rough.filepath if rough else None,
        "metallic_map": metal.filepath if metal else None,
        "occlusion_map": occlusion.filepath if occlusion else None,
        "procedural_nodes": procedural_nodes(mat),
        "users": mat.users,
        "alpha_mode": gltf_alpha_mode(mat),
        "render_method": getattr(mat, "surface_render_method", None) or mat.blend_method,
    }


@handler
def list_materials(name=None):
    if name is not None:
        return {"name": name, **params_of(material_of(name)), "faces": faces_using(material_of(name))}
    rows = []
    for mat in bpy.data.materials:
        if not mat.node_tree or not any(n.type == "BSDF_PRINCIPLED" for n in mat.node_tree.nodes):
            rows.append({"name": mat.name, "users": mat.users, "note": "no Principled BSDF"})
            continue
        p = params_of(mat)
        rows.append({"name": mat.name, "color": p["color"], "users": p["users"], "texture": bool(p["texture"]),
                     "procedural_nodes": p["procedural_nodes"], "not_exported": bool(p["procedural_nodes"])})
    return {"count": len(rows), "materials": rows, "faces_without_material": faces_without_material()}


def material_of(name):
    mat = bpy.data.materials.get(name)
    if mat is None:
        raise ValueError(f"No material {name}. Create it first with set_material. Known: {sorted(bpy.data.materials.keys())}")
    return mat


@handler
def assign_material_faces(object, material, where=None):
    obj = get_object(object)
    if obj.type != "MESH":
        raise ValueError(f"{obj.name} is {obj.type}, not MESH")
    mat = material_of(material)
    slots = [s.material for s in obj.material_slots]
    if mat not in slots:
        obj.data.materials.append(mat)
        slots.append(mat)
    index = slots.index(mat)
    bm = edit_bmesh(obj)
    faces = need(pick_faces(bm, obj, where), "faces")
    for face in faces:
        face.material_index = index
    commit(bm, obj)
    return {"object": obj.name, "material": material, "slot": index, "faces": len(faces)}


def signature(mat):
    p = params_of(mat)
    maps = tuple(p[key] for key in ("texture", "normal_map", "roughness_map", "metallic_map", "occlusion_map"))
    return (*maps, tuple(p["procedural_nodes"]), p["alpha"] < 1)


def numbers(mat):
    p = params_of(mat)
    bsdf = principled(mat)
    emission = p["emission"]
    return [*socket(bsdf, "Base Color").default_value[:3], p["roughness"], p["metallic"], p["alpha"], p["coat"], p["subsurface"],
            *(socket(bsdf, "Emission Color", "Emission").default_value[:3] if emission else (0, 0, 0)),
            emission["strength"] if emission else 0.0]


def similar(a, b, tolerance):
    return signature(a) == signature(b) and all(abs(x - y) <= tolerance for x, y in zip(numbers(a), numbers(b)))


def group_look_alikes(mats, tolerance):
    groups = []
    for mat in mats:
        for group in groups:
            if similar(group[0], mat, tolerance):
                group.append(mat)
                break
        else:
            groups.append([mat])
    return groups


def collapse_duplicate_slots(mesh):
    seen = {}
    remap = {}
    for i, mat in enumerate(mesh.materials):
        remap[i] = seen.setdefault(mat, i)
    if all(k == v for k, v in remap.items()):
        return
    indices = [remap.get(p.material_index, p.material_index) for p in mesh.polygons]
    mesh.polygons.foreach_set("material_index", indices)
    for i in sorted((k for k, v in remap.items() if k != v), reverse=True):
        mesh.materials.pop(index=i)
    mesh.update()


def drop_idle_slots(mesh):
    """Removes empty slots and slots no face uses. An empty slot that faces point at stays: its removal would repaint them."""
    if not len(mesh.polygons) or not len(mesh.materials):
        return 0, 0
    indices = np.zeros(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", indices)
    indices = np.clip(indices, 0, len(mesh.materials) - 1)
    used = set(indices.tolist())
    idle = [i for i in range(len(mesh.materials)) if i not in used]
    if not idle:
        return 0, 0
    empty = sum(1 for i in idle if mesh.materials[i] is None)
    kept = [i for i in range(len(mesh.materials)) if i in used]
    new_index = np.zeros(len(mesh.materials), dtype=np.int32)
    new_index[kept] = np.arange(len(kept))
    for i in reversed(idle):
        mesh.materials.pop(index=i)
    mesh.polygons.foreach_set("material_index", new_index[indices])
    mesh.update()
    return empty, len(idle) - empty


def purge_orphans():
    orphans = [m for m in bpy.data.materials if m.users == 0 and not m.use_fake_user and not m.is_grease_pencil]
    names = sorted(m.name for m in orphans)
    for mat in orphans:
        bpy.data.materials.remove(mat)
    return names


@handler
def dedupe_materials(tolerance=0.01, names=None, clean_slots=True, remove_orphans=True):
    pool = [material_of(n) for n in names] if names else list(bpy.data.materials)
    pool = [m for m in pool if m.node_tree and any(n.type == "BSDF_PRINCIPLED" for n in m.node_tree.nodes)]
    before = len(bpy.data.materials)
    merged = {}
    for group in group_look_alikes(pool, tolerance):
        keep, extras = group[0], group[1:]
        for extra in extras:
            extra.user_remap(keep)
            merged[extra.name] = keep.name
            bpy.data.materials.remove(extra)
    empty = unused = 0
    for mesh in bpy.data.meshes:
        collapse_duplicate_slots(mesh)
        if clean_slots:
            dropped = drop_idle_slots(mesh)
            empty, unused = empty + dropped[0], unused + dropped[1]
    orphans = purge_orphans() if remove_orphans else []
    result = {"removed": len(merged), "merged": merged, "empty_slots_removed": empty, "unused_slots_removed": unused,
              "orphans_removed": orphans, "materials_before": before, "materials_after": len(bpy.data.materials)}
    bare = faces_without_material()
    if bare:
        result["faces_without_material"] = bare
        result["note"] = "These faces point at an empty slot, so it was kept. Give them a material with assign_material_faces, then run this again"
    return result
