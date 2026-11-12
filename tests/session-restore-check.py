#!/usr/bin/env python3
"""Exercise session restoration with temporary settings and an isolated D-Bus."""
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dolphin_config import load


def validate_profile(settings, env=None):
    env = os.environ if env is None else env
    directory = env.get("DOLPHIN_SESSION_TEST_ROOT")
    token = env.get("DOLPHIN_SESSION_TEST_TOKEN")
    if not directory or not token:
        raise RuntimeError("The internal test mode requires an isolated temporary profile")
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        raise RuntimeError("The temporary test profile token is invalid")
    root = Path(directory).resolve(strict=True)
    if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith("dolphin-session-test-"):
        raise RuntimeError("The test profile must be a dedicated temporary directory")
    marker = root / ".session-test-profile"
    if marker.is_symlink() or not marker.is_file() or marker.read_text() != token:
        raise RuntimeError("The temporary test profile marker is missing or invalid")
    for name in ("HOME", "CFFIXED_USER_HOME"):
        value = env.get(name)
        if not value or Path(value).resolve() != root:
            raise RuntimeError(f"{name} does not point to the isolated test profile")
    paths = subprocess.run([str(settings.craft / "bin/qtpaths6"), "--paths", "GenericConfigLocation"],
                           check=True, capture_output=True, text=True, timeout=10, env=env).stdout.strip().split(":")
    if not paths or Path(paths[0]).resolve() != root / "Library/Preferences":
        raise RuntimeError("Qt configuration is not isolated in the temporary profile")
    return root


def test_in_bus(settings):
    home = validate_profile(settings)
    app = settings.app if os.environ.get("DOLPHIN_SESSION_TEST_INSTALLED") == "1" else settings.build / "bin/dolphin.app"
    binary = app / "Contents/MacOS/dolphin"
    qdbus = settings.craft / "bin/qdbus"

    def session_test(expected, urls_open, *args, add_url=None):
        env = dict(os.environ, DOLPHIN_SESSION_TEST_URLS="\n".join((home / name).as_uri() for name in ("first", "second")))
        env["DOLPHIN_SESSION_TEST_ADD_URLS"] = add_url or ""
        result = subprocess.run([str(binary), "--session-test", *args], capture_output=True, text=True, timeout=40, env=env)
        marker = f"DOLPHIN_SESSION_TEST_TAB_COUNT={expected}"
        urls = [line for line in result.stdout.splitlines() if line.startswith("DOLPHIN_SESSION_TEST_URL_OPEN=")]
        if result.returncode or marker not in result.stdout.splitlines() or urls != [f"DOLPHIN_SESSION_TEST_URL_OPEN={int(urls_open)}"] * 2:
            raise RuntimeError(f"Expected {marker}, exit={result.returncode}:\n{result.stdout}\n{result.stderr}")

    session_test(1, False)
    first, second = home / "first", home / "second"
    first.mkdir()
    second.mkdir()
    session = home / "Library/Preferences/session/dolphin_dolphin_dolphin"
    session_test(2, True, first.as_uri(), add_url=second.as_uri())
    if not session.is_file():
        raise RuntimeError("Dolphin did not save its session when closing the test window")
    saved_session = session.read_bytes()
    for changes in ({"DOLPHIN_SESSION_TEST_ROOT": ""}, {"DOLPHIN_SESSION_TEST_TOKEN": "wrong"},
                    # Well formed, so only the content check against the marker file can reject it.
                    {"DOLPHIN_SESSION_TEST_TOKEN": "0" * 64},
                    {"CFFIXED_USER_HOME": str(home / "other")}):
        result = subprocess.run([str(binary), "--session-test"], env=dict(os.environ, **changes),
                                capture_output=True, text=True, timeout=40)
        if result.returncode == 0 or "Session test requires a verified temporary profile" not in result.stderr:
            raise RuntimeError(f"The executable did not reject an unsafe test profile: {result.stderr}")
        if session.read_bytes() != saved_session:
            raise RuntimeError("An unsafe test invocation modified the saved session")
    result = subprocess.run([str(binary), "--self-test"], capture_output=True, text=True, timeout=40,
                            env=dict(os.environ, DOLPHIN_SESSION_TEST_ADD_URLS=second.as_uri()))
    if result.returncode or "DOLPHIN_SESSION_TEST_" in result.stdout or session.read_bytes() != saved_session:
        raise RuntimeError("The original self-test mode did not preserve its smoke-test behavior")
    session_test(2, True)
    session.unlink()
    other = subprocess.Popen([str(binary)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        service = f"org.kde.dolphin-{other.pid}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if other.poll() is not None:
                raise RuntimeError("The other Dolphin instance exited unexpectedly")
            result = subprocess.run([str(qdbus)], capture_output=True, text=True, timeout=10)
            if service in result.stdout.split():
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("The other Dolphin instance did not register its D-Bus service")
        session.write_bytes(saved_session)
        session_test(1, False, "--new-window")
    finally:
        other.terminate()
        try:
            other.wait(timeout=10)
        except subprocess.TimeoutExpired:
            other.kill()
            other.wait()
    print("Session restoration and another running instance: OK")


def main():
    settings = load()
    if sys.argv[1:] == ["--inside"]:
        test_in_bus(settings)
        return
    if sys.argv[1:] not in ([], ["--installed"]):
        raise SystemExit("Usage: python3 tests/session-restore-check.py [--installed]")
    with tempfile.TemporaryDirectory(prefix="dolphin-session-test-") as directory:
        directory = str(Path(directory).resolve())
        token = secrets.token_hex(32)
        (Path(directory) / ".session-test-profile").write_text(token)
        (Path(directory) / "Library/Preferences").mkdir(parents=True)
        env = dict(os.environ, HOME=directory, CFFIXED_USER_HOME=directory,
                   DOLPHIN_SESSION_TEST_ROOT=directory, DOLPHIN_SESSION_TEST_TOKEN=token,
                   QT_QPA_PLATFORM="offscreen", QT_DATA_DIRS=str(settings.craft / "share"))
        env["DOLPHIN_SESSION_TEST_INSTALLED"] = "1" if sys.argv[1:] == ["--installed"] else "0"
        validate_profile(settings, env)
        command = [settings.craft / "bin/dbus-run-session", f"--dbus-daemon={ROOT / 'dbus-dolphin.sh'}",
                   f"--config-file={settings.craft / 'share/dbus-1/session.conf'}", "--",
                   sys.executable, Path(__file__).resolve(), "--inside"]
        subprocess.run([str(arg) for arg in command], check=True, env=env, timeout=420)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Session test failed: {error}", file=sys.stderr)
        sys.exit(1)
