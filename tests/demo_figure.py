"""Builds a small figure in the open Blender through the MCP server, checks it, renders it and removes it.

Needs Blender open with the add-on enabled. Run: uv run python tests/demo_figure.py
"""

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PARTS = ["fig_torso", "fig_head", "fig_arm_L", "fig_arm_R", "fig_leg_L", "fig_leg_R", "fig_foot_L", "fig_foot_R"]


async def main():
    params = StdioServerParameters(command="uv", args=["run", "--project", ".", "bl-mcp"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, /, **args):
                result = await session.call_tool(tool, args)
                text = "\n".join(c.text for c in result.content if c.type == "text")
                print(f"--- {tool}{' ERROR' if result.isError else ''}\n{text[:700]}")
                return text

            await call("loft", name="fig_torso", axis="Z", segments=20, sections=[
                {"at": [0, 0, 0.85], "size": [0.34, 0.2], "roundness": 3},
                {"at": [0, 0, 1.1], "size": [0.4, 0.22], "roundness": 3},
                {"at": [0, 0, 1.4], "size": [0.46, 0.24], "roundness": 2.6},
                {"at": [0, 0, 1.55], "size": [0.3, 0.18]},
            ])
            await call("create_primitive", kind="sphere", name="fig_head", size=[0.26, 0.28, 0.3], at=[0, 0, 1.55], anchor=[0.5, 0.5, 0], segments=24)
            await call("limb", name="fig_arm_L", points=[[0.26, 0, 1.45], [0.36, 0, 1.15], [0.38, 0, 0.88]], radii=[0.06, 0.05, 0.04])
            await call("mirror", name="fig_arm_L", axis="X", at=0)
            await call("limb", name="fig_leg_L", points=[[0.1, 0, 0.85], [0.11, 0, 0.45], [0.11, 0, 0.08]], radii=[0.085, 0.065, 0.05])
            await call("mirror", name="fig_leg_L", axis="X", at=0)
            await call("create_primitive", kind="cube", name="fig_foot_L", size=[0.11, 0.26, 0.08], at=[0.11, 0.05, 0], anchor=[0.5, 0.5, 0])
            await call("mirror", name="fig_foot_L", axis="X", at=0)
            await call("set_material", names=["fig_torso", "fig_arm_L", "fig_arm_R"], color="#3b6fd8")
            await call("set_material", names=["fig_leg_L", "fig_leg_R", "fig_foot_L", "fig_foot_R"], color="#2b2b3a")
            await call("set_material", names=["fig_head"], color="#f0c8a0")

            await call("measure", names=["fig_torso", "fig_head"])
            await call("check_symmetry", names=["fig_arm_L", "fig_arm_R"], axis="X", at=0)
            await call("check_symmetry", names=PARTS, axis="X", at=0)
            await call("check_contacts", a="fig_torso", b="fig_head")
            await call("check_contacts", a="fig_torso", b="fig_arm_L")
            await call("check_contacts", a="fig_leg_L", b="fig_foot_L")
            await call("find_floating", names=PARTS, ground_z=0.0)
            await call("move_to_contact", a="fig_leg_L", to="fig_torso", axis="Z", depth=0.01)
            await call("move_to_contact", a="fig_leg_R", to="fig_torso", axis="Z", depth=0.01)
            await call("move_to_contact", a="fig_foot_L", to="fig_leg_L", axis="Z", depth=0.01)
            await call("move_to_contact", a="fig_foot_R", to="fig_leg_R", axis="Z", depth=0.01)
            await call("move_to_contact", a="fig_head", to="fig_torso", depth=0.02)
            for part in PARTS[1:]:
                await call("parent", child=part, to="fig_torso")
            await call("ground", names=["fig_torso"])
            await call("find_floating", names=PARTS, ground_z=0.0)
            await call("assert_spec", checks=[
                {"type": "size", "object": "fig_head", "axis": "z", "min": 0.22, "max": 0.35, "label": "head height"},
                {"type": "ratio", "a": "fig_head", "b": "fig_torso", "axis": "z", "min": 0.35, "max": 0.55, "label": "head to torso"},
                {"type": "contact", "a": "fig_head", "b": "fig_torso", "state": "intersecting", "max_depth": 0.03},
                {"type": "contact", "a": "fig_arm_L", "b": "fig_torso", "state": "connected"},
                {"type": "symmetry", "objects": PARTS, "axis": "X", "at": 0},
                {"type": "on_ground", "object": "fig_torso"},
                {"type": "connected", "names": PARTS, "ground_z": 0.0},
                {"type": "budget", "names": PARTS, "max_tris": 6000},
            ])
            await call("render_view", target=["fig_head", "fig_torso"], azimuth=25, elevation=12, mode="clay", name="demo_neck")
            await call("render_view", target=PARTS, azimuth=0, elevation=0, fov=0, mode="wire", name="demo_wire")
            await call("render_view", target=PARTS, azimuth=40, elevation=15, mode="ids", name="demo_ids")
            await call("check_mesh", name="fig_torso")
            await call("check_game_ready", names=PARTS, max_tris=3000, budget_only=True)
            await call("render_sheet", names=PARTS, size=384, views=["front", "side", "top", "iso"])

            if "--keep" not in __import__("sys").argv:
                await call("delete", names=PARTS)


asyncio.run(main())
