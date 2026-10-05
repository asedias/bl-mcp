import os
import platform
import shutil
import subprocess
from glob import glob
from pathlib import Path

PATTERNS = {
    "Darwin": [
        "/Applications/Blender*.app/Contents/MacOS/Blender",
        "~/Applications/Blender*.app/Contents/MacOS/Blender",
        "~/Library/Application Support/Steam/steamapps/common/Blender/Blender.app/Contents/MacOS/Blender",
    ],
    "Linux": [
        "/usr/bin/blender",
        "/usr/local/bin/blender",
        "/snap/bin/blender",
        "/opt/blender*/blender",
        "~/blender*/blender",
        "~/.steam/steam/steamapps/common/Blender/blender",
    ],
    "Windows": [
        "C:/Program Files/Blender Foundation/Blender */blender.exe",
        "C:/Program Files (x86)/Steam/steamapps/common/Blender/blender.exe",
    ],
}


def running_blenders():
    if platform.system() == "Windows":
        return []
    try:
        out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        for marker in ("/MacOS/Blender", "/blender"):
            if marker in line:
                path = line.split(marker)[0] + marker
                if os.path.isfile(path) and path not in found:
                    found.append(path)
                break
    return found


def installed_blenders():
    system = platform.system()
    found = []
    for pattern in PATTERNS.get(system, []):
        found += sorted(glob(os.path.expanduser(pattern)), reverse=True)
    return found


def version_of(path):
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30).stdout
        return out.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def find_blenders():
    """Every Blender binary found, best first, with the way it was found."""
    ordered = [("running", p) for p in running_blenders()]
    on_path = shutil.which("blender")
    if on_path:
        ordered.append(("PATH", on_path))
    ordered += [("installed", p) for p in installed_blenders()]
    seen, result = set(), []
    for how, path in ordered:
        real = str(Path(path).resolve())
        if real not in seen:
            seen.add(real)
            result.append({"path": path, "found_by": how})
    return result


def find_blender():
    found = find_blenders()
    return found[0]["path"] if found else None


def main():
    path = find_blender()
    if path is None:
        raise SystemExit("Blender not found. Open Blender, or install it in a standard folder.")
    print(path)


if __name__ == "__main__":
    main()
