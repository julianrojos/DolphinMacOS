#!/usr/bin/env python3
"""Install a reversible set of generated Open With bridges for pilot types."""
import fcntl
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path.home() / "Applications/Dolphin Open With Pilot"
MARKER = ".dolphin-pilot"
TEMP_PREFIX = ".dolphin-pilot-"
LOCK = ROOT / "run/macos-pilot.lock"
spec = importlib.util.spec_from_file_location("preview", ROOT / "tools/preview-macos-bridges.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def desktop(identifier, app):
    # LaunchServices does not provide a reliable desktop-menu category.
    name = app["name"].removesuffix(".app").replace("\\", "\\\\").replace("\n", "\\n")
    return ("[Desktop Entry]\nX-Dolphin-Pilot=true\nType=Application\n"
            f"Name={name}\nExec=/usr/bin/open -b {identifier} %F\n"
            f"MimeType={';'.join(app['mimeTypes'])};\n"
            "Terminal=false\n")


def prepare(directory, apps, existing):
    (directory / MARKER).write_text("Managed by Dolphin macOS pilot\n")
    for identifier, app in apps.items():
        if identifier not in existing:
            (directory / f"{identifier}.desktop").write_text(desktop(identifier, app))


def is_managed(directory):
    return directory.is_dir() and not directory.is_symlink() and (directory / MARKER).is_file()


def validate_managed(directory):
    if not is_managed(directory):
        raise RuntimeError(f"Refusing to replace an unmanaged directory: {directory}")
    for item in directory.iterdir():
        if item.is_symlink() or not item.is_file() or (item.name != MARKER and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*\.desktop", item.name)):
            raise RuntimeError(f"Unexpected item in managed directory, inspect it manually: {item}")
        if item.name != MARKER and "X-Dolphin-Pilot=true\n" not in item.read_text():
            raise RuntimeError(f"Unmanaged file, inspect it manually: {item}")


def is_recoverable(directory):
    # An empty stage can only be ours: it is created inside our own working
    # folder and the marker is its first file.
    return is_managed(directory) or (directory.name == "stage" and directory.is_dir()
                                     and not directory.is_symlink() and not any(directory.iterdir()))


def rebuild_cache():
    env = dict(os.environ, QT_DATA_DIRS=str(ROOT / "CraftRoot/share"))
    subprocess.run([str(ROOT / "CraftRoot/bin/kbuildsycoca6"), "--noincremental"],
                   check=True, env=env, stdout=subprocess.DEVNULL)


def recover_leftovers():
    """Resolve working folders left by an interrupted run.

    A run moves the active folder to <temp>/previous before placing the new one,
    so an abrupt stop can leave the only copy there. Restore it if nothing took
    its place. Validate all folders and rebuild the cache before removing any
    leftovers, preserving them for a retry if rebuilding fails.
    """
    leftovers = sorted(TARGET.parent.glob(TEMP_PREFIX + "*"))
    if not leftovers:
        return
    for leftover in leftovers:
        if leftover.is_symlink() or not leftover.is_dir():
            raise RuntimeError(f"Unexpected item, inspect it manually: {leftover}")
        contents = {item.name for item in leftover.iterdir()}
        if not contents <= {"stage", "previous"} or not all(is_recoverable(leftover / name) for name in contents):
            raise RuntimeError(f"Unexpected content in an interrupted pilot folder, inspect it manually: {leftover}")
        for name in contents:
            directory = leftover / name
            if is_managed(directory):
                validate_managed(directory)
    if TARGET.exists() or TARGET.is_symlink():
        validate_managed(TARGET)
    for leftover in leftovers:
        previous = leftover / "previous"
        if previous.exists() and not TARGET.exists():
            previous.rename(TARGET)
            print(f"Restored the pilot bridges left by an interrupted run from {leftover}", file=sys.stderr)
    rebuild_cache()
    for leftover in leftovers:
        shutil.rmtree(leftover)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another pilot installation or removal is running") from error
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        recover_leftovers()
        update(args)


def update(args):
    if TARGET.exists() or TARGET.is_symlink():
        validate_managed(TARGET)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=TARGET.parent))
    preserve = False
    try:
        stage = temp / "stage"
        previous = temp / "previous"
        if not args.remove:
            result = subprocess.run(["swift", str(ROOT / "tools/query-macos-apps.swift"), *preview.TYPES],
                                    check=True, capture_output=True, text=True)
            apps = preview.build_associations(json.loads(result.stdout), preview.is_installed_app)
            existing = {path.stem for path in (ROOT / "share/applications").glob("*.desktop")}
            stage.mkdir()
            prepare(stage, apps, existing)
        had_previous = TARGET.exists()
        if had_previous:
            TARGET.rename(previous)
            preserve = True
        try:
            if not args.remove:
                stage.rename(TARGET)
            rebuild_cache()
            preserve = False
        except Exception:
            if TARGET.exists():
                shutil.rmtree(TARGET)
            if had_previous:
                try:
                    previous.rename(TARGET)
                    preserve = False
                except OSError as error:
                    preserve = True
                    raise RuntimeError(f"Rollback failed; previous bridges are preserved at {previous}: {error}") from error
            try:
                rebuild_cache()
            except (OSError, subprocess.SubprocessError) as error:
                preserve = True
                print(f"Cache could not be rebuilt after rollback; retry the operation: {error}", file=sys.stderr)
            raise
    finally:
        if not preserve:
            shutil.rmtree(temp)
    print("Pilot bridges removed" if args.remove else "Pilot bridges installed; restart Dolphin")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f"Pilot installation failed: {error}", file=sys.stderr)
        sys.exit(1)
