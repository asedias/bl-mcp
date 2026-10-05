summary: Character or creature from a front and a side image: hull or loft, limbs, mirror, compare, fit, rig, export.

Use for a figure with a front and a side image. The figure stands on Z = 0, looks to -Y and is symmetric about X = 0.

## Numbers first

- Height in metres. Share of the head in the height. Shoulder and hip width. Arm and leg length.
- Write them with `assert_spec`: check types size, ratio, symmetry, on_ground. `save_spec`.

## Steps

1. `status`, `scene_tree`, `checkpoint`.
2. `prepare_reference` for the front image and for the side image. Look at the preview: no red holes, no contact with the crop border. Read `warning`.
3. The figure in the side image must look to the left. If it looks to the right, use `flip='x'`.
4. `measure_profile(reference=, height_m=)` on the front image: widths per band and the separate runs (arms and legs). Take the numbers for the checks and for loft sections.
5. First solid. Pick one:
   - `visual_hull(name=, front=, side=, height_m=)`: exact in both outlines, with arms, ears and nose. The inside is a straight extrusion.
   - `loft_from_masks(name=, front=, side=, height_m=)`: a round body from the widest run of each band, without arms. `z_range` builds a part of the height.
   - No usable images: `loft` for the torso, `create_primitive` sphere for the head.
6. `measure` the solid. `loft_from_masks` loses half a band at the top and at the bottom: set the height with `set_dimensions(name=, z=, anchor=[0.5, 0.5, 0])`.
7. Limbs on one side: `limb(name=, points=, radii=)` for an arm and a leg, `blob` for a hand. End the names with `_L`. Then `mirror(name=, axis='X', at=0)`: the copy gets `_R`.
8. Joints: `move_to_contact` with `depth` 0.005 to 0.02 for neck, shoulders and hips. Then `find_floating`: no floating group. Read `tiny_gaps`: a gap of millimetres is a visible seam.
9. `parent` all parts to one root. `ground` the root.
10. `render_sheet` for the overview. `compare_view` for front, side and back with `height_m` and `names`. Read the band table: where the model is wider, narrower or shifted. Fix the worst band first.
11. Shape, one change at a time: `transform_region` with `symmetric='x'` (wider head, taper), `sculpt(op='grab')` and `sculpt(op='smooth')` for soft forms, `inset_faces` and `bevel_edges` for details. Pick faces with `mesh_info`, then `select_faces`. After each change `compare_view`: keep it only if the IoU grows.
12. Form right, parts in the wrong place: `fit_to_reference(parts=, references=, height_m=, mirror_pairs=)`. It takes a checkpoint named before_fit. Read `rejected` and `visible_share`.
13. `check_symmetry(names=, axis='X', at=0)`, `check_mesh` on every part, `run_spec`.
14. `render_view` close-ups: mode clay for the form, wire for the topology, backfaces for flipped faces.
15. Before the rig: `shade(mode='auto')`, `decimate` to the budget, then `unwrap` or `palette_uv`. Call `compare_view` again after `decimate`.
16. Rig: `create_armature(name=, bones=)` with joint positions from the reference. List parents before children. `bind(meshes=, armature=)`. `check_weights(mesh=, max_influences=4)`: no vertex without weight.
17. `pose_sheet` with extreme poses: arms up, knees bent, torso turned. Look for tears and collapsed joints.
18. `check_game_ready`, `export_glb(influences=4)`, `inspect_glb`. See `export-for-game`.

## Traps

- Without `height_m`, `compare_view` assumes the model size. A model that is too big passes.
- Dark parts near the background colour are lost from the mask: hair, shoes. The preview of `prepare_reference` shows it. The model then looks too tall against the reference.
- `visual_hull` matches both outlines but not the surface between them. A round belly is a box inside. Round it with `sculpt` or `subdivide`.
- `fit_to_reference` moves, scales and tilts whole parts. It does not change a shape. It can hide a part inside the body to gain IoU: the guard lists such moves in `rejected`.
- Tools that take `names` or `target` include the children. To frame the head alone in `render_view`, do not parent the head to the body before step 9.
- `mirror` swaps `_L` and `_R` in the name. A part with another name gets the suffix _mirror.
- `bind` overwrites vertex groups with the bone names. With `method='auto'` it falls back to proximity weights on a mesh that is not clean.
- `decimate` in collapse mode distorts shapes and UVs. Decimate before `unwrap` and before `bind`.
- A reference in perspective does not fit flat views. Use `scene-from-photo` for a photo.

## Done when

- `run_spec` passes. `check_symmetry` finds nothing.
- The IoU of front, side and back no longer grows with single changes.
- `check_weights` reports no problem. The pose sheet shows no tear.
- `check_game_ready` gives `ready` true. `inspect_glb` gives no warnings.
