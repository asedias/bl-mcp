import json
import os
import socket

HOST = "127.0.0.1"
PORT = int(os.environ.get("BL_MCP_PORT", "9877"))
TIMEOUT = 600


class BlenderError(Exception):
    pass


def call(method, /, **params):
    try:
        conn = socket.create_connection((HOST, PORT), timeout=5)
    except OSError as error:
        raise BlenderError(
            f"Cannot reach Blender on {HOST}:{PORT}. Open Blender and enable the 'BL MCP Bridge' add-on "
            f"(see README, 'Install'). {error}"
        ) from error
    with conn, conn.makefile("rwb") as stream:
        conn.settimeout(TIMEOUT)
        stream.write(json.dumps({"method": method, "params": params}).encode() + b"\n")
        stream.flush()
        line = stream.readline()
    if not line:
        raise BlenderError("Blender closed the connection")
    reply = json.loads(line)
    if not reply["ok"]:
        raise BlenderError(reply["error"])
    return reply["result"]
