summary: Hard-surface prop from known dimensions: primitives at real size, attached details, cuts, bevels, checks.

Use for a crate, a barrel, furniture, a tool, a door. With an orthographic sheet use `weapon-from-sheet`.

## Numbers first

- Overall size in metres on X, Y and Z. Size and position of each detail. Limits for triangles and materials.
- Write them with `assert_spec`: check types size, position, on_ground, clean, connected, budget. `save_spec`.

## Steps

1. `status`, `scene_tree`, `checkpoint`.
2. Main form at real size: `create_primitive(kind=, name=, size=[x, y, z], at=[0, 0, 0], anchor=[0.5, 0.5, 0])`. This anchor stands the form on the ground. `rotate_deg` turns it: a barrel along X is a cylinder with `rotate_deg=[0, 90, 0]`.
3. Other forms: `lathe` for turned shapes (bottle, wheel, column), `sweep` for pipes and rails, `extrude_profile` for a plate with an outline, `solidify` for sheet parts.
4. Details: build each at real size, then `attach(part=, to=, part_anchor=, to_anchor=, offset=)`. An anchor is a fraction of the bounding box: [0.5, 0.5, 0] is the bottom centre, [0.5, 0.5, 1] the top centre. Read `boxes_used`.
5. Sink each detail 0.5 to 2 mm into its base: `move_to_contact` with `depth`, or a negative `offset`. Then `find_floating(ground_z=0)` and `check_contacts` for each detail and its base: a render does not show a 2 mm gap, these numbers do. Fix every gap before the next step.
6. Repeats: `array(object=, count=, offset=)` for rows, `radial_array(object=, count=, axis=, center=)` for rings (bolts, spokes).
7. Openings: one cutter, then `boolean(a=, b=, operation='difference')`. Recess: `inset_faces`, then `extrude_faces` with a negative `distance`. Text: `text_mesh(text=, on_object=, engrave=true)`.
8. Symmetric prop: build one side, then `mirror`. Call `check_symmetry` after every shaping step.
9. Bevels last: `bevel_edges(object=, width=, segments=, where=)`, one group of similar edges per call. Read `achieved_width` and `clamped`.
10. `shade(names=, mode='auto', weighted_normals=true)`. Repeat it after every `boolean` on a smooth part: the cut adds thin faces, and plain auto smooth bleeds dark patches around the cut.
11. Look: `render_view` at the corners in the modes solid, normals and backfaces. `render_sheet` for the proportions.
12. `check_mesh` on every part: issues none. `find_floating`: no floating group. `run_spec`.
13. Pivot: `set_origin(names=, anchor=[0.5, 0.5, 0])` for a standing prop. `set_origin(names=, at=)` on the hinge axis for a door or a lid. `parent` the moving parts to the root.
14. Fixed parts with one material: `combine`. Then `set_material`, `check_game_ready` and the recipe `export-for-game`.

## Traps

- Faces in one plane. A detail that only touches its base flickers in the game and gives zero-area faces in a union. Sink it (step 5).
- `attach` measures each box with the children of the object. A part with children lands off. `boxes_used` shows the boxes it took. Use `with_children=false` for the two objects alone.
- `boolean` refuses when the result is open, and changes nothing. Seen causes: a cut over an older cut, a cut that touches a neighbour cut, an open input mesh. Call `repair_mesh` on the input, or make one combined cutter with `combine`.
- `bevel_edges` clamps all bevels of one call to the tightest edge. Many bevelled edges with `achieved_width` near 0 is a failure. `rollback`, then bevel a smaller group with `where`.
- Do not bevel a whole part after cuts. It gives zero-area faces. A later `weld` with a wide distance opens the mesh; `weld` refuses and names a safe distance.
- Parts placed by coordinates look joined in a render and are not. The first version of the demo lantern had a handle 3 mm above its pivots; `find_floating` lists such parts, `check_contacts` gives the gap in metres.
- Glass: `set_material(alpha=0.1, coat=0.5)` reads as frosted. Clear glass is `transmission=1` with `roughness` near 0 (Cycles, glTF transmission extension).
- A scale on a turned object shears it. Set the size with `set_dimensions` before `transform_objects` turns the object.
- One smoothing angle does not fit a part with bevels and flat chamfers. `weighted_normals=true` keeps the flat faces flat.
- `transform_region` without `symmetric` can pick faces of one side only. It warns; `check_symmetry` gives the count.
- `delete` of a parent leaves the children in place without a parent. Parent them again.

## Done when

- `run_spec` passes: sizes, ground, clean, connected, budget.
- `check_mesh` gives issues none on every part. `find_floating` finds nothing.
- The origin of every moving part is on its axis. `measure` shows the origin.
- `check_game_ready` gives `ready` true.
