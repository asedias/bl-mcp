# bl-mcp

MCP server for a live Blender. It gives an AI agent tools to build, measure, check and look at a model, not only to run raw `bpy` code.

## Why

Raw `bpy` access has two problems. The agent cannot see 3D, and a wrong move of 3 cm gives no error. These tools make such mistakes visible as numbers and images, and give the agent safe operations in world units. Every tool that changes geometry reports what it really did: achieved widths, open edges, parts it could not process.

## Install

Needs [`uv`](https://docs.astral.sh/uv/) and Blender 5.0 or newer.

1. Get the code: `git clone https://github.com/asedias/bl-mcp`.
2. Link or copy `addon/bl_bridge` into the Blender add-ons folder, for example on macOS
   `~/Library/Application Support/Blender/<version>/scripts/addons/`.
3. In Blender: Edit > Preferences > Add-ons > enable **BL MCP Bridge**. The console prints `listening on 127.0.0.1:9877`.
4. Add the server to the MCP client. Claude Code:

```
claude mcp add blender -- uv run --project /path/to/bl-mcp bl-mcp
```

Any client with a JSON config:

```json
{
  "mcpServers": {
    "blender": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "/path/to/bl-mcp", "bl-mcp"]
    }
  }
}
```

The server alone also runs without a clone: `uvx --from git+https://github.com/asedias/bl-mcp bl-mcp`. The add-on still has to come from the repository, at the same version.

The agent calls `status` first. It shows both versions, compares the tools of the server with the handlers of the add-on, and says which side to restart when they differ. When Blender is not open it says where Blender is installed.

The server and the add-on talk by JSON lines on `127.0.0.1:9877`. Set `BL_MCP_PORT` on both sides to change the port. The socket listens on localhost only.

## Toolsets

The server has 113 tools in 7 sets. All sets are on by default. Clients that load tool descriptions on demand (Claude Code, Codex) handle this well. For a client with a tool limit, pick the sets with `BL_MCP_TOOLSETS` (a comma list; `core` is always on):

```json
"env": { "BL_MCP_TOOLSETS": "core,model,reference,game" }
```

| Set | Tools | For |
|---|---|---|
| `core` | 32 | scene, measuring, placing, review renders, checks, checkpoints, recipes, `run_python` |
| `model` | 30 | mesh editing by selection, sculpting, booleans, arrays, lathe, sweep |
| `reference` | 11 | reference images and photos: masks, outlines, comparison, camera matching |
| `level` | 14 | blockout from a plan, walkability, routes, sightlines, terrain, scatter |
| `look` | 12 | materials, baking, lights, camera, world, final render |
| `rig` | 10 | armature, skinning, poses, UV, vertex colour |
| `game` | 4 | game checks, GLB export, import and inspection |
| `dev` | 1 | `reload_addon`; off unless named |

`status` lists the sets that are off with their tools. `bl_mcp/toolsets.py` is the table; the server refuses to start when a tool has no set.

## Recipes

The agent sees only the server instructions and the tool descriptions. Step-by-step recipes ship inside the package (`bl_mcp/recipes/`) and reach the agent in two ways:

- the tool `recipe`: no argument lists the topics, `recipe(topic)` returns one with the general rules;
- MCP prompts built from the same files: `model_from_reference`, `hard_surface_prop`, `weapon_from_sheet`, `scene_from_photo`, `blockout_level`, `materials_and_render`, `prepare_for_game`, `review_model`.

Topics: `rules`, `character-from-reference`, `prop-hard-surface`, `weapon-from-sheet`, `scene-from-photo`, `level-blockout`, `materials-and-render`, `export-for-game`.

## Tools

Units are metres, coordinates are world coordinates, Z is up, the front faces -Y. Anchors are fractions of a world bounding box: `(0.5, 0.5, 0)` is the bottom centre. `where` picks faces by a condition: `normal` ('+Z' or a vector) with `angle`, `x`/`y`/`z` ranges, `box`, `area`, `index`.

**core.** `status`, `recipe`, `scene_tree`, `measure`, `run_python` (with a persistent `session`). Review: `render_sheet` (overview sheet with a metre grid), `render_view` (any angle; modes solid, clay, xray, flat, wire, ids, normals, backfaces). Build and place: `create_primitive`, `duplicate`, `mirror`, `delete`, `parent`, `transform_objects`, `set_origin`, `attach` (anchor to anchor), `move_to_contact` (slide a part until it touches), `ground`, `set_dimensions`, `apply_transforms`, `set_material` (flat colour up to full PBR with maps), `shade` (flat, smooth, auto, weighted normals). Check: `assert_spec` (size, position, ratio, gap, contact, symmetry, inside, ground, clean, budget, connected), `save_spec`, `run_spec`, `find_floating`, `check_contacts`, `check_mesh` (also UV numbers). Safety: `checkpoint`, `diff_since` (size, position, topology, material slots), `rollback`, `save_blend`, `job_status`.

**model.** `mesh_info`, `select_faces`, then `extrude_faces`, `inset_faces`, `delete_faces`, `subdivide_faces`, `bevel_edges`, `bisect`, `weld`, `transform_region` (with proportional falloff and a symmetric selection). `sculpt` (grab, inflate, smooth, flatten, pinch by numbers), `deform` (bend, twist, taper, stretch), `shrinkwrap`, `remesh`, `subdivide`, `decimate`. Solids: `boolean`, `repair_mesh`, `combine`, `array`, `radial_array`, `solidify`, `lathe`, `sweep`, `limb`, `loft`, `blob`, `extrude_profile` (with holes), `text_mesh` (also engraved). `check_symmetry`.

**reference.** `prepare_reference` (crop, automatic background threshold, hole filling, flip, rotate, a mask preview), `measure_profile` (widths per band, a millimetre grid), `trace_outline` (outline and holes), `visual_hull`, `loft_from_masks`, `compare_view` (world-registered IoU from six views, band table, overlay sheet, inner edge agreement, orientation hint), `fit_to_reference` (moves, scales and tilts parts; background job). Photos: `match_camera` (background job), `overlay_reference`, `pixel_to_world`, `place_at_pixel`.

**level.** `build_from_grid` (a text plan), `walkable_map`, `route`, `check_passages` (doors and corridors), `sightline_map`, `viewshed`, `raycast`, `line_of_sight`, `scatter`, `place_on`, `terrain`, `path_carve`, `rock`, `noise_displace`.

**look.** `list_materials`, `assign_material_faces`, `dedupe_materials` (also removes empty slots and orphans), `procedural_material` (wood, checker, diamond, bricks, noise, marble, worn metal), `bake_maps` (colour, normal with rounded edges, roughness, metallic, AO, ORM; background job; the material is rebuilt on image textures, so glTF gets them), `add_light`, `list_lights`, `setup_lighting` (three_point, sun, soft_studio, night, metal), `set_world` (colour or HDRI), `set_camera`, `set_post`, `render_final` (eevee, cycles, workbench; exposure by hand or automatic; the scene settings are restored).

**rig.** `create_armature`, `list_bones`, `bind`, `transfer_weights`, `check_weights`, `pose`, `pose_sheet`, `unwrap`, `paint_faces`, `palette_uv`.

**game.** `check_game_ready` (also the plain budget question), `export_glb` (with a texture size limit), `import_glb`, `inspect_glb`.

Long tools (`fit_to_reference`, `match_camera`, `bake_maps`) run as background jobs inside Blender in small slices, so Blender stays usable. If one needs more than its `wait` seconds the answer is a job id; ask `job_status`.

## Limits

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

## Finding Blender

`bl-mcp-find-blender` looks in this order: a running Blender process, `blender` on PATH, then standard install folders (macOS `/Applications`, `~/Applications`, Steam; Linux `/usr/bin`, snap, `/opt`; Windows `Program Files`). A running Blender reports its own path in `status`; with Blender closed, `status` gives the same search result.

## Parts

```
addon/bl_bridge/      Blender add-on: local socket, handlers that run in the Blender main thread
  core.py             registry, jobs, shared helpers, base tools
  profiles.py         shapes from reference images (mask, outline, profile, hull)
  compare.py          comparison with a reference (registered IoU, bands, inner edges, overlay)
  fit.py              automatic fit of parts to silhouettes (background job)
  meshops.py          pick faces by a condition; extrude, inset, bevel, cut, move
  sculpt.py           numeric sculpting and deformers
  hard.py             boolean, repair, arrays, lathe, sweep, decimate, origins
  rig.py              armatures, skinning, poses
  uvpaint.py          UV maps, vertex colour, palette UVs
  level.py            blockout from a plan, scatter, viewshed, passages, saved specs
  materials.py        PBR materials, maps, per-face materials, dedupe
  render.py           camera, light presets, world, final render, save
  organic.py          noise, terrain, rocks, paths
  procedural.py       procedural material presets, baking to maps
  lights.py           lights with settings, post effects, text meshes
  refcam.py           reference overlay, camera matching, pixels to world
bl_mcp/               MCP server (stdio)
  app.py              server object, instructions, shared helpers
  tools_*.py          one typed wrapper with a docstring per tool
  toolsets.py         tool-to-set table, BL_MCP_TOOLSETS
  recipes/            step-by-step recipes served by the `recipe` tool and the prompts
  locate.py           Blender locator
tests/                see Test
```

## Add a tool

1. Write a function with the `@handler` decorator in a module of `addon/bl_bridge/` (a new module goes into `FEATURES` in `__init__.py`). Return a `str` or a JSON-able value; a generator that yields progress and returns the value becomes a background job.
2. Add a test to `tests/headless.py` or to a `tests/test_<module>.py`.
3. Add a typed wrapper with a docstring in a `bl_mcp/tools_*.py` module. The docstring is the only documentation the agent reads: say what the tool does and when to use it, use `Literal` for fixed values, keep it under 1800 characters.
4. Put the tool into a set in `bl_mcp/toolsets.py`.
5. Add a call to `tests/smoke_all.py`: it fails when a tool is never called. Before you extend a recipe, run `tests/check_recipes.py`.

Prefer a parameter on an existing tool to a new tool.

## Test

```
uv run python tests/run_headless.py    # handlers in Blender without a window; add a file name to run one
uv run python tests/run_smoke.py       # every tool through the real server, in a private Blender
uv run python tests/smoke_all.py       # the same in the Blender you have open (builds smoke_* objects, removes them)
uv run python tests/check_recipes.py   # every tool and parameter named in a recipe exists; no Blender needed
```

The runners find Blender by themselves. The headless run calls the handlers directly. The smoke run goes through the real MCP server and socket, and catches what the headless run cannot (argument names, enums, image results, jobs). `tests/demo_figure.py` builds, checks and renders a small figure in the open Blender (`--keep` leaves it in the scene).

## License

MIT, see `LICENSE`.
