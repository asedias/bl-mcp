from typing import Literal

from .app import Vec3, call, mcp, text


@mcp.tool()
def noise_displace(
    object: str,
    amount: float,
    scale: float = 1.0,
    seed: int = 0,
    where: dict | None = None,
    mode: Literal["normal", "z", "vector"] = "normal",
    octaves: int = 3,
    spread: float = 0.0,
    falloff: Literal["smooth", "sphere", "root", "sharp", "inverse_square", "linear", "constant"] = "smooth",
) -> str:
    """Move the vertices by fractal noise. Use it for bumps on a surface, worn stone, uneven ground.
    `amount` is the largest shift in metres: no vertex moves further. `scale` is the size of the biggest bumps in metres
    (smaller scale gives finer bumps). `octaves` 1 to 8 adds finer detail on top, each at half strength.
    The same seed gives the same result. Another seed gives other bumps. The noise is sampled in world space.
    mode: normal (along each vertex normal), z (up and down only, for ground), vector (any direction, rough lumps).
    `where` picks faces like extrude_faces does (normal, x, y, z ranges, box, area, index); nothing outside is moved.
    `spread` is a soft border in metres around the picked faces, shaped by `falloff`. Without `where` the whole mesh moves.
    The mesh needs enough vertices to show the bumps: subdivide_faces or subdivide first.
    Returns the largest shift that happened."""
    return text(call("noise_displace", object=object, amount=amount, scale=scale, seed=seed, where=where, mode=mode, octaves=octaves, spread=spread, falloff=falloff))


@mcp.tool()
def terrain(
    name: str,
    size: list[float] = (20.0, 20.0),
    resolution: float = 0.5,
    height: float = 2.0,
    scale: float = 8.0,
    seed: int = 0,
    octaves: int = 4,
    edge_falloff: float = 0.0,
    flat_center: float = 0.0,
    at: Vec3 = (0.0, 0.0, 0.0),
    plateau_levels: int | None = None,
    skirt: float | None = None,
    smooth: bool = False,
) -> str:
    """Make a ground mesh from a noise height map, for outdoor levels. Same seed, same ground.
    `size` is [width along X, depth along Y] and `resolution` the grid step, in metres (0.5 looks low-poly). Over
    160000 vertices is an error: raise resolution.
    `height` is the full range above the z of the object. `scale` is the size of the biggest hills in metres;
    `octaves` adds finer bumps. `at` is the world position of the centre and the origin.
    `edge_falloff` 0-1 makes an island: the share of the half size at the border where the ground sinks to zero.
    `flat_center` is the radius of a level circle in the middle (for a building); it blends out over half that
    radius. `plateau_levels` (2 or more) makes terraces of equal height.
    The bottom is open. `skirt` (a world z below the lowest border point) adds walls down to that z and a flat
    bottom: a closed block. Faces are flat shaded unless smooth=true. Returns the vertex count and height range.
    Then use path_carve for roads and scatter for rocks and trees."""
    return text(call("terrain", name=name, size=list(size), resolution=resolution, height=height, scale=scale, seed=seed, octaves=octaves,
                     edge_falloff=edge_falloff, flat_center=flat_center, at=list(at), plateau_levels=plateau_levels, skirt=skirt, smooth=smooth))


@mcp.tool()
def path_carve(terrain: str, points: list[list[float]], width: float, depth: float, falloff: float | None = None) -> str:
    """Press a road, a ditch or a path into a terrain mesh along a polyline.
    `points` are world [x, y] pairs (extra values are ignored); give at least two. `width` is the full width in metres of
    the level floor. `depth` is how far the floor sinks, in metres (a negative value raises a bank).
    `falloff` is the width in metres of the sloped edge on each side; default is half of `width`. 0 gives a hard edge.
    The terrain needs a grid fine enough for the width: resolution of at most a third of `width` looks right.
    Existing vertices move only down by `depth` times a weight, so the road follows the hills. Use this on a mesh from
    the terrain tool."""
    return text(call("path_carve", terrain=terrain, points=points, width=width, depth=depth, falloff=falloff))


@mcp.tool()
def rock(
    name: str,
    radius: float = 0.5,
    seed: int = 0,
    roughness: float = 0.3,
    flatness: float = 0.0,
    detail: int = 3,
    at: Vec3 = (0.0, 0.0, 0.0),
    facets: bool = False,
) -> str:
    """Make a closed rock mesh: an icosphere roughened by noise and squashed. Same seed, same rock.
    `radius` is the half width in metres: the wider of the X and Y extents is 2 x radius.
    `roughness` 0 to 1 is how far the shape departs from a ball. `flatness` 0 to below 1 squashes it down (0.5 is a flat boulder).
    `detail` 1 to 5 is the subdivision: 1 gives 20 triangles, 2 gives 80, 3 gives 320, 4 gives 1280.
    For a low-poly game use detail 1 or 2 with facets=true. facets=true shades each face flat (hard crystal look);
    false shades smooth.
    `at` is where the bottom centre of the rock sits in world space; the object origin is there, so the rock stands on the ground.
    Vary seed, radius and flatness to make a set of different stones. The mesh passes check_mesh."""
    return text(call("rock", name=name, radius=radius, seed=seed, roughness=roughness, flatness=flatness, detail=detail, at=list(at), facets=facets))
