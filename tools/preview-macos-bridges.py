#!/usr/bin/env python3
"""Preview MIME associations for the initial macOS application pilot."""
import json
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = {"txt": "text/plain", "py": "text/x-python", "json": "application/json",
         "pdf": "application/pdf", "mp4": "video/mp4"}


def build_associations(results, eligible=lambda app: True):
    apps = {}
    for extension, mime in TYPES.items():
        for app in results.get(extension, {}).get("applications", []):
            identifier = app["bundleID"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", identifier) or not eligible(app):
                continue
            entry = apps.setdefault(identifier, {"name": app["name"], "mimeTypes": set()})
            entry["mimeTypes"].add(mime)
    return {identifier: {"name": data["name"], "mimeTypes": sorted(data["mimeTypes"])}
            for identifier, data in sorted(apps.items())}


def is_installed_app(app):
    path = Path(app["path"])
    roots = (Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications")
    return path.is_dir() and any(path.is_relative_to(root) for root in roots)


def main():
    result = subprocess.run(["swift", str(ROOT / "tools/query-macos-apps.swift"), *TYPES],
                            check=True, capture_output=True, text=True)
    print(json.dumps(build_associations(json.loads(result.stdout), is_installed_app), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
