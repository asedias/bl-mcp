from . import prompts, tools_core, tools_level, tools_lights, tools_materials, tools_mesh, tools_organic, tools_procedural, tools_recipes, tools_reference, tools_refcam, tools_render, tools_rig  # noqa: F401
from . import toolsets
from .app import mcp

MODULES = [tools_core, tools_reference, tools_mesh, tools_rig, tools_level, tools_materials, tools_render, tools_organic, tools_procedural, tools_lights, tools_refcam, tools_recipes, prompts]

toolsets.apply(mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
