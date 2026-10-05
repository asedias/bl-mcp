"""Automatic fit of parts to reference silhouettes: coordinate descent on the world-registered IoU."""

import time

import bpy
import mathutils
import numpy as np
from mathutils import Matrix, Vector

from .compare import drop_camera, model_objects, ortho_camera, reference_scale, registered, view_of
from .core import *  # noqa: F401,F403
from .core import checkpoint, handler
from .profiles import mask_bounds

PARAMS = ("dx", "dy", "dz", "sx", "sy", "sz", "rx", "ry", "rz")
NEUTRAL = {"dx": 0.0, "dy": 0.0, "dz": 0.0, "sx": 1.0, "sy": 1.0, "sz": 1.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}
GROUPS = {
    "shift": ("dx", "dy", "dz"),
    "scale": ("sx", "sy", "sz"),
    "tilt": ("rx", "ry", "rz"),
}


def mirrored(params):
    return {**params, "dx": -params["dx"], "ry": -params["ry"], "rz": -params["rz"]}


def transform_of(base, centre, p):
    rotation = mathutils.Euler([np.radians(p["rx"]), np.radians(p["ry"]), np.radians(p["rz"])]).to_matrix().to_4x4()
    scale = Matrix.Diagonal((p["sx"], p["sy"], p["sz"], 1))
    return Matrix.Translation((p["dx"], p["dy"], p["dz"])) @ Matrix.Translation(centre) @ rotation @ scale @ Matrix.Translation(-centre) @ base


def size_for(value, view):
    """A size given once for all views or as a dict per view: the value and whether it names this view."""
    if isinstance(value, dict):
        return value.get(view), True
    return value, False


def sample_reference(path, view, size, scale, extent_up, height_m, width_m, threshold):
    full = reference_mask(path, threshold)
    box = mask_bounds(full)
    (height, height_named), (width, width_named) = size_for(height_m, view), size_for(width_m, view)
    if height and width and height_named != width_named:
        height, width = (height, None) if height_named else (None, width)
    try:
        mpp, _ = reference_scale(box, height, width)
    except ValueError as error:
        raise ValueError(f"View {view}: {error}") from None
    ryc, rxc, inside = registered(full.shape, box, mpp, size, scale, extent_up)
    return full[ryc, rxc] & inside


def grab_pixels(scene, camera, path):
    scene.camera = camera
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True, scene=scene.name)
    return read_pixels(path)


MARKED, PLAIN = (1.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0, 1.0)


@handler
def fit_to_reference(parts, references, height_m=None, names=None, iterations=6, step_m=0.03, scale_step=0.05, tilt_deg=4.0,
                     size=160, threshold=0.06, mirror_pairs=(), tune=("shift", "scale", "tilt"),
                     max_shift=0.3, max_tilt=25.0, time_limit=600.0, width_m=None, max_hide=0.1):
    started = time.time()
    model, excluded = model_objects(names)
    movers = [get_object(n) for n in parts]
    for obj in movers:
        if obj not in model:
            model.append(obj)
    for a, b in mirror_pairs:
        if a not in parts or b not in parts:
            raise ValueError(f"Both parts of the pair {a!r}, {b!r} must be listed in `parts`")
    twin = {a: b for a, b in mirror_pairs}
    twin.update({b: a for a, b in mirror_pairs})
    followers = {b for _, b in mirror_pairs}
    lo, hi = require_bounds(model)
    center = (lo + hi) / 2
    scale = float(max(hi - lo)) * 1.4
    distance = (hi - lo).length * 2 + 1
    base = {o.name: o.matrix_world.copy() for o in movers}
    centres = {o.name: sum(require_bounds(group_of(o)), Vector()) / 2 for o in movers}
    checkpoint("before_fit")
    state = {o.name: dict(NEUTRAL) for o in movers}
    active = [p for g in tune for p in GROUPS[g]]
    steps = {"d": step_m, "s": scale_step, "r": tilt_deg}

    def apply(name, p):
        obj = bpy.data.objects[name]
        obj.matrix_world = transform_of(base[name], centres[name], p)
        if name in twin and name not in followers:
            other = twin[name]
            q = mirrored(p)
            mirror_base = base[other]
            bpy.data.objects[other].matrix_world = transform_of(mirror_base, centres[other], q)

    refs = {}
    for view, path in references.items():
        _, axes, _ = view_of(view)
        refs[view] = sample_reference(path, view, size, scale, float((hi - lo)[axes[1]]), height_m, width_m, threshold)
    cams = []
    colours = {o: tuple(o.color) for o in model}
    marked = []
    rejected = []
    with temp_scene(model, "mask") as scene, temp_scene([], "mask") as alone:
        try:
            # Object colours tell the tested part from the rest in one render: red is the part, white the others.
            scene.display.shading.color_type = "OBJECT"
            for obj in model:
                obj.color = PLAIN
            for view in references:
                cam = ortho_camera(scene, view_of(view)[0], center, scale, distance)
                alone.collection.objects.link(cam)
                cams.append((view, cam))
            for each in (scene, alone):
                each.render.resolution_x = each.render.resolution_y = size
            RENDERS.mkdir(parents=True, exist_ok=True)
            evals = [0]

            def mark(name):
                for obj in marked:
                    obj.color = PLAIN
                    alone.collection.objects.unlink(obj)
                marked[:] = group_of(bpy.data.objects[name]) + (group_of(bpy.data.objects[twin[name]]) if name in twin else [])
                for obj in marked:
                    obj.color = MARKED
                    alone.collection.objects.link(obj)

            def score():
                total, per, seen = 0.0, {}, 0
                for (view, cam) in cams:
                    pixels = grab_pixels(scene, cam, RENDERS / f"fit_{view}.png")
                    mask = pixels[:, :, 0] > 0.5
                    seen += int((mask & (pixels[:, :, 1] < 0.5)).sum())
                    union = (mask | refs[view]).sum()
                    per[view] = float((mask & refs[view]).sum() / union) if union else 0.0
                    total += per[view]
                evals[0] += 1
                return total / len(cams), per, seen

            def visible_share(seen):
                """Share of the marked part that the rest of the model does not cover, over all views."""
                own = sum(int((grab_pixels(alone, cam, RENDERS / f"fit_alone_{view}.png")[:, :, 0] > 0.5).sum()) for view, cam in cams)
                return seen / own if own else 0.0

            leaders = [o.name for o in movers if o.name not in followers]
            shown = {}
            for name in leaders:
                mark(name)
                best, per_view, seen = score()
                shown[name] = visible_share(seen)
            shown_before = dict(shown)
            before = dict(per_view)
            yield {"stage": "start", "iou": rnd(best)}
            step = dict(steps)
            for round_no in range(iterations):
                improved = False
                for name in leaders:
                    mark(name)
                    for param in active:
                        kind = param[0]
                        for direction in (1, -1):
                            if time.time() - started > time_limit:
                                break
                            trial = dict(state[name])
                            if kind == "d":
                                trial[param] += direction * step["d"]
                            elif kind == "s":
                                trial[param] *= 1 + direction * step["s"]
                            else:
                                trial[param] += direction * step["r"]
                            if abs(trial[param]) > (max_shift if kind == "d" else max_tilt) and kind != "s":
                                continue
                            if kind == "s" and not 0.4 <= trial[param] <= 2.0:
                                continue
                            apply(name, trial)
                            value, per, seen = score()
                            share = visible_share(seen) if value > best + 1e-4 else None
                            if share is not None and share < shown_before[name] - max_hide:
                                rejected.append({"part": name, "param": param, "value": rnd(trial[param], 4), "iou_gain": rnd(value - best),
                                                 "visible_share": [rnd(shown_before[name], 3), rnd(share, 3)]})
                            elif share is not None:
                                best, per_view, state[name], improved = value, per, trial, True
                                shown[name] = share
                                yield {"round": round_no + 1, "part": name, "param": param, "iou": rnd(best), "evals": evals[0]}
                                break
                            apply(name, state[name])
                            yield {"round": round_no + 1, "part": name, "evals": evals[0]}
                if time.time() - started > time_limit:
                    break
                if not improved:
                    step = {k: v / 2 for k, v in step.items()}
                    if step["d"] < step_m / 8:
                        break
            for name in state:
                apply(name, state[name])
        finally:
            for obj, colour in colours.items():
                obj.color = colour
            for _, cam in cams:
                drop_camera(cam)
    changed = {
        n: {k: rnd(v, 4) for k, v in p.items() if abs(v - NEUTRAL[k]) > 1e-6}
        for n, p in state.items()
        if any(abs(v - NEUTRAL[k]) > 1e-6 for k, v in p.items())
    }
    return {
        "iou_before": {k: rnd(v) for k, v in before.items()},
        "iou_after": {k: rnd(v) for k, v in per_view.items()},
        "mean_before": rnd(sum(before.values()) / len(before)),
        "mean_after": rnd(best),
        "changes": changed,
        "visible_share": {n: [rnd(shown_before[n], 3), rnd(shown[n], 3)] for n in leaders},
        "rejected_count": len(rejected),
        "rejected": rejected[:12],
        **({"excluded": excluded} if excluded else {}),
        "evaluations": evals[0],
        "seconds": rnd(time.time() - started, 1),
        "undo": "rollback to the checkpoint 'before_fit'",
        "note": "d* in metres (world), s* are scale factors about the part centre, r* in degrees; mirrored partners follow. visible_share is "
                "[before, after]: the share of the part that the rest of the model does not cover, over all views. rejected: moves that raised the IoU "
                f"but hid more than max_hide={max_hide} of the part behind or inside the model; they were not applied",
    }
