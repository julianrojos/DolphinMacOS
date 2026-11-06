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

    def test_report_compares_qt_and_macos_families(self):
        globs = ("50:text/html:*.html\n50:application/xhtml+xml:*.html\n"
                 "50:text/x-src:*.ts\n50:video/mp2t:*.ts\n"
                 "50:application/x-unknown:*.foo\n50:application/x-tar:*.tar.gz\n")
        app = [{"bundleID": "example.editor"}]
        results = {"html": {"isDynamic": False, "families": ["text"], "applications": app},
                   "ts": {"isDynamic": False, "families": ["video"], "applications": app},
                   "foo": {"isDynamic": True, "families": [], "applications": app}}
        report = module.make_report(globs, results, {"html": {"mime": "text/html", "text": True}, "ts": {"mime": "text/x-src", "text": True}, "foo": {"mime": "application/x-unknown", "text": False}})
        self.assertIn("html", report["matched"])
        self.assertIn("ts", report["ambiguous"])
        self.assertIn("foo", report["dynamic"])
        self.assertEqual(report["unsupportedPatterns"][0]["pattern"], "*.tar.gz")

    def test_application_types_use_qt_text_inheritance(self):
        globs = ("50:application/x-tgif:*.obj\n50:model/obj:*.obj\n"
                 "50:application/json:*.json\n50:application/x-shellscript:*.sh\n")
        app = [{"bundleID": "example.editor"}]
        mac = {ext: {"isDynamic": False, "families": ["text"], "applications": app}
               for ext in ("obj", "json", "sh")}
        qt = {"obj": {"mime": "application/x-tgif", "text": False},
              "json": {"mime": "application/json", "text": True},
              "sh": {"mime": "application/x-shellscript", "text": True}}
        report = module.make_report(globs, mac, qt)
        self.assertIn("obj", report["ambiguous"])
        self.assertIn("json", report["matched"])
        self.assertIn("sh", report["matched"])

    def test_uncomparable_families_require_matching_mime(self):
        globs = "50:application/x-cisco-vpn-settings:*.pcf\n50:application/pdf:*.pdf\n"
        app = [{"bundleID": "example.viewer"}]
        mac = {"pcf": {"isDynamic": False, "families": ["text"], "preferredMIMEType": "text/x-pkl", "applications": app},
               "pdf": {"isDynamic": False, "families": [], "preferredMIMEType": "application/pdf", "applications": app}}
        qt = {"pcf": {"mime": "application/x-cisco-vpn-settings", "text": False},
              "pdf": {"mime": "application/pdf", "text": False, "macMime": "application/pdf"}}
        report = module.make_report(globs, mac, qt)
        self.assertIn("pcf", report["ambiguous"])
        qt["pcf"]["text"] = True
        self.assertIn("pcf", module.make_report(globs, mac, qt)["ambiguous"])
        self.assertIn("pdf", report["matched"])
        qt["pdf"]["macMime"] = ""
        self.assertIn("pdf", module.make_report(globs, mac, qt)["unresolved"])

    def test_missing_macos_mime_is_accepted_unless_known_conflict(self):
        globs = "50:application/x-cd-image:*.iso\n50:image/x-hdr:*.pic\n"
        app = [{"bundleID": "example.viewer"}]
        mac = {"iso": {"isDynamic": False, "families": [], "preferredMIMEType": None, "applications": app},
               "pic": {"isDynamic": False, "families": ["image"], "preferredMIMEType": "image/pict", "applications": app}}
        qt = {"iso": {"mime": "application/x-cd-image", "text": False},
              "pic": {"mime": "image/x-hdr", "text": False}}
        report = module.make_report(globs, mac, qt)
        self.assertIn("iso", report["matched"])
        self.assertIn("reason", report["matched"]["iso"])
        self.assertIn("pic", report["ambiguous"])

    def test_same_family_rejects_a_different_known_type_but_not_another_name(self):
        globs = "50:video/mp4:*.f4v\n50:text/x-python:*.py\n50:text/html:*.html\n"
        app = [{"bundleID": "example.app"}]
        mac = {"f4v": {"isDynamic": False, "families": ["video"], "preferredMIMEType": "video/x-flv", "applications": app},
               "py": {"isDynamic": False, "families": ["text"], "preferredMIMEType": "text/x-python-script", "applications": app},
               "html": {"isDynamic": False, "families": ["text"], "preferredMIMEType": "text/html", "applications": app}}
        qt = {"f4v": {"mime": "video/mp4", "text": False, "macMime": "video/x-flv"},
              # Qt does not know text/x-python-script: the name resolves to nothing.
              "py": {"mime": "text/x-python", "text": True, "macMime": ""},
              "html": {"mime": "text/html", "text": True, "macMime": "text/html"}}
        report = module.make_report(globs, mac, qt)
        self.assertIn("f4v", report["ambiguous"])
        self.assertIn("reason", report["ambiguous"]["f4v"])
        self.assertIn("py", report["matched"])
        self.assertIn("html", report["matched"])

    def test_canonical_alias_and_case_matches_do_not_accept_other_formats(self):
        app = [{"bundleID": "example.viewer"}]
        globs = "50:application/gzip:*.gz\n50:application/x-pagemaker:*.pm\n"
        mac = {"gz": {"isDynamic": False, "families": [], "preferredMIMEType": "application/x-gzip", "applications": app},
               "pm": {"isDynamic": False, "families": [], "preferredMIMEType": "text/x-perl", "applications": app}}
        qt = {"gz": {"mime": "application/gzip", "text": False, "macMime": "APPLICATION/GZIP"},
              "pm": {"mime": "application/x-pagemaker", "text": False, "macMime": "text/x-perl"}}
        report = module.make_report(globs, mac, qt)
        self.assertIn("gz", report["matched"])
        self.assertIn("pm", report["unresolved"])

    def test_report_rejects_missing_apps_or_qt_type(self):
        globs = "50:application/x-test:*.test\n"
        for result in ({"isDynamic": False, "applications": []}, None):
            report = module.make_report(globs, {"test": result}, {"test": {"mime": "application/x-test", "text": False}})
            self.assertIn("test", report["unresolved"])

    def test_unknown_types_and_empty_results(self):
        self.assertEqual(module.build_associations({"unknown": {"applications": [{"bundleID": "x"}]}}), {})


if __name__ == "__main__":
    unittest.main()
