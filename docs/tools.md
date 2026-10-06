# Tools

Units are metres, coordinates are world coordinates, Z is up, the front faces -Y. Anchors are fractions of a world bounding box: `(0.5, 0.5, 0)` is the bottom centre. `where` picks faces by a condition: `normal` ('+Z' or a vector) with `angle`, `x`/`y`/`z` ranges, `box`, `area`, `index`.

**core.** `status`, `recipe`, `scene_tree`, `measure`, `run_python` (with a persistent `session`). Review: `render_sheet` (overview sheet with a metre grid), `render_view` (any angle or a camera standing at `eye`; modes solid, clay, xray, flat, wire, ids, normals, backfaces). Build and place: `create_primitive`, `duplicate`, `mirror`, `delete`, `parent`, `transform_objects` (a group, or each object to its own point with `place`), `set_origin`, `attach` (anchor to anchor), `move_to_contact` (slide a part until it touches), `ground`, `set_dimensions`, `apply_transforms`, `set_material` (flat colour up to full PBR with maps), `shade` (flat, smooth, auto, weighted normals). Check: `assert_spec` (size, position, ratio, gap, contact, symmetry, inside, ground, clean, budget, connected), `save_spec`, `run_spec`, `find_floating`, `check_contacts`, `check_mesh` (also UV numbers). Safety: `checkpoint`, `diff_since` (size, position, topology, material slots), `rollback`, `save_blend`, `job_status`.

**model.** `mesh_info`, `select_faces`, then `extrude_faces`, `inset_faces`, `delete_faces`, `subdivide_faces`, `bevel_edges`, `bisect`, `weld`, `transform_region` (with proportional falloff and a symmetric selection). `sculpt` (grab, inflate, smooth, flatten, pinch by numbers), `deform` (bend, twist, taper, stretch), `shrinkwrap`, `remesh`, `subdivide`, `decimate`. Solids: `boolean`, `repair_mesh`, `combine`, `array`, `radial_array`, `solidify`, `lathe`, `sweep`, `limb`, `loft`, `blob`, `extrude_profile` (with holes), `text_mesh` (also engraved). `check_symmetry`.

**reference.** `prepare_reference` (crop, automatic background threshold, hole filling, flip, rotate, a mask preview), `measure_profile` (widths per band, a millimetre grid), `trace_outline` (outline and holes), `visual_hull`, `loft_from_masks`, `compare_view` (world-registered IoU from six views, band table, overlay sheet, inner edge agreement, orientation hint), `fit_to_reference` (moves, scales and tilts parts; background job). Photos: `match_camera` (background job), `overlay_reference`, `pixel_to_world`, `place_at_pixel`.

**level.** `build_from_grid` (a text plan), `walkable_map` (regions with floor height, `probe` points), `route` (narrowest point, or why a wide route fails), `check_passages` (doors and corridors), `sightline_map`, `viewshed`, `raycast`, `line_of_sight`, `scatter`, `place_on`, `terrain`, `path_carve`, `rock`, `noise_displace`.

**look.** `list_materials`, `assign_material_faces`, `dedupe_materials` (also removes empty slots and orphans), `procedural_material` (wood, checker, diamond, bricks, noise, marble, worn metal), `bake_maps` (colour, normal with rounded edges, roughness, metallic, AO, ORM; background job; the material is rebuilt on image textures, so glTF gets them), `add_light`, `list_lights`, `setup_lighting` (three_point, sun, soft_studio, night, metal), `set_world` (colour or HDRI), `set_camera`, `set_post`, `render_final` (eevee, cycles, workbench; exposure by hand or automatic; the scene settings are restored).

**rig.** `create_armature`, `list_bones`, `bind`, `transfer_weights`, `check_weights`, `pose`, `pose_sheet`, `unwrap`, `paint_faces`, `palette_uv`.

**game.** `check_game_ready` (also the plain budget question), `export_glb` (with a texture size limit), `import_glb`, `inspect_glb`.

Long tools (`fit_to_reference`, `match_camera`, `bake_maps`) run as background jobs inside Blender in small slices, so Blender stays usable. If one needs more than its `wait` seconds the answer is a job id; ask `job_status`.

## Finding Blender

`bl-mcp-find-blender` looks in this order: a running Blender process, `blender` on PATH, then standard install folders (macOS `/Applications`, `~/Applications`, Steam; Linux `/usr/bin`, snap, `/opt`; Windows `Program Files`). A running Blender reports its own path in `status`; with Blender closed, `status` gives the same search result.
