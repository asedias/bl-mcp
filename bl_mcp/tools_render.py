from typing import Literal

from .app import Image, Vec3, call, mcp, text


@mcp.tool()
def set_camera(name: str = "camera", location: Vec3 | None = None, look_at: Vec3 | None = None, fov_deg: float = 35.0,
               ortho_scale: float | None = None, roll_deg: float = 0.0, frame: list[str] | None = None,
               azimuth: float | None = None, elevation: float | None = None, margin: float = 1.15,
               make_active: bool = True) -> str:
    """Create or update a camera for render_final. Place it one of two ways.
    Explicit: `location` and `look_at` in world metres; on an existing camera, one of them keeps the other.
    Framed: `frame` is a list of object names (with children); the camera stands so their box fits the view.
    `azimuth` (degrees around Z: 0 looks from the front at -Y, 90 from +X; 35 when empty) and `elevation` (above
    the horizon; 20 when empty) set the side; `margin` is spare room (1.15 = 15%); `look_at` overrides the aim point.
    `fov_deg` is the vertical field of view and is applied on every call, so repeat it on updates. fov_deg=0 or an
    `ortho_scale` (metres across) makes it orthographic. `roll_deg` rolls about the view axis. make_active sets the
    scene camera. Returns the location, the forward vector and the projection. For a camera that matches a photo
    use match_camera."""
    return text(call("set_camera", name=name, location=location and list(location), look_at=look_at and list(look_at),
                     fov_deg=fov_deg, ortho_scale=ortho_scale, roll_deg=roll_deg, frame=frame, azimuth=azimuth,
                     elevation=elevation, margin=margin, make_active=make_active))


@mcp.tool()
def setup_lighting(preset: Literal["three_point", "sun", "soft_studio", "night", "metal"] = "three_point", strength: float = 1.0, target: list[str] | None = None, color: str | list[float] | None = None) -> str:
    """Replace the studio lights with a preset. Lights are named bl_light_*; earlier ones are deleted first,
    so a second call never doubles them. Other lights in the scene are not touched.
    Presets: three_point (key, fill, rim), sun (one hard sun), soft_studio (large soft panels, even light),
    night (dim blue moon and a warm lamp), metal (for metal and glossy product shots: an interior HDRI that the surface
    reflects, a key spot and a rim spot). `strength` scales all of them (1 is a normal exposure).
    metal also replaces the world: set_world hdri='interior' at strength 0.6, hidden from the camera, so the backdrop keeps the colour it had.
    The answer has it under `world`; call set_world afterwards for another HDRI, rotation or backdrop. The other presets
    do not touch the world: with area lights only, metal has nothing to reflect and renders black or blown.
    `target` is a list of object names; light size and distance follow their box (default: all visible geometry).
    The key light stands front-right (azimuth 40) so it suits the default set_camera view.
    `color` tints the lights: '#rrggbb' or [r, g, b] (0-1). Pair it with set_world for the background."""
    return text(call("setup_lighting", preset=preset, strength=strength, target=target, color=color))


@mcp.tool()
def set_world(color: str | list[float] | None = None, strength: float = 1.0,
              preset: Literal["studio_grey", "white", "sky", "dark", "night"] | None = None, transparent: bool = False,
              hdri: str | None = None, rotation_deg: float = 0.0, visible_to_camera: bool = True) -> str:
    """Set the background and ambient light: a plain colour or an HDRI image. `color` is '#rrggbb' or [r, g, b] (0-1).
    An explicit `color` wins over the `preset` colour.
    `strength` multiplies the light (1 is normal). With neither colour, preset nor hdri only the strength changes.
    `hdri` lights the scene with an image and gives metal and glass something to reflect. It is a path to an .hdr or .exr
    file, or the name of a studio light shipped with Blender: city, courtyard, forest, interior, night, studio, sunrise, sunset
    (the answer lists them in `builtin_hdris`; an unknown name gives the list in the error). `rotation_deg` turns it about Z.
    visible_to_camera=false keeps the HDRI for light and reflections, and the camera sees the plain `color` or `preset`
    colour instead (without them: the colour the world had). Works in eevee and cycles.
    A later call without `hdri` and with a colour or preset makes the world a plain colour again.
    transparent=true makes the render background transparent (alpha 0) and the world only lights the scene.
    The flag stays on until set_world is called again with transparent=false."""
    return text(call("set_world", color=color, strength=strength, preset=preset, transparent=transparent, hdri=hdri,
                     rotation_deg=rotation_deg, visible_to_camera=visible_to_camera))


@mcp.tool()
def render_final(path: str, engine: Literal["eevee", "cycles", "workbench"] = "eevee", size: int | list[int] = 1024, samples: int = 64,
                 transparent: bool = False, camera: str | None = None,
                 file_format: Literal["PNG", "JPEG", "WEBP", "TIFF", "OPEN_EXR", "BMP"] = "PNG", denoise: bool = True, view_transform: str = "Standard",
                 exposure: float | None = None, auto_exposure: bool = False, meter: list[str] | None = None) -> list:
    """Render the scene to a file with its own lights, materials and camera, and show the picture. Needs a camera:
    call set_camera first (or pass `camera`). For quick check pictures use render_sheet (overview) or render_view (any
    angle, no set-up). `path` is absolute, or relative to the work folder; the folder is created.
    `engine`: eevee (fast), cycles (slow, CPU, real light), workbench (flat preview, no lights needed).
    `size` is pixels for a square, or [width, height]. `samples` is the quality: 16-64 for eevee, 32-256 for cycles.
    `transparent` writes alpha (PNG, WEBP, TIFF, OPEN_EXR) and hides the world. `denoise` is for cycles only.
    `view_transform`: Standard keeps colours true; Filmic, AgX or Khronos PBR Neutral if the Blender build has them.
    `exposure` is in stops for this render only (+1 doubles the light); without it the scene exposure (set_post) is used.
    auto_exposure=true first renders a small probe and picks the exposure that puts the median luminance of the
    geometry at mid grey; the answer has `auto_exposure`. `meter` is a list of object names (with children) to
    measure instead of all geometry: give the model, so a floor or backdrop does not steer the exposure.
    Except for OPEN_EXR the answer has tone numbers of the written picture (0-1): `frame` and, when the geometry is
    known (meter, auto_exposure or transparent), `object`: median, mean, clipped_highlights and crushed_blacks.
    `warnings` appears when over 10% is clipped or over 50% is black. Read these numbers before you trust the
    picture. The scene settings are restored afterwards."""
    result = call("render_final", path=path, engine=engine, size=size, samples=samples, transparent=transparent,
                  camera=camera, file_format=file_format, denoise=denoise, view_transform=view_transform,
                  exposure=exposure, auto_exposure=auto_exposure, meter=meter)
    if file_format.upper() in {"PNG", "JPEG"}:
        return [text(result), Image(path=result["path"])]
    return text(result)


@mcp.tool()
def save_blend(path: str, make_current: bool = False, compress: bool = True) -> str:
    """Save the scene to a .blend file. By default it saves a copy: the open file and its name stay as they were.
    make_current=true makes the saved file the open one (like Save As). `path` is absolute or relative to the work
    folder; .blend is added if missing. compress=true gives a smaller file."""
    return text(call("save_blend", path=path, make_current=make_current, compress=compress))

