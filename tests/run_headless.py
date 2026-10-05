"""Finds Blender by itself and runs the handler tests without a window.

uv run python tests/run_headless.py                  every tests/headless.py and tests/test_*.py
uv run python tests/run_headless.py tests/test_x.py  one file
"""

import subprocess
import sys
from pathlib import Path

from bl_mcp.locate import find_blender

blender = find_blender()
if blender is None:
    sys.exit("Blender not found. Open Blender, or install it in a standard folder.")
here = Path(__file__).parent
scripts = [Path(a).resolve() for a in sys.argv[1:]] or [here / "headless.py", *sorted(here.glob("test_*.py"))]
print(f"Using {blender}")
code = 0
for script in scripts:
    print(f"== {script.name}")
    code = max(code, subprocess.run([blender, "-b", "--factory-startup", "--python", str(script)]).returncode)
sys.exit(code)
