summary: Weapon or other flat hard-surface object from an orthographic sheet with several panels (side, top, front, back).

Use for a sheet of flat views. For a perspective photo use `scene-from-photo`.

## Conventions

- The muzzle is the front: it points to -Y. Length is along Y, width along X, height along Z.
- Each view expects one picture. `prepare_reference` and `compare_view` turn a panel with `flip` ('x' or 'y') and `rotate` (90, 180, 270 clockwise; the flip comes first).

| View | Camera on | Picture the view expects |
|---|---|---|
| right (side) | +X | muzzle to the left |
| left | -X | muzzle to the right |
| top | +Z | muzzle at the bottom, +X to the right |
| bottom | -Z | muzzle at the top, +X to the right |
| front | -Y | +X to the right |
| back | +Y | -X to the right |

- A top panel with the muzzle to the right needs `rotate=90`. With the muzzle to the left it needs `rotate=270`.
- Trust the muzzle direction, not the caption of the panel. A panel named "left" can show the right view.
- Real size per view: `height_m` is the size along the vertical of the turned picture, `width_m` along its horizontal. Give one. Side, front, back: `height_m` is the height. Top, bottom: `height_m` is the length, or `width_m` is the width.
- Panels of one sheet can have different scales (top 4 % longer than side in a test). Give each view its real size. Do not carry pixels from one panel to another.

## Steps

1. `status`, `scene_tree`, `checkpoint`.
2. Cut the panels: `prepare_reference(image=, crop=[x0, y0, x1, y1], out=)`, one call per panel. Leave `threshold` empty. Look at the preview. Read the hole counts and `warning`.
3. Turn the main side panel to the right view (muzzle to the left): `flip='x'` if needed.
4. Fix the size: `measure_profile(reference=, height_m=)` on the side panel gives the length for a height. If the sheet ratio differs from the given dimensions, keep one dimension and record the deviation of the other. Write size checks for length, height and width with `assert_spec`. `save_spec`.
5. Read the part borders: `measure_profile(grid=true, region=[x0, z0, x1, z1])`. The grid is in millimetres: x from the centre of the silhouette box, z from its bottom. Write down the borders of every part and every cut.
6. Hull: `trace_outline(reference=, height_m=, simplify=0.0008, holes=true)`, then `extrude_profile(name=, points=, holes=, depth=, plane='YZ')` with the largest width as depth. Grid x is now world Y, grid z is world Z. Do not move the hull before the parts exist.
7. Check the hull: `compare_view(view='right', names=, height_m=)`. Expect an IoU of 0.95 or more at this step. Under 0.3, read `hint`: the panel is mirrored or turned. `checkpoint`.
8. Split the hull. For each part: `duplicate` the hull, `extrude_profile` a region polygon from step 5 (`plane='YZ'`, depth larger than the hull), then `boolean(a=, b=, operation='intersect')` with the copy as a and the region as b. The part keeps the exact silhouette. Use the same border numbers for both neighbours. Delete the hull when all parts exist.
9. Widths: read them from the top and front panels with `measure_profile`. `set_dimensions(name=, x=)` per part. The default anchor keeps the part centred on X.
10. Parts off the centre plane (grip plates, levers, buttons): build one side, name it with `_L`, `mirror`. Sink each 0.5 mm into its neighbour.
11. Chamfers and tapers: `bisect` at the height, then `transform_region(where=, scale=, symmetric='x')`.
12. Cuts (serrations, ports, grooves, rail slots, bore): one cutter from `create_primitive` with `rotate_deg`, `array(count=, offset=)`, `mirror` to the other side, `combine` the cutters, one `boolean` difference per part. Cut before you bevel.
13. After each shaping step (9 to 12, and 14): `check_symmetry(names=, axis='X')` and `check_mesh` on the part. Target: no vertex without a partner, issues none.
14. Bevels: `bevel_edges(object=, width=, where=)`, one group of similar edges per call. Read `achieved_width` and `clamped`. Then `shade(mode='auto', weighted_normals=true)`.
15. Origins: `set_origin(names=, at=)`. Root (frame): the grip centre. Hammer, trigger, safety: the hinge axis. Magazine: its bottom. `parent` every part to the root. Move the root to the world origin with `transform_objects`.
16. Compare all views: `compare_view` for right, left, top, front and back, each with `names`, its real size, the right `flip` and `rotate`, and `out`. Fix the worst bands. Reached in a test: side 0.97, top 0.95, back 0.94, front 0.90.
17. Inner detail: read `inner_detail` of the same view before and after a cut. The edge agreement must grow. Do not aim at 1.
18. Materials: `set_material(metallic=1, roughness=0.4)` for steel. `procedural_material(kind='diamond')` for a knurled grip, `kind='worn_metal'` for used steel. Then `bake_maps(object=, maps=['base_color', 'normal', 'orm'])`. Bake a grip plate before `mirror`: the copy shares the UV and the maps. See `materials-and-render`.
19. `run_spec`, `check_game_ready`, `export_glb(max_texture_size=1024)`, `inspect_glb`. See `export-for-game`.

## Traps

- Holes in the mask. Glossy steel on a grey background reads as background. The preview shows red holes and the IoU drops (0.87 against 0.93). Raise `fill_holes` until only real openings (a trigger guard) stay open. A `threshold` that is too low glues background to the outline: the box grows.
- One-sided defect. `transform_region` with a `where` by normal took the faces of one side only. The side IoU stayed 0.97. `check_symmetry` found 40 vertices, up to 6 mm off. Use `symmetric='x'` and read its `warning`.
- `boolean` refuses when the result is open. Seen causes: a new cut over an old cut on a slanted face, a cut that touches a neighbour cut, faces in one plane. Make one combined cutter, or make the overlap larger, or rebuild the part from its profile.
- `bevel_edges` clamps all bevels of one call to the tightest edge. A count of 494 bevelled edges with `achieved_width` near 0 is a failure: `rollback` and bevel a smaller group. A bevel over a whole cut part gave 101 zero-area faces.
- `weld` with a distance wider than the thinnest face opens the mesh. It refuses and names a safe distance. Use that distance.
- One smoothing angle does not fit a part with bevels and flat chamfers: false shadows follow the faces. Use `weighted_normals=true`.
- `fit_to_reference` moved a small lever off its place for 0.002 IoU. Place small parts from the grid.
- `loft_from_masks` does not fit a flat object (side IoU 0.84, height short). `visual_hull` gives 0.96 when the front panel is clean.
- `decimate` in collapse mode lowers the match (0.962 to 0.949 at ratio 0.5). Compare after it.
- Without `names`, `compare_view` takes everything visible. Read `excluded`.
- A magazine panel can have its own scale. Take its size from the side view of the weapon.

## Done when

- Length, height and width are within 3 % of the target. `run_spec` passes.
- Every view is compared with the correct turn and its own real size.
- `check_symmetry` finds nothing on every symmetric part.
- `check_game_ready` gives `ready` true. `inspect_glb` gives no warnings.
