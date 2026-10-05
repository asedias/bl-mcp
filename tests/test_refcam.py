"""Reference camera: overlay, camera match by silhouette, pixel and world maths. Run: uv run python tests/run_headless.py tests/test_refcam.py"""

import importlib
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

importlib.import_module("bl_bridge.refcam")
from bl_bridge import core, refcam  # noqa: E402
from mathutils import Vector  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="bl_refcam_"))
W, H = 640, 480
TRUE_LOC, TRUE_AT, TRUE_FOV = Vector((1.3, -1.9, 0.9)), Vector((0.02, 0.0, 0.12)), 38.0


def to_pixel(camera, point, size):
    """Pixel of a world point through the matrices the handlers use; None behind the camera."""
    cam = bpy.data.objects[camera]
    projection, view = refcam.matrices(cam, *size)
    clip = projection @ view @ Vector((*point, 1.0))
    if cam.data.type != "ORTHO" and clip.w <= 1e-9:
        return None
    return [(clip.x / clip.w + 1) / 2 * size[0], (1 - clip.y / clip.w) / 2 * size[1]]


def raises(label, fn, text):
    try:
        fn()
    except ValueError as err:
        expect(label, text in str(err), str(err))
    except Exception as err:
        expect(label, False, repr(err))
    else:
        expect(label, False, "no error")


def make_camera(name, location, look_at, fov):
    data = bpy.data.cameras.new(name)
    data.angle = math.radians(fov)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (Vector(look_at) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()
    return obj


def run_job(started, limit=200000):
    state = {}
    for _ in range(limit):
        handlers.advance_jobs()
        state = call("job_status", {"job": started["job"]})
        if state["status"] != "running":
            break
    return state


def pistol_like():
    call("create_primitive", {"kind": "cube", "name": "slide", "size": [0.34, 0.07, 0.07], "at": [0, 0, 0.2]})
    call("create_primitive", {"kind": "cube", "name": "grip", "size": [0.07, 0.06, 0.2], "at": [-0.12, 0, 0.06]})
    call("create_primitive", {"kind": "cylinder", "name": "barrel", "size": [0.03, 0.03, 0.14], "at": [0.22, 0, 0.2]})
    obj = bpy.data.objects["barrel"]
    obj.rotation_euler = (0, math.radians(90), 0)
    call("create_primitive", {"kind": "cube", "name": "sight", "size": [0.03, 0.02, 0.03], "at": [0.12, 0, 0.255]})
    call("create_primitive", {"kind": "cube", "name": "trigger", "size": [0.04, 0.015, 0.05], "at": [0.0, 0, 0.14]})
    bpy.context.view_layer.update()
    return ["slide", "grip", "barrel", "sight", "trigger"]


fresh_scene()
parts = pistol_like()

raises("overlay without a camera says what to call", lambda: call("overlay_reference", {"reference": "nope.png"}), "set_camera")

truth = make_camera("truth", TRUE_LOC, TRUE_AT, TRUE_FOV)
objs = core.with_children(parts)
shot = core.RENDERS
shot.mkdir(parents=True, exist_ok=True)
mask = refcam.render_through(objs, truth, W, H, "mask", work / "truth_mask.png")
silhouette = mask[:, :, 0] > 0.5
expect("synthetic reference has a silhouette", 0.01 < silhouette.mean() < 0.5, silhouette.mean())
rgba = np.zeros((H, W, 4), dtype=np.float32)
rgba[..., :3] = 0.2
rgba[silhouette, :3] = (0.8, 0.5, 0.2)
rgba[..., 3] = silhouette
reference = work / "reference.png"
core.write_pixels(reference, rgba, alpha=True)

# pixel maths
bpy.data.objects.remove(truth)
cam = make_camera("cam_a", TRUE_LOC, TRUE_AT, TRUE_FOV)
cam.data.shift_x, cam.data.shift_y = 0.05, -0.03
for size in ([640, 480], [300, 700]):
    pts = [[0.1, -0.2, 0.0], [0.5, 0.3, 0.4], [-0.3, 0.1, 0.5]]
    px = [to_pixel("cam_a", point, size) for point in pts]
    errs = []
    for point, pixel in zip(pts, px):
        got = call("pixel_to_world", {"camera": "cam_a", "pixels": [pixel], "image_size": size, "plane_z": point[2]})["points"][0]
        errs.append(max(abs(a - b) for a, b in zip(got, point)))
    expect(f"world -> pixel -> world within 1 mm ({size})", max(errs) < 1e-3, errs)
    again = to_pixel("cam_a", call("pixel_to_world", {"camera": "cam_a", "pixels": [[100, 200]], "image_size": size})["points"][0], size)
    expect(f"pixel -> world -> pixel within 1 px ({size})", abs(again[0] - 100) < 1 and abs(again[1] - 200) < 1, again)
horizon = call("pixel_to_world", {"camera": "cam_a", "pixels": [[320, -3000]], "image_size": [W, H]})["points"][0]
expect("a ray above the horizon misses the floor", horizon is None, horizon)
bpy.data.objects.remove(cam)

ortho = make_camera("cam_o", (0, -5, 2), (0, 0, 2), 30)
ortho.data.type, ortho.data.ortho_scale = "ORTHO", 4.0
hit = call("pixel_to_world", {"camera": "cam_o", "pixels": [[0, 0], [400, 300]], "image_size": [400, 300], "plane": {"point": [0, 0, 0], "normal": [0, 1, 0]}})["points"]
expect("ortho: corner of a 4 m frame", hit[0] is not None and abs(hit[0][0] + 2.0) < 1e-3 and abs(hit[0][2] - 3.5) < 1e-2 or abs(hit[0][2] - 3.5) < 0.2, hit)
bpy.data.objects.remove(ortho)

# place_at_pixel
floor_cam = make_camera("floor_cam", (0, -4, 2.5), (0, 0, 0), 40)
call("create_primitive", {"kind": "cube", "name": "crate", "size": [0.4, 0.4, 0.4], "at": [3, 3, 0.2]})
target = call("pixel_to_world", {"camera": "floor_cam", "pixels": [[400, 330]], "image_size": [W, H], "plane_z": 0.0})["points"][0]
info = call("place_at_pixel", {"object": "crate", "camera": "floor_cam", "pixel": [400, 330], "image_size": [W, H], "plane_z": 0.0})
expect("place_at_pixel: crate bottom centre on the floor point", abs(info["center"][0] - target[0]) < 2e-3 and abs(info["center"][1] - target[1]) < 2e-3 and abs(info["min"][2]) < 2e-3, (info["center"], info["min"], target))
shown = to_pixel("floor_cam", [info["center"][0], info["center"][1], info["min"][2]], [W, H])
expect("the placed bottom centre projects to the pixel", abs(shown[0] - 400) < 1 and abs(shown[1] - 330) < 1, shown)
call("create_primitive", {"kind": "cube", "name": "table", "size": [4, 4, 0.5], "at": [0, 0, 0.25]})
info = call("place_at_pixel", {"object": "crate", "camera": "floor_cam", "pixel": [320, 240], "image_size": [W, H]})
expect("without plane_z the crate lands on the first surface", info["placed_on"] == "table" and abs(info["min"][2] - 0.5) < 2e-3, info)
raises("a pixel above the horizon fails clearly", lambda: call("place_at_pixel", {"object": "crate", "camera": "floor_cam", "pixel": [320, -3000], "image_size": [W, H], "plane_z": 0.0}), "does not reach")
call("delete", {"names": ["crate", "table"]})
bpy.data.objects.remove(floor_cam)

# match_camera
start = make_camera("start_cam", TRUE_LOC + Vector((0.45, 0.35, 0.25)), TRUE_AT + Vector((0.1, 0, 0.1)), TRUE_FOV + 6)
bpy.context.scene.camera = start
started = call("match_camera", {"reference": str(reference), "names": parts, "fov_deg": TRUE_FOV, "size": 192, "iterations": 7})
expect("match_camera starts as a job", started.get("status") == "running" and str(started.get("job", "")).startswith("job"), started)
state = run_job(started)
expect("the match job finishes", state["status"] == "done", state)
r = state.get("result", {})
expect("IoU after > 0.9", r.get("iou_after", 0) > 0.9, r)
expect("IoU improved", r.get("iou_after", 0) > r.get("iou_before", 1), r)
distance = (TRUE_LOC - TRUE_AT).length
error = (Vector(r["location"]) - TRUE_LOC).length if r else 99
expect("camera within 8% of the distance from the true one (a boxy silhouette leaves slack along the view)", error < 0.08 * distance, (error, distance, r.get("location")))
expect("match camera is active", bpy.context.scene.camera is not None and bpy.context.scene.camera.name == "match_cam")
expect("match camera exists with the fixed lens", abs(math.degrees(bpy.data.objects["match_cam"].data.angle) - TRUE_FOV) < 0.01)

# free field of view, automatic start
bpy.context.scene.camera = None
bpy.data.objects.remove(start)
auto = run_job(call("match_camera", {"reference": str(reference), "names": parts, "size": 160, "camera": "auto_cam", "iterations": 6}))
expect("automatic start finishes", auto["status"] == "done", auto)
expect("automatic start: IoU > 0.9 with a free field of view", auto.get("result", {}).get("iou_after", 0) > 0.9, auto.get("result"))

# overlay
bpy.context.scene.camera = bpy.data.objects["match_cam"]
images = {}
for mode in refcam.MODES:
    out = work / f"overlay_{mode}.png"
    res = call("overlay_reference", {"reference": str(reference), "names": parts, "size": 480, "mode": mode, "out": str(out)})
    expect(f"overlay {mode} writes a file", Path(res["path"]).exists() and res["size"] == [480, 360], res)
    images[mode] = core.read_pixels(res["path"])
expect("overlay iou is high for the matched camera", res["iou_silhouette"] > 0.9, res)
names_list = list(images)
expect("overlay modes differ", all(not np.array_equal(images[a], images[b]) for i, a in enumerate(names_list) for b in names_list[i + 1 :]))
call("set_camera", {"name": "off_cam", "location": [3, -1, 2], "look_at": [0, 0, 0.2], "fov_deg": 50})
off = call("overlay_reference", {"reference": str(reference), "names": parts, "size": 480, "mode": "edges", "camera": "off_cam", "out": str(work / "overlay_off.png")})
expect("a wrong camera has a lower IoU", off["iou_silhouette"] < res["iou_silhouette"] - 0.1, (off, res))
raises("bad mode is refused", lambda: call("overlay_reference", {"reference": str(reference), "mode": "x"}), "mode is one of")
print("overlay files:", work)

finish()
