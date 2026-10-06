import inspect
from typing import Literal

from .app import Vec3, call, mcp, text

Axis = Literal["X", "Y", "Z"]
Falloff = Literal["smooth", "sphere", "root", "sharp", "inverse_square", "linear", "constant"]
Region = Literal["faces", "vertices"]

WHERE = """`where` picks faces (or vertices, edges) by a condition, all given keys must hold: normal ('+Z', '-X' or [x,y,z]) with
angle (degrees, default 25); x, y, z ranges [min, max] (null means open) on the world centre; box [[x0,y0,z0],[x1,y1,z1]];
area [min, max]; index [...]. {} or null picks everything. Look at mesh_info first to see where the faces are."""


def tool_with(*notes):
    """Registers a tool whose description is its docstring plus shared notes: a docstring cannot be an expression."""

    def register(fn):
        return mcp.tool(description="\n".join([inspect.cleandoc(fn.__doc__), *notes]))(fn)

    return register


@mcp.tool()
def mesh_info(object: str) -> str:
    """Counts of vertices, edges and faces, and the faces grouped by direction (+X, -X, +Y, -Y, +Z, -Z, other) with
    their area and the world range of their centres. Read it before you pick faces with `where`."""
    return text(call("mesh_info", object=object))


@tool_with(WHERE)
def select_faces(object: str, where: dict | None = None) -> str:
    """Preview a face selection without changing anything: how many faces, their area, the world range of their
    centres and the first indices."""
    return text(call("select_faces", object=object, where=where))


@tool_with(WHERE)
def extrude_faces(object: str, where: dict | None = None, distance: float = 0.0, offset: Vec3 | None = None, scale: float = 1.0, inset: float = 0.0) -> str:
    """Extrude the picked faces as one region. `distance` is along their average normal (negative digs in); `offset` is a
    world vector instead. `scale` resizes the new cap about its centre (a taper); `inset` first shrinks the region by that
    many metres. Typical: raise a roof, make a post, a step, a window recess."""
    return text(call("extrude_faces", object=object, where=where, distance=distance, offset=offset and list(offset), scale=scale, inset=inset))


@tool_with(WHERE)
def inset_faces(object: str, where: dict | None = None, thickness: float | None = None, depth: float = 0.0, individual: bool = False) -> str:
    """Inset the picked faces by `thickness` metres (empty: 0.02 m, less on objects under 0.3 m), optionally pushing
    the inner face by `depth` (negative is a recess). individual=true insets each face on its own."""
    return text(call("inset_faces", object=object, where=where, thickness=thickness, depth=depth, individual=individual))


@tool_with(WHERE)
def delete_faces(object: str, where: dict | None = None) -> str:
    """Delete the picked faces of one mesh (makes openings: doors, windows, open boxes). Use delete to remove whole
    objects."""
    return text(call("delete_faces", object=object, where=where))


@tool_with(WHERE)
def subdivide_faces(object: str, where: dict | None = None, cuts: int = 1) -> str:
    """Add geometry without changing the shape: split the picked faces into a grid, `cuts` cuts per edge, to bend,
    sculpt or displace later. Use subdivide to round the whole mesh, remesh for an even skin over merged parts."""
    return text(call("subdivide_faces", object=object, where=where, cuts=cuts))


@mcp.tool()
def bevel_edges(object: str, width: float | None = None, segments: int = 2, angle: float = 30.0, where: dict | None = None, profile: float = 0.5,
                width_type: Literal["offset", "width", "depth", "percent", "absolute"] = "offset") -> str:
    """Round or chamfer the edges sharper than `angle` degrees (optionally only those whose midpoint is inside `where`,
    which uses x, y, z ranges and box). width is in metres (empty: 0.02 m, less on objects under 0.3 m), segments 1 is a chamfer, 3 is round. profile 0.5 is circular.
    width_type `width` is the distance between the two new edges. Only edges with two faces
    can be bevelled. Overlapping bevels are clamped, and one tight edge limits every bevel of the call: the answer gives
    `width` (asked), `achieved_width` (min and median measured on the result, in metres), `clamped` (edges under 90% of
    the asked width) and a `warning` when most are clamped. Doubled vertices and zero-area faces are removed afterwards
    (merged_vertices, removed_zero_faces)."""
    return text(call("bevel_edges", object=object, width=width, segments=segments, angle=angle, where=where, profile=profile, width_type=width_type))


@mcp.tool()
def bisect(object: str, axis: Axis = "Z", at: float = 0.0, clear: Literal["inner", "outer"] | None = None, fill: bool = False) -> str:
    """Cut the mesh with a world plane (across `axis` at the coordinate `at`): adds an edge loop there, like a loop cut
    placed in metres. `clear` removes one side (the inner side is the negative side of the axis);
    fill=true closes the cut. Use it to slice, to add a loop for later extrusion, or to trim a part flat."""
    return text(call("bisect", object=object, axis=axis, at=at, clear=clear, fill=fill))


@mcp.tool()
def weld(object: str, distance: float | None = None, where: dict | None = None, allow_open: bool = False) -> str:
    """Merge vertices closer than `distance` metres (empty: 0.0001 m, less on objects under 0.3 m; optionally only those inside `where`: x, y, z, box). Fixes doubled
    vertices and seams after joining parts. For a broken mesh with holes and junk use repair_mesh. A distance wider
    than the thinnest faces collapses them and opens the mesh: the call then fails, changes nothing, and names the new
    boundary and non-manifold edges, their world box and a smaller distance that is safe. allow_open=true welds anyway
    and puts the same report into `warning`."""
    return text(call("weld", object=object, distance=distance, where=where, allow_open=allow_open))


@tool_with(WHERE)
def transform_region(
    object: str,
    where: dict | None = None,
    move: Vec3 | None = None,
    scale: float | Vec3 | None = None,
    rotate_deg: Vec3 | None = None,
    pivot: Vec3 | None = None,
    falloff: float = 0.0,
    falloff_type: Falloff = "smooth",
    mode: Region = "faces",
    symmetric: Literal["x", "y", "z"] | None = None,
) -> str:
    """Move, scale and rotate the vertices of the picked faces (mode faces) or the picked vertices (mode vertices)
    in world terms. `pivot` defaults to the region centre. falloff > 0 drags the neighbours too, like proportional
    editing: weights fall from 1 at the region to 0 at `falloff` metres away, shaped by falloff_type.
    Use it to widen a head, taper a leg, raise a ridge. `symmetric` adds the mirror twins of the picked vertices
    about the centre of the mesh box on that world axis (the answer gives mirrored_vertices and without_twin); the
    transform itself is not mirrored. Without it the answer has a `warning` when the mesh is mirror-symmetric and
    the selection lies on both sides of the plane but is not symmetric."""
    return text(call("transform_region", object=object, where=where, move=move and list(move), scale=scale if not isinstance(scale, tuple) else list(scale), rotate_deg=rotate_deg and list(rotate_deg), pivot=pivot and list(pivot), falloff=falloff, falloff_type=falloff_type, mode=mode, symmetric=symmetric))


@tool_with(WHERE)
def sculpt(
    object: str,
    op: Literal["grab", "inflate", "smooth", "flatten", "pinch"],
    at: Vec3 | None = None,
    radius: float | None = None,
    where: dict | None = None,
    mode: Region = "faces",
    spread: float = 0.0,
    falloff: Falloff = "smooth",
    move: Vec3 | None = None,
    amount: float | None = None,
    strength: float | None = None,
    iterations: int = 2,
    factor: float = 0.5,
    keep_boundary: bool = True,
) -> str:
    """Sculpt by numbers: move the vertices under a brush. Brush: either `at` + `radius` (a sphere in the world,
    strongest at the centre), or `where` (+ mode) with `spread`, the number of metres around the region that still
    feel the brush; `falloff` shapes the fade. The mesh needs enough vertices: subdivide_faces first.
    op grab: pull the surface by the world vector `move`.
    op inflate: push it out (or in, negative) along its normals by `amount` metres.
    op smooth: relax it towards the average of the neighbours, `iterations` times by `factor`; with no brush it
    smooths the whole mesh; keep_boundary leaves open edges in place. For shading only use shade.
    op flatten: press the area onto its own average plane; `strength` 1 (default) is fully flat. Soles, table tops.
    op pinch: draw the area towards its centre in the surface plane (sharpens creases, narrows a part); `strength`
    1 collapses it, default 0.5.
    Parameters of another op are ignored. The answer has vertices_moved."""
    return text(call("sculpt", object=object, op=op, at=at and list(at), radius=radius, where=where, mode=mode, spread=spread, falloff=falloff,
                     move=move and list(move), amount=amount, strength=strength, iterations=iterations, factor=factor, keep_boundary=keep_boundary))


@mcp.tool()
def deform(object: str, kind: Literal["bend", "twist", "taper", "stretch"], amount: float, axis: Axis = "Z", origin: Vec3 | None = None, limits: list[float] = (0.0, 1.0), lock_x: bool = False, lock_y: bool = False) -> str:
    """Bend, twist, taper or stretch the whole mesh. bend and twist take `amount` in degrees, taper and stretch a
    factor. axis: for twist, taper and stretch it is the long axis of the part; for bend it is the axis the part curls
    around, so a standing bar (long along Z) bends forward with axis X or sideways with axis Y. origin is a world
    point (default the object origin); limits [0,1] restrict the effect to a fraction of the length. The mesh needs
    enough vertices along the axis: subdivide_faces first."""
    return text(call("deform", object=object, kind=kind, amount=amount, axis=axis, origin=origin and list(origin), limits=list(limits), lock_x=lock_x, lock_y=lock_y))


@mcp.tool()
def shrinkwrap(object: str, target: str, method: Literal["nearest_surface", "nearest_vertex", "project"] = "nearest_surface", offset: float = 0.0,
               axis: Axis | None = None, direction: Literal["both", "positive", "negative"] = "both") -> str:
    """Snap the vertices of `object` onto the surface of `target` (clothes onto a body, a clean mesh onto a sculpt, a
    floor onto terrain). Method project moves them along `axis` (default Z) in `direction`. offset keeps a gap in
    metres. Subdivide the object first for a smooth fit."""
    return text(call("shrinkwrap", object=object, target=target, method=method, offset=offset, axis=axis, direction=direction))


@mcp.tool()
def remesh(object: str, voxel_size: float = 0.05, smooth_shading: bool = True) -> str:
    """Replace the topology: rebuild the mesh as an even voxel surface that fuses overlapping parts into one skin, for
    sculpting.
    A smaller voxel_size means more detail and many more triangles. The old topology and UVs are lost. Use subdivide
    to round a mesh and keep its topology, subdivide_faces to add geometry to picked faces."""
    return text(call("remesh", object=object, voxel_size=voxel_size, smooth_shading=smooth_shading))


@mcp.tool()
def blob(name: str, points: list[Vec3], radii: list[float], resolution: float = 0.05, threshold: float = 0.6) -> str:
    """Make one smooth organic mesh from overlapping balls (metaballs): the balls merge into a single skin. Good for
    hands, clouds, bushes, rocks, creature bodies. One radius per point; nearby balls blend, so use radii a bit larger than
    the surface you want."""
    return text(call("blob", name=name, points=[list(p) for p in points], radii=radii, resolution=resolution, threshold=threshold))


@mcp.tool()
def boolean(a: str, b: str, operation: Literal["difference", "union", "intersect"] = "difference", keep_tool: bool = False,
            solver: Literal["EXACT", "MANIFOLD", "FLOAT"] = "EXACT", allow_open: bool = False, repair: bool = True) -> str:
    """Combine two meshes: `a` is changed, `b` is the tool and is deleted unless keep_tool. difference cuts b out of a.
    Both should be closed and have outward normals (check_mesh). With repair=true
    an open mesh is first healed with repair_mesh (the answer lists `repaired`). If that does not close it, the call
    fails and names the object, the number of open edges and where they are (world box). `a` keeps its own material
    slots: the faces made by `b` take the material of the faces of `a` next to them, and empty slots are removed.
    The result is welded and its zero-area faces are dissolved (merged_vertices, removed_zero_faces; doubled_vertices_left
    where parts only touch along an edge). The result is checked: when `solver` leaves new
    boundary or non-manifold edges, the other solvers and a tool shifted by a few micrometres are tried; the answer
    names the `solver` used (and tool_shift_m). If none gives a closed result the call fails, changes nothing, and gives
    the edge counts and their world box. allow_open=true skips the input check and keeps such a result with a `warning`.
    Use it for windows, doors, holes, notches."""
    return text(call("boolean", a=a, b=b, operation=operation, keep_tool=keep_tool, solver=solver, allow_open=allow_open, repair=repair))


@mcp.tool()
def repair_mesh(object: str, weld: float | None = None, fill_holes: bool = True, hole_sides: int = 8, remove_loose: bool = True, dissolve_degenerate: bool = True, recalc_normals: bool = True, remove_empty_slots: bool = True) -> str:
    """Heal one mesh in place: merge doubled vertices (`weld` in metres; empty follows the size, 0.0001 m for 0.3 m
    and more; 0 skips it), drop zero-area faces and edges (dissolve_degenerate), delete loose edges and vertices
    (remove_loose), fill holes of up to `hole_sides` edges (0 means any size; fill_holes=false skips it), turn
    normals outward, and remove material slots without a material (remove_empty_slots; their faces go to the first
    slot left). The answer gives `removed` (doubled_vertices, zero_area_faces, loose_edges, loose_vertices,
    empty_material_slots) and before and after counts: open_edges, non_manifold_edges (3 or more faces on one edge,
    not repaired), doubles, zero_faces, junk_vertices. Run it before boolean on parts you cut or joined by hand."""
    return text(call("repair_mesh", object=object, weld=weld, fill_holes=fill_holes, hole_sides=hole_sides, remove_loose=remove_loose, dissolve_degenerate=dissolve_degenerate, recalc_normals=recalc_normals, remove_empty_slots=remove_empty_slots))


@mcp.tool()
def set_origin(names: list[str], at: Vec3 | None = None, anchor: Vec3 | None = None) -> str:
    """Move the origin of each object without moving its geometry or its children in the world. Give either `at` (one
    world point for all) or `anchor` (fractions of the world box of each object, without children: (0.5, 0.5, 0) is the
    bottom centre, (0.5, 0.5, 0.5) the centre). Use it for pivots: a hinge axis, the base of a prop, the grip of a
    weapon. Mesh data shared with other objects becomes a private copy."""
    return text(call("set_origin", names=names, at=at and list(at), anchor=anchor and list(anchor)))


@mcp.tool()
def combine(names: list[str], name: str | None = None, delete_sources: bool = True) -> str:
    """Merge several meshes into one mesh object, as Join (Ctrl+J) does in Blender (in world space, materials kept).
    Do it before export to save draw calls. The parts are not welded or moved: use move_to_contact to close a gap."""
    return text(call("combine", names=names, name=name, delete_sources=delete_sources))


@mcp.tool()
def array(object: str, count: int, offset: Vec3, name: str | None = None, keep_source: bool = False) -> str:
    """Repeat an object `count` times along the world vector `offset` (step in metres) and merge the copies into one mesh.
    Fences, stairs, windows, planks, teeth."""
    return text(call("array", object=object, count=count, offset=list(offset), name=name, keep_source=keep_source))


@mcp.tool()
def radial_array(object: str, count: int, axis: Axis = "Z", center: Vec3 = (0, 0, 0), angle: float = 360.0, name: str | None = None, keep_source: bool = False) -> str:
    """Repeat an object around a world axis through `center`, over `angle` degrees (360 is a full circle), and merge the
    copies. Wheels' spokes, columns in a ring, petals, gears."""
    return text(call("radial_array", object=object, count=count, axis=axis, center=list(center), angle=angle, name=name, keep_source=keep_source))


@mcp.tool()
def solidify(object: str, thickness: float, offset: float = -1.0, even: bool = True) -> str:
    """Give a surface thickness in metres (walls from planes, cloth, leaves). offset -1 grows inward, 1 outward, 0 both ways."""
    return text(call("solidify", object=object, thickness=thickness, offset=offset, even=even))


@mcp.tool()
def lathe(name: str, profile: list[list[float]], axis: Axis = "Z", segments: int = 24, angle: float = 360.0, at: Vec3 = (0, 0, 0), cap: bool = False, close: bool = False) -> str:
    """Spin a profile around an axis. `profile` is a list of [radius, height] points from the bottom up. A profile that
    touches the axis (radius 0) at both ends makes a solid (vase, bottle, column, cone). A profile that stays away from the
    axis is an open tube: close=true repeats the first point so the loop is closed and the spin gives a ring (donut,
    tyre, pipe section, torus-like shapes). angle under 360 makes a wedge."""
    return text(call("lathe", name=name, profile=profile, axis=axis, segments=segments, angle=angle, at=list(at), cap=cap, close=close))


@mcp.tool()
def sweep(name: str, path: list[Vec3], radius: float = 0.05, radii: list[float] | None = None, sides: int = 8, profile: list[list[float]] | None = None, closed: bool = False, caps: bool = True, up: Vec3 = (0, 0, 1)) -> str:
    """Pull a cross-section along a path of world points: pipes, cables, railings, trims, horns, tails, roads. radii gives
    one radius per point (a taper). profile is a closed 2D polygon [[right, up], ...] of the cross-section (default a
    circle with `sides`); the frame turns smoothly along the path, `up` is the starting up direction."""
    return text(call("sweep", name=name, path=[list(p) for p in path], radius=radius, radii=radii, sides=sides, profile=profile, closed=closed, caps=caps, up=list(up)))


@mcp.tool()
def decimate(object: str, ratio: float | None = None, target_tris: int | None = None, mode: Literal["collapse", "planar"] = "collapse", angle: float = 5.0) -> str:
    """Reduce the triangle count. collapse: merges vertices to reach `ratio` (0..1 of the current triangles) or
    `target_tris`; it can distort shapes and UVs, so check with compare_view afterwards. planar: dissolves flat faces
    whose neighbours differ less than `angle` degrees (cleans up subdivided flat surfaces without changing the shape)."""
    return text(call("decimate", object=object, ratio=ratio, target_tris=target_tris, mode=mode, angle=angle))
