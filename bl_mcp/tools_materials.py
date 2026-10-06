from .app import call, mcp, text
from .tools_mesh import WHERE, tool_with


@mcp.tool()
def set_material(names: list[str], color: str | list[float], material: str | None = None, roughness: float = 0.8,
                 metallic: float = 0.0, alpha: float = 1.0, emission: dict | None = None, coat: float = 0.0,
                 subsurface: float = 0.0, texture: str | None = None, normal_map: str | None = None,
                 bump: dict | None = None, roughness_map: str | None = None, metallic_map: str | None = None,
                 orm_map: str | None = None, transmission: float = 0.0) -> str:
    """Create or rebuild a material (Principled BSDF, exports to glTF) and put it on whole meshes. The quick form is `names` and `color`: '#rrggbb' or
    [r, g, b] in 0..1. Without `material` the name comes from the numbers, so equal parameters reuse one material
    (fewer draw calls); an existing name is rebuilt. Slot 0 gets it: use assign_material_faces for parts of a mesh.
    alpha below 1 is glTF BLEND: glass only, transparent faces cost sorting. emission is {"color": "#ffcc66",
    "strength": 2.0}. coat is a clear layer. transmission 1 is clear glass (refracting, Cycles and
    KHR_materials_transmission; use alpha for cheap glass). subsurface does not reach glTF.
    Image paths (the meshes need a UV map: unwrap or palette_uv first): texture (base colour; `color` then tints
    it, '#ffffff' keeps it; alpha multiplies its alpha), normal_map (tangent space), roughness_map and metallic_map
    (grey), or orm_map instead of those two (R occlusion, G roughness, B metallic). A map replaces its number.
    bump {"scale": 20, "strength": 0.3} is a procedural noise for renders only: bake_maps turns it into a normal map.
    The answer has `gltf`: alphaMode, the factors and the texture slots that will be written. For patterns (wood,
    bricks, worn metal) use procedural_material."""
    return text(call("set_material", names=names, color=color, material=material, roughness=roughness, metallic=metallic,
                     alpha=alpha, emission=emission, coat=coat, subsurface=subsurface, texture=texture, normal_map=normal_map, bump=bump, transmission=transmission,
                     roughness_map=roughness_map, metallic_map=metallic_map, orm_map=orm_map))


@mcp.tool()
def list_materials(name: str | None = None) -> str:
    """Every material: name, colour, number of users, whether it has a texture and which procedural nodes it has.
    Procedural nodes (noise, gradients, math) are not exported to glTF: `not_exported` marks those materials.
    `faces_without_material` counts, per object, the faces that sit in an empty slot or have no slot. Fix them with
    assign_material_faces. Use it to find look-alikes before dedupe_materials.
    With `name` the answer is the card of that one material: colour, roughness, metallic, alpha, emission, coat,
    subsurface, the paths of its texture and maps (and the normal map colour space, which must be Non-Color),
    procedural nodes, users and `faces` per object. `alpha_mode` is the glTF alphaMode that export_glb writes (OPAQUE,
    BLEND or MASK); `render_method` is the EEVEE draw mode (DITHERED is the normal one for opaque)."""
    return text(call("list_materials", name=name))


@tool_with(WHERE)
def assign_material_faces(object: str, material: str, where: dict | None = None) -> str:
    """Put an existing material on part of a mesh: the picked faces get it, the other faces keep theirs. Adds a slot if the object has none for it.
    Other faces keep their material. One mesh with several materials costs one draw call per material in the engine, so keep
    the count low. Create the material first with set_material."""
    return text(call("assign_material_faces", object=object, material=material, where=where))


@mcp.tool()
def dedupe_materials(tolerance: float = 0.01, names: list[str] | None = None, clean_slots: bool = True,
                     remove_orphans: bool = True) -> str:
    """Merge materials that look the same: same colour, roughness, metallic, alpha, emission, coat and same textures,
    each within `tolerance` (0.01 means 1 percent). Users move to the first material of each group, the extras are deleted,
    and slots that now repeat inside a mesh are joined. Fewer materials means fewer draw calls. `names` limits the check.
    Returns how many were removed and the material count before and after. Textured and procedural materials only merge
    when their images and node types are the same.
    It also cleans up, on every mesh: clean_slots=true removes empty slots and slots that no face uses
    (`empty_slots_removed`, `unused_slots_removed`); remove_orphans=true deletes materials with zero users (`orphans_removed`).
    An empty slot that faces still point at is kept and listed in `faces_without_material`: assign those faces first.
    tolerance=0 merges only exact copies."""
    return text(call("dedupe_materials", tolerance=tolerance, names=names, clean_slots=clean_slots, remove_orphans=remove_orphans))
