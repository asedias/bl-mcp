"""Shapes from reference images: measure a silhouette, trace its outline, loft or extrude it."""

import math

import bmesh
import bpy
import numpy as np

from .core import *  # noqa: F401,F403
from .core import handler

MAGENTA = np.array((1.0, 0.0, 1.0), dtype=np.float32)
GLYPHS = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001010010010",
    "8": "111101111101111", "9": "111101111001111", "-": "000000111000000",
}


def turned(array, flip=None, rotate=0):
    """Mirror, then turn clockwise as seen. Rows run bottom-up, so a positive rot90 is clockwise on screen."""
    if flip not in (None, "x", "y"):
        raise ValueError("flip is 'x' (mirror left-right), 'y' (mirror top-bottom) or null")
    if rotate not in (0, 90, 180, 270):
        raise ValueError("rotate is 0, 90, 180 or 270 degrees clockwise")
    if flip == "x":
        array = array[:, ::-1]
    elif flip == "y":
        array = array[::-1]
    return np.rot90(array, int(rotate) // 90) if rotate else array


def auto_threshold(pixels):
    """Colour distance just above the noise of the border ring, which is taken as the background."""
    margin = max(2, int(0.02 * min(pixels.shape[:2])))
    ring = np.concatenate([pixels[:margin].reshape(-1, 4), pixels[-margin:].reshape(-1, 4),
                           pixels[:, :margin].reshape(-1, 4), pixels[:, -margin:].reshape(-1, 4)])[:, :3]
    background = np.median(ring, axis=0)
    noise = np.abs(ring - background).max(axis=1)
    # The upper quartile, not the maximum: an object that touches the border must not count as noise.
    return background, float(np.clip(5 * np.percentile(noise, 75) + 0.002, 0.012, 0.12))


def silhouette(pixels, threshold=None):
    """Mask and the threshold used: None with alpha, the automatic one when no threshold is given."""
    if pixels[:, :, 3].min() < 0.99:
        return mask_of(pixels, threshold), None
    if threshold is not None:
        return mask_of(pixels, threshold), threshold
    background, threshold = auto_threshold(pixels)
    return np.abs(pixels[:, :, :3] - background).max(axis=2) > threshold, threshold


def draw_label(image, text, x, top, zoom=2):
    """Digits on a dark plate; (x, top) is the top left corner, counted from the top of the picture."""
    height, width = image.shape[:2]
    w, h = (4 * len(text) + 1) * zoom, 7 * zoom
    if w > width or h > height:
        return
    x, top = int(np.clip(x, 0, width - w)), int(np.clip(top, 0, height - h))
    base = height - top - h
    image[base : base + h, x : x + w, :3] *= 0.2
    for i, char in enumerate(text):
        bits = np.array(list(GLYPHS[char]), dtype=int).reshape(5, 3).astype(bool)
        glyph = np.kron(bits, np.ones((zoom, zoom), dtype=bool))[::-1]
        left = x + (4 * i + 1) * zoom
        image[base + zoom : base + 6 * zoom, left : left + 3 * zoom, :3][glyph] = (1.0, 1.0, 0.3)


def grid_steps(mpp, label_px=56):
    """Spacing of the labelled and of the fine lines in metres: 1-2-5 steps, labels at least `label_px` apart."""
    for power in range(-3, 3):
        for digit, parts in ((1, 5), (2, 4), (5, 5)):
            major = digit * 10.0 ** power
            if major / mpp >= label_px:
                return major, major / parts
    return 500.0, 100.0


def draw_metric_grid(image, zero_x, zero_row, mpp):
    """Lines in metres from the pixel (zero_x, zero_row), rows counted from the bottom; labels in millimetres."""
    height, width = image.shape[:2]
    major, minor = grid_steps(mpp)
    parts = round(major / minor)
    lines = []
    for across, zero, length in ((True, zero_x, width), (False, zero_row, height)):
        k = math.ceil(-zero * mpp / minor)
        while zero + k * minor / mpp < length:
            lines.append((0 if k == 0 else 1 if k % parts == 0 else 2, across, int(zero + k * minor / mpp), k))
            k += 1
    for rank, across, px, _ in sorted(lines, reverse=True):
        line = image[:, px, :3] if across else image[px, :, :3]
        if rank == 0:
            line[:] = (1.0, 0.25, 0.25)
        elif rank == 1:
            line[:] = line * 0.3 + np.array((1.0, 0.9, 0.1)) * 0.7
        else:
            line[:] = line * 0.7 + np.array((0.0, 0.75, 1.0)) * 0.3
    for rank, across, px, k in lines:
        if rank == 2:
            continue
        text = str(round(k * minor * 1000))
        if across:
            draw_label(image, text, px + 2, 1)
            draw_label(image, text, px + 2, height - 15)
        else:
            draw_label(image, text, 1, height - px - 16)
            draw_label(image, text, width, height - px - 16)
    return major, minor


def grid_picture(pixels, box, mpp, region, size):
    """The reference over magenta with a metric grid; zero is the bottom centre of the silhouette box."""
    y0, y1, x0, x1 = box
    height, width = pixels.shape[:2]
    cover = pixels[:, :, 3:4]
    rgb = pixels[:, :, :3] * cover + MAGENTA * (1 - cover)
    zero_x, zero_row = (x0 + x1 + 1) / 2, float(y0)
    left, bottom, right, top = 0.0, 0.0, float(width), float(height)
    if region is not None:
        if len(region) != 4 or region[2] <= region[0] or region[3] <= region[1]:
            raise ValueError("region is [x0, z0, x1, z1] in metres, in the coordinates of the bands")
        left, right = (float(np.clip(zero_x + v / mpp, 0, width)) for v in (region[0], region[2]))
        bottom, top = (float(np.clip(zero_row + v / mpp, 0, height)) for v in (region[1], region[3]))
        if right - left < 2 or top - bottom < 2:
            raise ValueError("region is outside the picture")
    zoom = size / max(right - left, top - bottom)
    cols = np.clip((left + (np.arange(max(int((right - left) * zoom), 1)) + 0.5) / zoom).astype(int), 0, width - 1)
    rows = np.clip((bottom + (np.arange(max(int((top - bottom) * zoom), 1)) + 0.5) / zoom).astype(int), 0, height - 1)
    picture = np.ones((len(rows), len(cols), 4), dtype=np.float32)
    picture[:, :, :3] = rgb[rows][:, cols]
    major, minor = draw_metric_grid(picture, (zero_x - left) * zoom, (zero_row - bottom) * zoom, mpp / zoom)
    return picture, major, minor


def mask_bounds(mask):
    ys, xs = np.where(mask)
    if not len(ys):
        raise ValueError("The reference has no silhouette: lower `threshold` or use an image with alpha")
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def row_runs(row):
    padded = np.concatenate(([False], row, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


def band_runs(mask, y0, y1, x0, x1, bands):
    edges = np.linspace(y0, y1 + 1, bands + 1)
    result = []
    for k in range(bands):
        a, b = int(round(edges[k])), int(round(edges[k + 1]))
        union = mask[a : max(b, a + 1), x0 : x1 + 1].any(axis=0)
        result.append((a, max(b, a + 1), row_runs(union)))
    return result


@handler
def measure_profile(reference, height_m, bands=24, threshold=0.06, grid=False, region=None, grid_size=1280, out=None):
    pixels = read_pixels(reference)
    mask = mask_of(pixels, threshold)
    y0, y1, x0, x1 = mask_bounds(mask)
    mpp = height_m / (y1 - y0 + 1)
    centre = (x1 - x0 + 1) / 2
    profile = []
    for a, b, runs in band_runs(mask, y0, y1, x0, x1, bands):
        if not runs:
            profile.append({"z0": rnd((a - y0) * mpp, 4), "z1": rnd((b - y0) * mpp, 4), "empty": True})
            continue
        left, right = runs[0][0], runs[-1][1]
        profile.append({
            "z0": rnd((a - y0) * mpp, 4),
            "z1": rnd((b - y0) * mpp, 4),
            "width": rnd((right - left) * mpp, 4),
            "left": rnd((left - centre) * mpp, 4),
            "right": rnd((right - centre) * mpp, 4),
            "runs": [[rnd((l - centre) * mpp, 4), rnd((r - centre) * mpp, 4)] for l, r in runs],
            "filled_width": rnd(sum(r - l for l, r in runs) * mpp, 4),
        })
    result = {
        "height_m": height_m,
        "width_m": rnd((x1 - x0 + 1) * mpp, 4),
        "meters_per_pixel": rnd(mpp, 6),
        "note": "x is measured from the centre of the silhouette box, z from its bottom; runs are separate parts in a band (arms, legs)",
        "bands": profile,
    }
    if grid:
        picture, major, minor = grid_picture(pixels, (y0, y1, x0, x1), mpp, region, grid_size)
        path = Path(out).expanduser() if out else RENDERS / "reference_grid.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_pixels(path, picture)
        result["grid"] = {
            "path": str(path),
            "size": [picture.shape[1], picture.shape[0]],
            "labelled_step_m": major,
            "fine_step_m": minor,
            "note": "labels are millimetres in the coordinates of the bands: x from the red vertical line (centre of the silhouette box), z up from the red horizontal line (its bottom); yellow lines carry labels, blue lines are the fine step; pass region=[x0, z0, x1, z1] in metres to zoom in",
        }
    return result


def outline_loops(mask):
    padded = np.pad(mask, 1)
    core = padded[1:-1, 1:-1]
    below, above = ~padded[:-2, 1:-1], ~padded[2:, 1:-1]
    left, right = ~padded[1:-1, :-2], ~padded[1:-1, 2:]
    edges = {}

    def add(sel, start, end):
        ys, xs = np.where(core & sel)
        for y, x in zip(ys.tolist(), xs.tolist()):
            edges.setdefault((x + start[0], y + start[1]), []).append((x + end[0], y + end[1]))

    add(below, (0, 0), (1, 0))
    add(right, (1, 0), (1, 1))
    add(above, (1, 1), (0, 1))
    add(left, (0, 1), (0, 0))
    loops = []
    while edges:
        start = next(iter(edges))
        loop, here = [start], start
        while True:
            nxt = edges[here].pop()
            if not edges[here]:
                del edges[here]
            if nxt == start:
                break
            loop.append(nxt)
            here = nxt
            if here not in edges:
                break
        loops.append(loop)
    return loops


def loop_area(loop):
    pts = np.array(loop, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def simplify_loop(points, epsilon):
    pts = np.array(points, dtype=float)
    n = len(pts)
    if n < 4:
        return pts
    far = int(np.argmax(np.linalg.norm(pts - pts[0], axis=1)))
    keep = np.zeros(n, dtype=bool)
    keep[[0, far]] = True
    stack = [(0, far), (far, n)]
    while stack:
        a, b = stack.pop()
        end = pts[b % n]
        seg = end - pts[a]
        norm = np.linalg.norm(seg)
        span = pts[a + 1 : b]
        if not len(span):
            continue
        d = np.linalg.norm(span - pts[a], axis=1) if norm < 1e-12 else np.abs(seg[0] * (span[:, 1] - pts[a][1]) - seg[1] * (span[:, 0] - pts[a][0])) / norm
        i = int(np.argmax(d))
        if d[i] > epsilon:
            mid = a + 1 + i
            keep[mid] = True
            stack += [(a, mid), (mid, b)]
    return pts[keep]


def inside_loop(loop, point):
    pts = np.array(loop, dtype=float)
    a, b = pts, np.roll(pts, -1, axis=0)
    x, y = point
    spans = (a[:, 1] > y) != (b[:, 1] > y)
    crossing = a[spans, 0] + (y - a[spans, 1]) * (b[spans, 0] - a[spans, 0]) / (b[spans, 1] - a[spans, 1])
    return int((crossing > x).sum()) % 2 == 1


def hole_seed(loop):
    """Centre of the hole pixel at the first edge: loops keep the silhouette on their left, so the hole is on the right."""
    (x0, y0), (x1, y1) = loop[0], loop[1]
    return (x0 + x1) / 2 + (y1 - y0) / 2, (y0 + y1) / 2 - (x1 - x0) / 2


@handler
def trace_outline(reference, height_m, simplify=0.01, threshold=0.06, holes=False, min_hole=0.002):
    mask = reference_mask(reference, threshold)
    y0, y1, x0, x1 = mask_bounds(mask)
    mpp = height_m / (y1 - y0 + 1)
    loops = outline_loops(mask[y0 : y1 + 1, x0 : x1 + 1])
    outer = max(loops, key=lambda lp: abs(loop_area(lp)))
    width = (x1 - x0 + 1)

    def metres(loop):
        return [[rnd((x - width / 2) * mpp, 4), rnd(y * mpp, 4)] for x, y in simplify_loop(loop, simplify / mpp)]

    pts = metres(outer)
    result = {
        "points": pts,
        "count": len(pts),
        "height_m": height_m,
        "width_m": rnd(width * mpp, 4),
        "area_m2": rnd(abs(loop_area(outer)) * mpp * mpp, 4),
        "note": "[x, z] in metres: x from the centre of the box, z from its bottom; closed, counter-clockwise; holes are left out (holes=true returns them)",
    }
    if holes:
        outer_area = loop_area(outer)
        found = []
        for loop in loops:
            area = loop_area(loop)
            if area * outer_area < 0 and abs(area) >= min_hole * abs(outer_area) and inside_loop(outer, hole_seed(loop)):
                points = metres(loop)
                if len(points) >= 3:
                    found.append({"points": points, "area_m2": rnd(abs(area) * mpp * mpp, 6)})
        result["holes"] = sorted(found, key=lambda h: -h["area_m2"])
        result["note"] = ("[x, z] in metres: x from the centre of the box, z from its bottom; closed, counter-clockwise. holes: openings inside "
                          "the outline, largest first, clockwise; give their points to extrude_profile(holes=...) to cut them")
    return result


PLANES = {"XZ": (0, 2, 1), "YZ": (1, 2, 0), "XY": (0, 1, 2)}


def cut_with_temporary(target, cutter, operation):
    """Boolean with a throw-away cutter. Both are closed solids made here, so a flawed result is kept and reported."""
    # hard loads after this module on reload_addon: a top-level import would keep its old code.
    from .hard import boolean_merge, remove_with_data

    try:
        return boolean_merge(target, cutter, operation, allow_open=True)
    finally:
        remove_with_data(cutter)


def extrusion(name, points, depth, plane, at):
    a_axis, b_axis, d_axis = PLANES[plane.upper()]
    bm = bmesh.new()
    rings = []
    for offset in (-depth / 2, depth / 2):
        ring = []
        for a, b in points:
            p = [0.0, 0.0, 0.0]
            p[a_axis], p[b_axis], p[d_axis] = a + at[a_axis], b + at[b_axis], offset + at[d_axis]
            ring.append(bm.verts.new(p))
        rings.append(ring)
    n = len(points)
    bm.faces.new(rings[0])
    bm.faces.new(reversed(rings[1]))
    for i in range(n):
        bm.faces.new((rings[0][i], rings[0][(i + 1) % n], rings[1][(i + 1) % n], rings[1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return new_mesh_object(name, mesh)


@handler
def extrude_profile(name, points, depth, plane="XZ", at=(0, 0, 0), holes=None):
    if len(points) < 3:
        raise ValueError("A profile needs at least 3 points")
    if plane.upper() not in PLANES:
        raise ValueError("plane is XZ, YZ or XY")
    holes = [h["points"] if isinstance(h, dict) else h for h in holes or []]
    if any(len(h) < 3 for h in holes):
        raise ValueError("Each hole is a polygon of at least 3 points")
    solid = extrusion(name, [tuple(p) for p in points], depth, plane, at)
    warnings = []
    for index, hole in enumerate(holes):
        cutter = extrusion(f"{name}_hole_tmp{index}", [tuple(p) for p in hole], depth * 1.5, plane, at)
        warning = cut_with_temporary(solid, cutter, "DIFFERENCE").get("warning")
        if warning:
            warnings.append(warning)
    result = describe(solid)
    if holes:
        result["holes_cut"] = len(holes)
    if warnings:
        result["warnings"] = warnings
    return result


def section_of(runs, part, centre_px):
    if not runs:
        return None
    if part == "largest":
        l, r = max(runs, key=lambda run: run[1] - run[0])
    else:
        l, r = runs[0][0], runs[-1][1]
    return (l + r) / 2 - centre_px, r - l


@handler
def loft_from_masks(name, front, side, height_m, bands=16, at=(0, 0, 0), segments=20, roundness=2.5, threshold=0.06,
                    part="largest", side_faces="left", z_range=(0.0, 1.0), subdivisions=0):
    views = {}
    for key, path in (("front", front), ("side", side)):
        mask = reference_mask(path, threshold)
        y0, y1, x0, x1 = mask_bounds(mask)
        views[key] = (mask, y0, y1, x0, x1, height_m / (y1 - y0 + 1))
    sections, spans = [], []
    z_lo, z_hi = z_range
    rows = {k: band_runs(v[0], v[1], v[2], v[3], v[4], bands) for k, v in views.items()}
    for k in range(bands):
        t0, t1 = k / bands, (k + 1) / bands
        if t1 <= z_lo or t0 >= z_hi:
            continue
        f = section_of(rows["front"][k][2], part, (views["front"][4] - views["front"][3] + 1) / 2)
        s = section_of(rows["side"][k][2], part, (views["side"][4] - views["side"][3] + 1) / 2)
        if f is None or s is None:
            continue
        sign = 1 if side_faces == "left" else -1
        sections.append({
            "at": [at[0] + f[0] * views["front"][5], at[1] + sign * s[0] * views["side"][5], at[2] + (t0 + t1) / 2 * height_m],
            "size": [max(f[1] * views["front"][5], 0.005), max(s[1] * views["side"][5], 0.005)],
            "roundness": roundness,
        })
        spans.append((t0, t1))
    if len(sections) < 2:
        raise ValueError("Fewer than 2 bands have a silhouette in both views")

    def moved_to(section, t):
        return {**section, "at": [*section["at"][:2], at[2] + t * height_m]}

    # A section sits in the middle of its band: the end bands repeat at their outer edge so the body spans the full height.
    sections = [moved_to(sections[0], spans[0][0]), *sections, moved_to(sections[-1], spans[-1][1])]
    return loft(name, sections, "Z", segments, True, subdivisions)


@handler
def visual_hull(name, front, side, height_m, simplify=0.01, threshold=0.06, side_faces="left", at=(0, 0, 0)):
    def outline(path):
        return trace_outline(path, height_m, simplify, threshold)

    f, s = outline(front), outline(side)
    sign = 1 if side_faces == "left" else -1
    f_pts = [(x, z) for x, z in f["points"]]
    s_pts = [(sign * x, z) for x, z in s["points"]]
    if sign < 0:
        s_pts.reverse()
    reach = max(f["width_m"], s["width_m"]) * 1.5
    a = extrusion(name, f_pts, reach, "XZ", (at[0], at[1], at[2]))
    b = extrusion(name + "_side_tmp", s_pts, reach, "YZ", (at[0], at[1], at[2]))
    try:
        cut = cut_with_temporary(a, b, "INTERSECT")
    except ValueError:
        mesh = a.data
        bpy.data.objects.remove(a)
        bpy.data.meshes.remove(mesh)
        raise ValueError("The two silhouettes do not intersect: check side_faces and the alignment of the images") from None
    result = describe(a)
    if "warning" in cut:
        result["warning"] = cut["warning"]
    result["note"] = "Matches both silhouettes. Depth inside is a straight extrusion: refine it with sculpt (grab, smooth) or more views."
    return result


def label_runs(mask, diagonal=True):
    """Connected runs of each row: the runs as (y, start, end) and the blob root of each run."""
    reach = 0 if diagonal else 1
    runs, parent = [], []

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    previous = []
    for y in range(mask.shape[0]):
        current, first = [], 0
        for start, end in row_runs(mask[y]):
            index = len(runs)
            runs.append((y, start, end))
            parent.append(index)
            while first < len(previous) and runs[previous[first]][2] < start + reach:
                first += 1
            k = first
            while k < len(previous) and runs[previous[k]][1] + reach <= end:
                a, b = find(index), find(previous[k])
                if a != b:
                    parent[b] = a
                k += 1
            current.append(index)
        previous = current
    return runs, [find(i) for i in range(len(runs))]


def largest_component(mask):
    """Keep the biggest 8-connected blob; also return how many blobs there were."""
    runs, roots = label_runs(mask)
    totals = {}
    for (_, start, end), root in zip(runs, roots):
        totals[root] = totals.get(root, 0) + end - start
    if not totals:
        return mask, 0
    best = max(totals, key=totals.get)
    kept = np.zeros_like(mask)
    for (y, start, end), root in zip(runs, roots):
        if root == best:
            kept[y, start:end] = True
    return kept, len(totals)


def enclosed_holes(mask):
    """Background blobs that do not reach the picture border, each as a list of runs (y, start, end)."""
    padded = np.pad(~mask, 1, constant_values=True)
    runs, roots = label_runs(padded, diagonal=False)
    holes = {}
    for (y, start, end), root in zip(runs, roots):
        if root != roots[0]:
            holes.setdefault(root, []).append((y - 1, start - 1, end - 1))
    return list(holes.values())


def shrunk(image, longest):
    step = max(1, math.ceil(max(image.shape[:2]) / longest))
    return image[::step, ::step]


def mask_preview(rgb, solid, filled, opened):
    """Cut-out over magenta and the mask (white object, green filled holes, red holes left open), one above or beside the other."""
    cut = np.where(solid[..., None], rgb, MAGENTA)
    chart = np.zeros_like(cut)
    chart[solid] = 1.0
    chart[filled] = (0.2, 0.9, 0.3)
    chart[opened] = (0.95, 0.2, 0.2)
    cut, chart = shrunk(cut, 800), shrunk(chart, 800)
    wide = cut.shape[1] >= cut.shape[0]
    gap = np.full((4, cut.shape[1], 3) if wide else (cut.shape[0], 4, 3), 0.5, dtype=np.float32)
    sheet = np.concatenate([chart, gap, cut], axis=0) if wide else np.concatenate([cut, gap, chart], axis=1)
    return np.dstack([sheet, np.ones(sheet.shape[:2], dtype=np.float32)]), "top: cut-out, bottom: mask" if wide else "left: cut-out, right: mask"


@handler
def prepare_reference(image, out=None, crop=None, threshold=None, keep="largest", pad=0.02, fill_holes=0.01, flip=None, rotate=0):
    pixels = read_pixels(image)
    height, width = pixels.shape[:2]
    if crop:
        x0, y0, x1, y1 = crop
        a, b = int(round(x0 * width)), int(round(x1 * width))
        top, bottom = int(round(y0 * height)), int(round(y1 * height))
        pixels = pixels[height - bottom : height - top, a:b]
    if min(pixels.shape[:2]) < 4:
        raise ValueError("The crop is empty")
    mask, used = silhouette(pixels, threshold)
    found = int(mask.sum())
    blobs = None
    if keep == "largest":
        mask, blobs = largest_component(mask)
    if not mask.any():
        raise ValueError("No silhouette found: lower `threshold`, widen the crop, or give an image with a plain background")
    area = int(mask.sum())
    touching = [side for side, line in (("left", mask[:, 0]), ("right", mask[:, -1]), ("bottom", mask[0]), ("top", mask[-1])) if line.any()]
    holes = enclosed_holes(mask)
    filled, opened = np.zeros_like(mask), np.zeros_like(mask)
    left_open = 0
    for hole in holes:
        stays = sum(end - start for _, start, end in hole) > fill_holes * area
        left_open += stays
        for y, start, end in hole:
            (opened if stays else filled)[y, start:end] = True
    solid = mask | filled
    ys, xs = np.where(solid)
    margin = int(pad * max(pixels.shape[:2]))
    y0, y1 = max(ys.min() - margin, 0), min(ys.max() + 1 + margin, pixels.shape[0])
    x0, x1 = max(xs.min() - margin, 0), min(xs.max() + 1 + margin, pixels.shape[1])
    result = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.float32)
    result[..., :3] = pixels[y0:y1, x0:x1, :3]
    result[..., 3] = solid[y0:y1, x0:x1]
    result = turned(result, flip, rotate)
    path = Path(out).expanduser() if out else RENDERS / "prepared_reference.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_pixels(path, result, alpha=True)
    preview, layout = mask_preview(result[..., :3], result[..., 3] > 0.5, turned(filled[y0:y1, x0:x1], flip, rotate), turned(opened[y0:y1, x0:x1], flip, rotate))
    preview_path = path.with_name(path.stem + "_preview.png")
    write_pixels(preview_path, preview)
    answer = {
        "path": str(path),
        "size": [int(result.shape[1]), int(result.shape[0])],
        "silhouette_share": rnd(float(solid[y0:y1, x0:x1].mean()), 3),
        "threshold": "alpha" if used is None else rnd(used, 4),
        "blobs_found": blobs,
        "blobs_dropped": None if blobs is None else blobs - 1,
        "dropped_area_share": rnd(1 - area / found, 4),
        "holes": {
            "before": {"count": len(holes), "area_share": rnd(float((filled | opened).sum()) / area, 4)},
            "filled": len(holes) - left_open,
            "after": {"count": left_open, "area_share": rnd(float(opened.sum()) / area, 4)},
        },
        "kept": keep,
        "flip": flip,
        "rotate": rotate,
        "preview": str(preview_path),
        "preview_legend": f"{layout}. Cut-out: what stays, over magenta. Mask: white object, green filled holes, red holes left open, black background.",
        "note": "Background removed (alpha). Use this file as the reference of compare_view, fit_to_reference, visual_hull. Crop is [x0, y0, x1, y1] as fractions of the image from the top left. hole area_share is relative to the object area.",
    }
    warnings = []
    if left_open > 3:
        warnings.append(f"{left_open} holes stay open in the mask: if they are not real openings, raise fill_holes (share of the object area, now {fill_holes}) or lower threshold")
    if touching:
        warnings.append(f"the silhouette touches the {', '.join(touching)} border of the crop: the object may be cut, or the background is not plain; widen the crop")
    if area < 0.9 * found:
        warnings.append(f"{rnd(100 * (1 - area / found), 1)}% of the silhouette was in other blobs and is dropped: if the object fell apart, lower threshold or use keep='all'")
    if warnings:
        answer["warning"] = "; ".join(warnings)
    return answer
