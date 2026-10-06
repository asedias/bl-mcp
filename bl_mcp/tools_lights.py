from typing import Literal

from .app import Vec3, call, mcp
from .app import text as as_text


@mcp.tool()
def add_light(kind: Literal["spot", "point", "area", "sun"] | None = None, name: str = "light", location: Vec3 | None = None,
              look_at: Vec3 | None = None, power_w: float | None = None, color: str | list[float] | None = None, spot_size_deg: float | None = None,
              blend: float | None = None, radius: float | None = None, size: float | list[float] | None = None, shadow_soft: bool | None = None,
              temperature_k: float | None = None, cutoff_m: float | None = None) -> str:
    """Create or update one light you control (setup_lighting makes a whole preset instead). The same `name` updates
    that light and keeps every setting you omit; it never makes a copy. A new light is a spot of 1000 W. spot is a cone, point shines all ways, area is a panel, sun gives parallel rays.
    `location` is in world metres; `look_at` is the point a spot, area or sun aims at. A new light without them sits
    at [0, 0, 3] and points down.
    `power_w` is watts; for a sun it is W/m2 (1-5, about 3 is a normal day). A point or spot needs about 40 W at
    1 m, 150 W at 2 m, 600 W at 4 m for a normal exposure; an area panel a third of that.
    `color` is '#rrggbb' or linear [r, g, b]; `temperature_k` (800-20000) multiplies it with a blackbody tint.
    Spot: `spot_size_deg` is the full cone angle (1-180), `blend` (0-1) softens its edge. `cutoff_m` stops a spot or
    point hard at that distance.
    `radius` (spot, point) is the source size in metres: bigger means softer shadows. `size` (area) is [width, height]
    in metres or one number for a square (1 m when empty). shadow_soft=false makes hard shadows.
    Names that start with bl_light_ belong to setup_lighting and are refused. Remove lights with delete."""
    return as_text(call("add_light", kind=kind, name=name, location=location and list(location), look_at=look_at and list(look_at),
                     power_w=power_w, color=color, spot_size_deg=spot_size_deg, blend=blend, radius=radius, size=size,
                     shadow_soft=shadow_soft, temperature_k=temperature_k, cutoff_m=cutoff_m))


@mcp.tool()
def list_lights() -> str:
    """List every light in the scene: name, kind, place, aim (`direction`), power, colour and the kind's settings.
    `preset` is true for the bl_light_* lights that setup_lighting makes. Remove lights with delete (names, prefix
    or lights)."""
    return as_text(call("list_lights"))


@mcp.tool()
def set_post(vignette: dict | None = None, glare: dict | None = None, color: dict | None = None, exposure: float | None = None,
             contrast: float | None = None, reset: bool = False) -> str:
    """Set post-processing for render_final: vignette, glare, colour, exposure, contrast. It builds a compositor tree,
    works with every engine and is not shown in the viewport. A call changes only what you pass and keeps the rest.
    Pass false to switch one effect off (vignette=false); reset=true removes everything this tool set.
    `vignette` {"strength": 0-1 (how dark the corners get), "softness": 0-1 (how far in the fade starts)}; both
    start at 0.5. The darkening is an ellipse that follows the picture shape.
    `glare` {"type": "bloom" | "fog_glow" | "streaks", "threshold": 1.0 (how bright a pixel must be to glow; lower
    = more glow), "size": 1-9 (8 when empty)}. It needs pixels above 1: strong lights or emission.
    `color` {"saturation": 1.0 (0 = grey), "gamma": 1.0 (above 1 brightens the mid-tones)}.
    `exposure` is in stops (+1 doubles the light). `contrast` is -1 to 1.
    It refuses to replace a compositor tree it did not make. Returns the active settings."""
    return as_text(call("set_post", vignette=vignette, glare=glare, color=color, exposure=exposure, contrast=contrast, reset=reset))


@mcp.tool()
def text_mesh(text: str, size: float = 0.1, depth: float = 0.01, at: Vec3 | None = None, plane: Literal["XZ", "XY", "YZ"] = "XZ",
              font: str | None = None, align: Literal["center", "left", "right"] = "center", bevel: float = 0.0, name: str = "text",
              on_object: str | None = None, offset: float = 0.0005, engrave: bool = False) -> str:
    """Make a text label as a closed mesh, or engrave text into a mesh. `size` is the height of a capital letter and
    `depth` the thickness, in metres. `\\n` starts a new line.
    `plane`: XZ stands upright and reads from the front (-Y), XY lies flat and reads from above, YZ stands and reads
    from +X. The back face is on the plane.
    `at` is the anchor in the world (the origin when empty) and the object origin; `align` puts the middle, the left
    end or the right end of the text there; vertically the text is centred.
    `font` is a path to a .ttf or .otf file. The built-in font has Latin and Cyrillic; a font without a glyph shows
    nothing for that character. `bevel` rounds the edges (0 to depth/2). The same `name` replaces the earlier text.
    `on_object` (a mesh) puts the text on its surface: a ray through `at` along the plane normal finds the first hit,
    and the text lands `offset` metres above it (a decal that does not z-fight). The text stays flat: use it on flat
    or nearly flat surfaces.
    engrave=true cuts the letters `depth` deep into on_object instead, with the checks and clean-up of boolean; no
    text object stays and `bevel` is ignored. The mesh must be closed. The answer has the volume before and after."""
    return as_text(call("text_mesh", text=text, size=size, depth=depth, at=at and list(at), plane=plane, font=font, align=align,
                            bevel=bevel, name=name, on_object=on_object, offset=offset, engrave=engrave))
