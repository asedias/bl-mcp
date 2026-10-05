from typing import Literal

from .app import call, call_waiting, mcp, text


@mcp.tool()
def procedural_material(names: list[str], kind: Literal["wood", "checker", "diamond", "bricks", "noise", "marble", "worn_metal"],
                        color_a: str | None = None, color_b: str | None = None, scale: float = 1.0, roughness: float | None = None,
                        material: str | None = None, seed: int = 0, params: dict | None = None) -> str:
    """Give meshes a procedural node material for renders. It does NOT reach glTF: run bake_maps afterwards to turn
    it into images. Kinds: wood (rings, fibres, knots), checker, diamond (knurled bump), bricks (with mortar), noise
    (mottled), marble (veins), worn_metal (used steel: dirt in cavities, bright edges, scratches, rounded edges).
    color_a is the main colour, color_b the second (dark grain, mortar, veins, dirt), both '#rrggbb'; each kind has
    its own when empty. `scale` is the pattern frequency; `seed` shifts the pattern. `roughness` is 0-1; for
    worn_metal it is the clean metal, dirt and scratches add to it.
    Patterns lie on the UV map (a mesh without one is unwrapped with smart project and listed in `unwrapped`), so
    their size follows the UV islands. worn_metal works in object space instead: no seams, sizes follow the object.
    Its dirt, edge wear and rounding use ray-traced nodes: seen in cycles and bake_maps, not in eevee, and neighbour
    objects darken the cavities, so build the model first.
    `params` (optional): bump_strength; wood: grain_stretch (6), knots (true), distortion; marble: distortion;
    bricks: mortar (0.03); noise: detail_scale; worn_metal: dirt (0.6), edge_wear (0.5), scratches (0.3), metallic
    (1.0), and in metres bevel_radius, wear_width, ao_distance.
    The same `material` name rebuilds it. Slot 0 of each mesh gets it. For a plain colour or image maps use
    set_material."""
    return text(call("procedural_material", names=names, kind=kind, color_a=color_a, color_b=color_b, scale=scale,
                     roughness=roughness, material=material, seed=seed, params=params))


@mcp.tool()
def bake_maps(object: str, size: int = 1024,
              maps: list[Literal["base_color", "normal", "roughness", "metallic", "ao", "orm"]] | None = None,
              out_dir: str | None = None, margin: int = 8, samples: int = 16, replace_material: bool = True,
              uv_layer: str | None = None, bevel_radius: float | None = None, wait: float = 100.0) -> str:
    """Bake the material of one mesh into PNG maps on its UV, so glTF can carry a procedural or layered material.
    Uses Cycles on the CPU. `maps`: base_color (sRGB), normal (tangent space), roughness, metallic, ao, orm (one
    image: R occlusion, G roughness, B metallic). Empty means base_color, normal, roughness, ao. For a metal ask
    for base_color, normal, orm.
    Files are <object>_<map>.png in `out_dir` (the work folder, bakes/, when empty). `size` is pixels, a power of
    two: 512-1024 for props, 2048 for a hero asset. `margin` is the pixel padding around UV islands. `samples`: 16
    is enough for colour and normal, raise it for a clean ao.
    `bevel_radius` (metres, about 0.2-0.5% of the object size) rounds hard edges in the normal map only; it needs a
    material without an image normal map.
    The mesh needs a UV map without overlaps (check_mesh reports the UV); without one it is unwrapped with smart
    project. `uv_layer` picks another layer. A material without bump gives a flat normal map and the answer says so.
    replace_material=true builds the Principled material `<object>_baked` from the images and puts it on the mesh,
    so export_glb writes the textures. ao alone stays a file; inside orm it becomes occlusionTexture.
    One call bakes one object. Background job, one map per step (a 2048 px map takes 20-60 s): after `wait` seconds
    the answer is a job id for job_status (cancel=true stops it). Do not edit the object while it runs."""
    return text(call_waiting("bake_maps", wait=wait, object=object, size=size, maps=maps or ["base_color", "normal", "roughness", "ao"],
                             out_dir=out_dir, margin=margin, samples=samples, replace_material=replace_material, uv_layer=uv_layer,
                             bevel_radius=bevel_radius, background=True))
