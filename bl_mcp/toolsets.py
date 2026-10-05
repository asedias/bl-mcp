"""Which tools this server process offers. BL_MCP_TOOLSETS picks the sets; `core` is always on."""

import os

TOOLSETS = {
    "core": [
        "status", "recipe", "scene_tree", "measure", "run_python", "job_status", "render_sheet", "render_view",
        "checkpoint", "rollback", "diff_since", "save_blend", "create_primitive", "transform_objects", "set_origin",
        "attach", "move_to_contact", "ground", "set_dimensions", "apply_transforms", "parent", "duplicate", "delete",
        "mirror", "set_material", "shade", "find_floating", "check_contacts", "check_mesh", "assert_spec", "save_spec",
        "run_spec",
    ],
    "model": [
        "mesh_info", "select_faces", "extrude_faces", "inset_faces", "delete_faces", "subdivide_faces", "bevel_edges",
        "bisect", "weld", "transform_region", "sculpt", "deform", "shrinkwrap", "remesh", "blob", "boolean",
        "repair_mesh", "combine", "array", "radial_array", "solidify", "lathe", "sweep", "decimate", "limb", "loft",
        "subdivide", "check_symmetry", "text_mesh", "extrude_profile",
    ],
    "reference": [
        "prepare_reference", "measure_profile", "trace_outline", "loft_from_masks", "visual_hull", "compare_view",
        "fit_to_reference", "overlay_reference", "match_camera", "pixel_to_world", "place_at_pixel",
    ],
    "level": [
        "build_from_grid", "scatter", "place_on", "walkable_map", "route", "check_passages", "sightline_map",
        "viewshed", "raycast", "line_of_sight", "terrain", "path_carve", "rock", "noise_displace",
    ],
    "look": [
        "list_materials", "assign_material_faces", "dedupe_materials", "procedural_material", "bake_maps", "add_light",
        "list_lights", "set_post", "set_camera", "setup_lighting", "set_world", "render_final",
    ],
    "rig": [
        "create_armature", "list_bones", "bind", "transfer_weights", "check_weights", "pose", "pose_sheet", "unwrap",
        "paint_faces", "palette_uv",
    ],
    "game": ["check_game_ready", "export_glb", "import_glb", "inspect_glb"],
    "dev": ["reload_addon"],
}
DEFAULT = [name for name in TOOLSETS if name != "dev"]
SERVER_ONLY_TOOLS = {"recipe", "reload_addon"}
ALWAYS_LOADED = ["status", "recipe", "scene_tree", "measure", "render_view", "run_python"]

state = {"known": set(), "on": list(DEFAULT), "off": []}


def chosen(value=None):
    """Toolset names from BL_MCP_TOOLSETS: a comma list, `all` for every default set; unset means all default sets."""
    value = os.environ.get("BL_MCP_TOOLSETS", "") if value is None else value
    asked = [part.strip().lower() for part in value.split(",") if part.strip()]
    unknown = [name for name in asked if name != "all" and name not in TOOLSETS]
    if unknown:
        raise ValueError(f"BL_MCP_TOOLSETS: unknown toolsets {unknown}. Known: {list(TOOLSETS)}, or 'all'.")
    picked = {"core", *(DEFAULT if not asked or "all" in asked else []), *(name for name in asked if name != "all")}
    return [name for name in TOOLSETS if name in picked]


def without_titles(schema):
    """FastMCP adds a `title` to every property; it repeats the name and costs a tenth of the tool list."""
    if isinstance(schema, list):
        return [without_titles(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {key: without_titles(value) for key, value in schema.items() if not (key == "title" and isinstance(value, str))}


def apply(mcp):
    """Check that every tool has one toolset, drop the tools of the sets that are off, slim the schemas."""
    registered = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    placed = [name for names in TOOLSETS.values() for name in names]
    problems = {
        "without a toolset": sorted(set(registered) - set(placed)),
        "in a toolset but not registered": sorted(set(placed) - set(registered)),
        "in two toolsets": sorted({name for name in placed if placed.count(name) > 1}),
    }
    if any(problems.values()):
        raise RuntimeError(f"bl_mcp/toolsets.py does not match the registered tools: { {k: v for k, v in problems.items() if v} }")
    state["known"] = set(registered)
    state["on"] = chosen()
    state["off"] = [name for name in DEFAULT if name not in state["on"]]
    kept = {name for toolset in state["on"] for name in TOOLSETS[toolset]}
    for name, tool in registered.items():
        if name not in kept:
            mcp.remove_tool(name)
            continue
        tool.parameters = without_titles(tool.parameters)
        if name in ALWAYS_LOADED:
            tool.meta = {**(tool.meta or {}), "anthropic/alwaysLoad": True}


def report():
    """What `status` says about toolsets, so the agent knows which tools exist but are off."""
    info = {"on": state["on"]}
    if state["off"]:
        info["off"] = {name: TOOLSETS[name] for name in state["off"]}
        info["note"] = "Tools of the sets that are off are not offered. Set BL_MCP_TOOLSETS (comma list, or unset for all) and restart the MCP server."
    return info
