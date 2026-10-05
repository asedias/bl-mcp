"""Starts a private Blender without a window with the bridge, runs tests/smoke_all.py against it, then stops it.

uv run python tests/run_smoke.py
The Blender you work in is not touched. To test your own open Blender instead, run tests/smoke_all.py directly.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bl_mcp.locate import find_blender

PORT = os.environ.get("BL_MCP_SMOKE_PORT", "9878")
here = Path(__file__).parent
blender = find_blender()
if blender is None:
    sys.exit("Blender not found. Open Blender, or install it in a standard folder.")

work = tempfile.mkdtemp(prefix="bl_smoke_")
env = {**os.environ, "BL_MCP_PORT": PORT, "BL_MCP_WORK": work}
server = subprocess.Popen([blender, "-b", "--factory-startup", "--python", str(here / "serve_headless.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(120):
        try:
            socket.create_connection(("127.0.0.1", int(PORT)), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.5)
    else:
        sys.exit(f"The private Blender did not open port {PORT}")
    code = subprocess.run([sys.executable, "-u", str(here / "smoke_all.py")], env=env).returncode
finally:
    server.terminate()
    server.wait(timeout=20)
sys.exit(code)
