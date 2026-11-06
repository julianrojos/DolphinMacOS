"""Test association planning without consulting the local application database."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "tools/preview-macos-bridges.py"
spec = importlib.util.spec_from_file_location("bridge_preview", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PreviewTests(unittest.TestCase):
    def test_combines_types_for_the_same_bundle(self):
        app = {"bundleID": "example.editor", "name": "Editor"}
        result = module.build_associations({"txt": {"applications": [app]},
                                            "py": {"applications": [app, app]}})
        self.assertEqual(result, {"example.editor": {"name": "Editor", "mimeTypes": ["text/plain", "text/x-python"]}})

    def test_rejects_invalid_ids_and_unwanted_paths(self):
        apps = [{"bundleID": "../unsafe", "name": "Bad"}, {"bundleID": "example.ok", "name": "No"}]
        self.assertEqual(module.build_associations({"txt": {"applications": apps}}, lambda app: False), {})
        self.assertEqual(module.build_associations({"txt": {"applications": apps}}),
                         {"example.ok": {"name": "No", "mimeTypes": ["text/plain"]}})

    def test_excluded_first_copy_does_not_hide_a_valid_copy(self):
        copies = [{"bundleID": "example.editor", "name": "Old Editor", "path": "/Volumes/Backup/Editor.app"},
                  {"bundleID": "example.editor", "name": "Editor", "path": "/Applications/Editor.app"}]
        result = module.build_associations({"txt": {"applications": copies}},
                                           lambda app: app["path"].startswith("/Applications/"))
        self.assertEqual(result, {"example.editor": {"name": "Editor", "mimeTypes": ["text/plain"]}})

    def test_unknown_types_and_empty_results(self):
        self.assertEqual(module.build_associations({"unknown": {"applications": [{"bundleID": "x"}]}}), {})


if __name__ == "__main__":
    unittest.main()
