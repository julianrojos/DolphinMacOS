import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("session_restore_check", ROOT / "tests/session-restore-check.py")
session_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session_check)


class SessionProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dolphin-session-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.marker = self.root / ".session-test-profile"
        self.marker.write_text("a" * 64)
        self.env = {"HOME": str(self.root), "CFFIXED_USER_HOME": str(self.root),
                    "DOLPHIN_SESSION_TEST_ROOT": str(self.root), "DOLPHIN_SESSION_TEST_TOKEN": "a" * 64}
        self.settings = session_check.load()

    def test_direct_internal_mode_refuses_to_launch_without_profile(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith("DOLPHIN_SESSION_TEST_")}
        result = subprocess.run([sys.executable, str(ROOT / "tests/session-restore-check.py"), "--inside"],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an isolated temporary profile", result.stderr)

    def test_invalid_marker_or_home_is_rejected_before_querying_qt(self):
        for changes in ({"DOLPHIN_SESSION_TEST_TOKEN": "wrong"}, {"HOME": str(self.root.parent)},
                        {"CFFIXED_USER_HOME": str(self.root.parent)}):
            with self.subTest(changes=changes), patch.dict(os.environ, self.env | changes), \
                 patch.object(session_check.subprocess, "run") as run:
                with self.assertRaises(RuntimeError):
                    session_check.validate_profile(self.settings)
                run.assert_not_called()

    def test_well_formed_token_that_differs_from_the_marker_is_rejected(self):
        with patch.dict(os.environ, self.env | {"DOLPHIN_SESSION_TEST_TOKEN": "b" * 64}), \
             patch.object(session_check.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "marker is missing or invalid"):
                session_check.validate_profile(self.settings)
            run.assert_not_called()

    def test_symlink_marker_is_rejected(self):
        target = self.root / "other-marker"
        self.marker.rename(target)
        self.marker.symlink_to(target)
        with patch.dict(os.environ, self.env), patch.object(session_check.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "marker"):
                session_check.validate_profile(self.settings)
            run.assert_not_called()

    def test_qt_must_use_the_same_temporary_profile(self):
        for path, valid in ((self.root / "Library/Preferences", True), (self.root.parent / "Library/Preferences", False)):
            result = subprocess.CompletedProcess([], 0, str(path) + ":/Library/Preferences\n", "")
            with self.subTest(path=path), patch.dict(os.environ, self.env), \
                 patch.object(session_check.subprocess, "run", return_value=result):
                if valid:
                    self.assertEqual(session_check.validate_profile(self.settings), self.root)
                else:
                    with self.assertRaisesRegex(RuntimeError, "Qt configuration is not isolated"):
                        session_check.validate_profile(self.settings)


if __name__ == "__main__":
    unittest.main()
