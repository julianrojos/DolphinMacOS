"""Verify rendering and bridge deduplication without changing user settings."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
import subprocess
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pilot", ROOT / "tools/install-macos-pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class PilotTests(unittest.TestCase):
    def test_prepare_skips_existing_and_escapes_names(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            apps = {"com.example.Editor": {"name": "Editor.app", "mimeTypes": ["text/plain"]},
                    "com.example.Other": {"name": "Other.app", "mimeTypes": ["application/pdf"]}}
            pilot.prepare(folder, apps, {"com.example.Editor"})
            self.assertFalse((folder / "com.example.Editor.desktop").exists())
            text = (folder / "com.example.Other.desktop").read_text()
            self.assertIn("Name=Other\n", text)
            self.assertIn("Exec=/usr/bin/open -b com.example.Other %F\n", text)
            self.assertIn("MimeType=application/pdf;\n", text)
            self.assertNotIn("\nCategories=", text)

    def test_install_remove_and_cache_failure_restore_previous(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "pilot"
            payload = {"txt": {"applications": [{"bundleID": "example.editor", "name": "Editor", "path": "/Applications/Editor.app"}]}}
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                if args[0] == "swift":
                    return subprocess.CompletedProcess(args, 0, json.dumps(payload))
                if fail_cache[0]:
                    fail_cache[0] = False
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0)
            fail_cache = [False]
            with mock.patch.object(pilot, "TARGET", target), mock.patch.object(pilot, "LOCK", Path(temp) / "pilot.lock"), mock.patch.object(pilot.preview, "is_installed_app", return_value=True), \
                 mock.patch.object(pilot.subprocess, "run", side_effect=run), mock.patch("sys.argv", ["pilot"]):
                pilot.main()
                original = (target / "example.editor.desktop").read_text()
                fail_cache[0] = True
                with self.assertRaises(subprocess.CalledProcessError):
                    pilot.main()
                self.assertEqual((target / "example.editor.desktop").read_text(), original)
                self.assertEqual(len(calls), 5)
                with mock.patch("sys.argv", ["pilot", "--remove"]):
                    pilot.main()
                self.assertFalse(target.exists())

    def test_unmanaged_directory_is_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "pilot"
            target.mkdir()
            (target / "user.txt").write_text("keep")
            with mock.patch.object(pilot, "TARGET", target), mock.patch.object(pilot, "LOCK", Path(temp) / "pilot.lock"), mock.patch("sys.argv", ["pilot", "--remove"]):
                with self.assertRaisesRegex(RuntimeError, "unmanaged"):
                    pilot.main()
            self.assertEqual((target / "user.txt").read_text(), "keep")

    def isolated(self, temp):
        target = Path(temp) / "Applications" / "pilot"
        target.parent.mkdir()
        return target, mock.patch.multiple(pilot, TARGET=target, LOCK=Path(temp) / "pilot.lock")

    def managed(self, folder, name="example.editor"):
        folder.mkdir(parents=True)
        (folder / pilot.MARKER).write_text("Managed by Dolphin macOS pilot\n")
        (folder / f"{name}.desktop").write_text("[Desktop Entry]\nX-Dolphin-Pilot=true\n")

    def test_interrupted_run_restores_the_only_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            leftover = target.parent / (pilot.TEMP_PREFIX + "abc")
            self.managed(leftover / "previous")
            with paths, mock.patch("sys.stderr"), mock.patch.object(pilot, "rebuild_cache") as rebuild:
                pilot.recover_leftovers()
            rebuild.assert_called_once()
            self.assertTrue((target / "example.editor.desktop").is_file())
            self.assertFalse(leftover.exists())

    def test_obsolete_leftover_is_removed_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            self.managed(target, "example.current")
            leftover = target.parent / (pilot.TEMP_PREFIX + "abc")
            self.managed(leftover / "previous", "example.old")
            self.managed(leftover / "stage", "example.new")
            with paths, mock.patch.object(pilot, "rebuild_cache") as rebuild:
                pilot.recover_leftovers()
            # The run may have stopped before rebuilding the cache for the new folder.
            rebuild.assert_called_once()
            self.assertEqual(sorted(p.name for p in target.iterdir()), [pilot.MARKER, "example.current.desktop"])
            self.assertFalse(leftover.exists())

    def test_unknown_leftover_content_is_reported_and_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            leftover = target.parent / (pilot.TEMP_PREFIX + "abc")
            (leftover / "previous").mkdir(parents=True)
            (leftover / "previous" / "user.txt").write_text("keep")
            with paths, mock.patch.object(pilot, "rebuild_cache") as rebuild, \
                 self.assertRaisesRegex(RuntimeError, "inspect it manually"):
                pilot.recover_leftovers()
            rebuild.assert_not_called()
            self.assertEqual((leftover / "previous" / "user.txt").read_text(), "keep")

    def test_empty_stage_is_removed_but_unmarked_content_is_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            empty = target.parent / (pilot.TEMP_PREFIX + "empty")
            (empty / "stage").mkdir(parents=True)
            with paths, mock.patch.object(pilot, "rebuild_cache"):
                pilot.recover_leftovers()
            self.assertFalse(empty.exists())
            partial = target.parent / (pilot.TEMP_PREFIX + "partial")
            (partial / "stage").mkdir(parents=True)
            (partial / "stage" / "unknown.desktop").write_text("not marked")
            with paths, mock.patch.object(pilot, "rebuild_cache"), \
                 self.assertRaisesRegex(RuntimeError, "inspect it manually"):
                pilot.recover_leftovers()
            self.assertTrue((partial / "stage" / "unknown.desktop").exists())

    def test_failed_cache_rebuild_keeps_previous_for_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            self.managed(target, "example.current")
            leftover = target.parent / (pilot.TEMP_PREFIX + "retry")
            self.managed(leftover / "previous", "example.old")
            with paths, mock.patch.object(pilot, "rebuild_cache", side_effect=[OSError("failed"), None]):
                with self.assertRaises(OSError):
                    pilot.recover_leftovers()
                self.assertTrue((leftover / "previous/example.old.desktop").exists())
                pilot.recover_leftovers()
            self.assertFalse(leftover.exists())

    def test_recovery_preserves_foreign_file_inside_managed_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            self.managed(target)
            leftover = target.parent / (pilot.TEMP_PREFIX + "foreign")
            self.managed(leftover / "previous")
            foreign = leftover / "previous/user.txt"
            foreign.write_text("keep")
            with paths, mock.patch.object(pilot, "rebuild_cache") as rebuild:
                with self.assertRaisesRegex(RuntimeError, "inspect it manually"):
                    pilot.recover_leftovers()
                rebuild.assert_not_called()
            self.assertEqual(foreign.read_text(), "keep")

    def test_no_leftovers_do_not_rebuild_the_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            _, paths = self.isolated(temp)
            with paths, mock.patch.object(pilot, "rebuild_cache") as rebuild:
                pilot.recover_leftovers()
            rebuild.assert_not_called()

    def test_concurrent_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            with paths, mock.patch("sys.argv", ["pilot", "--remove"]), \
                 mock.patch.object(pilot.fcntl, "flock", side_effect=BlockingIOError), \
                 mock.patch.object(pilot, "update") as update:
                with self.assertRaisesRegex(RuntimeError, "Another pilot"):
                    pilot.main()
                update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
