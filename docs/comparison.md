# How it compares

Facts from the projects' own READMEs and tool lists, read on 2026-10-06. Corrections welcome.

| | bl-mcp | [mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) (ahujasid) | [Blender Lab MCP](https://projects.blender.org/lab/blender_mcp) | [blender-ai-mcp](https://github.com/PatrykIti/blender-ai-mcp) (PatrykIti) |
|---|---|---|---|---|
| How the agent acts | typed tools; `run_python` as the last resort | writes Blender Python (`execute_blender_code`) | Blender Python plus read-only tools | typed tools; Python only in a read-only code mode |
| Tools | 113 in 7 toolsets | 9 | 27 | about 190, a small profile by default |
| Numbers about geometry | `measure`, `check_mesh`, `check_symmetry`, `assert_spec` | no | no | `scene_measure_*`, `scene_assert_dimensions` |
| Comparison with a reference | silhouette IoU per view, band table, overlay, auto fit, camera matching | no | no | reference checkpoints scored by a vision model, silhouette metrics |
| Mesh safety | `boolean` and `weld` check their result and refuse to open a mesh; `repair_mesh` | no | no | `mesh_inspect`; no refusal stated |
| Export for games | `check_game_ready`, GLB export with texture limit, `inspect_glb` | no | no | `export_glb`, `import_glb`, FBX, OBJ |
| Asset libraries, AI generation | no | Poly Haven, Sketchfab, Poly Pizza, Tripo, Hyper3D, Hunyuan3D | no | no |
| Long operations | background jobs inside Blender | not stated | a second Blender process, synchronous | async wrappers |
| Workflow knowledge | `recipe` tool and prompts | no | API and manual search tools | goal router |
| Blender | 5.0+ | 3.0+ | 5.1+ | 4.0+ |
| License | MIT | MIT | GPL-3.0-or-later | Apache-2.0 |
| Telemetry | none | anonymous usage on by default, content opt-in | none stated | none stated |

Pick mcp-for-blender when you want asset search and model generation with the least set-up. Pick Blender Lab when you want the official add-on and documentation search. Pick bl-mcp when the agent must build to measure and ship a clean mesh.
