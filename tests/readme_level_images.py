"""Pictures of the demo level blockout for the docs. Run: "$(uv run bl-mcp-find-blender)" -b --python tests/readme_level_images.py

Opens docs/demo/blockout.blend and writes docs/img/level_*.png through the handlers.
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("BL_MCP_WORK", str(Path(tempfile.gettempdir()) / "bl_mcp_readme_level"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy  # noqa: E402

from _harness import call, expect, finish  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img"
LIMIT = 400_000
T_SPAWN, A_SITE = [0, -38, 1.6], [24, 0, 1.6]


def shrink(path):
    while path.stat().st_size > LIMIT:
        image = bpy.data.images.load(str(path))
        image.scale(round(image.size[0] * 0.85), round(image.size[1] * 0.85))
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
    print(f"{path.name}: {path.stat().st_size // 1024} KB")


def keep(source, name):
    target = OUT / name
    target.write_bytes(Path(source).read_bytes())
    shrink(target)


bpy.ops.wm.open_mainfile(filepath=str(ROOT / "docs" / "demo" / "blockout.blend"))
OUT.mkdir(parents=True, exist_ok=True)

overview = call("render_view", {"azimuth": 35, "elevation": 42, "fov": 40, "size": 1100, "margin": 0.8, "mode": "solid", "name": "level_overview"})
keep(overview["path"], "level_overview.png")

walk = call("walkable_map", {"start": T_SPAWN, "probe": [T_SPAWN, A_SITE, [0, 0, 1.2]]})
expect("the whole floor is one reachable region", walk["largest_regions"][0]["reachable"], walk["largest_regions"])
keep(walk["image"], "level_walkable.png")

sight = call("sightline_map", {"cell": 0.75, "long_sightline": 60, "start": T_SPAWN})
keep(sight["image"], "level_sightlines.png")

eye = call("render_view", {"eye": T_SPAWN, "look_at": [12, -30, 1.2], "fov": 80, "size": 900, "isolate": False, "name": "level_eye"})
keep(eye["path"], "level_eye.png")

route = call("route", {"start": T_SPAWN, "end": A_SITE, "min_width": 3})
expect("T spawn reaches site A with 3 m of width", route["reachable"] and route["narrowest_m"] >= 3, route)
(OUT / "level_numbers.txt").write_text(
    "walkable_map probes: " + str(walk["probes"]) + "\n"
    + f"route T spawn -> A: length {route['length_m']} m, straight {route['straight_line_m']} m, narrowest {route['narrowest_m']} m at {route['narrowest_at']}\n"
    + f"sightline_map: {sight.get('area_with_a_sightline_over_60_m_m2')} m2 with a sightline over 60 m, mean {sight.get('mean_sightline_m')} m\n"
)
finish()
