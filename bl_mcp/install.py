"""Puts the add-on into the Blender of this machine and enables it: bl-mcp-install-addon [--link] [--blender PATH]."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from .locate import find_blender

ADDON = Path(__file__).resolve().parent.parent / "addon" / "bl_bridge"
ASK_FOLDER = "import bpy; print('ADDONS=' + bpy.utils.user_resource('SCRIPTS', path='addons', create=True))"
ENABLE = "import bpy; bpy.ops.preferences.addon_enable(module='bl_bridge'); bpy.ops.wm.save_userpref(); print('ENABLED')"


def blender_says(blender, expression):
    # No --factory-startup: save_userpref would write factory preferences over the user's own.
    run = subprocess.run([blender, "-b", "--python-expr", expression], capture_output=True, text=True, timeout=120)
    return run.stdout + run.stderr


def main():
    parser = argparse.ArgumentParser(description="Copy (or link) addon/bl_bridge into the add-ons folder of Blender and enable it.")
    parser.add_argument("--blender", help="path to the Blender executable; found by itself when omitted")
    parser.add_argument("--link", action="store_true", help="symlink the folder instead of copying, so a git pull updates the add-on")
    args = parser.parse_args()
    blender = args.blender or find_blender()
    if blender is None:
        sys.exit("Blender not found. Pass --blender PATH, or install Blender in a standard folder.")
    if not ADDON.is_dir():
        sys.exit(f"The add-on folder is missing: {ADDON}. Run this from a clone of the repository.")
    out = blender_says(blender, ASK_FOLDER)
    folder = next((line.split("=", 1)[1].strip() for line in out.splitlines() if line.startswith("ADDONS=")), None)
    if folder is None:
        sys.exit(f"Blender did not report its add-ons folder:\n{out[-800:]}")
    target = Path(folder) / "bl_bridge"
    if target.is_symlink() or target.exists():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    if args.link:
        target.symlink_to(ADDON, target_is_directory=True)
    else:
        shutil.copytree(ADDON, target, ignore=shutil.ignore_patterns("__pycache__"))
    out = blender_says(blender, ENABLE)
    if "ENABLED" not in out:
        sys.exit(f"Copied to {target}, but Blender could not enable it:\n{out[-800:]}")
    print(f"{'Linked' if args.link else 'Copied'} {ADDON} -> {target}")
    print(f"Enabled BL MCP Bridge in {blender}. Restart Blender if it is open: an open Blender keeps its own preferences.")


if __name__ == "__main__":
    main()
