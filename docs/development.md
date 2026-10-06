# Development

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
uv run python tests/agent_run.py --env model.env --task task.md --out runs/x   # any OpenAI-compatible model as the agent
```

The runners find Blender by themselves. The headless run calls the handlers directly. The smoke run goes through the real MCP server and socket, and catches what the headless run cannot (argument names, enums, image results, jobs). `tests/demo_figure.py` builds, checks and renders a small figure in the open Blender (`--keep` leaves it in the scene).

## CI and releases

`.github/workflows/check.yml` runs the recipe check and lists the tools on every push. `.github/workflows/release.yml` runs on a tag `v*`: it checks that the tag equals the add-on and package versions, zips `addon/bl_bridge` for Install from Disk and creates the GitHub release with the zip attached.
