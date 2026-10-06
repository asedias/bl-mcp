# Limits

- `check_contacts` and `find_floating` find intersection by sample points (vertices and triangle centres) sunk into the other mesh. Two thin bars that cross without a sample inside are not found. Closed meshes with inward normals are handled; open shells are not.
- `rollback` opens the checkpoint file. The open file then is the checkpoint copy: use Save As before you save. It also clears the `run_python` sessions. Checkpoints belong to a scene; the link is lost when the scene is never saved and the file is reopened.
- Level tools work on a grid of rays: a wall thinner than `cell` can leak, and a doorway narrower than the agent plus one cell is not walkable at a coarse `cell`. Widths are accurate to about one cell and err on the small side. The area chosen by default is the largest one on the lowest floor level (not wall tops); pass `start` when there are several levels.
- Tools that take `names` or `target` include the children of each object. To frame only a head, do not parent the head to the body.
- The reference tools need an image with an alpha channel or a plain background. Look at the mask preview of `prepare_reference`: parts close to the background colour can be lost.
- `compare_view` measures the silhouette. A defect on one side of a symmetric part does not show in a side view: run `check_symmetry`. Its `inner_detail` number compares two runs of one model; textures in the reference keep it far from 1.
- `visual_hull` is a straight extrusion inside: it matches both outlines but not the surface between them.
- Procedural material nodes (the `bump` of `set_material`, every `procedural_material`) and subsurface do not reach glTF without `bake_maps`. `list_materials` marks them.
- `fit_to_reference` moves whole parts (with children). It fixes placement and proportions, not shapes.
- `boolean` cleans and checks its result, tries the other solvers, and refuses instead of leaving an open mesh (`allow_open=true` keeps it). Parts that only touch along an edge keep doubled vertices there.
- `bevel_edges`: Blender clamps every bevel of one call to the tightest edge. Bevel edges of similar size per call and read `achieved_width`.
- Tolerances that matter for small parts (weld distance, contact, floating, symmetry, bevel width) default to a value relative to the object size, so a 5 cm part works without scaling the scene.
- `match_camera` needs the whole photo, not a crop, and a simple box model leaves some play along the view ray: fix the field of view when you know it. `set_post` refuses to replace a compositor tree it did not make.
- Automatic exposure and the `metal` lighting preset are tuned with the Standard view transform.
- `render_view` modes `normals` and `backfaces` use EEVEE with a material override, `wire` uses temporary wireframe copies. The scene is never changed.
- Flat views are orthographic and share one scale. `iso` has no grid.
- Handlers run in the Blender main thread. Blender is busy while a render runs.
- Asset search and AI model generation are not included.
