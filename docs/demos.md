# Demos and where the tools come from

bl-mcp was not designed as a tool catalogue. It grew while an agent built real game assets in Blender: a character from front and side references, props, a pistol from an orthographic sheet, level blockouts for a game. Each round went the same way: an agent session, a report of where it fell back to raw Python, where a tool lied by omission and where the result was wrong without anyone noticing. Then the tools were changed and the next session ran against them. The recipes are the distilled logs of those sessions, traps included.

Every tool has a headless test of its handler and a smoke call through the real MCP server, and the server refuses to start when a tool has no toolset. Tools that no session needed were merged or removed.

## The lantern

![A brass lantern built by an agent with the tools: Cycles render](img/final.png)

| `render_sheet`: the overview the agent gets after each step | `compare_view`: reference, model, overlay, difference |
|---|---|
| ![render_sheet](img/sheet.png) | ![compare_view](img/compare.png) |

What the agent reads instead of a screenshot:

```
bevel_edges {"object": "lamp_base", "width": 0.002, "segments": 2}
{"bevelled": 480, "width": 0.002, "achieved_width": {"min": 0.002, "median": 0.002}, "clamped": 0, "tris": 2880}

find_floating {"names": [...9 parts], "ground_z": 0}
{"parts": 9, "connected_groups": 1, "floating": ["none"], "tiny_gaps": ["none"]}

compare_view {"reference": "lantern_front.png", "view": "front", "height_m": 0.301}
{"iou_registered": 0.8144, "worst_bands": [{"z0": 0, "z1": 0.025, "model_width": 0.196, "reference_width": 0.17, "delta_pct": 15.3, "verdict": "model wider"}]}
```

How to read it: the model's base was made 15 % too wide on purpose for this picture. A finished part reads 0.95 or more at this size; the band table says which height range is off, by how many metres and in which direction, so the next call is `set_dimensions` on that part, not a guess.

The lantern above was built, textured, lit and rendered by Claude Fable 5.1 through these tools in one session: 163 model calls, 106 tool calls, 18 k output tokens. The first version had a handle 3 mm above its pivots; `find_floating` now catches that before the render. The script is `tests/readme_images.py`, the scene is `demo/lantern.blend`.
