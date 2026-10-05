"""Calls every tool of the server once in the open Blender, then removes what it made.

Needs Blender open with the add-on enabled. Run: uv run python tests/smoke_all.py
Everything it creates is named smoke_*; only data it created is removed at the end.
rollback is called without a name only (it lists): a real rollback replaces the open file (the headless tests cover it).
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TMP = Path(tempfile.gettempdir())
GLB = str(TMP / "bl_mcp_smoke.glb")
RENDERS = Path(os.environ.get("BL_MCP_WORK") or TMP / "bl_mcp") / "renders"
BLOCKS = ("meshes", "armatures", "metaballs", "materials", "images", "lights", "cameras")


async def main():
    forwarded = {k: os.environ[k] for k in ("BL_MCP_PORT", "BL_MCP_WORK") if k in os.environ} | {"BL_MCP_TOOLSETS": "all,dev"}
    params = StdioServerParameters(command="uv", args=["run", "--project", ".", "bl-mcp"], env=forwarded or None)
    failures, called = [], set()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            prompts = {p.name for p in (await session.list_prompts()).prompts}

            async def call(tool, /, **args):
                called.add(tool)
                result = await session.call_tool(tool, args)
                text = "\n".join(c.text for c in result.content if c.type == "text")
                images = sum(1 for c in result.content if c.type == "image")
                if result.isError:
                    failures.append(f"{tool}: {text[-900:]}")
                print(f"{'FAIL' if result.isError else 'ok  '} {tool}{' +image' if images else ''}: {text[:100].replace(chr(10), ' ')}")
                return text

            await call("status")
            await call("recipe")
            await call("recipe", topic="weapon-from-sheet")
            await call("reload_addon")
            before = await call("scene_tree")
            existing = [line.split(" [")[0].strip() for line in before.splitlines() if " [" in line]
            await call("run_python", code=f"before_data = {{k: {{i.name for i in getattr(bpy.data, k)}} for k in {BLOCKS!r}}}", session="smoke", reset=True)

            # level: a plan, then the checks
            await call("build_from_grid", layout=["#########", "#...#...#", "#.S.D.O.#", "#...#...#", "#########"], cell=1.0, name="smoke_lv", origin=[40, 0, 0])
            level = ["smoke_lv_floor", "smoke_lv_walls"]
            await call("walkable_map", names=level, cell=0.5)
            await call("route", start=[42.5, 2.5, 0], end=[46.5, 2.5, 0], names=level, cell=0.25)
            await call("sightline_map", names=level, cell=1.0, max_range=20)
            await call("check_passages", names=level, min_door=1.5, min_corridor=0.4, cell=0.25)
            await call("viewshed", point=[42.5, 2.5, 0], names=level, cell=0.25)
            await call("raycast", origin=[43, 2, 5], direction=[0, 0, -1])
            await call("line_of_sight", a=[41.5, 2.5, 1.5], b=[47.5, 2.5, 1.5])
            await call("create_primitive", kind="torus", name="smoke_ring", size=[1.0, 1.0, 0.3], at=[30, 0, 0.15])
            await call("create_primitive", kind="cube", name="smoke_tree", size=[0.3, 0.3, 1.0], at=[0, 20, 0])
            await call("create_primitive", kind="cube", name="smoke_meadow", size=[10, 10, 0.2], at=[100, 100, 0], anchor=[0.5, 0.5, 1])
            await call("scatter", source=["smoke_tree", "smoke_ring"], surface=["smoke_meadow"], count=6, seed=1, area=[96, 96, 104, 104], min_distance=0.8)
            await call("place_on", object="smoke_tree", surface=["smoke_meadow"], at=[100, 100])

            # a figure: build, check, render
            await call("loft", name="smoke_torso", axis="Z", sections=[
                {"at": [0, 3, 0.8], "size": [0.4, 0.22], "roundness": 3},
                {"at": [0, 3, 1.5], "size": [0.3, 0.2]},
            ])
            await call("create_primitive", kind="sphere", name="smoke_head", size=[0.26, 0.28, 0.3], at=[0, 3, 1.5], anchor=[0.5, 0.5, 0], segments=24)
            await call("limb", name="smoke_arm_L", points=[[0.25, 3, 1.4], [0.35, 3, 1.0]], radii=[0.06, 0.04])
            await call("mirror", name="smoke_arm_L", axis="X", at=0)
            figure = ["smoke_torso", "smoke_head", "smoke_arm_L", "smoke_arm_R"]
            await call("set_material", names=figure, color="#3b6fd8")
            await call("move_to_contact", a="smoke_head", to="smoke_torso", depth=0.01)
            await call("attach", part="smoke_arm_L", to="smoke_torso", part_anchor=[0.5, 0.5, 1], to_anchor=[1, 0.5, 0.9])
            await call("set_dimensions", name="smoke_head", z=0.3)
            await call("shade", names=["smoke_head"], mode="auto")
            await call("subdivide", names=["smoke_head"], levels=1)
            await call("apply_transforms", names=["smoke_head"])
            await call("duplicate", name="smoke_head", new_name="smoke_head_copy", offset=[0, 2, 0])
            await call("parent", child="smoke_head_copy", to="smoke_torso")
            await call("ground", names=["smoke_torso"])
            await call("measure", names=figure)
            await call("find_floating", names=figure, ground_z=0.0)
            await call("check_contacts", a="smoke_head", b="smoke_torso")
            await call("check_symmetry", names=["smoke_arm_L", "smoke_arm_R"], axis="X", at=0)
            await call("check_mesh", name="smoke_torso")
            await call("check_game_ready", names=figure, max_tris=100000, budget_only=True)
            await call("check_game_ready", names=figure, max_tris=100000)
            spec = [{"type": "size", "object": "smoke_head", "axis": "z", "equals": 0.3, "tol": 0.01}, {"type": "on_ground", "object": "smoke_torso", "z": 0.0, "tol": 1.0}]
            await call("assert_spec", checks=spec)
            await call("save_spec", name="smoke_rules", checks=spec)
            await call("run_spec", name="smoke_rules")
            if "smoke_rules" not in await call("run_spec"):
                failures.append("run_spec without a name should list the stored specs")
            await call("render_sheet", names=figure, size=192)
            await call("render_view", target=figure, mode="ids", size=192, azimuth=0, elevation=0, fov=0, name="smoke_ref")
            await call("render_view", target=figure, mode="ids", size=192, azimuth=90, elevation=0, fov=0, name="smoke_side")
            await call("render_view", target=figure, mode="backfaces", size=128, name="smoke_back")
            front, side = str(RENDERS / "smoke_ref.png"), str(RENDERS / "smoke_side.png")
            fitted = await call("compare_view", reference=front, view="front", names=figure, size=192)
            if '"iou_outline": 0.9' not in fitted and '"iou_outline": 1.0' not in fitted:
                failures.append(f"the outline of itself should match: {fitted[:160]}")

            # from the reference images
            await call("prepare_reference", image=front, out=str(RENDERS / "smoke_prepared.png"))
            await call("measure_profile", reference=front, height_m=1.9, bands=8)
            await call("trace_outline", reference=front, height_m=1.9, simplify=0.02)
            await call("extrude_profile", name="smoke_prism", points=[[0, 0], [0.4, 0], [0.4, 1.0], [0, 1.0]], depth=0.2, at=[60, 0, 0])
            await call("loft_from_masks", name="smoke_lofted", front=front, side=side, height_m=1.9, bands=8, at=[62, 0, 0])
            await call("visual_hull", name="smoke_hull", front=front, side=side, height_m=1.9, at=[64, 0, 0])
            await call("compare_view", reference=front, view="front", names=figure, height_m=1.9, size=192, colors=2)
            await call("fit_to_reference", parts=["smoke_head"], references={"front": front}, height_m=1.9, names=figure, iterations=1, size=96, wait=150)
            jobs = await call("job_status")

            # mesh surgery, sculpt, hard surface
            await call("create_primitive", kind="cube", name="smoke_cube", size=[1, 1, 1], at=[70, 0, 0.5])
            await call("mesh_info", object="smoke_cube")
            await call("select_faces", object="smoke_cube", where={"normal": "+Z"})
            await call("extrude_faces", object="smoke_cube", where={"normal": "+Z"}, distance=0.4, scale=0.7)
            await call("inset_faces", object="smoke_cube", where={"normal": "+Z", "z": [1.2, None]}, thickness=0.05, depth=-0.03)
            await call("subdivide_faces", object="smoke_cube", where={"normal": "-Z"}, cuts=2)
            await call("bevel_edges", object="smoke_cube", width=0.03, segments=2, angle=60)
            await call("bisect", object="smoke_cube", axis="Z", at=0.3)
            await call("transform_region", object="smoke_cube", where={"normal": "+X"}, move=[0.1, 0, 0], falloff=0.3)
            await call("weld", object="smoke_cube", distance=0.0001)
            await call("delete_faces", object="smoke_cube", where={"normal": "-Z", "z": [None, 0.01]})
            await call("set_origin", names=["smoke_cube"], anchor=[0.5, 0.5, 0])
            await call("create_primitive", kind="plane", name="smoke_grid", size=[1, 1, 0.001], at=[72, 0, 0])
            await call("subdivide_faces", object="smoke_grid", where={}, cuts=9)
            await call("sculpt", object="smoke_grid", op="grab", at=[72, 0, 0], radius=0.4, move=[0, 0, 0.3])
            await call("sculpt", object="smoke_grid", op="inflate", amount=0.02, at=[72, 0, 0.1], radius=0.3)
            await call("sculpt", object="smoke_grid", op="smooth", iterations=2)
            await call("sculpt", object="smoke_grid", op="flatten", at=[72, 0, 0.1], radius=0.8, strength=0.5)
            await call("sculpt", object="smoke_grid", op="pinch", strength=0.1, where={})
            await call("create_primitive", kind="cube", name="smoke_bar", size=[0.2, 0.2, 2.0], at=[74, 0, 1.0])
            await call("subdivide_faces", object="smoke_bar", where={}, cuts=6)
            await call("deform", object="smoke_bar", kind="bend", amount=45, axis="X")
            await call("create_primitive", kind="sphere", name="smoke_ball", size=[1, 1, 1], at=[76, 0, 0.5], segments=16)
            await call("create_primitive", kind="plane", name="smoke_skin", size=[0.5, 0.5, 0.001], at=[76, 0, 1.0])
            await call("subdivide_faces", object="smoke_skin", where={}, cuts=6)
            await call("shrinkwrap", object="smoke_skin", target="smoke_ball")
            await call("create_primitive", kind="cube", name="smoke_rm", size=[1, 1, 1], at=[78, 0, 0.5])
            await call("remesh", object="smoke_rm", voxel_size=0.2)
            await call("decimate", object="smoke_rm", target_tris=100)
            await call("blob", name="smoke_blob", points=[[80, 0, 0.5], [80.3, 0, 0.5]], radii=[0.4, 0.4])
            await call("create_primitive", kind="cube", name="smoke_b1", size=[1, 1, 1], at=[82, 0, 0.5])
            await call("create_primitive", kind="cylinder", name="smoke_b2", size=[0.4, 0.4, 2], at=[82, 0, 0.5], segments=16)
            await call("boolean", a="smoke_b1", b="smoke_b2", operation="difference")
            await call("create_primitive", kind="cube", name="smoke_c1", size=[1, 1, 1], at=[84, 0, 0.5])
            await call("create_primitive", kind="cube", name="smoke_c2", size=[1, 1, 1], at=[85.5, 0, 0.5])
            await call("combine", names=["smoke_c1", "smoke_c2"], name="smoke_cc")
            await call("create_primitive", kind="cube", name="smoke_a1", size=[0.5, 0.5, 0.5], at=[88, 0, 0.25])
            await call("array", object="smoke_a1", count=3, offset=[0.8, 0, 0])
            await call("create_primitive", kind="cube", name="smoke_r1", size=[0.2, 0.2, 0.2], at=[93, 0, 0.1])
            await call("radial_array", object="smoke_r1", count=5, axis="Z", center=[92, 0, 0])
            await call("create_primitive", kind="plane", name="smoke_sol", size=[1, 1, 0.001], at=[96, 0, 0])
            await call("solidify", object="smoke_sol", thickness=0.1)
            await call("lathe", name="smoke_vase", profile=[[0, 0], [0.4, 0], [0.4, 0.6], [0, 0.8]], at=[98, 0, 0])
            await call("lathe", name="smoke_loop", profile=[[0.4, 0.0], [0.5, 0.1], [0.4, 0.2], [0.3, 0.1]], close=True, at=[102, 0, 0])
            await call("sweep", name="smoke_pipe", path=[[100, 0, 0], [100, 0, 1], [101, 0, 1.5]], radius=0.05)

            # rig and UV
            await call("create_primitive", kind="cylinder", name="smoke_rigmesh", size=[0.3, 0.3, 1.4], at=[110, 0, 0.7], segments=12)
            for height in (0.4, 0.8, 1.1):
                await call("bisect", object="smoke_rigmesh", axis="Z", at=height)
            await call("create_armature", name="smoke_rig", bones=[
                {"name": "root", "head": [110, 0, 0], "tail": [110, 0, 0.6]},
                {"name": "spine", "head": [110, 0, 0.6], "tail": [110, 0, 1.0], "parent": "root"},
                {"name": "head", "head": [110, 0, 1.0], "tail": [110, 0, 1.4], "parent": "spine"},
            ])
            await call("list_bones", armature="smoke_rig")
            await call("bind", meshes=["smoke_rigmesh"], armature="smoke_rig")
            await call("check_weights", mesh="smoke_rigmesh")
            await call("pose", armature="smoke_rig", pose={"spine": [30, 0, 0]})
            await call("pose_sheet", armature="smoke_rig", poses={"rest": {}, "lean": {"spine": [30, 0, 0]}}, meshes=["smoke_rigmesh"], view="side", size=96)
            await call("pose", armature="smoke_rig", pose={})
            await call("duplicate", name="smoke_rigmesh", new_name="smoke_rigcopy")
            await call("run_python", code="o = bpy.data.objects['smoke_rigcopy']; o.vertex_groups.clear(); o.modifiers.clear(); o.parent = None; o.matrix_world = bpy.data.objects['smoke_rigmesh'].matrix_world")
            await call("transfer_weights", target="smoke_rigcopy", donor="smoke_rigmesh", armature="smoke_rig")
            await call("unwrap", names=["smoke_rigmesh"], method="smart")
            if '"islands"' not in await call("check_mesh", name="smoke_rigmesh"):
                failures.append("check_mesh should report the UV map of an unwrapped mesh")
            await call("paint_faces", object="smoke_rigmesh", color="#ff8800", where={"normal": "+Z"})
            await call("palette_uv", object="smoke_rigmesh", cell=[1, 0], grid=[4, 4], where={"normal": "+Z"})


            # materials, camera, light, final render
            await call("set_material", names=["smoke_cube"], color="#ff8800", material="smoke_orange", roughness=0.4, metallic=0.2, coat=0.3, emission={"color": "#ff0000", "strength": 0.5})
            await call("list_materials")
            await call("list_materials", name="smoke_orange")
            await call("assign_material_faces", object="smoke_cube", material="smoke_orange", where={"normal": "+Z"})
            await call("dedupe_materials", tolerance=0.01)
            await call("set_camera", frame=figure, azimuth=30, elevation=15)
            await call("setup_lighting", preset="three_point", target=figure)
            await call("set_world", preset="studio_grey")
            await call("render_final", path=str(RENDERS / "smoke_final.png"), engine="workbench", size=160)
            await call("save_blend", path=str(TMP / "bl_mcp_smoke_copy.blend"))


            # organic shapes and terrain
            await call("terrain", name="smoke_terrain", size=[10, 10], resolution=1.0, height=1.5, at=[200, 0, 0], seed=2)
            await call("path_carve", terrain="smoke_terrain", points=[[196, 0], [204, 1]], width=1.5, depth=0.2)
            await call("rock", name="smoke_rock", radius=0.5, seed=4, detail=2, at=[210, 0, 0])
            await call("noise_displace", object="smoke_rock", amount=0.03, scale=0.5, seed=1)


            # transform, repair, lights, text, procedural, bake, reference camera
            await call("transform_objects", names=["smoke_cube"], rotate_deg=[0, 0, 45])
            await call("repair_mesh", object="smoke_cube")
            await call("add_light", kind="spot", name="smoke_spot", location=[0, -3, 3], look_at=[0, 3, 1])
            await call("list_lights")
            await call("set_post", vignette={"strength": 0.4, "softness": 0.5})
            await call("delete", names=["smoke_spot"])
            await call("text_mesh", text="SMOKE", size=0.2, at=[300, 0, 0])
            await call("procedural_material", names=["smoke_grid"], kind="wood")
            await call("bake_maps", object="smoke_grid", size=64, samples=1, out_dir=str(TMP / "bl_mcp_smoke_bake"))
            await call("overlay_reference", reference=front, camera="camera", names=figure, size=192)
            await call("pixel_to_world", camera="camera", pixels=[[96, 96]], image_size=[192, 192])
            await call("place_at_pixel", object="smoke_tree", camera="camera", pixel=[96, 150], image_size=[192, 192], plane_z=0)
            await call("match_camera", reference=front, names=figure, size=96, iterations=2, wait=200)

            # state, export
            await call("checkpoint", name="smoke")
            if '"smoke"' not in await call("rollback"):
                failures.append("rollback without a name should list the checkpoints")
            await call("run_python", code="smoke_value = 5", session="smoke")
            await call("run_python", code="print(smoke_value)", session="smoke")
            await call("export_glb", path=GLB, names=["smoke_torso"])
            await call("inspect_glb", path=GLB)
            await call("import_glb", path=GLB)
            await call("delete", names=["smoke_head_copy"])
            await call("diff_since", name="smoke")
            listed = json.loads(jobs)
            job_id = listed[-1]["job"] if listed else None
            if job_id:
                await call("job_status", job=job_id)
                await call("job_status", job=job_id, cancel=True)
            else:
                print("note: no job was listed; job_status with a job and with cancel is covered by the headless tests")

            await call("run_python", code=(
                f"keep = set({existing!r})\n"
                "for o in list(bpy.data.objects):\n"
                "    if o.name not in keep:\n"
                "        bpy.data.objects.remove(o)\n"
                "for block in before_data:\n"
                "    coll = getattr(bpy.data, block)\n"
                "    for item in [i for i in coll if i.name not in before_data[block] and i.users == 0]:\n"
                "        coll.remove(item)\n"
                "if 'bl_specs' in bpy.context.scene:\n"
                "    del bpy.context.scene['bl_specs']\n"
                "print(sorted(o.name for o in bpy.data.objects))"
            ), session="smoke")
            after = await call("scene_tree")
            if sorted(l.split(" [")[0].strip() for l in after.splitlines()) != sorted(existing):
                failures.append("scene was not restored")

            for prompt in sorted(prompts):
                shown = await session.get_prompt(prompt, {}) if prompt in {"review_model", "prepare_for_game"} else None
                print(f"ok   prompt {prompt}{' (rendered)' if shown else ''}")

    missing = sorted(tools - called)
    if missing:
        failures.append(f"tools never called: {missing}")
    print(f"\n{len(called)} of {len(tools)} tools called, {len(prompts)} prompts listed")
    print("FAILED:" if failures else "ALL PASSED", *failures, sep="\n" if failures else " ")
    sys.exit(1 if failures else 0)


asyncio.run(main())
