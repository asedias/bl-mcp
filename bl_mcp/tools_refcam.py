from typing import Literal

from .app import Image, Vec3, call, call_waiting, mcp, text


@mcp.tool()
def overlay_reference(reference: str, camera: str | None = None, names: list[str] | None = None, size: int = 1024, alpha: float = 0.5,
                      mode: Literal["blend", "edges", "difference", "split"] = "blend", threshold: float = 0.06, out: str | None = None, split: float = 0.5,
                      grid_height_m: float | None = None) -> list:
    """Draw the model and a reference picture on top of each other, seen through a scene camera: it shows how far
    the camera and the model are from the photo. The model is rendered from `camera` (the scene camera when empty;
    without one call set_camera or match_camera first) at the proportions of the reference; the long side is `size`
    pixels. `names` is the model (everything visible when empty).
    Modes: blend (the reference at `alpha`); edges (red reference outline, yellow reference inner edges, green model
    outline over the dimmed model: best for small shifts); difference (black is a match); split (reference left of
    a line at the `split` fraction of the width, model right: lines must continue across it).
    The answer has the path, the silhouette IoU and the picture. The reference outline comes from alpha or the
    corner colour; `threshold` is the colour distance. Give the original photo, not a crop.
    `grid_height_m` (the real height of the reference silhouette) draws a metric grid with millimetre labels; zero
    is the bottom centre of the silhouette box. It is true for a flat-on (orthographic) reference only. Before a
    model exists, read coordinates with measure_profile grid=true."""
    result = call("overlay_reference", reference=reference, camera=camera, names=names, size=size, alpha=alpha, mode=mode, threshold=threshold, out=out, split=split,
                  grid_height_m=grid_height_m)
    return [text(result), Image(path=result["path"])]


@mcp.tool()
def match_camera(reference: str, names: list[str] | None = None, camera: str = "match_cam", fov_deg: float | None = None, size: int = 256,
                 iterations: int = 8, threshold: float = 0.06, ground_z: float | None = None, init: dict | None = None,
                 time_limit: float = 300.0, wait: float = 100.0) -> str:
    """Find the camera that shows the model like a perspective photo of the real object (for flat orthographic
    views use compare_view). It tunes position, rotation, roll and field of view until the model silhouette best
    matches the reference silhouette. The camera `camera` is created or updated and becomes the scene camera. The
    answer has location, rotation, look_at, fov_deg and the IoU before and after.
    Give the whole original photo, not a crop: the picture frame is the camera frame. The outline comes from alpha
    or from the corner colour (plain background); `threshold` is the colour distance.
    Start: `init` {"location": [x,y,z], "look_at": [x,y,z], "fov_deg": 40}, else the active perspective camera,
    else 8 azimuths at 2 elevations are tried. A close start gives a better result.
    `fov_deg` fixes the angle across the LONGER image side: a known lens is far more reliable, because distance and
    field of view trade off. `ground_z` keeps the camera above that height. `size` is the working resolution;
    `iterations` is how many times the step is halved.
    A silhouette does not tell front from back on a symmetric model: check with overlay_reference. Background job:
    after `wait` seconds the answer is a job id for job_status."""
    result = call_waiting("match_camera", wait=wait, reference=reference, names=names, camera=camera, fov_deg=fov_deg, size=size,
                          iterations=iterations, threshold=threshold, ground_z=ground_z, init=init, time_limit=time_limit)
    return text(result)


@mcp.tool()
def pixel_to_world(camera: str, pixels: list[list[float]], image_size: list[float], plane_z: float = 0.0, plane: dict | None = None) -> str:
    """Turn picture pixels into world points. A ray goes from the camera through each pixel and hits the plane z=`plane_z`
    (the floor by default) or `plane` {"point": [x,y,z], "normal": [x,y,z]}. `pixels` is a list of [x, y]: x to the
    right, y down, from the top left of a picture of `image_size` [width, height]. It uses the field of view, the sensor
    fit, the lens shift and orthographic cameras. A point is null if the ray is parallel to the plane or the plane is
    behind the camera. Use it to read sizes and positions off a photo after match_camera (for example the width of
    something that stands on the floor). Heights above the plane cannot be read from one view."""
    return text(call("pixel_to_world", camera=camera, pixels=pixels, image_size=image_size, plane_z=plane_z, plane=plane))


@mcp.tool()
def place_at_pixel(object: str, camera: str, pixel: list[float], image_size: list[float], plane_z: float | None = None, anchor: Vec3 = (0.5, 0.5, 0)) -> str:
    """Move an object so that a point of its box lands where a picture pixel points. `anchor` is the point of the box
    of the object with its children as fractions (0.5, 0.5, 0 is the middle of the bottom). `pixel` is [x, y] in a
    picture of `image_size` [width, height], y down. With `plane_z` the ray from `camera` hits that horizontal plane.
    Without it the ray stops on the first surface of the scene (the object itself is ignored) and, if there is none,
    on the plane at the bottom height of the object. It only moves: size and rotation stay. Returns the description of
    the object and what it was placed on. Use it to put parts where the photo shows them, after match_camera.
    Without a photo use attach, move_to_contact or place_on."""
    return text(call("place_at_pixel", object=object, camera=camera, pixel=pixel, image_size=image_size, plane_z=plane_z, anchor=list(anchor)))
