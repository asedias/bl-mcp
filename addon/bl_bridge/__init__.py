"""Bridge between the MCP server and the open Blender: JSON lines over a local socket."""

bl_info = {
    "name": "BL MCP Bridge",
    "author": "asedias",
    "version": (0, 4, 0),
    "blender": (5, 0, 0),
    "category": "Development",
    "description": "Local socket for this package",
}

import json
import os
import queue
import socket
import threading
import traceback

FEATURES = ["profiles", "compare", "fit", "meshops", "sculpt", "hard", "rig", "uvpaint", "level", "materials", "render", "organic", "procedural", "lights", "refcam"]
PORT = int(os.environ.get("BL_MCP_PORT", "9877"))
REQUEST_TIMEOUT = 600

jobs = queue.Queue()
state = {"sock": None}


class Job:
    def __init__(self, request):
        self.request = request
        self.done = threading.Event()
        self.response = None


def pump():
    from . import core, handlers

    while True:
        try:
            job = jobs.get_nowait()
        except queue.Empty:
            return 0.005 if core.advance_jobs() else 0.02
        try:
            if job.request["method"] == "__reload__":
                import importlib

                for name in ["core", *FEATURES]:
                    importlib.reload(importlib.import_module(f"{__name__}.{name}"))
                importlib.reload(handlers)
                job.response = {"ok": True, "result": f"reloaded core and {len(FEATURES)} feature modules"}
                job.done.set()
                continue
            result = handlers.call(job.request["method"], job.request.get("params", {}))
            job.response = {"ok": True, "result": result}
        except Exception:
            job.response = {"ok": False, "error": traceback.format_exc(limit=4)}
        job.done.set()


def serve(conn):
    with conn, conn.makefile("rwb") as stream:
        for line in stream:
            job = Job(json.loads(line))
            jobs.put(job)
            if not job.done.wait(REQUEST_TIMEOUT):
                job.response = {"ok": False, "error": "Blender did not answer in time"}
            stream.write(json.dumps(job.response).encode() + b"\n")
            stream.flush()


def accept_loop(sock):
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        threading.Thread(target=serve, args=(conn,), daemon=True).start()


def register():
    import bpy

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", PORT))
    sock.listen()
    state["sock"] = sock
    threading.Thread(target=accept_loop, args=(sock,), daemon=True).start()
    bpy.app.timers.register(pump, persistent=True)
    print(f"BL MCP Bridge: listening on 127.0.0.1:{PORT}")


def unregister():
    import bpy

    if bpy.app.timers.is_registered(pump):
        bpy.app.timers.unregister(pump)
    if state["sock"] is not None:
        state["sock"].close()
        state["sock"] = None
