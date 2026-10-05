from .app import mcp
from .tools_recipes import recipe_text


def task(goal, topic):
    return f"{goal}\n\n{recipe_text(topic)}"


@mcp.prompt()
def model_from_reference(reference_image: str, subject: str, height_m: float = 1.0) -> str:
    """Build a character or creature that matches front and side reference images."""
    return task(f"Build {subject} (height {height_m} m) to match the image {reference_image}. Follow this recipe.", "character-from-reference")


@mcp.prompt()
def hard_surface_prop(subject: str, size_m: str) -> str:
    """Build a hard-surface prop from known dimensions."""
    return task(f"Build {subject} with the size {size_m} (metres, X Y Z). Follow this recipe.", "prop-hard-surface")


@mcp.prompt()
def weapon_from_sheet(sheet_image: str, subject: str, length_m: float) -> str:
    """Build a weapon or another flat object from an orthographic sheet with several panels."""
    return task(f"Build {subject} (length {length_m} m) from the sheet {sheet_image}. Follow this recipe.", "weapon-from-sheet")


@mcp.prompt()
def scene_from_photo(photo: str, description: str) -> str:
    """Build a scene that matches one perspective photo."""
    return task(f"Build this scene to match the photo {photo}: {description}. Follow this recipe.", "scene-from-photo")


@mcp.prompt()
def blockout_level(description: str, player_height_m: float = 1.8) -> str:
    """Block out a level and prove it by measurements."""
    return task(f"Block out this level: {description}. The player is {player_height_m} m high. Follow this recipe.", "level-blockout")


@mcp.prompt()
def materials_and_render(names: str = "", image_path: str = "render.png") -> str:
    """Give a finished model its materials and make a final render."""
    target = f"the objects {names}" if names else "everything visible"
    return task(f"Give {target} materials that reach glTF, then render to {image_path}. Follow this recipe.", "materials-and-render")


@mcp.prompt()
def prepare_for_game(names: str = "", max_tris: int = 5000) -> str:
    """Take a model to an exportable, budgeted state."""
    target = f"the objects {names}" if names else "everything visible"
    return task(f"Prepare {target} for a game (budget {max_tris} triangles). Follow this recipe.", "export-for-game")


@mcp.prompt()
def review_model(names: str = "") -> str:
    """Audit an existing model and report what is wrong."""
    target = f"the objects {names}" if names else "the whole scene"
    return task(
        f"Audit {target}. Do not change anything: run only the checks of this recipe and skip the steps that change the scene. "
        "Report the problems with numbers, worst first, and the step that fixes each.",
        "export-for-game",
    )
