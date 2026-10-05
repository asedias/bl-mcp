"""Compare the model with a reference image: registered silhouette, bands, inner edges, colour classes, overlay sheet."""

import math

import bpy
import mathutils
import numpy as np
from mathutils import Vector

from .core import *  # noqa: F401,F403
from .core import handler
from .profiles import mask_bounds, turned

SHEET_VIEWS = {
    # name: (camera euler in degrees, world axes shown as (horizontal, vertical), what the picture shows)
    "front": ((90, 0, 0), (0, 2), "+X to the right, +Z up"),
    "back": ((90, 0, 180), (0, 2), "-X to the right, +Z up"),
    "right": ((90, 0, 90), (1, 2), "camera on +X, the front (-Y) points to the left, +Z up"),
    "left": ((90, 0, -90), (1, 2), "camera on -X, the front (-Y) points to the right, +Z up"),
    "top": ((0, 0, 0), (0, 1), "+X to the right, the front (-Y) at the bottom"),
    "bottom": ((180, 0, 0), (0, 1), "+X to the right, the front (-Y) at the top"),
}
SHEET_VIEWS["side"] = SHEET_VIEWS["right"]
HELPER_WORDS = ("floor", "ground", "backdrop", "studio")
NORMAL_TURN = 0.2
DEPTH_STEP = 0.002


def view_of(view):
    if view not in SHEET_VIEWS:
        raise ValueError("view is front, back, left, right (side is the same as right), top or bottom")
    return SHEET_VIEWS[view]


def model_objects(names):
    """The objects to compare and the names left out: without `names`, a floor or backdrop far bigger than the rest."""
    if names:
        return with_children(names), []
    objs = scene_objects()
    longest, suspects = {}, []
    for obj in objs:
        box = bounds_of([obj])
        thin, _, longest[obj.name] = sorted(box[1] - box[0]) if box else (0.0, 0.0, 0.0)
        if thin < 0.05 * longest[obj.name] or any(word in obj.name.lower() for word in HELPER_WORDS):
            suspects.append(obj)
    rest = max((longest[o.name] for o in objs if o not in suspects), default=0.0)
    helpers = [o for o in suspects if rest > 0 and longest[o.name] > 3 * rest]
    return [o for o in objs if o not in helpers], [o.name for o in helpers]


def ortho_camera(scene, euler, center, scale, distance):
    data = bpy.data.cameras.new("bl_cam")
    data.type, data.ortho_scale, data.clip_start, data.clip_end = "ORTHO", scale, 0.01, distance * 4
    camera = bpy.data.objects.new("bl_cam", data)
    scene.collection.objects.link(camera)
    rotation = mathutils.Euler([math.radians(a) for a in euler])
    camera.rotation_euler = rotation
    camera.location = center - (rotation.to_matrix() @ Vector((0, 0, -1))) * distance
    return camera


def drop_camera(camera):
    data = camera.data
    bpy.data.objects.remove(camera)
    bpy.data.cameras.remove(data)


def shoot(scene, euler, center, scale, distance, size, path):
    camera = ortho_camera(scene, euler, center, scale, distance)
    scene.camera = camera
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.filepath = str(path)
    try:
        bpy.ops.render.render(write_still=True, scene=scene.name)
    finally:
        drop_camera(camera)
    return read_pixels(path)


def reference_scale(box, height_m, width_m, fallback_m=None):
    """Metres per reference pixel and the size that set it; the box is the silhouette box of the reference."""
    y0, y1, x0, x1 = box
    if height_m and width_m:
        raise ValueError("Give height_m (real size along the vertical of the picture) or width_m (along its horizontal), not both")
    if width_m:
        return width_m / (x1 - x0 + 1), f"width_m={width_m}"
    if height_m:
        return height_m / (y1 - y0 + 1), f"height_m={height_m}"
    if fallback_m is None:
        raise ValueError("Give height_m or width_m: the real size of the subject in the picture")
    return fallback_m / (y1 - y0 + 1), None


def registered(shape, box, mpp, size, scale, extent_up):
    """The reference pixel under each tile pixel: reference bottom on the model bottom, horizontal centres equal."""
    y0, y1, x0, x1 = box
    offsets = ((np.arange(size) + 0.5) / size - 0.5) * scale
    gh, gv = np.meshgrid(offsets, offsets)
    rx = np.floor((x0 + x1 + 1) / 2 + gh / mpp).astype(int)
    ry = np.floor(y0 + (gv + extent_up / 2) / mpp).astype(int)
    inside = (rx >= 0) & (rx < shape[1]) & (ry >= 0) & (ry < shape[0])
    return np.clip(ry, 0, shape[0] - 1), np.clip(rx, 0, shape[1] - 1), inside


def boundary(mask):
    padded = np.pad(mask, 1)
    inner = padded[1:-1, 1:-1] & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    return mask & ~inner


def grown(mask, steps):
    for _ in range(steps):
        padded = np.pad(mask, 1)
        mask = padded[1:-1, 1:-1] | padded[:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, :-2] | padded[1:-1, 2:]
    return mask


def inner_edges(gray, mask, threshold=0.08):
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    strong = np.hypot(gx, gy) > threshold
    eroded = mask.copy()
    for shift in (1, 2):
        eroded &= np.roll(mask, shift, 0) & np.roll(mask, -shift, 0) & np.roll(mask, shift, 1) & np.roll(mask, -shift, 1)
    return strong & eroded


def geometry_material(distance, span):
    """Emission that writes the view-space normal (x, y) into red and green and the depth into blue."""
    mat = bpy.data.materials.new("bl_geometry")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    geometry = nodes.new("ShaderNodeNewGeometry")
    to_camera = {}
    for kind, socket in (("NORMAL", "Normal"), ("POINT", "Position")):
        node = nodes.new("ShaderNodeVectorTransform")
        node.vector_type, node.convert_from, node.convert_to = kind, "WORLD", "CAMERA"
        links.new(geometry.outputs[socket], node.inputs[0])
        to_camera[kind] = node
    packed = nodes.new("ShaderNodeVectorMath")
    packed.operation = "MULTIPLY_ADD"
    packed.inputs[1].default_value = packed.inputs[2].default_value = (0.5, 0.5, 0.5)
    links.new(to_camera["NORMAL"].outputs[0], packed.inputs[0])
    normal, position = nodes.new("ShaderNodeSeparateXYZ"), nodes.new("ShaderNodeSeparateXYZ")
    links.new(packed.outputs[0], normal.inputs[0])
    links.new(to_camera["POINT"].outputs[0], position.inputs[0])
    away = nodes.new("ShaderNodeMath")
    away.operation = "ABSOLUTE"
    links.new(position.outputs["Z"], away.inputs[0])
    depth = nodes.new("ShaderNodeMath")
    depth.operation = "MULTIPLY_ADD"
    depth.inputs[1].default_value, depth.inputs[2].default_value = 1 / span, 0.5 - distance / span
    links.new(away.outputs[0], depth.inputs[0])
    colour = nodes.new("ShaderNodeCombineXYZ")
    links.new(normal.outputs["X"], colour.inputs["X"])
    links.new(normal.outputs["Y"], colour.inputs["Y"])
    links.new(depth.outputs[0], colour.inputs["Z"])
    emission = nodes.new("ShaderNodeEmission")
    links.new(colour.outputs[0], emission.inputs["Color"])
    links.new(emission.outputs[0], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    return mat


def geometry_pass(objs, euler, center, scale, distance, span, size, path):
    mat = geometry_material(distance, span)
    try:
        with temp_scene(objs, "material") as scene:
            scene.render.engine = "BLENDER_EEVEE"
            set_if_valid(scene.eevee, "taa_render_samples", 1)
            set_if_valid(scene.view_settings, "view_transform", "Raw")
            scene.render.image_settings.color_depth = "16"
            scene.view_layers[0].material_override = mat
            return shoot(scene, euler, center, scale, distance, size, path)[:, :, :3]
    finally:
        bpy.data.materials.remove(mat)


def geometry_edges(code, model, depth_step):
    """Creases (the normal turns) and steps (the depth jumps) between neighbour pixels, inside the model outline."""
    normal, depth = code[:, :, :2], code[:, :, 2]
    edges = np.zeros(model.shape, dtype=bool)
    edges[:-1] |= np.linalg.norm(np.diff(normal, axis=0), axis=2) > NORMAL_TURN
    edges[:, :-1] |= np.linalg.norm(np.diff(normal, axis=1), axis=2) > NORMAL_TURN
    edges[1:-1] |= np.abs(np.diff(depth, 2, axis=0)) > depth_step
    edges[:, 1:-1] |= np.abs(np.diff(depth, 2, axis=1)) > depth_step
    return edges & ~grown(~model, 2)


def edge_agreement(ref_edges, model_edges, reach):
    """Shares of reference edges near a model edge and of model edges near a reference edge, and their F1."""
    if not ref_edges.any():
        return None
    recall = float((ref_edges & grown(model_edges, reach)).sum() / ref_edges.sum())
    precision = float((model_edges & grown(ref_edges, reach)).sum() / model_edges.sum()) if model_edges.any() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return f1, recall, precision


def outline_iou(model_crop, ref_mask):
    """IoU with the reference scaled to the model height and centred: it ignores the size, not the proportions."""
    ref_crop = crop(ref_mask)
    height = model_crop.shape[0]
    width = max(1, round(ref_crop.shape[1] * height / ref_crop.shape[0]))
    if width > 8 * model_crop.shape[1]:
        return 0.0
    canvas = max(width, model_crop.shape[1])
    a, b = np.zeros((height, canvas), dtype=bool), np.zeros((height, canvas), dtype=bool)
    a[:, (canvas - model_crop.shape[1]) // 2 :][:, : model_crop.shape[1]] = model_crop
    b[:, (canvas - width) // 2 :][:, :width] = resize_nearest(ref_crop, height, width)
    return float((a & b).sum() / (a | b).sum())


def fitted_iou(model, ref_mask, box, size, scale, extent_up):
    """IoU with the reference scaled to the model height: the shape without the size, sampled like the registered one."""
    rows, cols, inside = registered(ref_mask.shape, box, extent_up / (box[1] - box[0] + 1), size, scale, extent_up)
    ref = ref_mask[rows, cols] & inside
    either = (model | ref).sum()
    return float((model & ref).sum() / either) if either else 0.0


def orientation_hint(model, raw_mask, flip, rotate, view):
    """Tries the 8 mirrored and turned copies of the reference; a hint when one fits the model far better."""
    model_crop = crop(model)
    now = outline_iou(model_crop, turned(raw_mask, flip, rotate))
    tries = [(outline_iou(model_crop, turned(raw_mask, f, r)), f, r) for f in (None, "x") for r in (0, 90, 180, 270)]
    top = max(t[0] for t in tries)
    # Near-symmetric outlines tie: the first try within reach of the top is the simplest change.
    best, best_flip, best_rotate = next(t for t in tries if t[0] >= top - 0.02)
    if best < max(0.5, now + 0.2):
        return None
    return (f"The reference fits far better in another orientation: flip={best_flip!r}, rotate={best_rotate} gives an outline IoU of {rnd(best, 3)} "
            f"against {rnd(now, 3)} as given. The {view} view shows {SHEET_VIEWS[view][2]}. height_m and width_m are sizes of the turned picture.")


def kmeans(colors, k, iterations=8):
    order = np.argsort(colors.sum(axis=1))
    centres = colors[order[np.linspace(0, len(colors) - 1, k).astype(int)]].copy()
    for _ in range(iterations):
        labels = np.argmin(((colors[:, None, :] - centres[None]) ** 2).sum(axis=2), axis=1)
        for i in range(k):
            if (labels == i).any():
                centres[i] = colors[labels == i].mean(axis=0)
    return centres


def band_table(model, ref, lo_v, scale, size, bands, mpp_tile):
    rows = []
    edges = np.linspace(0, 1, bands + 1)
    for k in range(bands):
        a = int(edges[k] * size)
        b = max(int(edges[k + 1] * size), a + 1)
        entry = {"z0": rnd(lo_v[k][0], 3), "z1": rnd(lo_v[k][1], 3)}
        extents = []
        for mask in (model, ref):
            cols = np.flatnonzero(mask[a:b].any(axis=0))
            extents.append((cols.min(), cols.max() + 1) if len(cols) else None)
        if extents[0] is None and extents[1] is None:
            continue
        m, r = extents
        entry["model_width"] = rnd((m[1] - m[0]) * mpp_tile, 3) if m else 0.0
        entry["reference_width"] = rnd((r[1] - r[0]) * mpp_tile, 3) if r else 0.0
        diff = entry["model_width"] - entry["reference_width"]
        entry["delta_m"] = rnd(diff, 3)
        entry["delta_pct"] = rnd(100 * diff / entry["reference_width"], 1) if entry["reference_width"] else None
        entry["shift_m"] = rnd(((m[0] + m[1]) - (r[0] + r[1])) / 2 * mpp_tile, 3) if m and r else None
        rows.append(entry)
    return rows


@handler
def compare_view(reference, view="front", names=None, height_m=None, size=512, bands=16, threshold=0.06, colors=0,
                 width_m=None, flip=None, rotate=0, out=None):
    euler, axes, shows = view_of(view)
    raw_pixels = read_pixels(reference)
    ref_pixels = turned(raw_pixels, flip, rotate)
    ref_mask_full = mask_of(ref_pixels, threshold)
    box = mask_bounds(ref_mask_full)
    objs, excluded = model_objects(names)
    lo, hi = require_bounds(objs)
    center = (lo + hi) / 2
    scale = float(max(hi - lo)) * 1.25
    span = (hi - lo).length
    distance = span * 2 + 1
    RENDERS.mkdir(parents=True, exist_ok=True)
    with temp_scene(objs, "mask") as scene:
        model = shoot(scene, euler, center, scale, distance, size, RENDERS / f"cmp_mask_{view}.png")[:, :, 0] > 0.5
    with temp_scene(objs, "material") as scene:
        configure_extra_look(scene, "clay")
        clay = shoot(scene, euler, center, scale, distance, size, RENDERS / f"cmp_clay_{view}.png")[:, :, :3]
    flat = None
    if colors:
        with temp_scene(objs, "material") as scene:
            configure_extra_look(scene, "flat")
            flat = shoot(scene, euler, center, scale, distance, size, RENDERS / f"cmp_flat_{view}.png")[:, :, :3]

    across, up = (float((hi - lo)[axis]) for axis in axes)
    mpp, given = reference_scale(box, height_m, width_m, up)
    ryc, rxc, inside = registered(ref_mask_full.shape, box, mpp, size, scale, up)
    ref = ref_mask_full[ryc, rxc] & inside
    ref_rgb = np.where(inside[..., None], ref_pixels[ryc, rxc, :3], 0.1)

    both, either = (model & ref).sum(), (model | ref).sum()
    registered_iou = float(both / either) if either else 0.0
    mpp_tile = scale / size
    v0 = center[axes[1]] - scale / 2
    spans = np.linspace(lo[axes[1]], hi[axes[1]], bands + 1)
    tile_rows = [((spans[k] - v0) / scale, (spans[k + 1] - v0) / scale) for k in range(bands)]
    band_info = []
    for k in range(bands):
        a, b = int(tile_rows[k][0] * size), max(int(tile_rows[k][1] * size), int(tile_rows[k][0] * size) + 1)
        table = band_table(model[a:b], ref[a:b], [(spans[k] - lo[axes[1]], spans[k + 1] - lo[axes[1]])], scale, b - a, 1, mpp_tile)
        if table:
            band_info.append({**table[0], "z0": rnd(spans[k] - lo[axes[1]], 3), "z1": rnd(spans[k + 1] - lo[axes[1]], 3)})
    for entry in band_info:
        pct = entry.get("delta_pct")
        entry["verdict"] = "ok" if pct is None or abs(pct) < 8 else ("model wider" if pct > 0 else "model narrower")
        if entry.get("shift_m") is not None and abs(entry["shift_m"]) > 0.02 and entry["verdict"] == "ok":
            entry["verdict"] = "shifted right" if entry["shift_m"] > 0 else "shifted left"
    worst = sorted(band_info, key=lambda e: -abs(e.get("delta_m") or 0))[:3]

    zone = ~grown(~(model & ref), 2)
    ref_edges = inner_edges(ref_rgb.mean(axis=2), ref) & zone
    reach = max(2, round(size * 0.006))
    try:
        code = geometry_pass(objs, euler, center, scale, distance, span, size, RENDERS / f"cmp_geometry_{view}.png")
        model_edges = geometry_edges(code, model, DEPTH_STEP * scale / span)
        agreement = edge_agreement(ref_edges, model_edges & zone, reach)
        detail_note = ("edge_agreement is 0..1: it joins the share of reference inner edges (colour changes inside the outline) with a model edge (crease or "
                       f"depth step) within {reach} px and the share of model edges with a reference edge that near. It rises when a detail is added in the "
                       "right place and does not see the outline. Shading and texture of the reference also make edges, so compare runs, do not aim at 1.")
        if agreement is None:
            detail_note = "not measured: the reference has no inner edges inside the common area (a flat mask?)"
    except RuntimeError as error:
        model_edges, agreement = np.zeros_like(model), None
        detail_note = f"not measured: the edge render failed ({str(error).strip().splitlines()[-1]})"

    shade = clay * 0.6
    overlay = shade.copy()
    overlay[inner_edges(ref_rgb.mean(axis=2), ref)] = (1.0, 0.85, 0.2)
    overlay[model_edges] = (0.2, 0.85, 1.0)
    overlay[boundary(ref)] = (1.0, 0.15, 0.15)
    overlay[boundary(model)] = (0.2, 1.0, 0.3)
    diff = np.zeros((size, size, 3), dtype=np.float32)
    diff[model & ref] = 1.0
    diff[model & ~ref] = (0.2, 0.9, 0.3)
    diff[~model & ref] = (0.95, 0.2, 0.2)
    sheet = np.ones((size, size * 4, 4), dtype=np.float32)
    for i, tile in enumerate((ref_rgb, clay, overlay, diff)):
        sheet[:, i * size : (i + 1) * size, :3] = tile
    sheet_path = Path(out).expanduser() if out else RENDERS / f"compare_{view}.png"
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    write_pixels(sheet_path, sheet)

    y0, y1, x0, x1 = box
    result = {
        "view": view,
        "picture": shows,
        "iou_registered": rnd(registered_iou),
        "iou_outline": rnd(fitted_iou(model, ref_mask_full, box, size, scale, up)),
        "alignment": "reference bottom on model bottom, horizontal centres equal, scale from " + (given or "the model height (give height_m or width_m to check size)"),
        "reference_size_m": [rnd((x1 - x0 + 1) * mpp), rnd((y1 - y0 + 1) * mpp)],
        "model_size_m": [rnd(across), rnd(up)],
        "inner_detail": {
            "edge_agreement": None if agreement is None else rnd(agreement[0]),
            "reference_edges_matched": None if agreement is None else rnd(agreement[1]),
            "model_edges_matched": None if agreement is None else rnd(agreement[2]),
            "note": detail_note,
        },
        "worst_bands": worst,
        "bands": band_info,
        "sheet": str(sheet_path),
        "sheet_legend": "tiles left to right: reference, model, overlay (red reference outline, green model outline, yellow reference inner edges, blue model inner edges), difference (white both, green model only, red reference only)",
    }
    if registered_iou < 0.3:
        hint = orientation_hint(model, mask_of(raw_pixels, threshold), flip, rotate, view)
        if hint:
            result["hint"] = hint
    if excluded:
        result["excluded"] = excluded
        result["warning"] = f"Left out as helpers (flat or named like a floor, over 3 times bigger than the rest): {', '.join(excluded)}. Pass names to choose the model yourself."
    if colors:
        ref_fg = ref_rgb[ref]
        picks = ref_fg[np.linspace(0, len(ref_fg) - 1, min(len(ref_fg), 20000)).astype(int)]
        palette = kmeans(picks, colors)
        label = lambda arr: np.argmin(((arr[:, None, :] - palette[None]) ** 2).sum(axis=2), axis=1)
        ref_labels = np.full(ref.shape, -1)
        ref_labels[ref] = label(ref_rgb[ref])
        model_labels = np.full(model.shape, -1)
        model_labels[model] = label(flat[model])
        classes = []
        for i, colour in enumerate(palette):
            r_area, m_area = (ref_labels == i), (model_labels == i)
            union = (r_area | m_area).sum()
            classes.append({
                "colour": hex_of(np.clip(colour, 0, 1)),
                "reference_share": rnd(r_area.sum() / max(ref.sum(), 1), 3),
                "model_share": rnd(m_area.sum() / max(model.sum(), 1), 3),
                "iou": rnd((r_area & m_area).sum() / union, 3) if union else None,
            })
        result["colour_classes"] = classes
        result["colour_note"] = "classes come from the reference colours; the model is drawn flat with its material colours"
    return result
