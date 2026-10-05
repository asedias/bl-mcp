from typing import Literal

from .app import Image, Vec3, call, call_waiting, mcp, text

Flip = Literal["x", "y"]
Turn = Literal[0, 90, 180, 270]
Plane = Literal["XZ", "YZ", "XY"]
SideFaces = Literal["left", "right"]


@mcp.tool()
def prepare_reference(
    image: str,
    out: str | None = None,
    crop: list[float] | None = None,
    threshold: float | None = None,
    keep: Literal["largest", "all"] = "largest",
    pad: float = 0.02,
    fill_holes: float = 0.01,
    flip: Flip | None = None,
    rotate: Turn = 0,
) -> list:
    """Clean a real-world reference for the other reference tools: crop it, remove the background and keep only the
    biggest object (a photo with two donuts and a caption becomes one donut with a transparent background). `crop` is
    [x0, y0, x1, y1] as fractions of the image from the top left (one panel of a sheet of views). keep=all keeps every blob.
    `threshold` is the colour distance from the background; leave it out and it is set just above the noise of the
    picture border (the answer shows the value). The background must be plain.
    `fill_holes` closes holes inside the object that are smaller than this share of the object area (glare on steel
    that looks like background); bigger openings such as a trigger guard stay. 0 closes nothing, 1 closes all.
    `flip` 'x' mirrors left-right, 'y' top-bottom; `rotate` turns clockwise by degrees (flip first).
    Use them to bring a panel to the picture a view expects (see compare_view).
    The result is an RGBA PNG cropped to the silhouette with `pad` margin; use its path as the reference of
    compare_view, fit_to_reference, visual_hull, measure_profile. The answer has the hole count and hole area share
    before and after filling, the blobs dropped, a `warning` (many open holes, the object touches the crop border, a
    big part dropped) and a preview picture: the cut-out over magenta and the mask (white object, green filled
    holes, red open holes). Look at the preview: alpha is not visible in the PNG itself."""
    result = call("prepare_reference", image=image, out=out, crop=crop, threshold=threshold, keep=keep, pad=pad, fill_holes=fill_holes, flip=flip, rotate=rotate)
    return [text(result), Image(path=result["preview"])]


@mcp.tool()
def measure_profile(
    reference: str,
    height_m: float,
    bands: int = 24,
    threshold: float = 0.06,
    grid: bool = False,
    region: list[float] | None = None,
    grid_size: int = 1280,
    out: str | None = None,
) -> list:
    """Measure a silhouette in a reference image in metres (use measure for an object of the scene). The image
    height is mapped to `height_m`. Returns, for
    each horizontal band from the bottom: width, left and right edge from the centre, the separate runs (arms and
    legs are separate runs) and the filled width. Use the numbers for loft sections, assert_spec checks or to find
    where the model differs. The outline comes from alpha or from the corner colour (see prepare_reference).
    grid=true also returns the reference with a metric grid (labels in millimetres, the same coordinates as the
    bands: x from the centre of the silhouette box, z from its bottom), to read where parts and details are.
    `region` [x0, z0, x1, z1] in metres zooms the grid picture into a part; `grid_size` is its long side in pixels;
    `out` saves it to a file."""
    result = call("measure_profile", reference=reference, height_m=height_m, bands=bands, threshold=threshold, grid=grid, region=region, grid_size=grid_size, out=out)
    return [text(result), Image(path=result["grid"]["path"])] if grid else [text(result)]


@mcp.tool()
def trace_outline(reference: str, height_m: float, simplify: float = 0.01, threshold: float = 0.06, holes: bool = False, min_hole: float = 0.002) -> str:
    """Trace the outer outline of a reference silhouette as a closed polygon of [x, z] points in metres (x from the
    centre of the silhouette box, z from its bottom). `simplify` is the largest allowed deviation in metres. Feed
    the points to extrude_profile, or build a hull with visual_hull. holes=true also returns `holes`: the openings
    inside the outline (a trigger guard, a handle) as polygons, largest first, each at least `min_hole` of the outline
    area; give them to extrude_profile as `holes`. The reference must keep its openings (prepare_reference fill_holes)."""
    return text(call("trace_outline", reference=reference, height_m=height_m, simplify=simplify, threshold=threshold, holes=holes, min_hole=min_hole))


@mcp.tool()
def extrude_profile(name: str, points: list[list[float]], depth: float, plane: Plane = "XZ", at: Vec3 = (0, 0, 0), holes: list | None = None) -> str:
    """Make a solid by extruding a closed 2D polygon, centred on its depth. plane XZ: points are [x, z] and the
    depth runs along Y (front outline); YZ: [y, z], depth along X (side outline); XY: [x, y], depth along Z (top).
    `at` shifts the result in the world. `holes` is a list of polygons in the same coordinates (or the `holes` of
    trace_outline as they are): each is cut through the solid with the checks of boolean; a flawed cut is kept and
    listed in `warnings`. Good for soles, panels, signs, floor plans, outline-based parts."""
    return text(call("extrude_profile", name=name, points=points, depth=depth, plane=plane, at=list(at), holes=holes))


@mcp.tool()
def loft_from_masks(
    name: str,
    front: str,
    side: str,
    height_m: float,
    bands: int = 16,
    at: Vec3 = (0, 0, 0),
    segments: int = 20,
    roundness: float = 2.5,
    part: Literal["largest", "extent"] = "largest",
    side_faces: SideFaces = "left",
    z_range: list[float] = (0.0, 1.0),
    subdivisions: int = 0,
    threshold: float = 0.06,
) -> str:
    """Build one rounded body from a front and a side silhouette image (with numbers instead of images use loft): per band the width comes from the front image and the
    depth and forward offset from the side image, so the cross-sections follow both outlines. part=largest uses the
    widest run in a band (the torso, not the arms); part=extent uses everything. side_faces says which way the
    figure looks in the side image (left matches the world: the front is -Y). z_range limits the height as
    fractions (0.0 to 0.5 builds the lower half). roundness 2 is an ellipse, 4 a rounded box. The body spans the
    full height (or z_range): the first and the last band end flat at their outer edge."""
    return text(call("loft_from_masks", name=name, front=front, side=side, height_m=height_m, bands=bands, at=list(at), segments=segments, roundness=roundness, part=part, side_faces=side_faces, z_range=list(z_range), subdivisions=subdivisions, threshold=threshold))


@mcp.tool()
def visual_hull(name: str, front: str, side: str, height_m: float, simplify: float = 0.01, side_faces: SideFaces = "left", at: Vec3 = (0, 0, 0), threshold: float = 0.06) -> str:
    """Make a solid that matches BOTH silhouettes exactly: the front outline extruded and intersected with the side
    outline extruded. Arms, ears, noses and other outline details come out right in both views. The inside is a
    straight extrusion, so refine curved surfaces afterwards (sculpt, subdivide). Use it for a precise first
    form of characters, props and vehicles."""
    return text(call("visual_hull", name=name, front=front, side=side, height_m=height_m, simplify=simplify, side_faces=side_faces, at=list(at), threshold=threshold))


@mcp.tool()
def compare_view(
    reference: str,
    view: Literal["front", "back", "left", "right", "side", "top", "bottom"] = "front",
    names: list[str] | None = None,
    height_m: float | None = None,
    size: int = 512,
    bands: int = 16,
    colors: int = 0,
    threshold: float = 0.06,
    width_m: float | None = None,
    flip: Flip | None = None,
    rotate: Turn = 0,
    out: str | None = None,
) -> list:
    """Compare the model with a reference image in one flat view: the main metric of a build from references.
    The reference is placed in the world: its bottom on the model bottom, horizontal centres equal.
    Scale: `height_m` is the real size of the subject along the VERTICAL of the (turned) picture, `width_m` along
    its horizontal; give one, and a model that is too big or too small is caught. With none the reference is fitted
    to the model height and only the outline shape is compared. `iou_outline` is always that shape-only match.
    Views (the model front faces -Y, Z up) and the picture each expects. front: +X to the right. back: -X to the
    right. right (side is the same): camera on +X, the front points LEFT. left: the front points right. top: +X to
    the right, the front at the BOTTOM. bottom: the front at the top. `flip` ('x' left-right, 'y' top-bottom) and
    `rotate` (degrees clockwise; flip first) turn the reference for this call.
    `names` is the model (empty: everything visible but a huge floor or backdrop, listed in `excluded`).
    Returns iou_registered, both sizes, a table per band along the vertical (widths, delta, shift, verdict; worst
    first) and `inner_detail`: edge_agreement 0..1 between the reference inner edges and the creases and depth steps
    of the model (the IoU does not see slots and holes inside the outline). Under IoU 0.3 a `hint` says if a mirrored or turned reference fits far better. The image: reference,
    model, overlay (red reference outline, green model outline, yellow and blue inner edges), difference; `out` also
    saves it. colors=N adds the match of N colour classes of the reference. For a perspective photo use
    match_camera and overlay_reference."""
    result = call("compare_view", reference=reference, view=view, names=names, height_m=height_m, size=size, bands=bands, colors=colors, threshold=threshold,
                  width_m=width_m, flip=flip, rotate=rotate, out=out)
    return [text(result), Image(path=result["sheet"])]


@mcp.tool()
def fit_to_reference(
    parts: list[str],
    references: dict[str, str],
    height_m: float | dict[str, float] | None = None,
    names: list[str] | None = None,
    iterations: int = 6,
    step_m: float = 0.03,
    scale_step: float = 0.05,
    tilt_deg: float = 4.0,
    size: int = 160,
    mirror_pairs: list[list[str]] = (),
    tune: list[Literal["shift", "scale", "tilt"]] = ("shift", "scale", "tilt"),
    max_shift: float = 0.3,
    max_tilt: float = 25.0,
    time_limit: float = 600.0,
    wait: float = 100.0,
    threshold: float = 0.06,
    width_m: float | dict[str, float] | None = None,
    max_hide: float = 0.1,
) -> str:
    """Move, scale and tilt parts by itself to raise the match with reference silhouettes. Use it when the forms
    are roughly right: it fixes placement and proportions, not shapes. For each part in `parts` it keeps the changes
    that raise the world-registered IoU over all views (as compare_view measures it).
    `references` maps a view (as in compare_view) to an image; `names` is the whole model (everything visible but a
    huge floor or backdrop when empty).
    Scale per view, as in compare_view: `height_m` (vertical of the picture) or `width_m` (horizontal). Each is one
    number for all views or a dict per view, and every view needs one: height_m=0.152 with width_m={"top": 0.0325}.
    A size that names the view wins over a plain number.
    `mirror_pairs` [["arm_L","arm_R"]] keeps pairs symmetric (list both in `parts`). `tune` picks what may change.
    Guard: a move that raises the IoU but hides the part is refused: `visible_share` (the share of the part that the
    rest of the model does not cover) may drop by `max_hide` at most (1 turns the guard off). The answer lists
    `rejected` moves and visible_share [before, after].
    It takes the checkpoint 'before_fit' first: rollback undoes it. Background job: after `wait` seconds the answer
    is a job id for job_status."""
    result = call_waiting("fit_to_reference", wait=wait, parts=parts, references=references, height_m=height_m, names=names, iterations=iterations, step_m=step_m, scale_step=scale_step, tilt_deg=tilt_deg, size=size, mirror_pairs=[list(p) for p in mirror_pairs], tune=list(tune), max_shift=max_shift, max_tilt=max_tilt, time_limit=time_limit, threshold=threshold, width_m=width_m, max_hide=max_hide)
    return text(result)
