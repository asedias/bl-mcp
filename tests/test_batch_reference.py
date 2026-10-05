"""Reference tools on an orthographic sheet: masks, views, scale per view, inner detail, fit guard, holes, grid.

Run: uv run python tests/run_headless.py tests/test_batch_reference.py
"""

import importlib
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import *  # noqa: E402

importlib.import_module("bl_bridge.refcam")

work = Path(os.environ.get("BL_MCP_WORK", "/tmp/bl_work_batch_reference")) / "batch_reference"
work.mkdir(parents=True, exist_ok=True)
PX = 2000
MARGIN = 10


def raises(label, fn, text):
    try:
        fn()
    except ValueError as err:
        expect(label, text in str(err), str(err))
    else:
        expect(label, False, "no error")


def run_job(started, limit=200000):
    state = {}
    for _ in range(limit):
        handlers.advance_jobs()
        state = call("job_status", {"job": started["job"]})
        if state["status"] != "running":
            break
    return state


def picture(size_m, rects):
    """RGBA rows bottom-up; rects are (left, right, bottom, top, grey) in metres from the bottom left of the subject box."""
    width, height = (round(v * PX) for v in size_m)
    image = np.zeros((height + 2 * MARGIN, width + 2 * MARGIN, 4), dtype=np.float32)
    for left, right, bottom, top, grey in rects:
        image[MARGIN + round(bottom * PX) : MARGIN + round(top * PX), MARGIN + round(left * PX) : MARGIN + round(right * PX)] = (grey, grey, grey, 1)
    return image


def save(name, image):
    path = work / name
    handlers.write_pixels(path, image, alpha=True)
    return str(path)


def alpha_of(path):
    return handlers.read_pixels(path)[:, :, 3] > 0.5


def box(name, x, y, z):
    call("create_primitive", {"kind": "cube", "name": name, "size": [x[1] - x[0], y[1] - y[0], z[1] - z[0]],
                              "at": [(x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2]})
    return name


def brief(result):
    return {k: v for k, v in result.items() if k not in ("bands", "worst_bands", "sheet_legend", "note", "preview_legend")}


# 1. prepare_reference: steel close to the background, glare, a real opening
rng = np.random.default_rng(7)
steel = np.ones((200, 300, 4), dtype=np.float32)
steel[:, :, :3] = 0.83 + rng.uniform(-0.004, 0.004, (200, 300, 1))
steel[50:150, 40:260, :3] = 0.95
steel[120:128, 100:160, :3] = 0.87
steel[135:143, 180:240, :3] = 0.87
for k in range(6):
    steel[100:103, 110 + 20 * k : 113 + 20 * k, :3] = 0.83
steel[60:85, 60:90, :3] = 0.83
steel_path = save("steel.png", steel)

first = call("prepare_reference", {"image": steel_path, "out": str(work / "steel_auto.png"), "pad": 0})
expect("auto threshold sits just above the background noise", isinstance(first["threshold"], float) and 0.01 <= first["threshold"] < 0.03, brief(first))
expect("the first call gives a solid mask: glare filled, the big opening kept",
       first["holes"]["before"]["count"] == 7 and first["holes"]["filled"] == 6 and first["holes"]["after"]["count"] == 1 and "warning" not in first, brief(first))
solid = alpha_of(first["path"])
expect("the output size is the object box", first["size"] == [220, 100] and solid.shape == (100, 220), first["size"])
expect("glare is solid, the opening is open", solid[51, 71] and solid[72, 62] and not solid[20, 35], (solid[51, 71], solid[72, 62], solid[20, 35]))
expect("hole area share is reported before and after", 0.03 < first["holes"]["after"]["area_share"] < first["holes"]["before"]["area_share"] < 0.05, first["holes"])
preview = handlers.read_pixels(first["preview"])
expect("the preview shows the cut-out above the mask", Path(first["preview"]).exists() and preview.shape[:2] == (204, 220), preview.shape)
expect("the preview marks filled holes green and the open one red",
       tuple(np.round(preview[51, 71, :3], 1)) == (0.2, 0.9, 0.3) and preview[20, 35, 0] > 0.9 and preview[20, 35, 1] < 0.3 and preview[104 + 20, 35, 2] > 0.9,
       (preview[51, 71], preview[20, 35], preview[124, 35]))

old = call("prepare_reference", {"image": steel_path, "out": str(work / "steel_006.png"), "threshold": 0.06, "fill_holes": 0})
expect("threshold 0.06 without filling leaves the holes and warns", old["holes"]["after"]["count"] == 9 and "holes stay open" in old.get("warning", ""), brief(old))
closed = call("prepare_reference", {"image": steel_path, "out": str(work / "steel_closed.png"), "pad": 0, "fill_holes": 1})
expect("fill_holes=1 closes the opening too", closed["holes"]["after"]["count"] == 0 and closed["silhouette_share"] > first["silhouette_share"], brief(closed))
cut = call("prepare_reference", {"image": steel_path, "out": str(work / "steel_cut.png"), "crop": [0.2, 0, 1, 1]})
expect("an object cut by the crop gives a warning", "touches the left border" in cut.get("warning", ""), brief(cut))


def opening_at(path):
    """Centre of the opening as fractions of the picture: x from the left, y from the top."""
    mask = alpha_of(path)
    ys, xs = np.where(~mask)
    return xs.mean() / mask.shape[1], 1 - ys.mean() / mask.shape[0]


fx, fy = opening_at(first["path"])
mirrored = call("prepare_reference", {"image": steel_path, "out": str(work / "steel_flip.png"), "pad": 0, "flip": "x"})
mx, my = opening_at(mirrored["path"])
expect("flip x mirrors left-right", abs(mx - (1 - fx)) < 0.02 and abs(my - fy) < 0.02, ((fx, fy), (mx, my)))
tipped = call("prepare_reference", {"image": steel_path, "out": str(work / "steel_flip_y.png"), "pad": 0, "flip": "y"})
tx, ty = opening_at(tipped["path"])
expect("flip y mirrors top-bottom", abs(tx - fx) < 0.02 and abs(ty - (1 - fy)) < 0.02, ((fx, fy), (tx, ty)))
turned = call("prepare_reference", {"image": steel_path, "out": str(work / "steel_cw.png"), "pad": 0, "rotate": 90})
rx, ry = opening_at(turned["path"])
expect("rotate 90 turns clockwise: the bottom left goes to the top left", turned["size"] == [100, 220] and abs(rx - (1 - fy)) < 0.02 and abs(ry - fx) < 0.02, ((fx, fy), (rx, ry)))
raises("a wrong rotate is refused", lambda: call("prepare_reference", {"image": steel_path, "rotate": 45}), "rotate is")


# 2. compare_view: a pistol-like model, the front is -Y
fresh_scene()
BODY, GRIP, LEVER = ((-0.015, 0.015), (-0.135, 0.135), (0.11, 0.15)), ((-0.015, 0.015), (0.06, 0.12), (0, 0.11)), ((0.015, 0.025), (0.02, 0.06), (0.12, 0.14))
pistol = [box("body", *BODY), box("grip", *GRIP), box("lever", *LEVER)]
right_view = picture((0.27, 0.15), [(0, 0.27, 0.11, 0.15, 0.8), (0.195, 0.255, 0, 0.11, 0.8), (0.155, 0.195, 0.12, 0.14, 0.55), (0.045, 0.105, 0.125, 0.14, 0.2)])
top_view = picture((0.04, 0.27), [(0, 0.03, 0, 0.27, 0.8), (0.03, 0.04, 0.155, 0.195, 0.8)])
right_ref, left_ref = save("right.png", right_view), save("left.png", right_view[:, ::-1])
top_ref, bottom_ref = save("top.png", top_view), save("bottom.png", top_view[::-1])
lying_ref = save("top_lying.png", np.rot90(top_view, -1))

right = call("compare_view", {"reference": right_ref, "view": "right", "names": pistol, "height_m": 0.15, "out": str(work / "cmp_right.png")})
expect("right view matches its picture", right["iou_registered"] > 0.97, brief(right))
expect("out writes the sheet to the given file", right["sheet"] == str(work / "cmp_right.png") and Path(right["sheet"]).exists(), right["sheet"])
side = call("compare_view", {"reference": right_ref, "view": "side", "names": pistol, "height_m": 0.15})
expect("side is the same as right", side["iou_registered"] == right["iou_registered"], (side["iou_registered"], right["iou_registered"]))
wrong = call("compare_view", {"reference": right_ref, "view": "left", "names": pistol, "height_m": 0.15})
expect("the right picture does not fit the left view", wrong["iou_registered"] < 0.6, brief(wrong))
left = call("compare_view", {"reference": left_ref, "view": "left", "names": pistol, "height_m": 0.15})
expect("left view matches the mirrored picture", left["iou_registered"] > 0.97, brief(left))
flipped = call("compare_view", {"reference": right_ref, "view": "left", "names": pistol, "height_m": 0.15, "flip": "x"})
expect("flip x makes the right picture fit the left view", flipped["iou_registered"] > 0.97, brief(flipped))
bottom = call("compare_view", {"reference": bottom_ref, "view": "bottom", "names": pistol, "height_m": 0.27})
expect("bottom view matches the top picture mirrored top-bottom", bottom["iou_registered"] > 0.97, brief(bottom))
raises("an unknown view is refused", lambda: call("compare_view", {"reference": right_ref, "view": "under", "names": pistol}), "view is front, back, left, right")

lying = call("compare_view", {"reference": lying_ref, "view": "top", "names": pistol, "height_m": 0.27})
expect("a lying top picture has a low IoU and a hint to turn it", lying["iou_registered"] < 0.3 and "rotate=90" in lying.get("hint", "") and "flip=None" in lying["hint"], brief(lying))
by_length = call("compare_view", {"reference": lying_ref, "view": "top", "names": pistol, "height_m": 0.27, "rotate": 90})
expect("rotate 90 with the length as height_m fits the top view", by_length["iou_registered"] > 0.97 and "hint" not in by_length, brief(by_length))
by_width = call("compare_view", {"reference": lying_ref, "view": "top", "names": pistol, "width_m": 0.04, "rotate": 90})
expect("width_m gives the same scale", by_width["iou_registered"] > 0.97 and by_width["reference_size_m"] == [0.04, 0.27] and by_width["model_size_m"] == [0.04, 0.27], brief(by_width))
too_big = call("compare_view", {"reference": top_ref, "view": "top", "names": pistol, "width_m": 0.06})
expect("a wrong width_m is seen as a size error", too_big["iou_registered"] < 0.7 and too_big["reference_size_m"][1] > 0.4, brief(too_big))
raises("height_m and width_m together are refused", lambda: call("compare_view", {"reference": top_ref, "view": "top", "names": pistol, "height_m": 0.27, "width_m": 0.04}), "not both")

call("create_primitive", {"kind": "plane", "name": "studio_floor", "size": [3, 3, 1], "at": [0, 0, 0]})
call("create_primitive", {"kind": "cube", "name": "plinth", "size": [2, 2, 0.02], "at": [0, 0, -0.01]})
bpy.ops.object.light_add(type="POINT", location=(1, 1, 1))
bpy.ops.object.camera_add(location=(0, -1, 0.1))
default_set = call("compare_view", {"reference": top_ref, "view": "top", "height_m": 0.27})
expect("without names the floor and the plinth are left out and named", sorted(default_set.get("excluded", [])) == ["plinth", "studio_floor"] and "studio_floor" in default_set["warning"]
       and default_set["iou_registered"] > 0.97, brief(default_set))
with_floor = call("compare_view", {"reference": top_ref, "view": "top", "names": [*pistol, "studio_floor"], "height_m": 0.27})
expect("names can still include the floor", with_floor["iou_registered"] < 0.1 and "excluded" not in with_floor, brief(with_floor))
call("delete", {"names": ["studio_floor", "plinth"]})

plain = right["inner_detail"]
box("slot_cutter", (0.01, 0.02), (-0.09, -0.03), (0.125, 0.14))
call("boolean", {"a": "body", "b": "slot_cutter", "operation": "difference"})
slotted = call("compare_view", {"reference": right_ref, "view": "right", "names": pistol, "height_m": 0.15, "out": str(work / "cmp_right_slot.png")})
detail = slotted["inner_detail"]
expect("a slot cut where the reference shows one does not move the IoU", abs(slotted["iou_registered"] - right["iou_registered"]) < 0.002, (slotted["iou_registered"], right["iou_registered"]))
expect("the slot raises the edge agreement", detail["edge_agreement"] > plain["edge_agreement"] + 0.2 and detail["reference_edges_matched"] > 0.9, (plain, detail))
expect("inner detail says how to read it", "edge_agreement is 0..1" in detail["note"], detail["note"])
flat_ref = save("right_flat.png", picture((0.27, 0.15), [(0, 0.27, 0.11, 0.15, 1.0), (0.195, 0.255, 0, 0.11, 1.0)]))
flat = call("compare_view", {"reference": flat_ref, "view": "right", "names": pistol, "height_m": 0.15})
expect("a flat mask has no inner detail score", flat["inner_detail"]["edge_agreement"] is None and "not measured" in flat["inner_detail"]["note"], flat["inner_detail"])


# 3. fit_to_reference: size per view, and no hiding of a part inside the body
fresh_scene()
SIGHT = ((-0.005, 0.005), (-0.12, -0.10), (0.15, 0.16))
gun = [box("body", *BODY), box("grip", *GRIP), box("sight", *SIGHT)]
top_plain = save("top_plain.png", picture((0.03, 0.27), [(0, 0.03, 0, 0.27, 1.0)]))
fit_args = {"parts": ["sight"], "names": gun, "step_m": 0.01, "tune": ["shift"], "iterations": 4, "size": 160}

one_height = run_job(call("fit_to_reference", {**fit_args, "references": {"right": flat_ref, "top": top_plain}, "height_m": 0.15, "max_hide": 1}))
call("rollback", {"name": "before_fit"})
expect("one height for every view puts the top view at a wrong scale", one_height["status"] == "done" and one_height["result"]["iou_before"]["top"] < 0.7, one_height)
no_size = run_job(call("fit_to_reference", {**fit_args, "references": {"right": flat_ref, "top": top_plain}, "height_m": {"right": 0.15}}))
expect("a view without a size fails with its name", no_size["status"] == "failed" and "View top" in no_size.get("error", ""), no_size)

hidden = run_job(call("fit_to_reference", {**fit_args, "references": {"right": flat_ref, "top": top_plain}, "height_m": 0.15, "width_m": {"top": 0.03}, "max_hide": 1}))
result = hidden.get("result", {})
expect("height_m with width_m for the top view registers both views", hidden["status"] == "done" and result["iou_before"]["top"] > 0.95 and result["iou_before"]["right"] > 0.9, hidden)
expect("without the guard the sight sinks into the body for a better IoU",
       result["changes"].get("sight", {}).get("dz", 0) < -0.008 and result["visible_share"]["sight"][1] < 0.2 and result["mean_after"] > result["mean_before"], result)
call("rollback", {"name": "before_fit"})

guarded = run_job(call("fit_to_reference", {**fit_args, "references": {"right": flat_ref, "top": top_plain}, "height_m": {"right": 0.15, "top": 0.27}}))
result = guarded.get("result", {})
expect("a dict of heights per view works", guarded["status"] == "done" and result["iou_before"]["top"] > 0.95, guarded)
expect("the guard refuses the move and reports it", "dz" not in result["changes"].get("sight", {}) and result["rejected_count"] > 0 and result["rejected"][0]["part"] == "sight"
       and result["rejected"][0]["param"] == "dz" and result["rejected"][0]["iou_gain"] > 0 and result["rejected"][0]["visible_share"][1] < result["rejected"][0]["visible_share"][0], result)
expect("the sight stays where it was", abs(bpy.data.objects["sight"].matrix_world.translation.z - 0.155) < 1e-6 and result["visible_share"]["sight"] == [1.0, 1.0], result["visible_share"])
expect("object colours are restored after the fit", all(tuple(bpy.data.objects[n].color) == (1.0, 1.0, 1.0, 1.0) for n in gun))


# 4. loft_from_masks spans the full height
fresh_scene()
front_mask = save("loft_front.png", picture((0.04, 0.152), [(0, 0.04, 0, 0.152, 1.0)]))
side_mask = save("loft_side.png", picture((0.1, 0.152), [(0, 0.1, 0, 0.152, 1.0)]))
lofted = call("loft_from_masks", {"name": "lofted", "front": front_mask, "side": side_mask, "height_m": 0.152, "bands": 16})
expect("the loft is as tall as height_m", abs(lofted["size"][2] - 0.152) < 0.0005 and abs(lofted["min"][2]) < 0.0005, lofted)
half = call("loft_from_masks", {"name": "lofted_half", "front": front_mask, "side": side_mask, "height_m": 0.152, "bands": 16, "z_range": [0.0, 0.5]})
expect("z_range ends at its fraction", abs(half["size"][2] - 0.076) < 0.0005, half)
expect("the loft stays a clean closed mesh", call("check_mesh", {"name": "lofted"})["issues"] == ["none"], call("check_mesh", {"name": "lofted"}))


# 5. trace_outline returns holes, extrude_profile cuts them
frame_ref = save("frame.png", picture((0.2, 0.1), [(0, 0.2, 0, 0.1, 1.0), (0.05, 0.1, 0.03, 0.07, 0.0)]))
frame_pixels = handlers.read_pixels(frame_ref)
frame_pixels[MARGIN + 60 : MARGIN + 140, MARGIN + 100 : MARGIN + 200, 3] = 0
frame_pixels[MARGIN + 20 : MARGIN + 24, MARGIN + 300 : MARGIN + 304, 3] = 0
frame_ref = save("frame.png", frame_pixels)
outline = call("trace_outline", {"reference": frame_ref, "height_m": 0.1, "simplify": 0.001})
expect("holes are left out by default", "holes" not in outline and "holes=true" in outline["note"], outline)
traced = call("trace_outline", {"reference": frame_ref, "height_m": 0.1, "simplify": 0.001, "holes": True})
hole = traced["holes"][0] if traced.get("holes") else {}
xs, zs = [p[0] for p in hole.get("points", [[0, 0]])], [p[1] for p in hole.get("points", [[0, 0]])]
expect("the opening comes back as one polygon in the outline coordinates, a speck is dropped",
       len(traced["holes"]) == 1 and abs(hole["area_m2"] - 0.002) < 1e-5 and abs(min(xs) + 0.05) < 1e-3 and abs(max(xs)) < 1e-3 and abs(min(zs) - 0.03) < 1e-3 and abs(max(zs) - 0.07) < 1e-3, traced)
every = call("trace_outline", {"reference": frame_ref, "height_m": 0.1, "simplify": 0.001, "holes": True, "min_hole": 0})
expect("min_hole=0 keeps the speck", len(every["holes"]) == 2, every["holes"])
solid = call("extrude_profile", {"name": "plate", "points": traced["points"], "depth": 0.02, "plane": "XZ", "at": [0, 5, 0]})
holed = call("extrude_profile", {"name": "plate_holed", "points": traced["points"], "depth": 0.02, "plane": "XZ", "at": [0, 6, 0], "holes": traced["holes"]})
expect("extrude_profile reports the cut", holed.get("holes_cut") == 1 and holed["size"] == solid["size"], holed)
expect("a ray through the opening hits the solid plate only", call("raycast", {"origin": [-0.025, 4, 0.05], "direction": [0, 1, 0], "max_distance": 1.5})["hit"]
       and not call("raycast", {"origin": [-0.025, 5.5, 0.05], "direction": [0, 1, 0], "max_distance": 1.0})["hit"]
       and call("raycast", {"origin": [0.05, 5.5, 0.05], "direction": [0, 1, 0], "max_distance": 1.0})["hit"])
expect("the plate with a hole is a clean closed mesh", call("check_mesh", {"name": "plate_holed"})["issues"] == ["none"], call("check_mesh", {"name": "plate_holed"}))
raises("a hole needs three points", lambda: call("extrude_profile", {"name": "bad", "points": traced["points"], "depth": 0.02, "holes": [[[0, 0], [1, 1]]]}), "at least 3 points")


# 6. metric grid on a reference
measured = call("measure_profile", {"reference": right_ref, "height_m": 0.15, "bands": 6})
expect("measure_profile draws no grid unless asked", "grid" not in measured)
ruled = call("measure_profile", {"reference": right_ref, "height_m": 0.15, "bands": 6, "grid": True, "grid_size": 1120, "out": str(work / "grid.png")})
grid = ruled["grid"]
sheet = handlers.read_pixels(grid["path"])
expect("the grid picture has the asked size and round steps", grid["size"] == [1120, 640] and grid["labelled_step_m"] == 0.02 and abs(grid["fine_step_m"] - 0.005) < 1e-9, grid)
zero_x, zero_row, per_metre = (MARGIN + 270) * 2, MARGIN * 2, PX * 2
expect("the zero lines are red at the bottom centre of the silhouette", np.allclose(sheet[307, zero_x, :3], (1.0, 0.25, 0.25), atol=0.02) and np.allclose(sheet[zero_row, 900, :3], (1.0, 0.25, 0.25), atol=0.02),
       (sheet[307, zero_x, :3], sheet[zero_row, 900, :3]))
at_60mm, at_100mm = zero_x + int(0.06 * per_metre), zero_row + int(0.1 * per_metre)
expect("labelled lines stand every 20 mm in the coordinates of the bands", sheet[250, at_60mm, 0] > 0.9 and sheet[250, at_60mm, 2] < 0.45 and sheet[at_100mm, 300, 0] > 0.9 and sheet[at_100mm, 300, 2] < 0.45,
       (sheet[250, at_60mm, :3], sheet[at_100mm, 300, :3]))
label = sheet[640 - 15 : 640 - 1, at_60mm + 2 : at_60mm + 20, :3]
expect("a labelled line carries digits", float((label[:, :, 2] < 0.4).mean()) > 0.1 and float((label.max(axis=2) < 0.25).mean()) > 0.3, label.mean(axis=(0, 1)))
zoomed = call("measure_profile", {"reference": right_ref, "height_m": 0.15, "grid": True, "grid_size": 1000, "region": [-0.05, 0.1, 0.0, 0.15], "out": str(work / "grid_zoom.png")})
expect("region zooms into a part with a finer step", zoomed["grid"]["size"] == [1000, 1000] and zoomed["grid"]["labelled_step_m"] == 0.005 and abs(zoomed["grid"]["fine_step_m"] - 0.001) < 1e-9, zoomed["grid"])
raises("a region outside the picture is refused", lambda: call("measure_profile", {"reference": right_ref, "height_m": 0.15, "grid": True, "region": [5, 5, 6, 6]}), "outside the picture")

fresh_scene()
box("block", (-0.1, 0.1), (-0.1, 0.1), (0, 0.15))
call("set_camera", {"location": [0, -2, 0.075], "look_at": [0, 0, 0.075]})
bare = call("overlay_reference", {"reference": right_ref, "size": 560, "out": str(work / "overlay.png")})
ruler = call("overlay_reference", {"reference": right_ref, "size": 560, "grid_height_m": 0.15, "out": str(work / "overlay_grid.png")})
drawn = handlers.read_pixels(ruler["path"])
expect("overlay_reference draws the grid only when asked", "grid" not in bare and ruler["grid"]["labelled_step_m"] == 0.05 and not np.array_equal(drawn, handlers.read_pixels(bare["path"])), ruler)
expect("the overlay grid starts at the bottom centre of the reference silhouette", np.allclose(drawn[157, MARGIN + 270, :3], (1.0, 0.25, 0.25), atol=0.02) and np.allclose(drawn[MARGIN, 150, :3], (1.0, 0.25, 0.25), atol=0.02),
       (drawn[157, MARGIN + 270, :3], drawn[MARGIN, 150, :3]))

print("files:", work)
finish()
