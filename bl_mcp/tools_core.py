from typing import Literal

from . import toolsets
from .app import BlenderError, Image, Vec3, call, call_waiting, mcp, registry_gaps, sheet, text, EXPECTED_ADDON  # noqa: F401

Axis = Literal["X", "Y", "Z"]


@mcp.tool()
def status() -> str:
    """Call it first. Blender version, add-on version, open file, scene and its object count, and the toolsets of this
    server. It compares the tools of this server with the handlers of the add-on: `server_is_stale` means restart the MCP
    server, `addon_is_stale` means restart Blender. When Blender is not reachable it says where Blender is installed."""
    try:
        info = call("status")
    except BlenderError as error:
        return text(bridge_down(str(error)))
    version = info.get("addon_version") or ""
    if not version.startswith(EXPECTED_ADDON):
        info["warning"] = f"Add-on {version or 'unknown'} does not match the server ({EXPECTED_ADDON}.x): update the add-on files and restart Blender."
    handlers = info.pop("handlers", None)
    if handlers is None:
        info["addon_is_stale"] = "The add-on does not report its handlers, so the tool lists were not compared. Restart Blender."
    else:
        info["handlers"] = len(handlers)
        info.update(registry_gaps(handlers))
    info["toolsets"] = toolsets.report()
    return text(info)


def bridge_down(error):
    from .locate import find_blenders, version_of

    found = find_blenders()
    result = {"bridge": "down", "error": error, "blender_found": found}
    if found:
        best = found[0]["path"]
        result["version"] = version_of(best)
        result["headless"] = f'"{best}" --background --factory-startup --python script.py -- args'
        result["hint"] = "Open Blender and enable the add-on BL MCP Bridge (Edit > Preferences > Add-ons), then call status again."
    else:
        result["hint"] = "Blender was not found in PATH or the standard install folders. Install or open Blender."
    return result


@mcp.tool()
def reload_addon() -> str:
    """Reload the add-on code inside Blender after its files changed. No restart needed. Scene stays as it is."""
    return text(call("__reload__"))


@mcp.tool()
def scene_tree(limit: int = 200) -> str:
    """Every object with type, collection, parent (by indent), world size, world minimum corner and triangle count.
    Shows the first `limit` objects."""
    return call("scene_tree", limit=limit)


@mcp.tool()
def measure(names: list[str]) -> str:
    """World-space size, min, max, center, origin position, origin inside the bounding box (0..1 per axis),
    rotation in degrees and scale. Notes say 'scale not applied' or 'negative scale'. Use it after every move.
    Use measure_profile to measure a reference image instead of an object."""
    return text(call("measure", names=names))


@mcp.tool()
def run_python(code: str, session: str | None = None, reset: bool = False, paths: list[str] | None = None) -> str:
    """Run Python in Blender (bpy, bmesh, mathutils, Vector, np, math are ready). Returns stdout, and the added,
    changed and removed objects with their world sizes, so silent mistakes show up. Prefer the other tools for
    moving, sizing and checking. The tool descriptions are the documentation: do not read the add-on source here. With `session` the variables, functions and imports stay between calls under that
    name (reset=true clears them; rollback clears all sessions). `paths` are folders added to the import path:
    keep your helper modules there and `import` them once."""
    return text(call("run_python", code=code, session=session, reset=reset, paths=paths or []))


@mcp.tool()
def job_status(job: str | None = None, cancel: bool = False) -> str:
    """State of a background job: running with progress, done with its result, failed with the error. Long tools
    (fit_to_reference, match_camera, bake_maps) return a job id when they run longer than their `wait` seconds.
    Without `job` it lists all jobs of this Blender session. cancel=true stops the job; the scene keeps the changes
    the job already made: use rollback to undo them."""
    return text(call("job_status", job=job, cancel=cancel))


@mcp.tool()
def attach(
    part: str,
    to: str,
    part_anchor: Vec3 = (0.5, 0.5, 0),
    to_anchor: Vec3 = (0.5, 0.5, 1),
    offset: Vec3 = (0, 0, 0),
    with_children: bool = True,
) -> str:
    """Align by bounding boxes: move `part` (with its children) so an anchor of its world box lands on an anchor of the
    box of `to`. Surfaces are not looked at: move_to_contact closes a real gap, place_on drops onto a surface. Anchors are fractions 0..1 per axis: (0.5,0.5,0) is bottom centre, (0.5,0.5,1) is top centre.
    Default puts the part on top of the target. `offset` is in metres. Both boxes include the children of each object;
    with_children=false measures the two objects alone (the children still move with the part). The answer gives
    `boxes_used` (objects, min, max, size of both boxes after the move) and `moved_by`; min and max at the top level
    are of `part` alone. Boxes do not follow round or slanted surfaces: use move_to_contact to close the real gap,
    place_on to drop onto uneven ground, transform_objects for a known offset."""
    return text(call("attach", part=part, to=to, part_anchor=list(part_anchor), to_anchor=list(to_anchor), offset=list(offset), with_children=with_children))


@mcp.tool()
def ground(names: list[str] | None = None, z: float = 0.0) -> str:
    """Set a level floor: move objects (all top-level objects when names is empty) so their lowest point sits at height
    z. No other object is looked at: use place_on when the floor is another object or not level."""
    return text(call("ground", names=names, z=z))


@mcp.tool()
def set_dimensions(
    name: str,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    uniform: bool = False,
    anchor: Vec3 = (0.5, 0.5, 0.5),
    apply: bool = True,
) -> str:
    """Set the size in metres. Empty axes stay. With uniform=true the first given axis sets a factor for all axes.
    The `anchor` point of the bounding box (fractions 0..1) stays where it is; (0.5,0.5,0) keeps the bottom.
    With apply=true the scale is baked into the mesh, so the object keeps scale 1 and exports cleanly."""
    return text(call("set_dimensions", name=name, x=x, y=y, z=z, uniform=uniform, anchor=list(anchor), apply=apply))


@mcp.tool()
def transform_objects(names: list[str], move: Vec3 | None = None, rotate_deg: Vec3 | None = None, scale: float | Vec3 | None = None, pivot: Vec3 | None = None) -> str:
    """Move, turn and scale objects together with their children. Order: scale, then rotate, then move. `rotate_deg`
    [rx, ry, rz] turns around the world X, then Y, then Z axis. `scale` is a number or [x, y, z] along the world axes.
    `pivot` is a world point for the turn and the scale; the default is the centre of the bounding box of all the
    objects and their children. Several objects turn as one group. Scaling a turned object by different factors
    on each axis shears it a little: set the size with set_dimensions first. The answer lists every object after the
    change. Use it when you know the numbers; to place a part against another use attach or move_to_contact."""
    return text(call("transform_objects", names=names, move=move and list(move), rotate_deg=rotate_deg and list(rotate_deg), scale=scale, pivot=pivot and list(pivot)))


@mcp.tool()
def apply_transforms(names: list[str], mode: Literal["scale", "scale_rotation", "all"] = "scale") -> str:
    """Bake the transform of meshes into their vertices, as Ctrl+A does. mode `all` also bakes the position: the
    origin goes to the world origin. Shared meshes are made single-user first, children keep their place in the
    world, mirrored (negative) scale is handled without flipped normals."""
    return text(call("apply_transforms", names=names, mode=mode))


@mcp.tool()
def shade(names: list[str], mode: Literal["smooth", "flat", "auto"] = "smooth", angle: float = 30.0, weighted_normals: bool = False) -> str:
    """Set shading of meshes. smooth: every face and edge smooth. flat: every face flat. auto: smooth faces, but edges
    sharper than `angle` degrees stay sharp (a cube stays crisp, a sphere becomes smooth). Cheap and exports as is.
    weighted_normals=true (with smooth or auto) adds a Weighted Normal modifier that keeps sharp edges: large flat faces
    stay flat and only the bevels blend. Use it for parts with both bevels and flat chamfers, where no single angle
    works. export_glb writes these normals while apply_modifiers is true. A later shade call without it removes it.
    It changes normals only: to move vertices use sculpt with op smooth."""
    return text(call("shade", names=names, mode=mode, angle=angle, weighted_normals=weighted_normals))


@mcp.tool()
def subdivide(names: list[str], levels: int = 1, apply: bool = True) -> str:
    """Round the whole mesh with Catmull-Clark subdivision: the shape changes, each level quadruples the faces. apply=true bakes it
    into the mesh and sets smooth shading. Watch the triangle count in the answer against your budget. Use
    subdivide_faces to cut picked faces into a grid without rounding, remesh for an even skin over merged parts."""
    return text(call("subdivide", names=names, levels=levels, apply=apply))


@mcp.tool()
def create_primitive(
    kind: Literal["cube", "sphere", "cylinder", "cone", "plane", "torus"],
    name: str,
    size: Vec3 = (1, 1, 1),
    at: Vec3 = (0, 0, 0),
    anchor: Vec3 = (0.5, 0.5, 0.5),
    segments: int = 16,
    rotate_deg: Vec3 | None = None,
) -> str:
    """Create a primitive with a real size in metres (no hidden scale). For a torus size is [outer width, outer depth,
    tube thickness], segments is the count around the ring. The `anchor`
    point of its bounding box (fractions 0..1) is placed at world point `at`: anchor (0.5,0.5,0) with at (0,0,0)
    stands the shape on the ground. `size` is the size before rotation. `rotate_deg` [rx, ry, rz] turns the shape
    about the point `at` around the world X, then Y, then Z axis, after it is placed. A barrel along +X: a cylinder
    with rotate_deg [0, 90, 0]. The answer shows the size and box after the turn."""
    return text(call("create_primitive", kind=kind, name=name, size=list(size), at=list(at), anchor=list(anchor), segments=segments, rotate_deg=rotate_deg and list(rotate_deg)))


@mcp.tool()
def limb(name: str, points: list[Vec3], radii: list[float], sides: int = 8, subdivisions: int = 2, apply: bool = True) -> str:
    """Make a smooth tube along a polyline of world points (Skin plus Subdivision). One radius per point, or one
    radius for all. Good for arms, legs, tails, tentacles, branches. Ends are rounded and stay inside the path."""
    return text(call("limb", name=name, points=[list(p) for p in points], radii=radii, sides=sides, subdivisions=subdivisions, apply=apply))


@mcp.tool()
def loft(name: str, sections: list[dict], axis: Axis = "Z", segments: int = 16, caps: bool = True, subdivisions: int = 0) -> str:
    """Make a closed body from cross-sections you give as numbers along an axis. A section is {"at": [x,y,z],
    "size": [w,d], "roundness": 2}: roundness 2 is an ellipse, 4 is a rounded box. Sections go in order along the
    axis. Good for torsos, heads, bottles, columns. With a front and a side image of the form use loft_from_masks:
    it reads the sections from the images."""
    return text(call("loft", name=name, sections=sections, axis=axis, segments=segments, caps=caps, subdivisions=subdivisions))


@mcp.tool()
def mirror(name: str, axis: Axis = "X", at: float = 0.0, new_name: str | None = None) -> str:
    """Make a mirrored copy of a mesh across the plane at `at` on the axis. Normals stay outward. The name swaps
    L/R, Left/Right (arm_L becomes arm_R), or gets '_mirror'. The origin of the copy is the mirror image of the source
    origin; the copy has no rotation and scale 1."""
    return text(call("mirror", name=name, axis=axis, at=at, new_name=new_name))


@mcp.tool()
def parent(child: str, to: str, keep_world: bool = True) -> str:
    """Make `child` follow `to`. With keep_world the child stays where it is."""
    return text(call("parent", child=child, to=to, keep_world=keep_world))


@mcp.tool()
def duplicate(name: str, new_name: str | None = None, offset: Vec3 = (0, 0, 0), linked: bool = False, rotate_deg: Vec3 | None = None, pivot: Vec3 | None = None) -> str:
    """Copy an object and move the copy by `offset` metres. linked=true shares the mesh data. `rotate_deg` [rx, ry, rz]
    then turns the copy around the world X, Y, Z axes (in that order) about `pivot`, a world point. The default pivot is
    the centre of the copy's bounding box, after the offset."""
    return text(call("duplicate", name=name, new_name=new_name, offset=list(offset), linked=linked, rotate_deg=rotate_deg and list(rotate_deg), pivot=pivot and list(pivot)))


@mcp.tool()
def delete(names: list[str] | None = None, with_children: bool = False, prefix: str | None = None, lights: Literal["added", "all"] | None = None) -> str:
    """Delete whole objects. Take a checkpoint first if you are not sure. Give at least one of: `names`; `prefix`
    (every object whose name starts with it: 'bl_light_' removes the setup_lighting preset); `lights` (`added`: the
    lights made by add_light, `all`: every light). with_children=true also deletes everything parented to them.
    Otherwise the children stay where they are in the world and lose the parent: the answer lists them as
    `unparented`. Use delete_faces to remove a part of a mesh."""
    return text(call("delete", names=names, with_children=with_children, prefix=prefix, lights=lights))


@mcp.tool()
def export_glb(path: str, names: list[str] | None = None, apply_modifiers: bool = True, skins: bool = True, influences: int = 4, animations: bool = False, draco: bool = False, tangents: bool = False, scale: float = 1.0, max_texture_size: int | None = None) -> str:
    """Write a GLB of the named objects (with children), or of all visible geometry. glTF uses +Y up and triangulates
    every face. influences 4 (or 8) is the bones per vertex that the game engine reads. draco compresses geometry (the game
    needs the Draco decoder). Options this Blender does not know are reported as ignored_options. `scale` multiplies the
    whole export about the world origin (a 0.1 m model with scale 10 leaves as 1 m). The scene is restored after the
    export; the scale is written as the node scale of the top objects. `max_texture_size` (pixels on the longer side)
    writes smaller copies of larger textures into the GLB; the images in the scene and on disk stay as they are. Nine
    2048 px maps make a file of about 25 MB: 1024 or 512 is enough for a small prop. The answer has `textures`: count,
    bytes, and name, size and bytes of each image in the file."""
    return text(call("export_glb", path=path, names=names, apply_modifiers=apply_modifiers, skins=skins, influences=influences, animations=animations, draco=draco, tangents=tangents, scale=scale, max_texture_size=max_texture_size))


@mcp.tool()
def import_glb(path: str) -> str:
    """Import a GLB or glTF file and list the new objects with their world sizes."""
    return text(call("import_glb", path=path))


@mcp.tool()
def check_mesh(name: str) -> str:
    """Triangle and n-gon count, open holes, loose parts, zero-area faces, doubled vertices, inward normals and
    unapplied scale. 'issues' is ['none'] when the mesh is clean. `uv` is the quality of the UV map: island count,
    used area, faces outside 0..1, degenerate faces and texel_density_spread (largest to smallest UV area per surface
    area: 1 is even, above 4 is stretched), or 'none' when the mesh has no UV map."""
    return text(call("check_mesh", name=name))


@mcp.tool()
def check_symmetry(names: list[str], axis: Axis = "X", at: float | None = None, tolerance: float | None = None) -> str:
    """Mirror all vertices of the objects across a plane and count those without a partner within `tolerance`.
    `at` is the plane position on the axis; empty means the middle of the bounding box. Empty tolerance means
    0.005 m for objects of 0.3 m and more, and less for small ones (it follows the size). The answer shows the value used."""
    return text(call("check_symmetry", names=names, axis=axis, at=at, tolerance=tolerance))


@mcp.tool()
def find_floating(
    names: list[str] | None = None,
    touch: float | None = None,
    near: float | None = None,
    search: float | None = None,
    ground_z: float | None = None,
    max_listed: int = 12,
) -> str:
    """Find parts that hang in the air. Meshes that touch or overlap form groups; the main group is the one
    that stands on `ground_z` (or the largest). Every other group is floating: the answer names its nearest part
    and the gap. `tiny_gaps` lists pairs that miss by `touch`..`near` metres (seams you cannot see). Run it
    after assembling a model, then fix with move_to_contact or attach. Long lists are folded to `max_listed` entries
    with a count. Empty touch and search follow the part size: 0.001 m and 1 m for parts of 0.3 m and more, less for
    small parts (a 5 cm part gets about a sixth). Empty near is 2 percent of the size of each pair (the diagonal of
    both parts together), at most 0.03 m: about 6 mm for a pair 0.3 m across. Each tiny gap shows the `near` it was
    held against. Give numbers in metres to fix them."""
    return text(call("find_floating", names=names, touch=touch, near=near, search=search, ground_z=ground_z, max_listed=max_listed))


@mcp.tool()
def move_to_contact(a: str, to: str, axis: Literal["X", "-X", "Y", "-Y", "Z", "-Z"] | None = None, depth: float = 0.0) -> str:
    """Close a gap by surfaces: slide `a` (with children) until its mesh touches the mesh of `to` (attach aligns
    boxes instead, place_on drops by a ray). Without `axis` it takes the shortest
    way; with an axis it slides along that axis only, so other coordinates stay. `depth` sinks the part into the
    target by that many metres to hide the seam: use 0.005..0.02 for limbs and necks. If the parts already
    overlap nothing moves. The whole object moves, never only its end: for a long part that must stay put at the
    other end, resize it with set_dimensions and anchor, or rebuild it with limb. Use attach to align by bounding
    boxes, combine to merge meshes into one object."""
    return text(call("move_to_contact", a=a, to=to, axis=axis, depth=depth))


@mcp.tool()
def check_contacts(a: str, b: str) -> str:
    """State of two meshes: 'intersecting' (one pushes into the other), 'touching' or 'apart' (with the smallest vertex
    distance). For an overlap it gives the deepest sample, the median depth and the share of each mesh that lies inside
    the other: a glaze shell on a donut may have a deep spot (a drip) but a small median. Use it to find floating or
    sunken parts."""
    return text(call("check_contacts", a=a, b=b))


@mcp.tool()
def render_sheet(
    names: list[str] | None = None,
    views: list[Literal["front", "back", "side", "top", "iso"]] = ("front", "side", "top", "iso"),
    size: int = 384,
    color_by: Literal["material", "object"] = "material",
) -> list:
    """Overview picture for checking: several fixed views on a metre grid, no scene camera or lights needed. The flat views are orthographic and share one scale. A grid
    shows metres, coloured lines show the world axes (X red, Y green, Z blue). `names` limits the objects (with
    children). color_by `object` gives every object its own colour and the answer has a `legend` of name to
    '#rrggbb' (the lit picture is a little darker or lighter). Use render_view for one free angle, a close-up or a
    check mode, render_final for the lit picture through the scene camera."""
    return sheet(call("render_sheet", names=names, views=list(views), size=size, color_by=color_by))


@mcp.tool()
def render_view(
    target: list[str] | None = None,
    azimuth: float = 35.0,
    elevation: float = 20.0,
    fov: float = 35.0,
    mode: Literal["solid", "clay", "xray", "flat", "wire", "ids", "normals", "backfaces"] = "solid",
    size: int = 512,
    isolate: bool = True,
    margin: float = 1.15,
    look_at: Vec3 | None = None,
    name: str = "view",
    eye: Vec3 | None = None,
) -> list:
    """Close-up picture for checking: one free angle with its own camera and light, no set-up needed. The camera frames the bounding volume of `target`
    (with children; empty means everything), so a tall figure and a small bolt both fill the picture. Azimuth 0 looks
    at the front (from -Y), 90 from +X, 180 from the back; elevation 0 is level, 90 is from above. fov 0 means
    orthographic. isolate=false draws the whole scene but still frames `target`: use it for close-ups of joints in
    context. Modes: solid (studio light, material colours), clay (one grey, shows form only), xray (see-through),
    flat (material colours without light), wire (edges: topology, hidden parts; lines are about 2 pixels wide at the
    centre of the frame at any zoom), ids (one flat colour per object, with a legend), normals (world normal as
    colour), backfaces (red where you see the inside of a face: flipped normals, open shells). `eye` puts the camera at a world point looking at `look_at` with `fov`
    (no framing): a player's view from a spawn at eye height, a look through a doorway. Use render_sheet for the
    overview with a metre grid, render_final for the scene lights, materials and camera."""
    result = call(
        "render_view", target=target, azimuth=azimuth, elevation=elevation, fov=fov, mode=mode, size=size,
        isolate=isolate, margin=margin, look_at=look_at and list(look_at), name=name, eye=eye and list(eye),
    )
    return sheet(result)


@mcp.tool()
def assert_spec(checks: list[dict]) -> str:
    """Write what the model must be, run all checks in one call, get pass or fail with the real numbers. State
    your expectations before you look at the result, then fix only the failures. Each check is a dict with
    "type" and optional "label". Types and fields:
    size {object, axis x|y|z, equals+tol | min | max, with_children?} world size in metres.
    position {object, axis, which min|max|center, equals+tol | min | max} world coordinate.
    ratio {a, b, axis, min | max | equals+tol} size of a divided by size of b (head vs body proportions).
    gap {a, b, min | max | equals+tol} distance between two meshes (0 if they overlap).
    contact {a, b, state touching|intersecting|apart|connected, max_depth?} 'connected' is touching or overlapping.
    symmetry {objects, axis, at?, tolerance?, max_unmatched_share?} mirror match of all vertices.
    inside {object, container, margin?} bounding box inside another's.
    on_ground {object, z?, tol?} lowest point of the object and its children.
    clean {object, ignore?} no open holes, loose parts, zero faces, inward normals.
    budget {names?, max_tris?, max_objects?, max_materials?, max_draw_calls?}.
    connected {names?, ground_z?} no floating groups.
    A failure shows 'actual', 'expected' and a 'fix' tool. A bad check or a missing object is reported as an
    'error' and the rest still run."""
    return text(call("assert_spec", checks=checks))


@mcp.tool()
def raycast(origin: Vec3, direction: Vec3, max_distance: float = 1000.0) -> str:
    """Shoot one ray in world space. Returns the first object hit, the distance, the point and the surface normal.
    Use it to find floors, ceilings, wall thickness and free space."""
    return text(call("raycast", origin=list(origin), direction=list(direction), max_distance=max_distance))


@mcp.tool()
def line_of_sight(a: str | Vec3, b: str | Vec3) -> str:
    """Can point or object `a` see `b`? Each is a world point or an object name (its bounding-box centre). The two
    named objects never block the ray. Returns the first blocker. Use it for sight lines, cover and corridors."""
    return text(call("line_of_sight", a=a, b=b))


@mcp.tool()
def walkable_map(
    names: list[str] | None = None,
    cell: float | None = None,
    agent_height: float = 1.8,
    agent_radius: float = 0.3,
    max_step: float = 0.35,
    max_slope_deg: float = 45.0,
    start: Vec3 | None = None,
    max_levels: int = 3,
) -> list:
    """Check where an agent of this size can walk, then flood from `start` (default: the largest area). Floors are
    found by rays, so ramps, stairs and several levels work. Returns the reachable, unreachable and blocked areas
    in m2 and a top-down image. `largest_regions` gives each region's area, whether it is reachable, its floor height
    range and its box: an unreachable region with a high floor_z is a roof or a crate top, not a design error. Use it to
    prove that every room, spawn and objective connects."""
    result = call(
        "walkable_map", names=names, cell=cell, agent_height=agent_height, agent_radius=agent_radius,
        max_step=max_step, max_slope_deg=max_slope_deg, start=start and list(start), max_levels=max_levels, probe=probe and [list(p) for p in probe],
    )
    return [text(result), Image(path=result["image"])]


@mcp.tool()
def sightline_map(
    names: list[str] | None = None,
    cell: float = 0.75,
    eye_height: float = 1.6,
    rays: int = 24,
    max_range: float = 60.0,
    long_sightline: float = 25.0,
    start: Vec3 | None = None,
) -> list:
    """Exposure of a level. For every reachable cell it shoots rays around at eye height and measures how far one
    can see. Returns a heat map (blue enclosed, red exposed), the longest sight lines with their positions and the
    area that has a sight line longer than `long_sightline`. Use it to find sniper alleys and to check that
    cover and corners break long views. Same agent settings as walkable_map."""
    result = call("sightline_map", names=names, cell=cell, eye_height=eye_height, rays=rays, max_range=max_range, long_sightline=long_sightline, start=start and list(start))
    return [text(result), Image(path=result["image"])]


@mcp.tool()
def route(
    start: Vec3,
    end: Vec3,
    names: list[str] | None = None,
    cell: float | None = None,
    min_width: float = 0.0,
    agent_height: float = 1.8,
    agent_radius: float = 0.3,
    max_step: float = 0.35,
    max_slope_deg: float = 45.0,
) -> list:
    """Shortest walkable route between two world points. Returns the length, the straight-line length, the narrowest
    free width on the route with its position, the highest step and waypoints, plus an image. `min_width` forbids
    narrower passages: use it to ask 'can a group or a wide vehicle go from A to B?'. If the points are in different
    regions it says so and why."""
    result = call("route", start=list(start), end=list(end), names=names, cell=cell, min_width=min_width, agent_height=agent_height, agent_radius=agent_radius, max_step=max_step, max_slope_deg=max_slope_deg)
    if "image" not in result:
        return [text(result)]
    return [text(result), Image(path=result["image"])]


@mcp.tool()
def inspect_glb(path: str, max_texture: int = 2048) -> str:
    """Read a GLB file without Blender: triangles, vertices, materials, textures with sizes, extensions, file size and
    warnings (missing normals or UV, oversized or non-power-of-two textures, duplicate node names). Run it on the
    file you exported, because that is what the game loads."""
    return text(call("inspect_glb", path=path, max_texture=max_texture))


@mcp.tool()
def check_game_ready(
    names: list[str] | None = None,
    name_pattern: str = r"^[A-Za-z0-9_]+$",
    max_tris: int | None = None,
    max_objects: int | None = None,
    max_materials: int | None = None,
    max_draw_calls: int | None = None,
    max_texture: int = 2048,
    require_uv: bool = True,
    symmetry_axis: Axis | None = "X",
    budget_only: bool = False,
) -> str:
    """Pre-export gate. Errors: bad names, unapplied scale, no material, faces without a material (a boolean cutter
    without one leaves them), inward normals, zero-area faces, oversized textures, budget overruns (the `max_*`
    limits). Warnings: duplicate suffixes (.001), many material slots, empty material slots, missing UV, n-gons, open
    shells, and a mesh that is nearly but not fully symmetric about `symmetry_axis`: under 10 percent of its vertices
    have no mirror partner (plane: the middle of its box, or 0). That is a side broken by an uneven selection; a
    silhouette does not show it. symmetry_axis=null skips it. `ready` is true when there are no errors.
    budget_only=true is the cheap budget question at any stage: it only counts tris, objects, materials and estimated
    draw calls of `names` (or all visible meshes) and lists the limits exceeded in `over_budget`. It also gives
    draw_calls_if_instanced: objects that repeat one mesh with the same materials cost one call with GPU instancing;
    the hint says when merging them with combine pays off."""
    return text(call("check_game_ready", names=names, name_pattern=name_pattern, max_tris=max_tris, max_objects=max_objects, max_materials=max_materials, max_draw_calls=max_draw_calls, max_texture=max_texture, require_uv=require_uv, symmetry_axis=symmetry_axis, budget_only=budget_only))


@mcp.tool()
def checkpoint(name: str = "last") -> str:
    """Save the scene as a named restore point. Checkpoints belong to the open file (an id kept in the scene): a new or
    another file does not see them."""
    return text(call("checkpoint", name=name))


@mcp.tool()
def rollback(name: str | None = None) -> str:
    """Return to a checkpoint of this file: everything done after it is lost. The open file becomes the checkpoint
    copy: use Save As before you save. Without `name` nothing is rolled back: the answer lists the checkpoints of the
    open file."""
    return text(call("rollback", name=name))
