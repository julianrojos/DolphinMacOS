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
# Shared with install-open-with.sh: both change the same links and the cache.
LOCK = ROOT / "run/open-with.lock"
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
    for identifier in existing:
        source = ROOT / "share/applications" / f"{identifier}.desktop"
        if not source.is_file():
            continue
        merged = merge_manual_bridge(source.read_text(), apps.get(identifier, {}).get("mimeTypes", []))
        (directory / f"{identifier}.bridge").write_text(merged.rstrip("\n") + "\nX-Dolphin-Pilot=true\n")


def merge_manual_bridge(content, additional_types):
    """Merge verified MIME types into a curated bridge while preserving metadata."""
    lines = content.splitlines(keepends=True)
    indexes = [index for index, line in enumerate(lines) if line.startswith("MimeType=")]
    if len(indexes) != 1:
        raise RuntimeError("A curated bridge must have exactly one MimeType entry")
    index = indexes[0]
    original = [value for value in lines[index].strip().removeprefix("MimeType=").split(";") if value]
    types = list(dict.fromkeys([*original, *sorted(additional_types)]))
    if any(not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", value) for value in types):
        raise RuntimeError("Invalid MIME type in curated bridge")
    lines[index] = "MimeType=" + ";".join(types) + ";\n"
    return "".join(lines)


def is_managed(directory):
    return directory.is_dir() and not directory.is_symlink() and (directory / MARKER).is_file()


def validate_managed(directory):
    if not is_managed(directory):
        raise RuntimeError(f"Refusing to replace an unmanaged directory: {directory}")
    for item in directory.iterdir():
        if item.name == ".DS_Store" and item.is_file() and not item.is_symlink():
            continue
        if item.is_symlink() or not item.is_file() or (item.name != MARKER and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*\.(?:desktop|bridge)", item.name)):
            raise RuntimeError(f"Unexpected item in managed directory, inspect it manually: {item}")
        if item.name != MARKER and "X-Dolphin-Pilot=true" not in item.read_text().splitlines():
            raise RuntimeError(f"Unmanaged file, inspect it manually: {item}")


def is_recoverable(directory):
    # An empty stage or resolved previous can only be ours: it is created
    # inside our own working folder and the marker is its first file.
    return is_managed(directory) or (directory.name in ("stage", "previous") and directory.is_dir()
                                     and not directory.is_symlink() and all(item.name == ".DS_Store" and item.is_file() and not item.is_symlink() for item in directory.iterdir()))


def sync_manual_links():
    """Point each curated bridge link at its merged copy, or back at the source.

    Every link is checked before any is changed, so a foreign file found late
    cannot leave the earlier links half updated.
    """
    manual_links = TARGET.parent / "Dolphin Open With"
    if not manual_links.exists():
        return
    sources = sorted((ROOT / "share/applications").glob("*.desktop"))
    if not any((manual_links / source.name).is_symlink() for source in sources):
        return
    plan = []
    for source in sources:
        link = manual_links / source.name
        merged = TARGET / (source.stem + ".bridge")
        desired = merged if merged.is_file() else source
        if not os.path.lexists(link):
            plan.append((link, desired))
            continue
        if not link.is_symlink():
            raise RuntimeError(f"Expected a managed symlink: {link}")
        current = Path(os.readlink(link))
        if current not in (source, merged):
            raise RuntimeError(f"Refusing to replace an unmanaged symlink: {link}")
        if current != desired:
            plan.append((link, desired))
    for link, desired in plan:
        replace_symlink(link, desired)


def replace_symlink(link, desired):
    fd, name = tempfile.mkstemp(prefix=".dolphin-link-", dir=link.parent)
    os.close(fd)
    os.unlink(name)
    try:
        os.symlink(desired, name)
        os.replace(name, link)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


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
        metadata = leftover / ".DS_Store"
        if os.path.lexists(metadata) and (metadata.is_symlink() or not metadata.is_file()):
            raise RuntimeError(f"Unexpected item, inspect it manually: {metadata}")
        contents = {item.name for item in leftover.iterdir()} - {".DS_Store"}
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
        if is_managed(previous) and not TARGET.exists():
            previous.rename(TARGET)
            print(f"Restored the pilot bridges left by an interrupted run from {leftover}", file=sys.stderr)
    sync_manual_links()
    rebuild_cache()
    for leftover in leftovers:
        clean_leftover(leftover)


def discard_managed_contents(directory):
    if not directory.is_dir() or directory.is_symlink():
        return
    # Remove the marker last: an interruption then leaves a folder that is
    # still recognised as ours and the next run can finish the cleanup.
    for item in sorted(directory.iterdir(), key=lambda path: path.name == MARKER):
        if item.name == ".DS_Store" and item.is_file() and not item.is_symlink():
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()


def clean_leftover(leftover):
    for name in ("stage", "previous"):
        subdir = leftover / name
        if subdir.is_dir() and not subdir.is_symlink():
            discard_managed_contents(subdir)
            if not any(path.name == ".DS_Store" for path in subdir.rglob(".DS_Store")):
                shutil.rmtree(subdir)
    if not any(path.name == ".DS_Store" for path in leftover.rglob(".DS_Store")):
        shutil.rmtree(leftover)


def ensure_manual_bridges():
    manual = TARGET.parent / "Dolphin Open With"
    sources = list((ROOT / "share/applications").glob("*.desktop"))
    if not any((manual / source.name).is_symlink() for source in sources):
        raise RuntimeError("Open With bridges are not installed; run ./install-open-with.sh first")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--full", action="store_true", help="Include verified MIME matches from the full database")
    parser.add_argument("--pilot", action="store_true", help="Use only the original five pilot extensions")
    args = parser.parse_args()
    if args.full and args.pilot:
        parser.error("--full and --pilot cannot be combined")
    args.full = not args.pilot
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another Open With installation, pilot update or removal is running") from error
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        recover_leftovers()
        if not args.remove:
            ensure_manual_bridges()
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
        ds_store = TARGET / ".DS_Store"
        if not args.remove:
            types = preview.TYPES
            globs = None
            if args.full:
                globs = (ROOT / "CraftRoot/share/mime/globs2").read_text()
                types, _ = preview.discover_globs(globs)
            result = subprocess.run(["swift", str(ROOT / "tools/query-macos-apps.swift"), *types],
                                    check=True, capture_output=True, text=True)
            results = json.loads(result.stdout)
            if args.full:
                report = preview.make_report(globs, results, preview.query_qt_types(types, results))
                types = {ext: record["qtMimeType"] for ext, record in report["matched"].items()}
                if not types:
                    raise RuntimeError("No verified MIME matches; refusing to replace existing bridges")
                # Keep the original pilot types unless the report rejected them.
                rejected = set(report["ambiguous"]) | set(report["dynamic"]) | set(report["unresolved"])
                types.update({ext: mime for ext, mime in preview.TYPES.items() if ext not in rejected})
                print(f"Compatible extensions (family check, not format verification): {len(types)}; ambiguous or unconfirmed: "
                      f"{sum(len(report[key]) for key in ('ambiguous', 'dynamic', 'unresolved'))}")
            apps = preview.build_associations(results, preview.is_installed_app, types)
            existing = {path.stem for path in (ROOT / "share/applications").glob("*.desktop")}
            stage.mkdir()
            prepare(stage, apps, existing)
        elif ds_store.is_file() and not ds_store.is_symlink():
            stage.mkdir()
            (stage / MARKER).write_text("Managed by Dolphin macOS pilot\n")
        if stage.exists() and ds_store.is_file() and not ds_store.is_symlink():
            shutil.copy2(ds_store, stage / ".DS_Store")
        had_previous = TARGET.exists()
        if had_previous:
            TARGET.rename(previous)
            preserve = True
        try:
            if stage.exists():
                stage.rename(TARGET)
            sync_manual_links()
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
                sync_manual_links()
                rebuild_cache()
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
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
