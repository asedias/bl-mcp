summary: Materials that reach glTF (PBR maps, procedural patterns baked to images) and a final render checked by numbers.

Use when the form is finished. Build and check the geometry first: a bake repeats after every change of the mesh.

## Steps: materials

1. `list_materials`: what exists, which materials are `not_exported`, which objects have `faces_without_material`.
2. Flat material: `set_material(names=, color=, roughness=, metallic=)`. Metallic is 0 or 1. The same numbers reuse one material.
3. Several materials on one mesh: `assign_material_faces(object=, material=, where=)`. Each material on a mesh is one draw call.
4. Final shading before any bake: `shade(names=, mode='auto', weighted_normals=true)` for hard surfaces.
5. Image maps need a UV map: `unwrap`. `check_mesh` shows the UV state: no face outside 0..1, even texel density.
6. `set_material(names=, color='#ffffff', texture=, normal_map=, orm_map=)`. Without a packed image use `roughness_map` and `metallic_map`. A map replaces its number. With a texture the colour is a tint.
7. Pattern: `procedural_material(names=, kind=, color_a=, color_b=, scale=)`. Kinds: wood, checker, diamond, bricks, noise, marble, worn_metal.
8. Join fixed parts with `combine` before the bake: one object gets one set of maps.
9. Test bake: `bake_maps(object=, size=512, maps=['base_color', 'normal', 'orm'])`. It is a background job: ask `job_status`. Do not edit the object while it runs.
10. Rounded edges without geometry: `bake_maps` with `bevel_radius`, 0.2 to 0.5 % of the object size. The kind worn_metal rounds edges itself.
11. Look at a probe render (step 16). Then bake at the final size: 1024 for a prop, 2048 for a hero asset.
12. `list_materials` again: no material is `not_exported`. `dedupe_materials` merges look-alikes and removes empty slots and orphans.

## Steps: render

13. Camera: `set_camera(frame=, azimuth=, elevation=, fov_deg=)`.
14. Light: `setup_lighting(preset=)`. Presets: three_point, sun, soft_studio, night, metal. For metal and gloss use `preset='metal'`, or `set_world(hdri='interior', strength=0.6, visible_to_camera=false)` with your own lights.
15. Accent light: `add_light(kind='spot', name=, location=, look_at=, power_w=)`. A spot needs about 40 W at 1 m, 150 W at 2 m, 600 W at 4 m. An area panel needs a third. Post effects: `set_post(vignette=, glare=, contrast=)`.
16. Probe: `render_final(path=, engine='cycles', size=512, samples=32, auto_exposure=true, meter=)` with the model as meter.
17. Read the numbers of the answer. In `object`: `clipped_highlights` under 0.10, `crushed_blacks` under 0.50. No `warnings`. A few percent of white is normal on metal.
18. Final: the same call with the final `size` and `samples` 128 or more.

## Traps

- Procedural nodes, `bump` and subsurface do not reach glTF. `list_materials` marks them. Bake them, or the game shows a flat colour.
- The dirt, edge wear and rounding of worn_metal come from ray-traced nodes. They show in cycles renders and in `bake_maps`. An eevee render shows clean metal.
- Metal under area lights and a dark world renders black. More light strength then blows it out. Metal needs an HDRI to reflect.
- A shadow that follows the faces and not the light is shading, not light. Fix it with `shade` and bake the normal map again. A normal map baked before a shading change is wrong.
- Overlapping UVs make the maps clash. UVs from `palette_uv` or from a joined mesh overlap. Call `unwrap` again before the bake.
- Each object gets its own maps, also when objects share a material. Nine 2048 px maps made a GLB of 25 MB. Use `export_glb(max_texture_size=)` and fewer baked objects.
- Bake one side of a mirrored pair, then `mirror`: the copy shares the UV and the maps.
- A first wear bake looked like camouflage: brown patches on pale steel. Keep dirt dark and neutral, lower it in `params`, and judge at 512 px before the long bake.
- Bloom from `glare` needs pixels brighter than 1: a strong light or emission. `set_post` refuses to replace a compositor tree it did not make.
- `setup_lighting` deletes only its own lights. A second accent light with the same `name` updates the first one.
- Alpha below 1 turns on blending. Use it for glass only. Blender renders do not show the occlusion channel of an ORM map: only the game uses it.

## Done when

- `list_materials` shows no material as `not_exported` and no `faces_without_material`.
- The final render has no `warnings`, and the numbers of step 17 hold.
- `inspect_glb` on the exported file lists the expected textures and sizes (see `export-for-game`).
