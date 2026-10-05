from typing import Literal

from .app import call, mcp, sheet, text


@mcp.tool()
def create_armature(name: str, bones: list[dict]) -> str:
    """Make a skeleton from numbers. `bones` is a list of {"name", "head": [x,y,z], "tail": [x,y,z], "parent": name (optional),
    "connect": bool (optional)} in world metres; list parents before children. For a biped: root, spine, chest, neck,
    head, and arms and legs with L/R suffixes. Then bind a mesh with bind, and test with pose."""
    return text(call("create_armature", name=name, bones=bones))


@mcp.tool()
def list_bones(armature: str) -> str:
    """Bones of an armature with parent, world head and tail, length."""
    return text(call("list_bones", armature=armature))


@mcp.tool()
def bind(meshes: list[str], armature: str, method: Literal["proximity", "auto"] = "proximity", max_influences: int = 4, falloff: float = 2.0) -> str:
    """Skin meshes to an armature: adds one vertex group per bone, the Armature modifier and the parent. method
    'proximity' weights each vertex by its distance to the nearest bones (up to max_influences, power `falloff`; fast,
    works on any mesh, good for stylised low-poly); 'auto' uses Blender's heat-map weights and falls back to
    proximity when the mesh is not clean. Existing groups with the same names are overwritten. Check with
    check_weights, then try poses with pose_sheet."""
    return text(call("bind", meshes=meshes, armature=armature, method=method, max_influences=max_influences, falloff=falloff))


@mcp.tool()
def transfer_weights(target: str, donor: str, armature: str | None = None) -> str:
    """Copy skin weights from a skinned mesh to another mesh by nearest vertex (same rig for clothes, hair, a new
    character body). Both meshes should stand in the same place. The Armature modifier is set up too."""
    return text(call("transfer_weights", target=target, donor=donor, armature=armature))


@mcp.tool()
def check_weights(mesh: str, max_influences: int = 4) -> str:
    """Skin quality: vertices without weight, with more than `max_influences` bones (glTF wants 4), weights that do not
    sum to 1, groups that match no bone, a missing Armature modifier."""
    return text(call("check_weights", mesh=mesh, max_influences=max_influences))


@mcp.tool()
def pose(armature: str, pose: dict | None = None, reset: bool = True) -> str:
    """Pose bones by numbers: {"bone": [rx, ry, rz]} in degrees (Euler XYZ, local to the bone), or {"bone": {"rot": [..],
    "loc": [..], "scale": [..]}}. reset=true clears all other bones first. An empty pose returns to rest. A bone along
    Z bends forward when rotated about X."""
    return text(call("pose", armature=armature, pose=pose or {}, reset=reset))


@mcp.tool()
def pose_sheet(armature: str, poses: dict, meshes: list[str] | None = None, view: Literal["front", "back", "side", "top", "iso"] = "front", size: int = 256) -> list:
    """One image with the mesh in several poses side by side, left to right in the order given: {"rest": {}, "walk":
    {"thigh_L": [30,0,0]}}. Use it to see joints bend, find tearing and collapsing, and compare with check_weights.
    The rest pose is restored afterwards."""
    return sheet(call("pose_sheet", armature=armature, poses=poses, meshes=meshes, view=view, size=size))


@mcp.tool()
def unwrap(names: list[str], method: Literal["smart", "angle", "conformal", "cube", "cylinder", "sphere"] = "smart", angle: float = 66.0, margin: float = 0.02, pack: bool = True) -> str:
    """Make a UV map. Method smart is Smart UV Project (a larger `angle` gives fewer, larger islands); angle is
    angle-based unwrap; cube, cylinder and sphere are projections. margin is the gap between islands (0..1); pack
    arranges the islands in the 0..1 square. Returns the UV numbers of each mesh: islands, used area, faces outside
    0..1, degenerate faces and texel_density_spread (1 is even, above 4 is stretched). check_mesh gives the same
    numbers for an existing UV map."""
    return text(call("unwrap", names=names, method=method, angle=angle, margin=margin, pack=pack))


@mcp.tool()
def paint_faces(object: str, color: str | list[float], where: dict | None = None, attribute: str = "Color") -> str:
    """Paint vertex colour on the picked faces (see select_faces for `where`: normal, x/y/z ranges, box, area, index).
    Colour is '#rrggbb' or [r,g,b]. For stylised models that use vertex colours instead of textures."""
    return text(call("paint_faces", object=object, color=color, where=where, attribute=attribute))


@mcp.tool()
def palette_uv(object: str, cell: list[int], grid: list[int] = (4, 4), where: dict | None = None, uv_layer: str = "UVMap") -> str:
    """Point the UVs of the picked faces at the centre of one cell of a palette texture, so the face takes that flat
    colour: cell [column, row] with row 0 at the top, grid [columns, rows]. For palette-atlas styles (one small colour
    grid image shared by all models)."""
    return text(call("palette_uv", object=object, cell=cell, grid=list(grid), where=where, uv_layer=uv_layer))
