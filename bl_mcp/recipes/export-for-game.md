summary: Take a finished model to a GLB that a game loads: gate, fixes, draw calls, origins, texture size, file check.

Use when form and materials are finished. glTF uses +Y up and triangulates every face: `export_glb` converts.

## Numbers first

- Limits of the game: triangles, objects, materials, draw calls, texture size, file size.
- Draw calls: one per object and material. Linked copies of one mesh can be one instanced call.

## Steps

1. `checkpoint`. Then `check_game_ready(names=, max_tris=, max_materials=, max_draw_calls=, max_texture=)`. Every error blocks the export. Read every warning.
2. Fix by message:
   - Bad name or a suffix like .001: rename the object with `run_python`.
   - Scale not applied: `apply_transforms(names=, mode='scale')`.
   - No material, or faces without a material: `set_material`, then `assign_material_faces` for the listed faces.
   - Inward normals, zero-area faces, doubled vertices: `repair_mesh`.
   - Open shell: `repair_mesh(object=, hole_sides=0)`. Confirm with `check_mesh`.
   - Missing UV: `unwrap`.
   - Too many triangles: `decimate(object=, mode='planar')` first, it keeps the shape. Then `decimate(object=, target_tris=)` and `compare_view` against the reference.
   - Nearly symmetric mesh: one side is broken. `check_symmetry` gives the count and the worst error. Fix the side, or rebuild it with `mirror`.
3. Materials: `dedupe_materials` merges look-alikes and removes empty slots and orphans. `list_materials`: no material is `not_exported`. Bake those that are with `bake_maps` (see `materials-and-render`).
4. Draw calls: `combine` the parts that never move apart and share materials. Keep moving parts apart.
5. Origins: `set_origin(names=, anchor=[0.5, 0.5, 0])` for a standing prop, `set_origin(names=, at=)` for a hinge or a grip. `parent` the parts to one root. Put the root at the world origin: `ground`, `transform_objects`. `measure` shows the origin.
6. `run_spec`. `check_game_ready` again: `ready` is true.
7. `export_glb(path=, names=, max_texture_size=1024, influences=4)` with the root as names. Read `textures` (count and bytes) and `ignored_options`.
8. `inspect_glb(path=)`: triangles, vertices, materials, textures, file size, warnings. This is what the game loads.
9. Compare the file with the scene: triangles and materials must equal the numbers of step 6. If they differ, find the cause before you ship.
10. Round trip for an important asset: `import_glb(path=)`, `measure` the import against the source, `delete` the import.
11. `save_blend`.

## Traps

- Textures decide the file size. Nine 2048 px maps made 25 MB. 1024 or 512 is enough for a small prop: `max_texture_size`.
- A `boolean` cutter without a material once left faces without a material. The gate reports them as an error. Assign them; `dedupe_materials` keeps an empty slot that faces still use.
- A near-symmetry warning is a real defect. In a test a chamfer moved the vertices of one side only. No silhouette showed it.
- `combine` saves draw calls but ends separate motion. For a batched variant: `checkpoint`, `combine`, export under another file name, `rollback`.
- After `rollback` the open file is the checkpoint copy. Call `save_blend(path=, make_current=true)` before a plain save.
- Weighted normals from `shade` reach the file only while `apply_modifiers` is true.
- `decimate` in collapse mode distorts shapes and UVs. Decimate before `unwrap`, `bake_maps` and `bind`.
- Draco makes the file smaller, but the game then needs the Draco decoder. Ask before you set `draco`.
- A skinned mesh needs at most 4 bones per vertex: `check_weights` before the export.
- A model built at another scale leaves at the right size with `scale` of `export_glb`. Do not scale the scene for it.
- N-gon warnings are normal for hard surfaces: the export triangulates.

## Done when

- `check_game_ready` gives `ready` true with your limits.
- `inspect_glb` gives no warnings. Its triangles, materials and textures equal the scene.
- The file size is under the limit.
- The origin of the root and of every moving part is where the game expects it.
