"""Check KIO filter state handling without touching the real installation."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dolphin_config import Settings
from dolphin_store import Store, put_tree, write_json

spec = importlib.util.spec_from_file_location("kio_filter", ROOT / "install-kio-filter.py")
kio_filter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kio_filter)


class KioFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dolphin-kio-state-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root, "26.08.2")
        self.settings.craft.mkdir()
        self.store = Store(self.settings.backups)
        self.relative = f"lib/libKF6KIOWidgets.{kio_filter.KIO_VERSION}.dylib"

    def artifact(self, name, value):
        tree = self.root / name
        library = tree / self.relative
        library.parent.mkdir(parents=True)
        library.write_bytes(value)
        return self.store.save(tree)

    def test_library_reinstall_accepts_only_recorded_original_or_filter(self):
        baseline = self.artifact("baseline", b"original")
        filtered = self.artifact("filtered", b"filtered")
        state = dict(schema=1, version=kio_filter.KIO_VERSION, baseline=baseline,
                     installed=filtered, managed=[self.relative])
        for artifact in (baseline, filtered):
            tree, manifest = self.store.load(artifact)
            put_tree(self.settings.craft, tree, manifest, state["managed"])
            kio_filter.verify_current_library(self.settings, self.store, state)
        (self.settings.craft / self.relative).write_bytes(b"unexpected Craft change")
        with self.assertRaisesRegex(RuntimeError, "changed outside"):
            kio_filter.verify_current_library(self.settings, self.store, state)

    def test_missing_or_malformed_state_is_handled(self):
        path = self.settings.backups / "kio-filter/installation.json"
        self.assertIsNone(kio_filter.checked_state(path, kio_filter.KIO_VERSION))
        for invalid in ({}, {"schema": 1}, {"schema": 1, "version": "wrong", "baseline": "a", "installed": "b", "managed": []}):
            with self.subTest(state=invalid):
                write_json(path, invalid)
                with self.assertRaisesRegex(RuntimeError, "Invalid KIO"):
                    kio_filter.checked_state(path, kio_filter.KIO_VERSION)

    def test_setup_skips_only_an_explicitly_unsupported_version(self):
        library = self.settings.craft / "lib/libKF6KIOWidgets.6.32.0.dylib"
        library.parent.mkdir(parents=True)
        library.write_bytes(b"newer KIO")
        (library.parent / "libKF6KIOWidgets.6.dylib").symlink_to(library.name)
        with mock.patch.object(kio_filter, "load", return_value=self.settings), \
             mock.patch.object(sys, "argv", ["install-kio-filter.py", "--skip-unsupported"]), \
             contextlib.redirect_stderr(io.StringIO()) as warning:
            kio_filter.main()
            self.assertIn("filter was not installed", warning.getvalue())
            pending = self.settings.backups / "kio-filter/pendiente.json"
            pending.parent.mkdir(parents=True, exist_ok=True)
            pending.touch()
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                kio_filter.main()
            pending.unlink()
            library.unlink()
            with self.assertRaisesRegex(RuntimeError, "missing or invalid"):
                kio_filter.main()

    def test_active_library_must_point_to_expected_version(self):
        expected = self.settings.craft / self.relative
        expected.parent.mkdir(parents=True)
        expected.write_bytes(b"expected KIO")
        alias = expected.parent / "libKF6KIOWidgets.6.dylib"
        alias.symlink_to(expected.name)
        self.assertEqual(kio_filter.verify_library_version(self.settings), expected)
        other = expected.parent / "libKF6KIOWidgets.6.32.0.dylib"
        other.write_bytes(b"other KIO")
        alias.unlink()
        alias.symlink_to(other.name)
        with self.assertRaisesRegex(RuntimeError, "active KIO library"):
            kio_filter.verify_library_version(self.settings)


if __name__ == "__main__":
    unittest.main()
