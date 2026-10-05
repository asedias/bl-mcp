summary: Level blockout from a text plan or boxes, proved by walkable area, routes, passage widths and sight lines.

Use for a grey-box level. The tools measure. They do not tell if the level is fun: that needs a playtest.

## Numbers first

- Player: 1.8 m high, radius 0.3 m, eyes at 1.6 m. These are the defaults of the level tools.
- Door: at least 1 m wide and 2.2 m high. Corridor: at least 2 m wide. Wall: 3 m high.
- Cover: low 1.0 to 1.25 m, high 1.75 m or more.
- From the game design: the longest allowed sight line, the travel distance between key points, limits for triangles and draw calls.

## Steps

1. `status`, `scene_tree`, `checkpoint`.
2. Plan: `build_from_grid(layout=, cell=1.0, name=)`. One string per row; row 0 is the +Y side. Characters: '#' wall, '.' floor, 'D' door, 'C' cover, 'S' spawn, 'O' objective, ' ' nothing. `legend` adds characters, for example low walls.
3. Without a plan: floor and walls as big boxes from `create_primitive`. Name them by zone: hall_floor, hall_wall_N.
4. Windows: `boolean` with a box cutter. Raised parts and steps: `extrude_faces`.
5. `walkable_map`: read the reachable and the unreachable area and look at the map. Every room, spawn and objective must be in the reachable area.
6. `route(start=, end=)` between the key points. Compare the length with the straight-line length. Read the narrowest width and its position. `min_width` tests a wide group.
7. `check_passages`: doors and corridors under the limits, with positions. Fix them and call it again.
8. `sightline_map`: red areas are exposed. Read the longest sight lines and their positions. Break a long line with cover or a corner.
9. `viewshed(point=)` from each spawn: what an enemy sees from there. Check key pairs with `line_of_sight(a=, b=)`.
10. Dress the level: `scatter(source=, surface=, count=, seed=, min_distance=)` for trees, rocks, crates. `place_on` for single props. Then repeat steps 5 to 9: props block routes.
11. Look from above: `render_sheet` with the top view. Look as a player: `set_camera(location=, look_at=)` at 1.6 m above a spawn, then `render_final(path=, engine='workbench')`.
12. `save_spec` with the rules of the level (types connected, size, gap, budget). Call `run_spec` after each round.
13. Change one thing per round. Double or halve a doubtful value. Then repeat steps 5 to 9.
14. `check_game_ready` with the limits, then the recipe `export-for-game`.

## Traps

- The level tools shoot a grid of rays. A wall thinner than `cell` leaks: the map shows a room as reachable through the wall. Make walls thicker than one cell, or lower `cell`.
- A doorway narrower than the agent plus one cell is not walkable at a coarse `cell`. A real 1 m door then reads as closed. Lower `cell` to 0.25 near the limits.
- A width is accurate to about one cell and errs on the small side. Do not fix a door that misses the limit by less than one cell: measure again with a smaller `cell`.
- With several floors the tools take the largest area on the lowest floor. Pass `start` to pick another area.
- `route` between two points in different regions gives no path. The answer says why. Fix the link (door, stair, ramp), not the points.
- A stair works only when each step is under `max_step` (0.35 m) and a ramp under `max_slope_deg` (45).
- `scatter` with the same `seed` gives the same result. Change the seed for another layout, not the count.
- `scatter` reports rejected tries with the cause: too close, not on the surface, too steep. Many rejects mean the area is full.
- One cover height repeated everywhere reads as boxes. Mix low and high cover.

## Done when

- Every spawn and objective is in the reachable area.
- No door or corridor is under its limit in `check_passages`.
- No sight line is longer than the design allows, except where it is planned.
- No spawn sees another spawn.
- `run_spec` passes. `check_game_ready` gives `ready` true.
