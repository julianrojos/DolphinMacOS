"""Exercise Open With setup using isolated configuration and application paths."""
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
import importlib.util
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_menu", ROOT / "install-menu.py")
menu_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu_module)


class OpenWithTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dolphin-open-with-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Dolphin project ñ"
        self.root.mkdir()
        self.target = self.root / "applications with spaces é"
        self.config = self.root / "configuration with spaces ü"
        self.menu = self.config / "menus/applications-merged/dolphin-open-with.menu"
        self.script = self.root / "install-open-with.sh"
        original = (ROOT / "install-open-with.sh").read_text()
        assignment = 'TARGET="$HOME/Applications/Dolphin Open With"'
        self.assertEqual(original.count(assignment), 1)
        self.script.write_text(original.replace(assignment, f"TARGET={shlex.quote(str(self.target))}"))
        shutil.copy2(ROOT / "install-menu.py", self.root / "install-menu.py")
        self.bin = self.root / "CraftRoot/bin"
        self.bin.mkdir(parents=True)
        self.tool("qtpaths6", f"printf '%s\\n' {shlex.quote(str(self.config))}\n")
        self.cache_called = self.root / "cache-called"
        self.tool("kbuildsycoca6", f"touch {shlex.quote(str(self.cache_called))}\n")
        source = self.root / "share/applications"
        source.mkdir(parents=True)
        self.bridge = source / "test-app.desktop"
        self.bridge.write_text("[Desktop Entry]\nType=Application\nName=Test App\n")

    def tool(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def run_setup(self, *args):
        return subprocess.run(["zsh", str(self.script), *args], capture_output=True, text=True)

    def test_unmanaged_menu_preserves_links_in_both_modes(self):
        self.target.mkdir()
        old = self.target / "old.desktop"
        old.symlink_to(self.bridge)
        self.menu.parent.mkdir(parents=True)
        content = "<Menu><Name>Existing user menu</Name></Menu>"
        self.menu.write_text(content)
        for args in ((), ("--remove",)):
            with self.subTest(args=args):
                result = self.run_setup(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(old.is_symlink())
                self.assertFalse((self.target / self.bridge.name).exists())
                self.assertEqual(self.menu.read_text(), content)
                self.assertFalse(self.cache_called.exists())
                self.assertIn("configurar el menú de aplicaciones", result.stderr)

    def test_directory_at_menu_path_preserves_contents_and_links(self):
        self.menu.mkdir(parents=True)
        sentinel = self.menu / "keep.txt"
        sentinel.write_text("user content")
        self.target.mkdir()
        old = self.target / "old.desktop"
        old.symlink_to(self.bridge)
        for args in ((), ("--remove",)):
            with self.subTest(args=args):
                result = self.run_setup(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Se esperaba un archivo de menú normal", result.stderr)
                self.assertIn(str(self.menu), result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertTrue(self.menu.is_dir())
                self.assertEqual(sentinel.read_text(), "user content")
                self.assertTrue(old.is_symlink())
                self.assertFalse((self.target / self.bridge.name).exists())
                self.assertFalse(self.cache_called.exists())

    def test_install_and_remove_are_repeatable(self):
        for _ in range(2):
            result = self.run_setup()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.target / self.bridge.name).resolve(), self.bridge.resolve())
            self.assertIn("Managed by Dolphin", self.menu.read_text())
            self.assertTrue(self.cache_called.exists())
        for _ in range(2):
            result = self.run_setup("--remove")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.target / self.bridge.name).is_symlink())
            self.assertFalse(self.menu.exists())

    def test_invalid_arguments_have_no_side_effects(self):
        for args in (("--invalid",), ("--remove", "--invalid"), ("--help", "--remove")):
            result = self.run_setup(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.menu.exists())
            self.assertFalse(self.target.exists())
            self.assertFalse(self.cache_called.exists())

    def test_help_without_craft_has_no_side_effects(self):
        shutil.rmtree(self.root / "CraftRoot")
        result = self.run_setup("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--remove", result.stdout)
        self.assertIn("open-with-cache.log", result.stdout)
        self.assertFalse(self.menu.exists())
        self.assertFalse(self.target.exists())
        self.assertFalse((self.root / "run").exists())

    def test_identical_menu_is_not_rewritten_but_cache_is_rebuilt(self):
        self.assertEqual(self.run_setup().returncode, 0)
        before = self.menu.stat()
        self.cache_called.unlink()
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self.menu.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        self.assertTrue(self.cache_called.exists())

    def test_failed_atomic_replace_preserves_menu_and_cleans_temporary_file(self):
        self.menu.parent.mkdir(parents=True)
        original = f"<!-- {menu_module.MARKER} -->\nold content"
        self.menu.write_text(original)
        self.menu.chmod(0o640)
        with patch.object(menu_module.os, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaises(OSError):
                menu_module.write_menu(self.menu)
        self.assertEqual(self.menu.read_text(), original)
        self.assertEqual(list(self.menu.parent.iterdir()), [self.menu])
        menu_module.write_menu(self.menu)
        self.assertEqual(self.menu.read_text(), menu_module.CONTENT)
        self.assertEqual(self.menu.stat().st_mode & 0o777, 0o640)

    def test_new_menu_gets_the_mode_of_a_normally_created_file(self):
        self.menu.parent.mkdir(parents=True)
        previous = menu_module.os.umask(0o022)
        try:
            menu_module.write_menu(self.menu)
        finally:
            menu_module.os.umask(previous)
        self.assertEqual(self.menu.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.menu.read_text(), menu_module.CONTENT)

    def test_managed_menu_symlink_is_preserved(self):
        self.menu.parent.mkdir(parents=True)
        destination = self.root / "managed menu destination é"
        destination.write_text(f"<!-- {menu_module.MARKER} -->\nold content")
        self.menu.symlink_to(destination)
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.menu.is_symlink())
        self.assertEqual(destination.read_text(), menu_module.CONTENT)

    def test_missing_cache_tool_is_detected_before_menu_changes(self):
        (self.bin / "kbuildsycoca6").unlink()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.menu.exists())
        self.assertFalse(self.target.exists())

    def test_link_failure_identifies_step_and_can_be_retried(self):
        self.target.write_text("conflicting file")
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("actualizar los enlaces a las aplicaciones", result.stderr)
        self.assertEqual(self.target.read_text(), "conflicting file")
        self.assertFalse(self.cache_called.exists())
        self.target.unlink()
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cache_failure_keeps_diagnostic_log_and_can_be_retried(self):
        self.tool("kbuildsycoca6", "echo 'cache failure detail' >&2\nexit 1\n")
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regeneración de la caché", result.stderr)
        self.assertIn("cache failure detail", (self.root / "run/open-with-cache.log").read_text())
        self.tool("kbuildsycoca6", "exit 0\n")
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
