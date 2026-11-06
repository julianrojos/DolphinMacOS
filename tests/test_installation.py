import json
import importlib.util
import io
import contextlib
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dolphin_config import Settings, load, read_json, check_version
import dolphin_install as installer
real_ensure_closed = installer.ensure_closed
spec = importlib.util.spec_from_file_location("cleanup", ROOT / "limpiar-copias.py")
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)
from dolphin_store import Store, collect, deploy, recover, verify_live, write_json


class InstallationTests(unittest.TestCase):
    def setUp(self):
        closed = patch.object(installer, "ensure_closed")
        closed.start()
        self.addCleanup(closed.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = Settings(self.root, load().version)
        self.craft = self.settings.craft
        self.craft.mkdir()
        self.store = Store(self.settings.backups)
        self.state_path = self.settings.backups / "instalacion.json"

    def tree(self, name, content, identifier=""):
        tree = self.root / name
        for relative in ("Applications/KDE/dolphin.app/Contents/MacOS/dolphin", "lib/library.dylib", "plugins/plugin.so"):
            destination = tree / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        (tree / "lib/alias.dylib").symlink_to("library.dylib")
        (tree / installer.INFO_PATH).write_bytes(plistlib.dumps({"CFBundleIdentifier": identifier}))
        return tree

    def managed_install(self):
        baseline = self.tree("baseline", b"source-original")
        modified = self.tree("modified", b"source-patched", "org.kde.dolphin")
        base_key, modified_key = self.store.save(baseline), self.store.save(modified)
        manifest = collect(modified)
        state = dict(schema=2, version=self.settings.version, baseline=base_key,
                     installed=modified_key, managed=sorted(manifest))
        deploy(self.craft, self.store, modified_key, state["managed"], self.state_path, state)
        return state, baseline, modified

    def test_snapshots_preserve_different_builds_and_detect_corruption(self):
        first = self.store.save(self.tree("first", b"A"))
        second = self.store.save(self.tree("second", b"B"))
        self.assertNotEqual(first, second)
        tree, _ = self.store.load(first)
        self.assertEqual((tree / "lib/library.dylib").read_bytes(), b"A")
        (tree / "lib/library.dylib").write_bytes(b"damaged")
        with self.assertRaisesRegex(RuntimeError, "dañada"):
            self.store.load(first)

    def test_deploy_replaces_executable_libraries_plugins_and_metadata(self):
        state, _, modified = self.managed_install()
        verify_live(self.craft, collect(modified), state["managed"])
        self.assertEqual((self.craft / "plugins/plugin.so").read_bytes(), b"source-patched")
        self.assertTrue((self.craft / "lib/alias.dylib").is_symlink())

    def test_failed_validation_rolls_back_all_files_and_state(self):
        self.managed_install()
        before, old_state = collect(self.craft), self.state_path.read_bytes()
        incoming = self.tree("incoming", b"new")
        (incoming / "new-file").write_text("new")
        key = self.store.save(incoming)
        managed = sorted(set(before) | set(collect(incoming)))
        def fail():
            raise RuntimeError("startup failed")
        with self.assertRaisesRegex(RuntimeError, "startup failed"):
            deploy(self.craft, self.store, key, managed, self.state_path, {"new": True}, fail)
        self.assertEqual(collect(self.craft), before)
        self.assertEqual(self.state_path.read_bytes(), old_state)
        self.assertFalse((self.settings.backups / "pendiente.json").exists())

    def test_recovery_of_interrupted_deployment(self):
        state, _, _ = self.managed_install()
        before = collect(self.craft)
        before_key = self.store.save(self.craft)
        incoming = self.tree("interrupted-target", b"interrupted")
        target_key = self.store.save(incoming)
        (self.craft / "plugins/plugin.so").write_bytes(b"interrupted")
        write_json(self.settings.backups / "pendiente.json", dict(before=before_key, target=target_key, managed=state["managed"], prior_state=state))
        recover(self.craft, self.store, self.state_path)
        self.assertEqual(collect(self.craft), before)
        self.assertEqual(read_json(self.state_path), state)

    def test_recovery_rejects_external_changes_without_partial_restore(self):
        state, _, _ = self.managed_install()
        before_key = self.store.save(self.craft)
        target = self.tree("recovery-target", b"target")
        target_key = self.store.save(target)
        (self.craft / "plugins/plugin.so").write_bytes(b"external")
        pending = self.settings.backups / "pendiente.json"
        write_json(pending, dict(before=before_key, target=target_key, managed=state["managed"], prior_state=state))
        before = collect(self.craft)
        with self.assertRaisesRegex(RuntimeError, "cambio externo"):
            recover(self.craft, self.store, self.state_path)
        self.assertEqual(collect(self.craft), before)
        self.assertTrue(pending.exists())
        del_data = read_json(pending)
        del del_data["target"]
        write_json(pending, del_data)
        with self.assertRaisesRegex(RuntimeError, "registro de recuperación es antiguo"):
            recover(self.craft, self.store, self.state_path)
        self.assertEqual(collect(self.craft), before)

    def test_patched_library_is_not_adopted_if_executable_changes(self):
        state, _, _ = self.managed_install()
        original_baseline = state["baseline"]
        (self.craft / installer.APP_PATH / "Contents/MacOS/dolphin").write_bytes(b"resigned")
        with patch.object(installer, "load", return_value=self.settings), patch.object(installer, "build_artifact") as build:
            with self.assertRaisesRegex(RuntimeError, "ha cambiado"):
                installer.main([])
            build.assert_not_called()
        self.assertEqual(read_json(self.state_path)["baseline"], original_baseline)

    def test_metadata_restore_uses_original_source_plist_and_keeps_patch(self):
        state, baseline, _ = self.managed_install()
        original = (baseline / installer.INFO_PATH).read_bytes()
        with patch.object(installer, "load", return_value=self.settings), \
             patch.object(installer, "sign_tree"), patch.object(installer, "run"), \
             patch.object(installer, "check_version"):
            installer.main(["--restaurar-metadatos"])
            self.assertEqual((self.craft / installer.INFO_PATH).read_bytes(), original)
            self.assertEqual((self.craft / "lib/library.dylib").read_bytes(), b"source-patched")
            installer.main(["--metadatos"])
            installer.main(["--metadatos"])
            installer.main(["--restaurar-metadatos"])
            self.assertEqual((self.craft / installer.INFO_PATH).read_bytes(), original)
        self.assertEqual(read_json(self.state_path)["baseline"], state["baseline"])

    def test_metadata_points_dock_launches_at_craft_data(self):
        tree = self.tree("metadata", b"x")
        installer.set_metadata(tree, self.settings.version, installer.data_dirs(self.settings))
        data = plistlib.loads((tree / installer.INFO_PATH).read_bytes())
        self.assertEqual(data["CFBundleIdentifier"], "org.kde.dolphin")
        self.assertEqual(data["LSEnvironment"], {"QT_DATA_DIRS": str(self.craft / "share")})

    def test_complete_restore_uses_unpatched_source_artifact(self):
        _, baseline, _ = self.managed_install()
        with patch.object(installer, "load", return_value=self.settings), patch.object(installer, "run"), patch.object(installer, "check_version"):
            installer.main(["--restaurar"])
        self.assertEqual(collect(self.craft), collect(baseline))

    def test_incomplete_or_invalid_manifests_are_rejected(self):
        for content in ("{", "[]", "{}", '{"schema":2}'):
            with self.subTest(content=content):
                self.state_path.write_text(content)
                with self.assertRaises(RuntimeError):
                    installer.load_state(self.settings)

    def test_wrong_binary_version_is_rejected(self):
        result = subprocess.CompletedProcess([], 0, "dolphin 99.0\n", "")
        with patch("dolphin_config.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "Versión instalada inesperada"):
                check_version(Path("fake"), self.settings.version)

    def copy_patches(self):
        shutil.copytree(load().patch_dir, self.settings.patch_dir)

    def copy_patched_sources(self):
        """Copy every file touched by the patches; return their relative paths."""
        real = load()
        filenames = sorted({Path(line[len("+++ b/"):].strip()) for patch_file in real.patches
                            for line in patch_file.read_text().splitlines() if line.startswith("+++ b/")})
        for filename in filenames:
            destination = self.settings.source / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(real.source / filename, destination)
        self.copy_patches()
        return filenames

    def source_contents(self, filenames):
        return {name: (self.settings.source / name).read_bytes() for name in filenames}

    def test_patch_toggling_does_not_guess_direction(self):
        filenames = self.copy_patched_sources()
        self.assertGreater(len(self.settings.patches), 1)
        installer.ensure_patch(self.settings, False)
        original = self.source_contents(filenames)
        installer.ensure_patch(self.settings, False)
        self.assertEqual(self.source_contents(filenames), original)
        installer.ensure_patch(self.settings, True)
        modified = self.source_contents(filenames)
        for name in filenames:
            self.assertNotEqual(modified[name], original[name])
        installer.ensure_patch(self.settings, True)
        self.assertEqual(self.source_contents(filenames), modified)

    def test_old_row_patch_is_migrated_and_reverted(self):
        filenames = self.copy_patched_sources()
        installer.ensure_patch(self.settings, False)
        original = self.source_contents(filenames)
        legacy = self.settings.patch_dir / "legacy/0001-accessibility-row-count.patch"
        subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(legacy)],
                       cwd=self.settings.source, check=True, capture_output=True)
        installer.ensure_patch(self.settings, False)
        self.assertEqual(self.source_contents(filenames), original)
        subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(legacy)],
                       cwd=self.settings.source, check=True, capture_output=True)
        installer.ensure_patch(self.settings, True)
        self.assertTrue(installer.patch_applies(self.settings, self.settings.patches[0], reverse=True))
        installer.ensure_patch(self.settings, False)
        self.assertEqual(self.source_contents(filenames), original)

    def test_legacy_patch_does_not_hide_unrelated_source_changes(self):
        filenames = self.copy_patched_sources()
        installer.ensure_patch(self.settings, False)
        legacy = self.settings.patch_dir / "legacy/0001-accessibility-row-count.patch"
        subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(legacy)],
                       cwd=self.settings.source, check=True, capture_output=True)
        source = self.settings.source / "src/kitemviews/accessibility/kitemlistviewaccessible.cpp"
        source.write_text(source.read_text().replace("return accessibleDelegate(columnCount() * row + column);", "return nullptr;"))
        before = self.source_contents(filenames)
        with self.assertRaisesRegex(RuntimeError, "no coincide"):
            installer.ensure_patch(self.settings, True)
        self.assertEqual(self.source_contents(filenames), before)

    def test_sources_with_an_earlier_patch_set_are_upgraded_and_reverted(self):
        filenames = self.copy_patched_sources()
        installer.ensure_patch(self.settings, False)
        original = self.source_contents(filenames)
        installer.ensure_patch(self.settings, True)
        modified = self.source_contents(filenames)
        for applied in range(1, len(self.settings.patches)):
            with self.subTest(applied=applied):
                installer.ensure_patch(self.settings, False)
                # Sources prepared before the later fixes existed.
                for patch_file in self.settings.patches[:applied]:
                    subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(patch_file)],
                                   cwd=self.settings.source, check=True, capture_output=True)
                partial = self.source_contents(filenames)
                self.assertNotIn(partial, (original, modified))
                installer.ensure_patch(self.settings, True)
                self.assertEqual(self.source_contents(filenames), modified)
                installer.ensure_patch(self.settings, False)
                for patch_file in self.settings.patches[:applied]:
                    subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(patch_file)],
                                   cwd=self.settings.source, check=True, capture_output=True)
                installer.ensure_patch(self.settings, False)
                self.assertEqual(self.source_contents(filenames), original)

    def test_unknown_sources_stop_at_the_mismatching_patch(self):
        filenames = self.copy_patched_sources()
        installer.ensure_patch(self.settings, False)
        target = self.settings.source / "src/kitemviews/kitemlistcontainer.cpp"
        target.write_text(target.read_text().replace("setAccessibleFocusAndAnnounceAll", "renamedUpstream"))
        before = self.source_contents(filenames)
        with self.assertRaisesRegex(RuntimeError, "no coincide"):
            installer.ensure_patch(self.settings, True)
        # Earlier patches stay applied (a later run detects them), the mismatching
        # patch and the ones after it are not applied.
        changed = {name for name in filenames if self.source_contents(filenames)[name] != before[name]}
        self.assertEqual(changed, {Path("src/kitemviews/accessibility/kitemlistviewaccessible.cpp")})

    def test_cli_configuration_errors_are_clear(self):
        for name in ("parchear-dolphin.py", "configurar-app.py", "limpiar-copias.py", "dolphin_config.py", "dolphin_install.py", "dolphin_store.py"):
            shutil.copy2(ROOT / name, self.root / name)
        (self.root / "dolphin-version.json").write_text('{"version":"99.0.0"}')
        for command in ("parchear-dolphin.py", "configurar-app.py", "limpiar-copias.py", "dolphin_config.py"):
            result = subprocess.run([sys.executable, str(self.root / command)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no tiene un parche", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_setup_uses_cache_only_for_dependencies_and_installs_complete_build(self):
        for name in ("setup.sh", "dolphin_config.py", "dolphin-version.json"):
            shutil.copy2(ROOT / name, self.root / name)
        self.copy_patches()
        craft = self.craft / "craft"
        craft.mkdir()
        (craft / "craftenv.sh").write_text('''
craft() {
    print -r -- "$*" >> "$ROOT/actions.log"
    if [[ "$*" == "--no-cache --configure dolphin" ]]; then
        mkdir -p "$SOURCE/src/kitemviews/accessibility" "$BUILD"
        touch "$SOURCE/src/kitemviews/accessibility/kitemlistviewaccessible.cpp" "$BUILD/CMakeCache.txt"
    fi
}
''')
        (self.root / "parchear-dolphin.py").write_text('from pathlib import Path\np=Path(__file__).parent\nassert (p/"CraftRoot/build/kde/applications/dolphin/work/build/CMakeCache.txt").exists()\n(p/"complete-install-called").touch()\n')
        # Stub: the real script writes to ~/Applications.
        open_with = self.root / "install-open-with.sh"
        open_with.write_text('#!/bin/zsh\ntest -f "${0:A:h}/complete-install-called"\ntouch "${0:A:h}/open-with-called"\n')
        open_with.chmod(0o755)
        (self.root / "install-kio-filter.py").write_text('from pathlib import Path\np=Path(__file__).parent\nassert (p/"open-with-called").exists()\n(p/"kio-filter-called").touch()\n')
        # Stub: the real script reloads the launchd D-Bus agent.
        dbus_fix = self.root / "fix-dbus-service.sh"
        dbus_fix.write_text('#!/bin/zsh\ntouch "${0:A:h}/dbus-fix-called"\n')
        dbus_fix.chmod(0o755)
        self.settings.build.mkdir(parents=True)
        (self.settings.build / "CMakeCache.txt").write_text("CMAKE_HOME_DIRECTORY:INTERNAL=/previous/source\n")
        result = subprocess.run(["zsh", str(self.root / "setup.sh")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        actions = (self.root / "actions.log").read_text().splitlines()
        self.assertIn("--install-deps dolphin", actions)
        self.assertNotIn("dolphin", actions)
        for action in ("fetch", "unpack", "configure"):
            self.assertIn(f"--no-cache --{action} dolphin", actions)
        self.assertTrue((self.root / "complete-install-called").exists())
        self.assertTrue((self.root / "open-with-called").exists())
        self.assertTrue((self.root / "kio-filter-called").exists())
        self.assertTrue((self.root / "dbus-fix-called").exists())
        archived = list((self.root / "bootstrap").glob("build-anterior.*/build/CMakeCache.txt"))
        self.assertEqual(len(archived), 1)
        self.assertIn("/previous/source", archived[0].read_text())

    def test_running_detection_handles_absolute_relative_and_bare_paths(self):
        for command in (str(self.settings.app / "Contents/MacOS/dolphin"), "./Applications/KDE/dolphin.app/Contents/MacOS/dolphin", "dolphin"):
            with self.subTest(command=command), patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, f"123 {command}\n", "")):
                with self.assertRaisesRegex(RuntimeError, "está abierto"):
                    real_ensure_closed(self.settings)
        with patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "123 /usr/bin/other\n", "")):
            real_ensure_closed(self.settings)

    def test_reinstall_recovers_after_external_change_without_adopting_it(self):
        state, baseline, corrected = self.managed_install()
        modified_exe = self.craft / installer.APP_PATH / "Contents/MacOS/dolphin"
        modified_exe.write_bytes(b"changed by Craft")
        before = collect(self.craft)
        with patch.object(installer, "load", return_value=self.settings), patch.object(installer, "validate_sources"), \
             patch.object(installer, "build_artifact", side_effect=[state["baseline"], state["installed"]]), \
             patch.object(installer, "run"), patch.object(installer, "check_version"):
            installer.main(["--reinstalar"])
        self.assertEqual(collect(self.craft), collect(corrected))
        self.assertEqual(read_json(self.state_path)["baseline"], state["baseline"])
        self.assertTrue(any(self.store.load(path.name)[1] == before for path in self.store.root.iterdir()))

    def test_dolphin_opened_during_build_blocks_deploy(self):
        state, _, _ = self.managed_install()
        before, old_state = collect(self.craft), self.state_path.read_bytes()
        opened = RuntimeError("Dolphin está abierto.")
        with patch.object(installer, "load", return_value=self.settings), patch.object(installer, "validate_sources"), \
             patch.object(installer, "build_artifact", side_effect=[state["baseline"], state["installed"]]), \
             patch.object(installer, "ensure_closed", side_effect=[None, opened]), \
             patch.object(installer, "deploy") as deploy:
            with self.assertRaisesRegex(RuntimeError, "está abierto"):
                installer.main([])
            deploy.assert_not_called()
        self.assertEqual(collect(self.craft), before)
        self.assertEqual(self.state_path.read_bytes(), old_state)

    def test_cleanup_initial_migration_protects_every_existing_copy(self):
        self.managed_install()
        old = self.store.save(self.tree("uncertain-original", b"possibly Craft"))
        copies, histories, pins = cleanup.plan(self.settings)
        self.assertEqual(copies, [])
        self.assertEqual(histories, [])
        self.assertIn(old, pins["artifacts"])
        with patch.object(cleanup, "load", return_value=self.settings), contextlib.redirect_stdout(io.StringIO()):
            cleanup.main(["--aplicar"])
        self.assertEqual(read_json(self.settings.backups / "protegidas.json"), pins)
        self.store.load(old)

    def test_cleanup_preview_matches_apply_and_preserves_pins(self):
        state, _, _ = self.managed_install()
        old = self.store.save(self.tree("pinned-original", b"Craft snapshot"))
        pins = dict(artifacts=[old, state["baseline"], state["installed"]], history=[])
        write_json(self.settings.backups / "protegidas.json", pins)
        for index in range(7):
            self.store.save(self.tree(f"extra-{index}", str(index).encode()))
            write_json(self.settings.backups / "historial" / f"extra-{index}.json", state)
        copies, histories, _ = cleanup.plan(self.settings)
        self.assertTrue(copies)
        self.assertTrue(histories)
        output = io.StringIO()
        with patch.object(cleanup, "load", return_value=self.settings), contextlib.redirect_stdout(output):
            cleanup.main([])
            for path in copies + histories:
                self.assertTrue(path.exists())
                self.assertIn(str(path), output.getvalue())
            cleanup.main(["--aplicar"])
        self.assertTrue(all(not path.exists() for path in copies + histories))
        self.store.load(old)
        self.store.load(state["baseline"])
        self.store.load(state["installed"])

    def test_cleanup_rejects_pending_missing_install_and_damaged_history(self):
        with self.assertRaisesRegex(RuntimeError, "registrada"):
            cleanup.plan(self.settings)
        state, _, _ = self.managed_install()
        pending = self.settings.backups / "pendiente.json"
        pending.write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "pendiente"):
            cleanup.plan(self.settings)
        pending.unlink()
        (self.settings.backups / "historial/bad.json").write_text("{")
        with self.assertRaisesRegex(RuntimeError, "JSON"):
            cleanup.plan(self.settings)

    def test_cleanup_preserves_active_kio_filter_and_pending_recovery(self):
        state, _, _ = self.managed_install()
        kio_original = self.store.save(self.tree("kio-original", b"original KIO"))
        kio_filtered = self.store.save(self.tree("kio-filtered", b"filtered KIO"))
        write_json(self.settings.backups / "protegidas.json", {"artifacts": [kio_original], "history": []})
        write_json(self.settings.backups / "kio-filter/installation.json",
                   {"schema": 1, "baseline": kio_original, "installed": kio_filtered})
        for index in range(4):
            self.store.save(self.tree(f"later-{index}", str(index).encode()))
        candidates, _, _ = cleanup.plan(self.settings)
        self.assertNotIn(self.store.root / kio_original, candidates)
        self.assertNotIn(self.store.root / kio_filtered, candidates)
        with patch.object(cleanup, "load", return_value=self.settings):
            with self.assertRaisesRegex(RuntimeError, "instalación activa"):
                cleanup.main(["--quitar-proteccion", f"copia:{kio_original}"])
        pending = self.settings.backups / "kio-filter/pendiente.json"
        pending.write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "pendiente"):
            cleanup.plan(self.settings)

    def test_cleanup_lock_failure_has_clear_error(self):
        self.managed_install()
        with patch.object(cleanup, "load", return_value=self.settings), patch.object(cleanup.fcntl, "flock", side_effect=BlockingIOError):
            with self.assertRaisesRegex(RuntimeError, "en curso"):
                cleanup.main([])

    def test_list_protections_is_read_only_and_marks_active_references(self):
        state, _, _ = self.managed_install()
        output = io.StringIO()
        before = collect(self.settings.backups)
        with patch.object(cleanup, "load", return_value=self.settings), contextlib.redirect_stdout(output):
            cleanup.main(["--listar-protecciones"])
        # La consulta puede crear el archivo de bloqueo, nunca el registro.
        after = collect(self.settings.backups)
        before.pop("instalacion.lock", None)
        after.pop("instalacion.lock", None)
        self.assertEqual(before, after)
        self.assertFalse((self.settings.backups / "protegidas.json").exists())
        self.assertIn(f"copia:{state['baseline']}", output.getvalue())
        self.assertIn("no retirable", output.getvalue())

    def test_active_protections_cannot_be_removed(self):
        state, _, _ = self.managed_install()
        for key in {state["baseline"], state["installed"]}:
            with patch.object(cleanup, "load", return_value=self.settings):
                with self.assertRaisesRegex(RuntimeError, "instalación activa"):
                    cleanup.main(["--quitar-proteccion", f"copia:{key}"])
        self.assertFalse((self.settings.backups / "protegidas.json").exists())

    def test_remove_protection_preserves_data_and_other_references(self):
        state, _, _ = self.managed_install()
        old = self.store.save(self.tree("old-protected", b"old"))
        _, _, initial_pins = cleanup.plan(self.settings)
        with patch.object(cleanup, "load", return_value=self.settings), contextlib.redirect_stdout(io.StringIO()):
            cleanup.main(["--quitar-proteccion", f"copia:{old}"])
        pins = read_json(self.settings.backups / "protegidas.json")
        self.assertNotIn(old, pins["artifacts"])
        self.assertEqual(set(pins["artifacts"]), set(initial_pins["artifacts"]) - {old})
        self.assertEqual(pins["history"], initial_pins["history"])
        self.store.load(old)
        self.store.load(state["baseline"])

    def test_protected_history_retains_its_artifacts_after_manual_unpin(self):
        import os
        state, _, _ = self.managed_install()
        old = self.store.save(self.tree("historical-artifact", b"old reference"))
        old_history = self.settings.backups / "historial/old.json"
        write_json(old_history, dict(state, baseline=old, installed=old))
        os.utime(old_history, ns=(1, 1))
        os.utime(self.store.root / old, ns=(1, 1))
        for index in range(4):
            self.store.save(self.tree(f"new-{index}", str(index).encode()))
            write_json(self.settings.backups / f"historial/recent-{index}.json", state)
        write_json(self.settings.backups / "protegidas.json", dict(artifacts=[old], history=[old_history.name]))
        with patch.object(cleanup, "load", return_value=self.settings), contextlib.redirect_stdout(io.StringIO()):
            cleanup.main(["--quitar-proteccion", f"copia:{old}"])
            self.assertNotIn(self.store.root / old, cleanup.plan(self.settings)[0])
            cleanup.main(["--quitar-proteccion", f"historial:{old_history.name}"])
        artifacts, histories, _ = cleanup.plan(self.settings)
        self.assertIn(self.store.root / old, artifacts)
        self.assertIn(old_history, histories)
        self.store.load(old)
        self.assertTrue(old_history.exists())

    def test_unpin_rejects_unknown_ids_and_incompatible_modes(self):
        self.managed_install()
        with patch.object(cleanup, "load", return_value=self.settings):
            for identifier in ("unknown", "copia:not-registered", "historial:../outside.json"):
                with self.assertRaises(RuntimeError):
                    cleanup.main(["--quitar-proteccion", identifier])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cleanup.main(["--quitar-proteccion", "copia:x", "--aplicar"])

    def test_cli_manifest_errors_are_clear(self):
        for name in ("parchear-dolphin.py", "configurar-app.py", "dolphin_config.py", "dolphin_install.py", "dolphin_store.py", "dolphin-version.json"):
            shutil.copy2(ROOT / name, self.root / name)
        self.copy_patches()
        for content in ("{", "{}", '{"schema":2}'):
            self.state_path.write_text(content)
            for command in ("parchear-dolphin.py", "configurar-app.py"):
                result = subprocess.run([sys.executable, str(self.root / command)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertTrue("JSON" in result.stderr or "manifiesto" in result.stderr)


if __name__ == "__main__":
    unittest.main()
