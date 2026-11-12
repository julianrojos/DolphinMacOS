"""Check launcher arguments with a fake D-Bus session and no real Dolphin."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_only_explicit_folder_arguments_are_forwarded(self):
        with tempfile.TemporaryDirectory(prefix="dolphin-launcher-test-") as directory:
            root = Path(directory).resolve() / "project with spaces ñ"
            root.mkdir()
            script = root / "abrir-dolphin.sh"
            shutil.copyfile(ROOT / script.name, script)
            app = root / "CraftRoot/Applications/KDE/dolphin.app/Contents/MacOS/dolphin"
            session = root / "CraftRoot/bin/dbus-run-session"
            daemon = root / "dbus-dolphin.sh"
            config = root / "CraftRoot/share/dbus-1/session.conf"
            for path in (app, session, daemon, config):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                path.chmod(0o755)
            record = root / "arguments.json"
            session.write_text(f"#!{sys.executable}\n" +
                               "import json, os, sys, time\n"
                               "from pathlib import Path\n"
                               "args = sys.argv[sys.argv.index('--') + 1:]\n"
                               "Path(os.environ['LAUNCHER_TEST_RECORD']).write_text(json.dumps(args))\n"
                               "time.sleep(30)\n")
            folder = root / "folder with spaces é"
            folder.mkdir()
            for args in ([], [str(folder)]):
                with self.subTest(args=args):
                    record.unlink(missing_ok=True)
                    process = subprocess.Popen(["zsh", str(script), *args], stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE, text=True, start_new_session=True,
                                               env=dict(os.environ, LAUNCHER_TEST_RECORD=str(record)))
                    try:
                        stdout, stderr = process.communicate(timeout=10)
                        self.assertEqual(process.returncode, 0, stdout + stderr)
                        self.assertEqual(json.loads(record.read_text()), [str(app), *args])
                    finally:
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
