"""Shared set-up for the headless test files: expect(), finish(), and the handlers.

A test file starts with `from _harness import *` and ends with `finish()`.
Run one file: uv run python tests/run_headless.py tests/test_<name>.py
Set BL_MCP_WORK to a private folder when several runs happen at once.
"""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon"))
from bl_bridge import handlers  # noqa: E402

call = handlers.call
failures = []


def expect(label, condition, detail=None):
    print(("ok   " if condition else "FAIL ") + label, "" if condition else detail)
    if not condition:
        failures.append(label)


def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def finish():
    print("FAILED:" if failures else "ALL PASSED", failures or "")
    sys.exit(1 if failures else 0)
