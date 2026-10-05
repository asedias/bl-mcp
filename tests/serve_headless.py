"""Runs the bridge in a Blender without a window, on BL_MCP_PORT (default 9878). Started by tests/run_smoke.py."""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("BL_MCP_PORT", "9878")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))

import bl_bridge  # noqa: E402

bl_bridge.register()
while True:
    time.sleep(bl_bridge.pump())
