import json
import os
import time

from mcp.server.fastmcp import FastMCP, Image

from . import toolsets
from .client import BlenderError, call

EXPECTED_ADDON = "0.4"

INSTRUCTIONS = """Tools for a live Blender. Units: metres, world coordinates, Z up, the front faces -Y.

Start: call status, then recipe. recipe() lists step-by-step recipes (character, prop, weapon from a sheet, scene
from a photo, level blockout, materials and render, export for a game); recipe(topic) gives one. Follow it.

Work as a loop, never as one big script:
1. Decide the numbers first (sizes, proportions, positions). Keep them as checks: assert_spec, save_spec, run_spec.
2. Build one part at a time and name it. Place parts with attach, move_to_contact, ground, set_dimensions,
   transform_objects, set_origin. Do not guess coordinates.
3. After each step measure (measure, find_floating, check_contacts, check_mesh, check_symmetry), then look
   (render_sheet for the overview, render_view for close-ups). Trust a number over a picture.
4. Compare with a reference by compare_view, not by eye.
5. Take checkpoint before a risky step; diff_since shows the change; rollback undoes it.
6. Read every warning in an answer: tools report what they could not do.

Tool groups, as words to search for: build (create_primitive, extrude_profile, lathe, sweep, loft, boolean, array,
mirror), shape (select_faces, extrude_faces, bevel_edges, bisect, transform_region, sculpt, deform), reference images
(prepare_reference, measure_profile, trace_outline, visual_hull, fit_to_reference, match_camera, overlay_reference),
look (set_material, procedural_material, bake_maps, add_light, setup_lighting, set_world, set_camera, render_final),
rig (create_armature, bind, pose_sheet, unwrap), level (build_from_grid, walkable_map, route, sightline_map, scatter),
game (check_game_ready, export_glb, inspect_glb).

run_python is the last resort, for what no tool does. Use session="name" to keep variables between calls.
"""


class Server(FastMCP):
    def tool(self, *args, structured_output=False, **kwargs):
        # Every tool returns text or images; the generated {"result": string} output schema only adds weight.
        return super().tool(*args, structured_output=structured_output, **kwargs)


def instructions():
    off = [name for name in toolsets.DEFAULT if name not in toolsets.chosen()]
    note = f"\nToolsets switched off by BL_MCP_TOOLSETS: {', '.join(off)}. Their tools are not offered; status lists them.\n" if off else ""
    if os.environ.get("BL_MCP_NO_PYTHON", "") not in ("", "0", "false"):
        note += "\nrun_python is switched off (BL_MCP_NO_PYTHON): only the typed tools are available.\n"
    return INSTRUCTIONS + note


mcp = Server("blender", instructions=instructions())

Vec3 = list[float]


def text(result):
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)


def sheet(result):
    return [text({k: v for k, v in result.items() if k != "path"}), Image(path=result["path"])]


def registry_gaps(handlers):
    """Lines for handlers this server process does not expose and for tools the add-on does not know."""
    tools = toolsets.state["known"] or {tool.name for tool in mcp._tool_manager.list_tools()}
    server_only = toolsets.SERVER_ONLY_TOOLS
    public = {name for name in handlers if not name.startswith("_")}
    gaps = {}
    if public - tools:
        gaps["server_is_stale"] = (
            f"The add-on has {len(public - tools)} tools this MCP server does not offer: {sorted(public - tools)}. The server "
            "process started before they were added. Restart the MCP server (in Claude Code: /mcp, reconnect): reload_addon does not restart it."
        )
    if tools - public - server_only:
        gaps["addon_is_stale"] = (
            f"The add-on does not know {len(tools - public - server_only)} tools of this server: {sorted(tools - public - server_only)}. "
            "They will fail with 'Unknown method'. Restart Blender (developers: the `dev` toolset has reload_addon)."
        )
    return gaps


def call_waiting(method, /, wait=100.0, **params):
    """Call a handler that may run as a background job; wait for it up to `wait` seconds."""
    result = call(method, **params)
    if not (isinstance(result, dict) and result.get("status") == "running" and "job" in result):
        return result
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(0.5)
        state = call("job_status", job=result["job"])
        if state["status"] == "done":
            return state["result"]
        if state["status"] in ("failed", "cancelled"):
            raise BlenderError(state.get("error") or "job cancelled")
    state = call("job_status", job=result["job"])
    state["note"] = f"Still running in Blender. Call job_status with job={result['job']!r} later, or with cancel=true to stop it."
    return state
