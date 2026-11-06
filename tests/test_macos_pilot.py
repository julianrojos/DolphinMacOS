"""Verify rendering and bridge deduplication without changing user settings."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
import shutil
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

    def test_preparation_marks_bridge_without_final_newline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            source = root / "share/applications/example.editor.desktop"
            source.parent.mkdir(parents=True)
            source.write_text("[Desktop Entry]\nMimeType=text/plain;\nCategories=Utility;")
            stage = Path(temp) / "stage"
            stage.mkdir()
            with mock.patch.object(pilot, "ROOT", root):
                pilot.prepare(stage, {}, {"example.editor"})
            content = (stage / "example.editor.bridge").read_text()
            self.assertIn("Categories=Utility;\nX-Dolphin-Pilot=true\n", content)
            pilot.validate_managed(stage)

    def test_sync_does_not_resurrect_removed_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            source = root / "share/applications/example.editor.desktop"
            source.parent.mkdir(parents=True)
            source.write_text("[Desktop Entry]\nMimeType=text/plain;\n")
            target = Path(temp) / "Applications/Dolphin Open With Pilot"
            links = target.parent / "Dolphin Open With"
            links.mkdir(parents=True)
            (links / ".DS_Store").write_text("keep")
            with mock.patch.multiple(pilot, ROOT=root, TARGET=target):
                pilot.sync_manual_links()
            self.assertFalse((links / source.name).exists())

    def test_missing_manual_install_is_explained(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "pilot"
            with mock.patch.object(pilot, "TARGET", target):
                with self.assertRaisesRegex(RuntimeError, "install-open-with.sh"):
                    pilot.ensure_manual_bridges()

    def test_ds_store_is_preserved_when_pilot_is_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "pilot"
            self.managed(target)
            (target / ".DS_Store").write_text("finder metadata")
            with mock.patch.object(pilot, "TARGET", target), mock.patch.object(pilot, "LOCK", Path(temp) / "pilot.lock"), \
                 mock.patch.object(pilot, "rebuild_cache"), mock.patch("sys.argv", ["pilot", "--remove"]):
                pilot.main()
            self.assertEqual((target / ".DS_Store").read_text(), "finder metadata")
            self.assertFalse((target / "example.editor.desktop").exists())

    def test_manual_bridge_merge_preserves_metadata_and_types(self):
        source = "[Desktop Entry]\nName=Editor\nMimeType=text/plain;application/json;\nCategories=Utility;\n"
        merged = pilot.merge_manual_bridge(source, {"text/plain", "text/x-python"})
        self.assertIn("MimeType=text/plain;application/json;text/x-python;\n", merged)
        self.assertIn("Categories=Utility;\n", merged)
        with self.assertRaises(RuntimeError):
            pilot.merge_manual_bridge(source, {"bad\nvalue"})

    def test_manual_links_switch_and_restore_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            source = root / "share/applications/example.editor.desktop"
            source.parent.mkdir(parents=True)
            source.write_text("[Desktop Entry]\nMimeType=text/plain;\n")
            target = Path(temp) / "Applications/Dolphin Open With Pilot"
            target.mkdir(parents=True)
            links = target.parent / "Dolphin Open With"
            links.mkdir()
            link = links / source.name
            link.symlink_to(source)
            merged = target / "example.editor.bridge"
            merged.write_text("merged")
            with mock.patch.multiple(pilot, ROOT=root, TARGET=target):
                pilot.sync_manual_links()
                self.assertEqual(link.resolve(), merged.resolve())
                merged.unlink()
                pilot.sync_manual_links()
                self.assertEqual(link.resolve(), source.resolve())
            self.assertEqual(len(list(links.iterdir())), 1)

    def test_sync_creates_missing_link_and_rejects_foreign_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            source = root / "share/applications/example.editor.desktop"
            source.parent.mkdir(parents=True)
            source.write_text("[Desktop Entry]\nMimeType=text/plain;\n")
            target = Path(temp) / "Applications/Dolphin Open With Pilot"
            links = target.parent / "Dolphin Open With"
            links.mkdir(parents=True)
            link = links / source.name
            other = source.parent / "example.other.desktop"
            other.write_text("[Desktop Entry]\nMimeType=text/plain;\n")
            (links / other.name).symlink_to(other)
            with mock.patch.multiple(pilot, ROOT=root, TARGET=target):
                pilot.sync_manual_links()
                self.assertEqual(link.resolve(), source.resolve())
                link.unlink()
                link.write_text("user file")
                with self.assertRaisesRegex(RuntimeError, "managed symlink"):
                    pilot.sync_manual_links()
                self.assertEqual(link.read_text(), "user file")

    def test_sync_checks_every_link_before_changing_any(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            sources = root / "share/applications"
            sources.mkdir(parents=True)
            first, second = sources / "a.first.desktop", sources / "b.second.desktop"
            for source in (first, second):
                source.write_text("[Desktop Entry]\nMimeType=text/plain;\n")
            target = Path(temp) / "Applications/Dolphin Open With Pilot"
            target.mkdir(parents=True)
            (target / "a.first.bridge").write_text("merged")
            links = target.parent / "Dolphin Open With"
            links.mkdir()
            (links / first.name).symlink_to(first)
            # Sorted after the first link: found only once the first would have changed.
            (links / second.name).write_text("user file")
            with mock.patch.multiple(pilot, ROOT=root, TARGET=target):
                with self.assertRaisesRegex(RuntimeError, "managed symlink"):
                    pilot.sync_manual_links()
            self.assertEqual((links / first.name).resolve(), first.resolve())
            self.assertEqual((links / second.name).read_text(), "user file")

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
            with mock.patch.object(pilot, "ensure_manual_bridges"), mock.patch.object(pilot, "TARGET", target), mock.patch.object(pilot, "LOCK", Path(temp) / "pilot.lock"), mock.patch.object(pilot.preview, "is_installed_app", return_value=True), \
                 mock.patch.object(pilot.subprocess, "run", side_effect=run), mock.patch("sys.argv", ["pilot", "--pilot"]):
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

    def test_empty_full_report_keeps_existing_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "pilot"
            self.managed(target)
            empty = {"matched": {}, "ambiguous": {}, "dynamic": {}, "unresolved": {}}
            output = subprocess.CompletedProcess(["swift"], 0, "{}")
            with mock.patch.object(pilot, "ensure_manual_bridges"), mock.patch.object(pilot, "TARGET", target), mock.patch.object(pilot, "LOCK", Path(temp) / "pilot.lock"), \
                 mock.patch.object(pilot.subprocess, "run", return_value=output), \
                 mock.patch.object(pilot.preview, "query_qt_types", return_value={}), \
                 mock.patch.object(pilot.preview, "make_report", return_value=empty), \
                 mock.patch("sys.argv", ["pilot", "--full"]):
                with self.assertRaisesRegex(RuntimeError, "No verified MIME"):
                    pilot.main()
            self.assertTrue((target / "example.editor.desktop").exists())

    def test_pilot_types_do_not_override_rejections(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "pilot"
            report = {"matched": {"txt": {"qtMimeType": "text/plain"}}, "ambiguous": {"py": {}},
                      "dynamic": {"pdf": {}}, "unresolved": {"mp4": {}}}
            output = subprocess.CompletedProcess(["swift"], 0, "{}")
            with mock.patch.object(pilot, "ensure_manual_bridges"), mock.patch.object(pilot, "TARGET", target), mock.patch.object(pilot, "LOCK", Path(temp) / "pilot.lock"), \
                 mock.patch.object(pilot.subprocess, "run", return_value=output), \
                 mock.patch.object(pilot.preview, "query_qt_types", return_value={}), \
                 mock.patch.object(pilot.preview, "make_report", return_value=report), \
                 mock.patch.object(pilot.preview, "build_associations", return_value={}) as build, \
                 mock.patch.object(pilot, "rebuild_cache"), mock.patch("sys.argv", ["pilot", "--full"]):
                pilot.main()
            types = build.call_args.args[2]
            for rejected in ("py", "pdf", "mp4"):
                self.assertNotIn(rejected, types)
            self.assertEqual(types["txt"], "text/plain")
            self.assertEqual(types["json"], "application/json")

    def test_unmanaged_directory_is_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "pilot"
            target.mkdir()
            (target / "user.txt").write_text("keep")
            with mock.patch.object(pilot, "ensure_manual_bridges"), mock.patch.object(pilot, "TARGET", target), mock.patch.object(pilot, "LOCK", Path(temp) / "pilot.lock"), mock.patch("sys.argv", ["pilot", "--remove"]):
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

    def test_interrupted_cleanup_is_finished_by_the_next_run(self):
        original_unlink = Path.unlink
        # Stop before the Nth removal: untouched, one bridge gone, and only the marker left.
        for removals in (0, 1, 2):
            with self.subTest(removals=removals), tempfile.TemporaryDirectory() as temp:
                target, paths = self.isolated(temp)
                self.managed(target, "example.current")
                leftover = target.parent / (pilot.TEMP_PREFIX + "abc")
                self.managed(leftover / "previous", "example.old")
                (leftover / "previous/example.older.desktop").write_text("[Desktop Entry]\nX-Dolphin-Pilot=true\n")
                count = 0

                def interrupting_unlink(path, *args, **kwargs):
                    nonlocal count
                    if count == removals:
                        raise KeyboardInterrupt
                    count += 1
                    return original_unlink(path, *args, **kwargs)

                with paths, mock.patch.object(pilot, "rebuild_cache"):
                    with mock.patch.object(Path, "unlink", interrupting_unlink), self.assertRaises(KeyboardInterrupt):
                        pilot.recover_leftovers()
                    self.assertTrue(leftover.exists())
                    pilot.recover_leftovers()
                self.assertFalse(leftover.exists())
                self.assertEqual(sorted(p.name for p in target.iterdir()), [pilot.MARKER, "example.current.desktop"])

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

    def test_recovery_tolerates_and_preserves_finder_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            self.managed(target)
            leftover = target.parent / (pilot.TEMP_PREFIX + "finder")
            self.managed(leftover / "previous")
            metadata = leftover / ".DS_Store"
            metadata.write_text("keep finder data")
            nested = leftover / "previous/.DS_Store"
            nested.write_text("keep nested data")
            with paths, mock.patch.object(pilot, "rebuild_cache") as rebuild:
                pilot.recover_leftovers()
                pilot.recover_leftovers()
            self.assertEqual(rebuild.call_count, 2)
            self.assertEqual(metadata.read_text(), "keep finder data")
            self.assertEqual(nested.read_text(), "keep nested data")

    def test_resolved_leftover_with_metadata_is_not_restored_after_pilot_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            target, paths = self.isolated(temp)
            self.managed(target)
            leftover = target.parent / (pilot.TEMP_PREFIX + "finder")
            self.managed(leftover / "previous", "example.old")
            (leftover / ".DS_Store").write_text("keep finder data")
            (leftover / "previous/.DS_Store").write_text("keep nested data")
            with paths, mock.patch.object(pilot, "rebuild_cache"):
                # First run resolves leftover while target exists.
                pilot.recover_leftovers()
                # Remove the active pilot installation.
                shutil.rmtree(target)
                self.assertFalse(target.exists())
                # Subsequent recovery must not restore the resolved previous version.
                pilot.recover_leftovers()
                self.assertFalse(target.exists())

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
                with self.assertRaisesRegex(RuntimeError, "Another Open With"):
                    pilot.main()
                update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
