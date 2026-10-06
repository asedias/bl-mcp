from .app import Image, Vec3, call, mcp, text


@mcp.tool()
def build_from_grid(
    layout: list[str],
    cell: float = 1.0,
    wall_height: float = 3.0,
    floor_thickness: float = 0.2,
    origin: Vec3 = (0, 0, 0),
    legend: dict | None = None,
    name: str = "level",
    door_height: float = 2.2,
    cover_height: float = 1.1,
    cover_fill: float = 0.6,
) -> str:
    """Block out a level from a text plan, one string per row, row 0 at the top (+Y), column 0 at the left. Default
    characters: '#' wall, '.' floor, ' ' nothing, 'D' doorway (floor, with a wall above `door_height`), 'C' cover box
    (`cover_height` high, `cover_fill` of the cell), 'S' spawn marker, 'O' objective marker. `legend` adds or changes
    characters: {"W": {"kind": "wall", "height": 1.2}} makes low walls; kinds are wall, floor, door, cover, marker
    (with "name"), void. Makes {name}_floor, {name}_walls, {name}_cover meshes and {name}_spawn_1 style empties. Then prove
    it with walkable_map, route, check_passages, sightline_map. One cell is `cell` metres: use 1 for rooms, 0.5 for detail."""
    return text(call("build_from_grid", layout=layout, cell=cell, wall_height=wall_height, floor_thickness=floor_thickness, origin=list(origin), legend=legend, name=name, door_height=door_height, cover_height=cover_height, cover_fill=cover_fill))


@mcp.tool()
def scatter(
    source: str | list[str],
    surface: list[str],
    count: int,
    seed: int = 0,
    area: list[float] | None = None,
    min_distance: float = 0.0,
    align_to_normal: bool = False,
    scale_range: list[float] = (1.0, 1.0),
    yaw_random: bool = True,
    max_slope_deg: float = 90.0,
    linked: bool = True,
    name: str | None = None,
    weights: list[float] | None = None,
) -> str:
    """Place `count` copies of an object at random on top of surface objects, standing on the surface: trees, rocks,
    crates, grass, sprinkles. `source` may be a list: each copy takes one at random and `weights` sets the odds.
    `area` [x0,y0,x1,y1] limits where (default: the surface bounds); min_distance keeps copies apart; max_slope_deg
    skips steep ground; align_to_normal tilts them with the ground; scale_range [min,max] and yaw_random vary them.
    The same seed gives the same result. linked=true shares one mesh (cheap). The answer counts the copies per source
    and why tries were rejected (too_close, not_on_surface, too_steep). For one object at a chosen spot use place_on."""
    return text(call("scatter", source=source, surface=surface, count=count, seed=seed, area=area, min_distance=min_distance, align_to_normal=align_to_normal, scale_range=list(scale_range), yaw_random=yaw_random, max_slope_deg=max_slope_deg, linked=linked, name=name, weights=weights))


@mcp.tool()
def place_on(object: str, surface: list[str], at: list[float] | None = None, yaw_deg: float | None = None) -> str:
    """Drop by a ray: lower an object (with children) until its lowest point lands on the first surface under it (or
    under world xy `at`). Use it for props on tables, floors with height changes, terrain. Use ground for a level floor at a known
    height, attach to align by bounding boxes, scatter for many copies."""
    return text(call("place_on", object=object, surface=surface, at=at, yaw_deg=yaw_deg))


@mcp.tool()
def viewshed(
    point: Vec3,
    names: list[str] | None = None,
    eye_height: float = 1.6,
    target_height: float = 1.0,
    cell: float | None = None,
    max_range: float = 60.0,
    agent_height: float = 1.8,
    agent_radius: float = 0.3,
    max_step: float = 0.35,
    max_slope_deg: float = 45.0,
) -> list:
    """What can be seen from a point: for each reachable cell, a ray from the eye to a point `target_height` above the
    floor. Returns visible and hidden area, the farthest visible distance and a map. Use it for spawns (what does an
    enemy see?), sniper spots, hiding places, objective visibility. The area is the one that contains the point."""
    result = call("viewshed", point=list(point), names=names, eye_height=eye_height, target_height=target_height, cell=cell, max_range=max_range, agent_height=agent_height, agent_radius=agent_radius, max_step=max_step, max_slope_deg=max_slope_deg)
    return [text(result), Image(path=result["image"])]


@mcp.tool()
def check_passages(
    names: list[str] | None = None,
    min_door: float = 1.0,
    min_corridor: float = 2.0,
    door_length: float = 1.5,
    cell: float | None = None,
    agent_height: float = 1.8,
    agent_radius: float = 0.3,
    start: Vec3 | None = None,
) -> list:
    """Find doorways and corridors of a level that are too narrow. It follows the centre line of the walkable area and reports narrow runs: a
    run up to `door_length` metres long is a doorway (limit `min_door`), a longer one a corridor (limit
    `min_corridor`). The width is the free width including the agent radius, accurate to about one cell, and it errs on the
    small side. Returns violations with positions and a map. `start` picks the area when there are several levels."""
    result = call("check_passages", names=names, min_door=min_door, min_corridor=min_corridor, door_length=door_length, cell=cell, agent_height=agent_height, agent_radius=agent_radius, start=start and list(start))
    return [text(result), Image(path=result["image"])]


@mcp.tool()
def save_spec(name: str, checks: list[dict]) -> str:
    """Store a list of assert_spec checks under a name inside the scene (it is saved with the .blend). Rerun it with run_spec
    after every change, in this or a later session."""
    return text(call("save_spec", name=name, checks=checks))


@mcp.tool()
def run_spec(name: str | None = None) -> str:
    """Run a stored spec (see save_spec) and return the assert_spec result. Without `name` nothing runs: the answer
    lists the stored specs with their number of checks."""
    return text(call("run_spec", name=name))


@mcp.tool()
def diff_since(name: str = "last", tolerance: float = 0.001) -> str:
    """What changed since a checkpoint: added and removed objects, and objects that moved or changed size by more than
    `tolerance` metres, with sizes before and now. A changed object also gets `topology` (counts of verts, edges,
    faces and tris, before -> now) and `material_slots` (the slot lists before and now) when they differ, so an edit
    that keeps the size still shows. Use it to review a long session or to see what a tool did."""
    return text(call("diff_since", name=name, tolerance=tolerance))
