"""From picture to world: reference overlay, camera match by silhouette, pixel and world conversions."""

import math
import time

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from .compare import boundary, inner_edges
from .core import *  # noqa: F401,F403
from .core import anchor_point, handler, make_caster, move_world
from .profiles import draw_metric_grid

MODES = ("blend", "edges", "difference", "split")
MAX_FRAME = 1280
MAX_EL = 85.0
STEPS = {"az": 10.0, "el": 6.0, "dist": 0.1, "shift": 0.06, "roll": 2.0, "fov": 0.06}


def camera_of(name):
    obj = get_object(name)
    if obj.type != "CAMERA":
        raise ValueError(f"{name!r} is not a camera")
    if obj.data.type == "PANO":
        raise ValueError("Panoramic cameras are not supported: use a perspective or orthographic camera")
    return obj


def frame_of(image_size):
    try:
        width, height = (float(v) for v in image_size)
    except (TypeError, ValueError):
        raise ValueError("image_size is [width, height] in pixels") from None
    if width <= 0 or height <= 0:
        raise ValueError("image_size must be positive")
    return width, height


def matrices(cam, width, height):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    projection = cam.calc_matrix_camera(depsgraph, x=int(round(width)) or 1, y=int(round(height)) or 1)
    return projection, cam.matrix_world.normalized().inverted()


def unproject(inverse, ndc_x, ndc_y, ndc_z):
    point = inverse @ Vector((ndc_x, ndc_y, ndc_z, 1.0))
    return point.xyz / point.w


def pixel_ray(cam, inverse, pixel, width, height):
    ndc_x, ndc_y = 2 * pixel[0] / width - 1, 1 - 2 * pixel[1] / height
    near, far = unproject(inverse, ndc_x, ndc_y, -1.0), unproject(inverse, ndc_x, ndc_y, 1.0)
    origin = near if cam.data.type == "ORTHO" else cam.matrix_world.translation.copy()
    return origin, (far - near).normalized()


def hit_plane(cam, origin, direction, point, normal):
    denom = normal.dot(direction)
    if abs(denom) < 1e-9:
        return None
    t = normal.dot(point - origin) / denom
    if cam.data.type != "ORTHO" and t <= 0:
        return None
    return origin + direction * t


def plane_of(plane_z, plane):
    if plane is None:
        return Vector((0, 0, plane_z)), Vector((0, 0, 1))
    try:
        point, normal = Vector(plane["point"]), Vector(plane["normal"])
    except (KeyError, TypeError, ValueError):
        raise ValueError('plane is {"point": [x, y, z], "normal": [x, y, z]}') from None
    if normal.length < 1e-9:
        raise ValueError("The plane normal must not be zero")
    return point, normal.normalized()


def pixel_list(pixels):
    if not len(pixels):
        raise ValueError("pixels is a list of [x, y]")
    if isinstance(pixels[0], (int, float)):
        pixels = [pixels]
    for p in pixels:
        if len(p) != 2:
            raise ValueError("pixels is a list of [x, y]")
    return pixels


@handler
def pixel_to_world(camera, pixels, image_size, plane_z=0.0, plane=None):
    cam = camera_of(camera)
    width, height = frame_of(image_size)
    point, normal = plane_of(plane_z, plane)
    projection, view = matrices(cam, width, height)
    inverse = (projection @ view).inverted()
    points = []
    for pixel in pixel_list(pixels):
        origin, direction = pixel_ray(cam, inverse, pixel, width, height)
        hit = hit_plane(cam, origin, direction, point, normal)
        points.append(None if hit is None else rvec(hit))
    return {
        "points": points,
        "camera": cam.name,
        "plane": {"point": rvec(point), "normal": rvec(normal)},
        "note": "null: the ray is parallel to the plane or the plane is behind the camera",
    }


def first_surface(origin, direction, ignored):
    cast = make_caster()
    start = origin
    for _ in range(64):
        hit = cast(start, direction)
        if hit is None:
            return None
        location, _, obj = hit
        if obj.name not in ignored:
            return location, obj
        start = location + direction * 1e-4
    return None


@handler
def place_at_pixel(object, camera, pixel, image_size, plane_z=None, anchor=(0.5, 0.5, 0)):
    cam = camera_of(camera)
    obj = get_object(object)
    width, height = frame_of(image_size)
    if len(pixel) != 2:
        raise ValueError("pixel is [x, y]")
    parts = group_of(obj)
    box = require_bounds(parts)
    projection, view = matrices(cam, width, height)
    origin, direction = pixel_ray(cam, (projection @ view).inverted(), pixel, width, height)
    surface = None
    if plane_z is None:
        found = first_surface(origin, direction, {o.name for o in parts})
        if found is not None:
            target, surface = found[0], found[1].name
    if surface is None:
        level = box[0].z if plane_z is None else plane_z
        target = hit_plane(cam, origin, direction, Vector((0, 0, level)), Vector((0, 0, 1)))
        if target is None:
            raise ValueError("The ray through this pixel does not reach the plane z=%s: pick a pixel below the horizon or another plane_z" % rnd(level))
    move_world(obj, target - anchor_point(box, anchor))
    result = describe(obj)
    result["placed_on"] = surface or f"plane z={rnd(target.z)}"
    result["target"] = rvec(target)
    return result


def render_through(objs, cam, width, height, look, path):
    with temp_scene(objs, "mask" if look == "mask" else "material") as scene:
        if look != "mask":
            configure_extra_look(scene, look)
        scene.collection.objects.link(cam)
        scene.camera = cam
        scene.render.resolution_x, scene.render.resolution_y = int(width), int(height)
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True, scene=scene.name)
    return read_pixels(path)


def resample(pixels, width, height):
    src_h, src_w = pixels.shape[:2]
    if (src_w, src_h) == (width, height):
        return pixels
    image = bpy.data.images.new("bl_resample", src_w, src_h, alpha=True)
    try:
        image.pixels.foreach_set(np.ascontiguousarray(pixels, dtype=np.float32).ravel())
        image.scale(width, height)
        flat = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(flat)
    finally:
        bpy.data.images.remove(image)
    return flat.reshape(height, width, 4)


def thick(mask):
    grown = mask.copy()
    for axis in (0, 1):
        grown |= np.roll(mask, 1, axis) | np.roll(mask, -1, axis)
    return grown


def iou_of(a, b):
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 0.0


def compose(mode, clay, ref_rgb, ref_mask, model, alpha, split):
    if mode == "blend":
        return ref_rgb * alpha + clay * (1 - alpha)
    if mode == "difference":
        return np.abs(ref_rgb - clay)
    if mode == "split":
        out = clay.copy()
        edge = int(round(np.clip(split, 0, 1) * clay.shape[1]))
        out[:, :edge] = ref_rgb[:, :edge]
        out[:, max(edge - 1, 0) : edge + 1] = 1.0
        return out
    out = clay * 0.6
    out[thick(inner_edges(ref_rgb.mean(axis=2), ref_mask))] = (1.0, 0.85, 0.2)
    out[thick(boundary(ref_mask))] = (1.0, 0.15, 0.15)
    out[thick(boundary(model))] = (0.2, 1.0, 0.3)
    return out


LEGENDS = {
    "blend": "reference weighted by alpha over the model (clay look)",
    "edges": "red: reference outline, yellow: reference inner edges, green: model outline, over the dimmed model",
    "difference": "absolute difference of reference and model render: black is a match",
    "split": "reference left of the white line, model right of it: the outline must continue across the line",
}


@handler
def overlay_reference(reference, camera=None, names=None, size=1024, alpha=0.5, mode="blend", threshold=0.06, out=None, split=0.5,
                      grid_height_m=None):
    if mode not in MODES:
        raise ValueError(f"mode is one of {', '.join(MODES)}")
    cam = camera_of(camera) if camera else bpy.context.scene.camera
    if cam is None:
        raise ValueError("The scene has no camera. Call set_camera first, or match_camera to fit one to the reference, or pass camera=")
    objs = with_children(names) if names else scene_objects()
    require_bounds(objs)
    pixels = read_pixels(reference)
    src_h, src_w = pixels.shape[:2]
    scale = size / max(src_w, src_h)
    width, height = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    RENDERS.mkdir(parents=True, exist_ok=True)
    clay = render_through(objs, cam, width, height, "clay", RENDERS / "overlay_clay.png")[:, :, :3]
    model = render_through(objs, cam, width, height, "mask", RENDERS / "overlay_mask.png")[:, :, 0] > 0.5
    ref_mask = resize_nearest(mask_of(pixels, threshold), height, width)
    scaled = resample(pixels, width, height)
    cover = scaled[:, :, 3:4]
    ref_rgb = scaled[:, :, :3] * cover + 0.1 * (1 - cover)
    image = np.ones((height, width, 4), dtype=np.float32)
    image[:, :, :3] = np.clip(compose(mode, clay, ref_rgb, ref_mask, model, alpha, split), 0, 1)
    grid = None
    if grid_height_m:
        box = box_of(ref_mask)
        if box is None:
            raise ValueError("The reference has no silhouette to scale the grid: lower `threshold` or use an image with alpha")
        major, minor = draw_metric_grid(image, (box[0] + box[1]) / 2, box[2], grid_height_m / (box[3] - box[2]))
        grid = {
            "labelled_step_m": major,
            "fine_step_m": minor,
            "note": "labels are millimetres on the reference: x from the red vertical line (centre of the silhouette box), z up from the red horizontal line (its bottom)",
        }
    path = RENDERS / f"overlay_{mode}.png" if out is None else Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_pixels(path, image)
    result = {
        "path": str(path),
        "size": [width, height],
        "mode": mode,
        "camera": cam.name,
        "iou_silhouette": rnd(iou_of(model, ref_mask)),
        "legend": LEGENDS[mode],
    }
    if grid:
        result["grid"] = grid
    return result


def direction_of(az, el):
    a, e = math.radians(az), math.radians(el)
    return Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))


def pose_of(center, p):
    toward = direction_of(p["az"], p["el"])
    base = (-toward).to_track_quat("-Z", "Y")
    basis = base.to_matrix()
    target = center + basis.col[0] * p["ox"] + basis.col[1] * p["oy"]
    rotation = base @ Quaternion((0, 0, 1), math.radians(p["roll"]))
    location = target + toward * p["dist"]
    return Matrix.Translation(location) @ rotation.to_matrix().to_4x4(), target


def params_from(location, rotation, center, fov):
    forward = rotation @ Vector((0, 0, -1))
    depth = (center - location).dot(forward)
    if depth < 0.05:
        depth = max((center - location).length, 0.1)
    target = location + forward * depth
    toward = (location - target) / depth
    base = (-toward).to_track_quat("-Z", "Y")
    basis = base.to_matrix()
    offset = target - center
    roll = (base.inverted() @ rotation).to_euler().z
    return {
        "az": math.degrees(math.atan2(toward.x, -toward.y)),
        "el": float(np.clip(math.degrees(math.asin(np.clip(toward.z, -1, 1))), -MAX_EL, MAX_EL)),
        "dist": depth,
        "ox": offset.dot(basis.col[0]),
        "oy": offset.dot(basis.col[1]),
        "roll": math.degrees(roll),
        "fov": fov,
    }


def long_side_fov(cam, width, height):
    projection, _ = matrices(cam, width, height)
    return math.degrees(2 * math.atan(max(1 / abs(projection[0][0]), 1 / abs(projection[1][1]))))


def start_from(init, fov_deg, center, frame):
    scene_cam = bpy.context.scene.camera
    if init is not None:
        try:
            location, look_at = Vector(init["location"]), Vector(init["look_at"])
        except (KeyError, TypeError, ValueError):
            raise ValueError('init is {"location": [x, y, z], "look_at": [x, y, z], "fov_deg": 40}') from None
        if (look_at - location).length < 1e-6:
            raise ValueError("init location and look_at must differ")
        rotation = (look_at - location).to_track_quat("-Z", "Y")
        return params_from(location, rotation, center, init.get("fov_deg") or fov_deg or 40.0), True
    if scene_cam is not None and scene_cam.type == "CAMERA" and scene_cam.data.type == "PERSP":
        matrix = scene_cam.matrix_world
        return params_from(matrix.translation, matrix.to_quaternion(), center, long_side_fov(scene_cam, *frame)), True
    return None, False


def clamped(p, fixed_fov):
    p["el"] = float(np.clip(p["el"], -MAX_EL, MAX_EL))
    p["dist"] = max(p["dist"], 0.02)
    p["fov"] = fixed_fov if fixed_fov else float(np.clip(p["fov"], 5.0, 120.0))
    return p


def box_of(mask):
    ys, xs = np.where(mask)
    return (xs.min(), xs.max() + 1, ys.min(), ys.max() + 1) if len(ys) else None


def aligned(p, model, ref_box, frame_long):
    """Scale the distance and shift the target so the model box lands on the reference box."""
    mine = box_of(model)
    if mine is None:
        return None
    mine_long = max(mine[1] - mine[0], mine[3] - mine[2])
    ref_long = max(ref_box[1] - ref_box[0], ref_box[3] - ref_box[2])
    q = dict(p)
    q["dist"] = p["dist"] * mine_long / ref_long
    metres_per_pixel = 2 * q["dist"] * math.tan(math.radians(p["fov"]) / 2) / frame_long
    q["ox"] = p["ox"] + ((mine[0] + mine[1]) - (ref_box[0] + ref_box[1])) / 2 * metres_per_pixel
    q["oy"] = p["oy"] + ((mine[2] + mine[3]) - (ref_box[2] + ref_box[3])) / 2 * metres_per_pixel
    return q


def trial_of(p, name, direction, k, fixed_fov):
    q = dict(p)
    width_m = 2 * p["dist"] * math.tan(math.radians(p["fov"]) / 2)
    if name in ("az", "el", "roll"):
        q[name] += direction * STEPS[name] * k
    elif name == "dist":
        q["dist"] *= 1 + direction * STEPS["dist"] * k
    elif name == "fov":
        q["fov"] *= 1 + direction * STEPS["fov"] * k
    else:
        q[name] += direction * STEPS["shift"] * k * width_m
    return clamped(q, fixed_fov)


def working_frame(ref_full, size):
    src_h, src_w = ref_full.shape
    box = box_of(ref_full)
    box_long = max(box[1] - box[0], box[3] - box[2])
    longest = int(min(MAX_FRAME, max(size, round(max(src_w, src_h) * size / box_long)), max(src_w, src_h)))
    longest = max(longest, 32)
    scale = longest / max(src_w, src_h)
    return max(1, round(src_w * scale)), max(1, round(src_h * scale))


def publish_camera(name, matrix, fov, frame_long, radius, dist):
    obj = bpy.data.objects.get(name)
    if obj is None:
        obj = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        bpy.context.scene.collection.objects.link(obj)
    data = obj.data
    data.type, data.sensor_fit, data.angle = "PERSP", "AUTO", math.radians(fov)
    data.shift_x = data.shift_y = 0.0
    data.clip_start, data.clip_end = 0.01, max(data.clip_end, (dist + radius) * 4)
    obj.matrix_world = matrix
    bpy.context.scene.camera = obj
    bpy.context.view_layer.update()
    return obj


@handler
def match_camera(reference, names=None, camera="match_cam", fov_deg=None, size=256, iterations=8, threshold=0.06,
                 ground_z=None, init=None, time_limit=300.0):
    started = time.time()
    existing = bpy.data.objects.get(camera)
    if existing is not None and existing.type != "CAMERA":
        raise ValueError(f"{camera!r} exists and is not a camera")
    model = with_children(names) if names else scene_objects()
    lo, hi = require_bounds(model)
    center, radius = (lo + hi) / 2, (hi - lo).length / 2
    if radius < 1e-6:
        raise ValueError("The model has no size")
    pixels = read_pixels(reference)
    src_h, src_w = pixels.shape[:2]
    full = mask_of(pixels, threshold)
    if not full.any():
        raise ValueError("The reference has no silhouette: lower `threshold` or use an image with alpha")
    width, height = working_frame(full, size)
    ref = resize_nearest(full, height, width)
    ref_box = box_of(ref)
    frame_long = max(width, height)
    fixed = float(fov_deg) if fov_deg else None
    given, from_start = start_from(init, fixed, center, (width, height))
    RENDERS.mkdir(parents=True, exist_ok=True)
    path = RENDERS / "refcam_mask.png"
    evals = [0]

    with temp_scene(model, "mask") as scene:
        data = bpy.data.cameras.new("bl_match_cam")
        data.sensor_fit = "AUTO"
        probe = bpy.data.objects.new("bl_match_cam", data)
        scene.collection.objects.link(probe)
        scene.camera = probe
        scene.render.resolution_x, scene.render.resolution_y = width, height
        scene.render.filepath = str(path)
        try:
            def score(p, check_ground=True):
                matrix, _ = pose_of(center, p)
                if check_ground and ground_z is not None and matrix.translation.z < ground_z + 0.02:
                    return -1.0, None
                probe.matrix_world = matrix
                data.angle = math.radians(p["fov"])
                data.clip_start, data.clip_end = 0.01, (p["dist"] + radius) * 4
                bpy.ops.render.render(write_still=True, scene=scene.name)
                evals[0] += 1
                mask = read_pixels(path)[:, :, 0] > 0.5
                return iou_of(mask, ref), mask

            def refine(p, value, mask):
                for _ in range(2):
                    q = aligned(p, mask, ref_box, frame_long)
                    if q is None:
                        break
                    q = clamped(q, fixed)
                    v, m = score(q, check_ground=False)
                    if v <= value:
                        break
                    p, value, mask = q, v, m
                return p, value, mask

            fov0 = fixed or 40.0
            if given is not None:
                best_p = clamped(given, fixed)
                best, best_mask = score(best_p, check_ground=False)
                before = best
                yield {"stage": "start", "iou": rnd(best)}
            else:
                best, best_p, best_mask, before = -1.0, None, None, 0.0
                dist0 = radius / math.sin(math.radians(fov0) / 2) * 1.15
                for el in (15.0, 40.0):
                    for az in range(0, 360, 45):
                        p = clamped({"az": float(az), "el": el, "dist": dist0, "ox": 0.0, "oy": 0.0, "roll": 0.0, "fov": fov0}, fixed)
                        v, m = score(p, check_ground=False)
                        before = max(before, v)
                        if v < 0.0:
                            continue
                        p, v, m = refine(p, v, m)
                        if v > best:
                            best_p, best, best_mask = p, v, m
                        yield {"stage": "seeds", "iou": rnd(best), "evals": evals[0]}
            if given is not None:
                best_p, best, best_mask = refine(best_p, best, best_mask)

            tuned = ["az", "el", "dist", "ox", "oy", "roll"] + ([] if fixed else ["fov"])
            moves = [((n, d),) for n in tuned for d in (1, -1)]
            moves += [((a, da), (b, db)) for i, a in enumerate(tuned) for b in tuned[i + 1 :] for da in (1, -1) for db in (1, -1)]
            k, halvings, sweeps = 1.0, 0, 0
            stopped = "converged"
            while halvings < iterations and best < 0.995 and stopped == "converged":
                improved = False
                for move in moves:
                    if time.time() - started > time_limit:
                        stopped = "time limit"
                        break
                    trial = best_p
                    for name, direction in move:
                        trial = trial_of(trial, name, direction, k, fixed)
                    value, mask = score(trial)
                    yield {"move": [m[0] for m in move], "iou": rnd(best), "evals": evals[0]}
                    if value > best + 1e-4:
                        best_p, best, best_mask, improved = trial, value, mask, True
                sweeps += 1
                if not improved or sweeps % 6 == 0:
                    k /= 2
                    halvings += 1
        finally:
            bpy.data.objects.remove(probe)
            bpy.data.cameras.remove(data)

    matrix, target = pose_of(center, best_p)
    cam = publish_camera(camera, matrix, best_p["fov"], frame_long, radius, best_p["dist"])
    result = {
        "camera": cam.name,
        "location": rvec(matrix.translation),
        "rotation_deg": rvec([math.degrees(a) for a in matrix.to_euler()], 2),
        "look_at": rvec(target),
        "distance": rnd(best_p["dist"]),
        "fov_deg": rnd(best_p["fov"], 2),
        "fov_note": "angle across the longer image side" + ("; fixed by the caller" if fixed else "; fitted"),
        "azimuth_deg": rnd(best_p["az"], 2),
        "elevation_deg": rnd(best_p["el"], 2),
        "roll_deg": rnd(best_p["roll"], 2),
        "iou_before": rnd(before),
        "iou_after": rnd(best),
        "start": "init or the scene camera" if from_start else "automatic (8 azimuths, 2 elevations)",
        "frame": [src_w, src_h],
        "evaluations": evals[0],
        "seconds": rnd(time.time() - started, 1),
        "stopped": stopped,
        "note": f"the camera is active; render it at the aspect of the reference ({src_w}x{src_h}) to see the same frame",
    }
    if best < 0.8:
        result["warning"] = "IoU below 0.8: give fov_deg if the lens is known, give init, or check the model against the photo (mirrored view, missing parts)"
    return result
