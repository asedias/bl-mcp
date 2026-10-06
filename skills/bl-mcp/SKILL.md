---
name: bl-mcp
description: Build, measure, check, compare and render 3D models in a live Blender through the bl-mcp MCP tools (server "blender", tools such as status, recipe, create_primitive, measure, compare_view, check_game_ready). Use it for any modelling, level blockout, material, render or GLB export task in Blender when the bl-mcp tools are available. Do not use it to drive Blender with raw Python when a tool exists.
license: MIT
---

# bl-mcp

The agent cannot see 3D. These tools answer with numbers and check pictures, so a part that sits 3 cm
off becomes an error instead of a surprise. Work in a loop: change one thing, measure, look, keep or undo.

## Start

1. `status`. It proves the bridge works and names the server and add-on versions. `server_is_stale` means
   restart the MCP server; `addon_is_stale` means restart Blender. With Blender closed it says where
   Blender is installed.
2. `scene_tree`. The scene is often not empty.
3. `recipe` lists the recipes; `recipe(topic)` gives the steps, the numbers to check and the traps for:
   `character-from-reference`, `prop-hard-surface`, `weapon-from-sheet`, `scene-from-photo`,
   `level-blockout`, `materials-and-render`, `export-for-game`. Read the one for the task before the first
   change. The `rules` come with every recipe.

## Rules that do not depend on the task

- Units are metres, Z is up, the front faces -Y. Left and right parts end in `_L` and `_R`.
- Decide the numbers first: sizes, ratios, positions. Write them as `assert_spec` checks, store them with
  `save_spec`, run `run_spec` after every change.
- Build one part at a time and name it. Place parts with `attach`, `move_to_contact`, `ground`,
  `set_dimensions`, `transform_objects`, `set_origin`. Do not guess coordinates.
- After every step measure (`measure`, `find_floating`, `check_contacts`, `check_mesh`,
  `check_symmetry`), then look (`render_sheet` for the overview, `render_view` for a close-up).
  A render does not show a 2 mm gap or a one-sided defect; the checks do. Trust a number over a picture.
- Compare with a reference through `compare_view`, not by eye.
- `checkpoint` before a risky step; `diff_since` shows what changed; `rollback` undoes it (whole scene).
- Read the whole answer. `warning`, `achieved_width`, `clamped`, `solver`, `excluded` tell what the tool
  could not do. A tool that refuses (`boolean`, `weld`) changed nothing: fix the cause, do not force it.
- Long tools (`fit_to_reference`, `match_camera`, `bake_maps`) return a job id when they run long: ask
  `job_status`. Do not edit the object while the job runs.
- `run_python` is the last resort, for what no tool does. Read its report of changed objects.

## Toolsets

The server may run with a subset (`BL_MCP_TOOLSETS`). `status` lists the sets that are off and their
tools. If a tool the recipe names is missing, say so to the user instead of rebuilding it in `run_python`.

## When to stop and ask

- The reference is ambiguous (which panel is the left view, what the real size is).
- A check fails twice after a fix: show the numbers and the picture, ask before a third attempt.
- The task needs a tool that is off or does not exist (asset libraries, AI generation, animation).
