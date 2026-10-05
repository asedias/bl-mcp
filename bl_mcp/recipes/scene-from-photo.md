summary: Scene that matches one perspective photo: matched camera, overlay, positions from pixels, final render.

Use for a photo from a real camera. The flat views of `compare_view` do not fit a photo: its IoU means nothing there. The silhouette IoU against a photo comes from `match_camera` and `overlay_reference` only.

## Numbers first

- One real size in the photo: the length of the main object, the width of a plank. Without it the scene has no scale.
- The size of the photo in pixels: [width, height].
- The lens, if known: the field of view across the longer side of the photo.

## Steps

1. `status`, `scene_tree`, `checkpoint`.
2. Use the whole original photo in every step. Do not crop it.
3. Build the ground or the table top at z = 0. Build the main object as a simple model at real size (see `prop-hard-surface` or `weapon-from-sheet`). Put it on the ground.
4. Start camera: `set_camera(location=, look_at=, fov_deg=)` close to the view of the photo. A close start gives a better match.
5. `match_camera(reference=, names=, fov_deg=, ground_z=0)` with the main object as names. Give `fov_deg` when the lens is known. It runs as a background job: ask `job_status`. Read the IoU before and after, and the frame size.
6. `overlay_reference(reference=, mode='edges')`: red is the outline of the photo, green the outline of the model. Then `mode='split'`: lines must continue across the white line. Read the IoU.
7. Outlines differ in shape: fix the model. Outlines differ in place or size: call `match_camera` again with `init` from the last answer.
8. Positions on the ground: `pixel_to_world(camera=, pixels=[[x, y]], image_size=[width, height], plane_z=0)`. A pixel is x to the right and y down from the top left. Measure a known length this way to prove the scale.
9. Each further object: build it at real size, then `place_at_pixel(object=, camera=, pixel=, image_size=, plane_z=)`. The `anchor` point of its box lands where the pixel points. It only moves the object: turn it with `transform_objects(names=, rotate_deg=)`.
10. After each object: `overlay_reference(reference=, mode='blend', alpha=0.5)`. Fix every shift of more than a few pixels.
11. Heights above the ground: take them from known sizes. One view cannot give them. For a point on a known surface use `plane` in `pixel_to_world`.
12. Light as in the photo. Read the light direction from the shadows. `add_light(kind=, location=, look_at=, power_w=)` for the key light, `set_world` for the ambient light. See `materials-and-render`.
13. `render_final(path=, camera=, size=[width, height], auto_exposure=true, meter=)` with the matched camera and the main object as meter.
14. Last check: `overlay_reference(reference=, mode='difference')`. Black is a match. `save_blend`.

## Traps

- A crop moves the centre of the frame and changes the field of view. `prepare_reference` crops to the silhouette: do not give its result to `match_camera`.
- `match_camera` needs the outline of the subject: an alpha channel or a plain background. A photo with a busy background has no outline. Make a copy of the photo with the same pixel size and a plain background, or set the camera by hand with `set_camera` and judge with `overlay_reference`.
- Distance and field of view trade off against each other. A simple box model leaves play along the view ray. Fix `fov_deg` when you know the lens.
- `fov_deg` of `match_camera` is the angle across the longer side of the picture. `fov_deg` of `set_camera` is the vertical angle. Do not copy one into the other for a wide picture.
- A silhouette does not tell the front from the back of a symmetric model. Check the result in the overlay.
- `overlay_reference` fails without a camera in the scene. `match_camera` makes its camera the active one.
- `place_at_pixel` without `plane_z` stops on the first surface under the pixel. Give `plane_z` for an object that stands on the ground behind another one.
- Separate renders hide position errors. In a test only the blend overlay showed that the lower frame edge sat 60 to 100 pixels off.
- `setup_lighting` replaces only its own lights. Lights from `add_light` stay: list them with `list_lights`.

## Done when

- The IoU of `overlay_reference` no longer grows with a new camera match.
- In the split overlay the edges of every object continue across the line.
- A known length, measured with `pixel_to_world`, is within 3 % of its real size.
- The numbers of `render_final` show no warning (see `materials-and-render`).
