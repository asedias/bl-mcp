"""Organic forms and ground: noise displacement, terrain, rocks, road carving."""

import random

import bmesh
import bpy
import numpy as np
from mathutils import Vector, noise

from .core import *  # noqa: F401,F403
from .core import handler, link_new
from .meshops import FALLOFFS, commit, edit_bmesh, region_of, region_weights, summary

MAX_TERRAIN_VERTS = 160000
DISPLACE_MODES = ("normal", "z", "vector")


def seed_offsets(seed, count):
    """Distinct noise lattice offsets per octave and axis; the seed is the only state."""
    rng = random.Random(seed)
    return [Vector((rng.uniform(-500, 500), rng.uniform(-500, 500), rng.uniform(-500, 500))) for _ in range(count)]


def fbm(point, offsets, octaves):
    """Fractal noise in about [-1, 1], clamped so callers can rely on the range."""
    total, amplitude, frequency, norm = 0.0, 1.0, 1.0, 0.0
    for octave in range(octaves):
        total += amplitude * noise.noise(point * frequency + offsets[octave])
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return max(-1.0, min(1.0, 1.4 * total / norm))


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def new_object(name, mesh, at, smooth):
    mesh.update(calc_edges=True)
    for polygon in mesh.polygons:
        polygon.use_smooth = smooth
    obj = bpy.data.objects.new(name, mesh)
    obj.location = Vector(at)
    return link_new(obj)


def require_positive(**values):
    for key, value in values.items():
        if value <= 0:
            raise ValueError(f"{key} must be above 0")


@handler
def noise_displace(object, amount, scale=1.0, seed=0, where=None, mode="normal", octaves=3, spread=0.0, falloff="smooth"):
    if mode not in DISPLACE_MODES:
        raise ValueError(f"mode is one of {list(DISPLACE_MODES)}")
    if falloff not in FALLOFFS:
        raise ValueError(f"falloff is one of {sorted(FALLOFFS)}")
    if not 1 <= octaves <= 8:
        raise ValueError("octaves is 1 to 8")
    require_positive(scale=scale)
    obj = get_object(object)
    bm = edit_bmesh(obj)
    if where is None:
        weights = {v.index: 1.0 for v in bm.verts}
    else:
        weights = region_weights(bm, obj, region_of(bm, obj, where, "faces"), spread, falloff)
    matrix = obj.matrix_world
    inverse = matrix.inverted_safe()
    normal_matrix = matrix.to_3x3().inverted_safe().transposed()
    bm.normal_update()
    axes = 3 if mode == "vector" else 1
    offsets = [seed_offsets(seed + 7919 * a, octaves) for a in range(axes)]
    biggest = 0.0
    for v in bm.verts:
        weight = weights.get(v.index)
        if not weight:
            continue
        world = matrix @ v.co
        point = world / scale
        if mode == "vector":
            push = Vector([fbm(point, offsets[a], octaves) for a in range(3)])
            if push.length > 1.0:
                push.normalize()
        elif mode == "z":
            push = Vector((0, 0, fbm(point, offsets[0], octaves)))
        else:
            push = (normal_matrix @ v.normal).normalized() * fbm(point, offsets[0], octaves)
        shift = push * amount * weight
        biggest = max(biggest, shift.length)
        v.co = inverse @ (world + shift)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    commit(bm, obj)
    return summary(obj, vertices_moved=len(weights), largest_shift=rnd(biggest, 5))


def height_grid(xs, ys, scale, seed, octaves):
    offset = seed_offsets(seed, octaves)
    heights = np.empty((len(xs), len(ys)))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            heights[i, j] = fbm(Vector((x / scale, y / scale, 0.0)), offset, octaves)
    low, high = heights.min(), heights.max()
    return (heights - low) / (high - low) if high > low else np.zeros_like(heights)


def island_mask(X, Y, width, depth, fraction):
    edge = np.minimum(width / 2 - np.abs(X), depth / 2 - np.abs(Y))
    return smoothstep(edge / (fraction * min(width, depth) / 2))


def flatten_centre(heights, X, Y, radius, resolution):
    level = heights[np.unravel_index(np.argmin(np.hypot(X, Y)), heights.shape)]
    blend = max(radius * 0.5, 2 * resolution)
    t = smoothstep((np.hypot(X, Y) - radius) / blend)
    return level * (1 - t) + heights * t


def border_loop(nx, ny):
    """Grid border indices in counter-clockwise order seen from above."""
    at = lambda i, j: i * ny + j  # noqa: E731
    return (
        [at(i, 0) for i in range(nx)]
        + [at(nx - 1, j) for j in range(1, ny)]
        + [at(i, ny - 1) for i in range(nx - 2, -1, -1)]
        + [at(0, j) for j in range(ny - 2, 0, -1)]
    )


def grid_triangles(nx, ny):
    at = lambda i, j: i * ny + j  # noqa: E731
    tris = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            a, b, c, d = at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1)
            tris += [(a, b, d), (b, c, d)] if (i + j) % 2 else [(a, b, c), (a, c, d)]
    return tris


def skirt_triangles(loop, base_start):
    """Side wall plus a bottom fan around a centre vertex (index base_start + len(loop)); no collinear slivers."""
    n = len(loop)
    base = [base_start + k for k in range(n)]
    centre = base_start + n
    sides = []
    for k in range(n):
        k2 = (k + 1) % n
        sides += [(loop[k], base[k], base[k2]), (loop[k], base[k2], loop[k2])]
    bottom = [(centre, base[(k + 1) % n], base[k]) for k in range(n)]
    return sides + bottom


@handler
def terrain(name, size=(20.0, 20.0), resolution=0.5, height=2.0, scale=8.0, seed=0, octaves=4, edge_falloff=0.0,
            flat_center=0.0, at=(0, 0, 0), plateau_levels=None, skirt=None, smooth=False):
    width, depth = size
    require_positive(width=width, depth=depth, resolution=resolution, height=height, scale=scale)
    if not 1 <= octaves <= 8:
        raise ValueError("octaves is 1 to 8")
    if not 0 <= edge_falloff <= 1:
        raise ValueError("edge_falloff is 0 to 1 (the share of the half size that fades to zero)")
    if plateau_levels is not None and plateau_levels < 2:
        raise ValueError("plateau_levels is at least 2")
    nx, ny = int(round(width / resolution)) + 1, int(round(depth / resolution)) + 1
    if nx < 2 or ny < 2:
        raise ValueError("resolution is larger than the terrain: lower resolution")
    if nx * ny > MAX_TERRAIN_VERTS:
        raise ValueError(f"{nx * ny} vertices is over the limit of {MAX_TERRAIN_VERTS}: raise resolution or reduce size")
    xs, ys = np.linspace(-width / 2, width / 2, nx), np.linspace(-depth / 2, depth / 2, ny)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    heights = height_grid(xs, ys, scale, seed, octaves)
    if plateau_levels:
        steps = plateau_levels - 1
        heights = np.round(heights * steps) / steps
    if edge_falloff > 0:
        heights = heights * island_mask(X, Y, width, depth, edge_falloff)
    if flat_center > 0:
        heights = flatten_centre(heights, X, Y, flat_center, resolution)
    z = heights * height
    verts = np.stack([X.ravel(), Y.ravel(), z.ravel()], axis=1)
    faces = grid_triangles(nx, ny)
    if skirt is not None:
        loop = border_loop(nx, ny)
        floor = skirt - at[2]
        if floor >= z.ravel()[loop].min():
            raise ValueError(f"skirt z={skirt} must be below the lowest border height {rnd(at[2] + z.ravel()[loop].min(), 3)}")
        base = verts[loop].copy()
        base[:, 2] = floor
        faces += skirt_triangles(loop, len(verts))
        middle = np.array([[0.0, 0.0, floor]])
        verts = np.vstack([verts, base, middle])
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts.tolist(), [], faces)
    obj = new_object(name, mesh, at, smooth)
    return summary(obj, vertices=len(verts), closed=skirt is not None, height_range=[rnd(float(z.min()), 3), rnd(float(z.max()), 3)])


@handler
def path_carve(terrain, points, width, depth, falloff=None):
    obj = get_object(terrain)
    if obj.type != "MESH":
        raise ValueError(f"{terrain} is {obj.type}, not MESH")
    if len(points) < 2:
        raise ValueError("Give at least 2 points")
    require_positive(width=width)
    edge = width / 2 if falloff is None else falloff
    matrix = np.array(obj.matrix_world)
    inverse = np.linalg.inv(matrix)
    count = len(obj.data.vertices)
    co = np.empty(count * 3)
    obj.data.vertices.foreach_get("co", co)
    local = co.reshape(-1, 3)
    world = (matrix[:3, :3] @ local.T).T + matrix[:3, 3]
    xy = world[:, :2]
    nearest = np.full(count, np.inf)
    for a, b in zip(points[:-1], points[1:]):
        a, b = np.array(a[:2], dtype=float), np.array(b[:2], dtype=float)
        ab = b - a
        t = np.clip(((xy - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
        nearest = np.minimum(nearest, np.linalg.norm(xy - (a + t[:, None] * ab), axis=1))
    weight = 1.0 - smoothstep((nearest - width / 2) / max(edge, 1e-6)) if edge > 0 else (nearest <= width / 2).astype(float)
    world[:, 2] -= depth * weight
    moved = (inverse[:3, :3] @ (world - matrix[:3, 3]).T).T
    obj.data.vertices.foreach_set("co", moved.ravel())
    obj.data.update()
    bpy.context.view_layer.update()
    return summary(obj, vertices_carved=int((weight > 0).sum()))


def rock_vertices(bm, seed, roughness, flatness):
    rng = random.Random(seed)
    offsets = seed_offsets(seed, 3)
    stretch = Vector((rng.uniform(0.8, 1.2), rng.uniform(0.8, 1.2), 1 - 0.7 * flatness))
    for v in bm.verts:
        direction = v.co.normalized()
        lump = fbm(direction * 1.5, offsets, 3)
        v.co = Vector(c * s for c, s in zip(direction * (1 + roughness * lump), stretch))


def fit_rock(bm, radius):
    """Scale to the wanted half width and move the origin to the bottom centre."""
    xs, ys, zs = ([v.co[i] for v in bm.verts] for i in range(3))
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2
    bmesh.ops.scale(bm, vec=(radius / half,) * 3, verts=bm.verts)
    xs, ys, zs = ([v.co[i] for v in bm.verts] for i in range(3))
    bmesh.ops.translate(bm, vec=(-(max(xs) + min(xs)) / 2, -(max(ys) + min(ys)) / 2, -min(zs)), verts=bm.verts)


@handler
def rock(name, radius=0.5, seed=0, roughness=0.3, flatness=0.0, detail=3, at=(0, 0, 0), facets=False):
    require_positive(radius=radius)
    if not 1 <= detail <= 5:
        raise ValueError("detail is 1 to 5 (1 = 20 faces, 2 = 80, 3 = 320)")
    if not 0 <= flatness < 1:
        raise ValueError("flatness is from 0 up to, not including, 1")
    if not 0 <= roughness <= 1:
        raise ValueError("roughness is 0 to 1")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=detail, radius=1.0)
    rock_vertices(bm, seed, roughness, flatness)
    fit_rock(bm, radius)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = new_object(name, mesh, at, smooth=not facets)
    return summary(obj, faces=len(obj.data.polygons), flat_shaded=facets)
