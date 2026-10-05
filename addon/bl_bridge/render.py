"""Camera, lights, world, final render, save."""

import math

import bpy
import numpy as np
from mathutils import Quaternion, Vector

from .core import *  # noqa: F401,F403
from .core import camera_fit, handler

LIGHT_PREFIX = "bl_light_"
FILE_FORMATS = {"PNG", "JPEG", "WEBP", "TIFF", "OPEN_EXR", "BMP"}
ENGINES = {
    "eevee": ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"),
    "cycles": ("CYCLES",),
    "workbench": ("BLENDER_WORKBENCH",),
}
WORLD_PRESETS = {
    "studio_grey": ((0.18, 0.18, 0.19), 1.0),
    "white": ((1.0, 1.0, 1.0), 1.0),
    "sky": ((0.32, 0.55, 1.0), 1.0),
    "dark": ((0.02, 0.02, 0.025), 1.0),
    "night": ((0.01, 0.015, 0.05), 0.6),
}
# name: (kind, azimuth, elevation, strength factor, size factor, rgb); azimuth 0 is the -Y side
LIGHT_RIGS = {
    "three_point": [
        ("key", "AREA", 40, 40, 1.0, 1.0, (1.0, 0.96, 0.9)),
        ("fill", "AREA", -60, 15, 0.35, 1.2, (0.85, 0.9, 1.0)),
        ("rim", "AREA", 180, 35, 0.8, 0.8, (1.0, 1.0, 1.0)),
    ],
    "sun": [("sun", "SUN", 35, 50, 1.0, 1.0, (1.0, 0.97, 0.92))],
    "soft_studio": [
        ("top", "AREA", 0, 85, 1.0, 2.0, (1.0, 1.0, 1.0)),
        ("left", "AREA", -75, 25, 0.5, 2.0, (1.0, 1.0, 1.0)),
        ("right", "AREA", 75, 25, 0.5, 2.0, (1.0, 1.0, 1.0)),
        ("front", "AREA", 0, 15, 0.3, 2.0, (1.0, 1.0, 1.0)),
    ],
    "night": [
        ("moon", "SUN", 60, 45, 0.12, 1.0, (0.45, 0.55, 1.0)),
        ("lamp", "POINT", -30, 30, 0.5, 0.2, (1.0, 0.65, 0.3)),
    ],
    "metal": [
        ("key", "SPOT", 40, 45, 0.2, 0.15, (1.0, 0.97, 0.92)),
        ("rim", "SPOT", 200, 35, 0.35, 0.1, (0.9, 0.95, 1.0)),
    ],
}
# preset: (built-in HDRI, world strength); metal shows what it reflects, so these presets also set the world
RIG_WORLDS = {"metal": ("interior", 0.6)}
SPOT_CONE_DEG = 50.0
HDRI_LIGHT = "bl_hdri_light"
BACKDROP = "bl_backdrop"
PROBE_PIXELS = 128
PROBE_SAMPLES = 16
MID_GREY = 0.18
HIGHLIGHT_CEILING = 0.9
HIGHLIGHT_PULL_STOPS = 1.5
EXPOSURE_LIMIT = 6.0
CLIPPED, CRUSHED = 0.98, 0.02
# a few percent of white is normal on metal: lamps mirror in it
CLIPPED_WARN, CRUSHED_WARN = 0.1, 0.5
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
DISPLAY_FORMATS = {"PNG", "JPEG", "WEBP", "TIFF", "BMP"}
AREA_WATTS_PER_M2 = 12.0
POINT_WATTS_PER_M2 = 36.0
SUN_WATTS = 3.0


def direction_of(azimuth, elevation):
    az, el = math.radians(azimuth), math.radians(max(-89.5, min(89.5, elevation)))
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


def aim(obj, position, target, roll_deg=0.0):
    forward = Vector(target) - Vector(position)
    if forward.length < 1e-9:
        raise ValueError("look_at equals the camera location")
    rotation = forward.to_track_quat("-Z", "Y")
    if roll_deg:
        rotation = Quaternion(forward.normalized(), math.radians(roll_deg)) @ rotation
    obj.location = position
    obj.rotation_euler = rotation.to_euler()
    bpy.context.view_layer.update()


def cloud_of(names):
    objs = with_children(names) if names else scene_objects()
    if not objs:
        raise ValueError("Nothing to frame: the scene has no visible geometry")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return np.vstack([points_of(o, depsgraph) for o in objs])


def box_of(names):
    cloud = cloud_of(names)
    low, high = Vector(cloud.min(axis=0)), Vector(cloud.max(axis=0))
    return (low + high) / 2, float(np.linalg.norm(high - low))


def camera_object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        data = bpy.data.cameras.new(name)
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
    elif obj.type != "CAMERA":
        raise ValueError(f"{name!r} exists and is not a camera")
    return obj


def fit_distance(cloud, center, direction, fov_deg, margin):
    """Distance that keeps the cloud in a vertical-fit frame, also in a square or tall render."""
    aspect = min(1.0, bpy.context.scene.render.resolution_x / bpy.context.scene.render.resolution_y)
    offsets = cloud - np.array(center)
    basis = (-direction).to_track_quat("-Z", "Y").to_matrix()
    right, up = np.array(basis.col[0]), np.array(basis.col[1])
    reach = np.maximum(np.abs(offsets @ right) / aspect, np.abs(offsets @ up))
    needed = reach * margin / math.tan(math.radians(fov_deg) / 2) + offsets @ np.array(direction)
    return float(needed.max()) + 0.01


def apply_lens(data, fov_deg, ortho_scale):
    if ortho_scale or not fov_deg:
        data.type = "ORTHO"
        if ortho_scale:
            data.ortho_scale = ortho_scale
    else:
        data.type, data.sensor_fit, data.angle_y = "PERSP", "VERTICAL", math.radians(fov_deg)


def camera_report(obj):
    data = obj.data
    forward = obj.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    return {
        "camera": obj.name,
        "location": rvec(obj.location, 3),
        "forward": rvec(forward, 3),
        "projection": "orthographic" if data.type == "ORTHO" else f"perspective {rnd(math.degrees(data.angle_y), 2)} deg",
        "ortho_scale": rnd(data.ortho_scale, 3) if data.type == "ORTHO" else None,
        "active": bpy.context.scene.camera is obj,
    }


@handler
def set_camera(name="camera", location=None, look_at=None, fov_deg=35.0, ortho_scale=None, roll_deg=0.0, frame=None,
               azimuth=None, elevation=None, margin=1.15, make_active=True):
    if frame and location is not None:
        raise ValueError("Give either location or frame, not both")
    if (azimuth is not None or elevation is not None) and not frame:
        raise ValueError("azimuth and elevation need frame")
    existing = bpy.data.objects.get(name)
    if not frame and location is None and look_at is None and existing is None:
        raise ValueError("A new camera needs location and look_at, or frame with azimuth and elevation")
    obj = camera_object(name)
    apply_lens(obj.data, fov_deg, ortho_scale)
    if frame:
        cloud = cloud_of(frame)
        center = Vector(look_at) if look_at is not None else Vector((cloud.min(axis=0) + cloud.max(axis=0)) / 2)
        direction = direction_of(35.0 if azimuth is None else azimuth, 20.0 if elevation is None else elevation)
        if obj.data.type == "ORTHO":
            distance, fitted_scale = camera_fit(cloud, center, direction, 0.0, margin)
            obj.data.ortho_scale = ortho_scale or fitted_scale
        else:
            distance = fit_distance(cloud, center, direction, fov_deg, margin)
        obj.data.clip_start, obj.data.clip_end = 0.01, max(100.0, distance * 4 + 10)
        aim(obj, center + direction * distance, center, roll_deg)
    else:
        position = Vector(location) if location is not None else obj.location.copy()
        target = Vector(look_at) if look_at is not None else position + obj.matrix_world.to_quaternion() @ Vector((0, 0, -1))
        aim(obj, position, target, roll_deg)
    if make_active:
        bpy.context.scene.camera = obj
    return camera_report(obj)


def clear_lights():
    removed = 0
    for obj in [o for o in bpy.data.objects if o.name.startswith(LIGHT_PREFIX)]:
        data = obj.data
        bpy.data.objects.remove(obj)
        if data is not None and data.users == 0:
            bpy.data.lights.remove(data)
        removed += 1
    return removed


def light_power(kind, strength, distance):
    if kind == "SUN":
        return SUN_WATTS * strength
    per_m2 = AREA_WATTS_PER_M2 if kind == "AREA" else POINT_WATTS_PER_M2
    return per_m2 * distance * distance * strength


@handler
def setup_lighting(preset="three_point", strength=1.0, target=None, color=None):
    if preset not in LIGHT_RIGS:
        raise ValueError(f"Unknown preset {preset!r}. Known: {sorted(LIGHT_RIGS)}")
    if strength <= 0:
        raise ValueError("strength must be positive")
    center, diagonal = box_of(target)
    diagonal = max(diagonal, 0.1)
    distance = diagonal * 1.6
    tint = parse_color(color) if color is not None else (1.0, 1.0, 1.0)
    clear_lights()
    world = None
    if preset in RIG_WORLDS:
        hdri, world_strength = RIG_WORLDS[preset]
        world = set_world(strength=world_strength * strength, hdri=hdri, visible_to_camera=False,
                          transparent=bpy.context.scene.render.film_transparent)
    made = []
    for label, kind, azimuth, elevation, factor, size_factor, rgb in LIGHT_RIGS[preset]:
        data = bpy.data.lights.new(LIGHT_PREFIX + label, kind)
        data.color = [a * b for a, b in zip(rgb, tint)]
        size = diagonal * size_factor
        if kind == "AREA":
            data.shape, data.size = "SQUARE", size
        elif kind == "POINT":
            data.shadow_soft_size = size
        elif kind == "SPOT":
            data.spot_size, data.spot_blend, data.shadow_soft_size = math.radians(SPOT_CONE_DEG), 0.5, size
        else:
            data.angle = math.radians(5 if preset == "sun" else 15)
        data.energy = light_power(kind, strength * factor, distance)
        obj = bpy.data.objects.new(LIGHT_PREFIX + label, data)
        bpy.context.scene.collection.objects.link(obj)
        position = center + direction_of(azimuth, elevation) * distance
        obj.location = position
        obj.rotation_euler = (center - position).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        made.append({"name": obj.name, "type": kind, "energy": rnd(data.energy, 2), "location": rvec(position, 3)})
    result = {"preset": preset, "lights": made, "centre": rvec(center, 3), "distance_m": rnd(distance, 3)}
    if world:
        result["world"] = world
    return result


def background_node(world):
    tree = world.node_tree
    node = next((n for n in tree.nodes if n.type == "BACKGROUND"), None)
    if node is None:
        node = tree.nodes.new("ShaderNodeBackground")
    output = next((n for n in tree.nodes if n.type == "OUTPUT_WORLD"), None)
    if output is None:
        output = tree.nodes.new("ShaderNodeOutputWorld")
    if not output.inputs["Surface"].is_linked:
        tree.links.new(node.outputs["Background"], output.inputs["Surface"])
    for link in list(tree.links):
        if link.to_node is node and link.to_socket.name == "Color":
            tree.links.remove(link)
    return node


def builtin_hdris():
    lights = bpy.context.preferences.studio_lights
    return {Path(light.name).stem: light.path for light in lights if light.type == "WORLD" and light.path}


def hdri_file(hdri):
    known = builtin_hdris()
    path = Path(known[hdri]) if hdri in known else Path(hdri).expanduser()
    if not path.is_file():
        raise ValueError(f"No HDRI {hdri!r}. Give a path to an .hdr or .exr file, or a built-in name: {sorted(known)}")
    return path


def backdrop_color(world):
    nodes = world.node_tree.nodes
    node = nodes.get(BACKDROP) or next((n for n in nodes if n.type == "BACKGROUND" and not n.inputs["Color"].is_linked), None)
    return list(node.inputs["Color"].default_value[:3]) if node else list(world.color)


def build_hdri_world(world, path, rotation_deg, backdrop, visible_to_camera):
    """The HDRI lights the scene and shows in reflections; when hidden, camera rays get the plain backdrop instead."""
    tree = world.node_tree
    tree.nodes.clear()
    new, link = tree.nodes.new, tree.links.new
    coords, mapping, env = new("ShaderNodeTexCoord"), new("ShaderNodeMapping"), new("ShaderNodeTexEnvironment")
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(rotation_deg))
    env.image = bpy.data.images.load(str(path), check_existing=True)
    link(coords.outputs["Generated"], mapping.inputs["Vector"])
    link(mapping.outputs["Vector"], env.inputs["Vector"])
    light, plain, output = new("ShaderNodeBackground"), new("ShaderNodeBackground"), new("ShaderNodeOutputWorld")
    light.name, plain.name = HDRI_LIGHT, BACKDROP
    plain.inputs["Color"].default_value = (*backdrop, 1.0)
    link(env.outputs["Color"], light.inputs["Color"])
    if visible_to_camera:
        link(light.outputs["Background"], output.inputs["Surface"])
    else:
        rays, mix = new("ShaderNodeLightPath"), new("ShaderNodeMixShader")
        link(rays.outputs["Is Camera Ray"], mix.inputs["Fac"])
        link(light.outputs["Background"], mix.inputs[1])
        link(plain.outputs["Background"], mix.inputs[2])
        link(mix.outputs["Shader"], output.inputs["Surface"])
    for x, node in enumerate(tree.nodes):
        node.location = (x * 220 - 1200, 0)
    return light


def hdri_report(world):
    env = next((n for n in world.node_tree.nodes if n.type == "TEX_ENVIRONMENT" and n.image), None)
    if env is None or world.node_tree.nodes.get(HDRI_LIGHT) is None:
        return {"hdri": None}
    mapping = next(n for n in world.node_tree.nodes if n.type == "MAPPING")
    return {
        "hdri": env.image.filepath,
        "rotation_deg": rnd(math.degrees(mapping.inputs["Rotation"].default_value[2]), 2),
        "visible_to_camera": not any(n.type == "MIX_SHADER" for n in world.node_tree.nodes),
        "builtin_hdris": sorted(builtin_hdris()),
    }


@handler
def set_world(color=None, strength=1.0, preset=None, transparent=False, hdri=None, rotation_deg=0.0, visible_to_camera=True):
    if preset is not None and preset not in WORLD_PRESETS:
        raise ValueError(f"Unknown preset {preset!r}. Known: {sorted(WORLD_PRESETS)}")
    path = hdri_file(hdri) if hdri is not None else None
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    world = scene.world
    set_if_valid(world, "use_nodes", True)
    base, base_strength = WORLD_PRESETS[preset] if preset else (None, 1.0)
    rgb = parse_color(color) if color is not None else base
    light = world.node_tree.nodes.get(HDRI_LIGHT)
    if path is not None:
        backdrop = rgb[:3] if rgb is not None else backdrop_color(world)
        light = build_hdri_world(world, path, rotation_deg, backdrop, visible_to_camera)
        world.color = backdrop
        base_strength = 1.0
    elif rgb is not None or light is None:
        if light is not None:
            world.node_tree.nodes.clear()
        light = background_node(world)
        if rgb is not None:
            light.inputs["Color"].default_value = (*rgb[:3], 1.0)
            world.color = rgb[:3]
    light.inputs["Strength"].default_value = strength * base_strength
    scene.render.film_transparent = bool(transparent)
    return {
        "color": rvec(backdrop_color(world), 4),
        "strength": rnd(light.inputs["Strength"].default_value, 3),
        "transparent": scene.render.film_transparent,
        **hdri_report(world),
    }


def pick_engine(engine):
    """The engine id this Blender accepts; found by assignment because add-on engines are not listed up front."""
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine {engine!r}. Known: {sorted(ENGINES)}")
    render = bpy.context.scene.render
    saved = render.engine
    try:
        for candidate in ENGINES[engine]:
            if set_if_valid_flag(render, "engine", candidate):
                return candidate
    finally:
        render.engine = saved
    raise ValueError(f"Engine {engine!r} is not available in this Blender")


def resolution_of(size):
    width, height = (size, size) if isinstance(size, (int, float)) else size
    width, height = int(width), int(height)
    if not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ValueError("size must be between 1 and 16384 pixels")
    return width, height


def render_state(scene):
    r = scene.render
    targets = [
        (r, a) for a in ("engine", "resolution_x", "resolution_y", "resolution_percentage", "filepath", "film_transparent", "use_file_extension")
    ] + [(r.image_settings, a) for a in ("file_format", "color_mode")]
    targets += [(r.image_settings, "color_depth"), (scene.view_settings, "view_transform"), (scene.view_settings, "exposure")]
    targets += [(scene.eevee, "taa_render_samples"), (scene, "camera")]
    targets += [(scene.cycles, a) for a in ("samples", "use_denoising", "device") if hasattr(scene, "cycles")]
    return [(t, a, getattr(t, a)) for t, a in targets if hasattr(t, a)]


def restore_state(saved):
    for target, attr, value in saved:
        set_if_valid(target, attr, value)


def configure_render(scene, engine_id, engine, width, height, samples, transparent, file_format, denoise, view_transform):
    r = scene.render
    r.engine = engine_id
    r.resolution_x, r.resolution_y, r.resolution_percentage = width, height, 100
    r.use_file_extension = False
    r.film_transparent = transparent
    r.image_settings.file_format = file_format
    keep_alpha = transparent and file_format in {"PNG", "WEBP", "TIFF", "OPEN_EXR"}
    r.image_settings.color_mode = "RGBA" if keep_alpha else "RGB"
    if not set_if_valid_flag(scene.view_settings, "view_transform", view_transform):
        raise ValueError(f"Unknown view_transform {view_transform!r}")
    if engine == "eevee":
        scene.eevee.taa_render_samples = samples
    elif engine == "cycles":
        scene.cycles.samples = samples
        scene.cycles.use_denoising = denoise
        scene.cycles.device = "CPU"


def set_if_valid_flag(target, attr, value):
    try:
        setattr(target, attr, value)
    except TypeError:
        return False
    return True


def meter_mask(cam, names, width, height):
    """Pixels of the named objects as the camera sees them, from a flat white render in a temporary scene."""
    objs = [o for o in with_children(names) if o.type in BOUNDED]
    if not objs:
        raise ValueError(f"meter {names} has no geometry")
    RENDERS.mkdir(parents=True, exist_ok=True)
    path = RENDERS / "meter_mask.png"
    with temp_scene([*objs, cam], "mask") as scene:
        scene.camera = cam
        scene.render.resolution_x, scene.render.resolution_y = width, height
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True, scene=scene.name)
    return read_pixels(path)[:, :, 0] > 0.5


def probe_size(width, height):
    scale = PROBE_PIXELS / max(width, height)
    return max(8, round(width * scale)), max(8, round(height * scale))


def render_probe(scene, engine, samples):
    """A small linear EXR with a transparent film: scene-referred light, and alpha marks the geometry."""
    r = scene.render
    r.resolution_x, r.resolution_y = probe_size(r.resolution_x, r.resolution_y)
    r.film_transparent = True
    r.image_settings.file_format, r.image_settings.color_mode = "OPEN_EXR", "RGBA"
    if engine == "eevee":
        scene.eevee.taa_render_samples = min(samples, PROBE_SAMPLES)
    elif engine == "cycles":
        scene.cycles.samples, scene.cycles.use_denoising = min(samples, PROBE_SAMPLES), False
    RENDERS.mkdir(parents=True, exist_ok=True)
    r.filepath = str(RENDERS / "exposure_probe.exr")
    bpy.ops.render.render(write_still=True)
    return read_pixels(r.filepath)


def choose_exposure(luma):
    """Stops that bring the median to mid grey; bright highlights may pull it down, but only by a limited amount."""
    median, high = float(np.percentile(luma, 50)), float(np.percentile(luma, 95))
    to_mid = math.log2(MID_GREY / max(median, 1e-6))
    to_ceiling = math.log2(HIGHLIGHT_CEILING / max(high, 1e-6))
    stops = max(min(to_mid, to_ceiling), to_mid - HIGHLIGHT_PULL_STOPS)
    stops = max(-EXPOSURE_LIMIT, min(EXPOSURE_LIMIT, stops))
    report = {"median": rnd(median, 5), "p95": rnd(high, 5), "pixels": int(luma.size), "exposure": rnd(stops, 2),
              "expected_median": rnd(median * 2**stops, 4), "expected_p95": rnd(high * 2**stops, 4)}
    if high < 1e-4:
        report["warning"] = "The metered pixels get almost no light: exposure cannot fix it. Add lights or a world (set_world hdri for metal)"
    return stops, report


def tone_stats(pixels, mask=None):
    luma = pixels[..., :3] @ LUMA
    if mask is not None:
        luma = luma[mask]
    return {"median": rnd(np.median(luma), 3), "mean": rnd(luma.mean(), 3),
            "clipped_highlights": rnd((luma >= CLIPPED).mean(), 4), "crushed_blacks": rnd((luma <= CRUSHED).mean(), 4)}


def tone_warnings(stats, subject):
    warnings = []
    if stats["clipped_highlights"] > CLIPPED_WARN:
        warnings.append(f"{stats['clipped_highlights']:.0%} of the {subject} is clipped to white: lower exposure, the light power or the world strength")
    if stats["crushed_blacks"] > CRUSHED_WARN:
        warnings.append(f"{stats['crushed_blacks']:.0%} of the {subject} is black: raise exposure or add light; metal needs something to reflect (set_world hdri)")
    return warnings


def tone_report(path, mask):
    """Tone numbers of the written picture, so a black or blown frame shows as a number."""
    pixels = read_pixels(path)
    report = {"frame": tone_stats(pixels)}
    if mask is not None and mask.shape != pixels.shape[:2]:
        mask = resize_nearest(mask, *pixels.shape[:2])
    if mask is None and pixels[..., 3].min() < 0.5:
        mask = pixels[..., 3] > 0.5
    if mask is not None and mask.any():
        report["object"] = tone_stats(pixels, mask)
    subject = "object" if "object" in report else "frame"
    warnings = tone_warnings(report[subject], subject)
    if warnings:
        report["warnings"] = warnings
    return report


@handler
def render_final(path, engine="eevee", size=1024, samples=64, transparent=False, camera=None, file_format="PNG",
                 denoise=True, view_transform="Standard", exposure=None, auto_exposure=False, meter=None):
    scene = bpy.context.scene
    if exposure is not None and auto_exposure:
        raise ValueError("Give exposure or auto_exposure, not both")
    file_format = file_format.upper()
    if file_format not in FILE_FORMATS:
        raise ValueError(f"file_format is one of {sorted(FILE_FORMATS)}")
    if samples < 1:
        raise ValueError("samples must be at least 1")
    engine_id = pick_engine(engine)
    width, height = resolution_of(size)
    cam = get_object(camera) if camera else scene.camera
    if cam is None:
        raise ValueError("No camera: call set_camera first or pass camera=")
    if cam.type != "CAMERA":
        raise ValueError(f"{cam.name!r} is not a camera")
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = RENDERS / target
    target.parent.mkdir(parents=True, exist_ok=True)
    saved = render_state(scene)
    started = time.time()
    mask = meter_mask(cam, meter, width, height) if meter else None
    probe = None
    try:
        if auto_exposure:
            configure_render(scene, engine_id, engine, width, height, samples, transparent, file_format, denoise, view_transform)
            scene.camera = cam
            pixels = render_probe(scene, engine, samples)
            if mask is None:
                mask = pixels[..., 3] > 0.5
            metered = (pixels[..., :3] @ LUMA)[resize_nearest(mask, *pixels.shape[:2])]
            if not metered.size:
                raise ValueError("auto_exposure found no geometry in the frame: aim the camera with set_camera frame=[...]")
            exposure, probe = choose_exposure(metered)
            restore_state(saved)
        configure_render(scene, engine_id, engine, width, height, samples, transparent, file_format, denoise, view_transform)
        if exposure is not None:
            scene.view_settings.exposure = exposure
        used_exposure = scene.view_settings.exposure
        scene.camera = cam
        scene.render.filepath = str(target)
        bpy.ops.render.render(write_still=True)
    finally:
        restore_state(saved)
    if not target.exists():
        raise ValueError(f"Blender wrote no file at {target}")
    result = {
        "path": str(target),
        "size": [width, height],
        "engine": engine_id,
        "seconds": rnd(time.time() - started, 2),
        "camera": cam.name,
        "bytes": target.stat().st_size,
        "exposure": rnd(used_exposure, 2),
    }
    if probe:
        result["auto_exposure"] = probe
    if file_format in DISPLAY_FORMATS:
        result.update(tone_report(target, mask))
    return result


@handler
def save_blend(path, make_current=False, compress=True):
    target = Path(path).expanduser()
    if target.suffix != ".blend":
        target = target.with_name(target.name + ".blend")
    if not target.is_absolute():
        target = WORK / target
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(target), copy=not make_current, compress=compress)
    return {"path": str(target), "bytes": target.stat().st_size, "current_file": bpy.data.filepath or None}

