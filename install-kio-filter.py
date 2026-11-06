#!/usr/bin/env python3
"""Build, verify and install the local KIO Open With filter reversibly."""
import argparse
import fcntl
import hashlib
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

from dolphin_config import load, read_json, check_version
from dolphin_install import ensure_closed
from dolphin_store import Store, collect, deploy, describe, digest, recover, verify_live

KIO_VERSION = "6.31.0"
SOURCE_URL = f"https://codeload.github.com/KDE/kio/tar.gz/refs/tags/v{KIO_VERSION}"
SOURCE_SHA256 = "ed444c7719cf044dafb90e50b2aefd81799573409336fb414d58d8b4c5ec7ccd"


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def exports(path):
    result = subprocess.run(["nm", "-gU", str(path)], check=True, capture_output=True, text=True)
    return {line.split()[-1] for line in result.stdout.splitlines() if len(line.split()) >= 2}


def checked_state(path, version):
    if not path.exists():
        return None
    state = read_json(path)
    if (set(state) != {"schema", "version", "baseline", "installed", "managed"}
            or state["schema"] != 1 or state["version"] != version
            or state["managed"] != [f"lib/libKF6KIOWidgets.{version}.dylib"]):
        raise RuntimeError("Invalid KIO filter installation manifest")
    return state


class UnsupportedKioVersion(RuntimeError):
    pass


def verify_library_version(settings):
    library = settings.craft / f"lib/libKF6KIOWidgets.{KIO_VERSION}.dylib"
    active = settings.craft / "lib/libKF6KIOWidgets.6.dylib"
    if not active.is_file():
        raise RuntimeError("The active KIO library is missing or invalid")
    resolved = active.resolve()
    if resolved != library.resolve():
        if resolved.parent == library.parent.resolve() and re.fullmatch(r"libKF6KIOWidgets\.\d+\.\d+\.\d+\.dylib", resolved.name):
            raise UnsupportedKioVersion(f"The active KIO library is {resolved.name}, not version {KIO_VERSION}")
        raise RuntimeError("The active KIO library points to an unexpected location")
    if not library.is_file():
        raise RuntimeError("The expected KIO library is missing")
    return library


def verify_current_library(settings, store, state):
    _, current = store.load(state["installed"])
    _, original = store.load(state["baseline"])
    try:
        verify_live(settings.craft, current, state["managed"])
    except RuntimeError as error:
        try:
            # Craft can restore the exact original when reinstalling KIO.
            verify_live(settings.craft, original, state["managed"])
        except RuntimeError:
            raise RuntimeError("The KIO library changed outside this installer; inspect it before continuing") from error


def prepare_library(settings, directory, source, build):
    cmake = settings.craft / "dev-utils/bin/cmake"
    patch_file = settings.root / f"patches/kio-{KIO_VERSION}/0001-filter-open-with-applications.patch"
    if not patch_file.is_file():
        raise RuntimeError(f"Missing patch: {patch_file}")
    reverse = subprocess.run(["patch", "--batch", "--forward", "--dry-run", "-R", "-p1", "-i", str(patch_file)],
                             cwd=source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if reverse.returncode:
        run("patch", "--batch", "--forward", "-p1", "-i", patch_file, cwd=source)
    log = settings.root / "run/kio-filter-build.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"Building KIO {KIO_VERSION}; log: {log}", flush=True)
    with log.open("w") as output:
        run(cmake, "-S", source, "-B", build, f"-DCMAKE_PREFIX_PATH={settings.craft}",
            f"-DCMAKE_INSTALL_PREFIX={settings.craft}", "-DBUILD_TESTING=OFF", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
            stdout=output, stderr=subprocess.STDOUT)
        run(cmake, "--build", build, "--target", "KF6KIOWidgets", "-j", str(os.cpu_count() or 4), stdout=output, stderr=subprocess.STDOUT)
    candidate = directory / f"libKF6KIOWidgets.{KIO_VERSION}.dylib"
    shutil.copy2(build / "bin" / candidate.name, candidate)
    old = settings.craft / "lib" / candidate.name
    if exports(candidate) != exports(old):
        raise RuntimeError("The rebuilt KIO library exports differ from the installed library; refusing to replace it")
    run("install_name_tool", "-id", settings.craft / "lib/libKF6KIOWidgets.6.dylib",
        "-change", "@rpath/libKF6KIOGui.6.dylib", settings.craft / "lib/libKF6KIOGui.6.dylib",
        "-change", "@rpath/libKF6KIOCore.6.dylib", settings.craft / "lib/libKF6KIOCore.6.dylib", candidate)
    run("codesign", "--force", "--sign", "-", candidate)
    run("codesign", "--verify", candidate)
    return candidate


def verify_dialog(settings, directory, candidate):
    cmake = settings.craft / "dev-utils/bin/cmake"
    test_build = directory / "tests"
    run(cmake, "-S", settings.root / "tests", "-B", test_build, f"-DCMAKE_PREFIX_PATH={settings.craft}")
    run(cmake, "--build", test_build, "--target", "open-with-dialog-check")
    probe = test_build / "open-with-dialog-check"
    run("install_name_tool", "-change", settings.craft / "lib/libKF6KIOWidgets.6.dylib", candidate, probe)
    run("codesign", "--force", "--sign", "-", probe)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_DATA_DIRS=str(settings.craft / "share"))
    run(settings.craft / "bin/dbus-run-session", f"--dbus-daemon={settings.root / 'dbus-dolphin.sh'}",
        f"--config-file={settings.craft / 'share/dbus-1/session.conf'}", "--", probe, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--restore", "--restaurar", action="store_true", help="Restore the previous KIO library")
    action.add_argument("--recover", "--recuperar", action="store_true", help="Undo an interrupted replacement")
    parser.add_argument("--skip-unsupported", action="store_true", help="Skip installation for an unsupported KIO version")
    parser.add_argument("--reuse-build", type=Path, help="Reuse a configured KIO build directory")
    args = parser.parse_args()
    settings = load()
    settings.backups.mkdir(parents=True, exist_ok=True)
    state_path = settings.backups / "kio-filter/installation.json"
    relative = f"lib/libKF6KIOWidgets.{KIO_VERSION}.dylib"
    if args.skip_unsupported and (args.restore or args.recover):
        parser.error("--skip-unsupported applies only to installation")
    with (settings.backups / "instalacion.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another installation or cleanup is running") from error
        store = Store(settings.backups)
        pending = state_path.parent / "pendiente.json"
        if pending.exists() and not args.recover:
            raise RuntimeError("A KIO replacement was interrupted; run this command with --recover")
        state = checked_state(state_path, KIO_VERSION)
        try:
            library = verify_library_version(settings)
        except UnsupportedKioVersion as error:
            if not args.skip_unsupported:
                raise
            print(f"Warning: {error}; the Open With filter was not installed. Adapt the patch before installing it.", file=sys.stderr)
            return
        ensure_closed(settings)
        if args.recover:
            recover(settings.craft, store, state_path)
            print("Recovered the previous KIO library")
            return
        if state:
            verify_current_library(settings, store, state)
        if args.restore:
            if not state:
                raise RuntimeError("No KIO filter installation is registered")
            target = state["baseline"]
            baseline = state["baseline"]
        else:
            with tempfile.TemporaryDirectory(prefix="dolphin-kio-filter-") as work:
                workdir = Path(work)
                if args.reuse_build:
                    build = args.reuse_build.resolve()
                    cache = (build / "CMakeCache.txt").read_text()
                    values = dict(line.split("=", 1) for line in cache.splitlines() if "=" in line)
                    source = Path(values.get("CMAKE_HOME_DIRECTORY:INTERNAL", ""))
                    if values.get("CMAKE_PROJECT_VERSION:STATIC") != KIO_VERSION or not source.is_dir():
                        raise RuntimeError("The selected build is not configured for the expected KIO version")
                else:
                    if sys.version_info < (3, 12):
                        raise RuntimeError("Python 3.12 or newer is required to safely extract the KIO source archive")
                    archive = workdir / "kio.tar.gz"
                    run("curl", "--fail", "--location", "--silent", "--show-error", SOURCE_URL, "--output", archive)
                    if hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_SHA256:
                        raise RuntimeError("The downloaded KIO archive does not match its expected SHA-256")
                    with tarfile.open(archive) as source_archive:
                        source_archive.extractall(workdir, filter="data")
                    source = workdir / f"kio-{KIO_VERSION}"
                    build = workdir / "build"
                candidate = prepare_library(settings, workdir, source, build)
                verify_dialog(settings, workdir, candidate)
                baseline = state["baseline"] if state else store.save(settings.craft, {relative: describe(library)})
                tree = workdir / "artifact"
                (tree / "lib").mkdir(parents=True)
                shutil.copy2(candidate, tree / relative)
                target = store.save(tree)
        ensure_closed(settings)
        updated = dict(schema=1, version=KIO_VERSION, baseline=baseline, installed=target, managed=[relative])
        def validate():
            run("codesign", "--verify", library)
            check_version(settings.app / "Contents/MacOS/dolphin", settings.version)
        deploy(settings.craft, store, target, [relative], state_path, updated, validate)
        if args.restore:
            print("Original KIO library restored and verified; restart Dolphin")
        else:
            print("KIO filter installed and verified; restart Dolphin")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"KIO filter installation failed: {error}", file=sys.stderr)
        sys.exit(1)
