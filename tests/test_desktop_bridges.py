"""Static checks for the .desktop bridges in share/applications."""
import configparser
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[1]
BRIDGES = sorted((ROOT / "share/applications").glob("*.desktop"))
EXEC = re.compile(r"^/usr/bin/open -b (?P<bundle>[A-Za-z0-9.-]+) %F$")
MIME = re.compile(r"^[a-z]+/[A-Za-z0-9.+-]+$")


def read_entry(path):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str  # .desktop keys are case sensitive
    parser.read(path, encoding="utf-8")
    return parser["Desktop Entry"]


def installed_app(bundle):
    if not shutil.which("mdfind"):
        return None
    result = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{bundle}'"],
                            capture_output=True, text=True, timeout=30)
    return result.stdout.strip() or None


class DesktopBridgeTests(unittest.TestCase):
    def test_relevant_apps_are_associated_with_text_pdf_and_video(self):
        expected = {
            "text/plain": {"com.apple.TextEdit"},
            "application/pdf": {"com.apple.Preview"},
            "video/mp4": {"com.apple.QuickTimePlayerX", "com.colliderli.iina", "org.videolan.vlc"},
        }
        for mime, apps in expected.items():
            with self.subTest(mime=mime):
                actual = {path.stem for path in BRIDGES if mime in read_entry(path).get("MimeType", "").split(";")}
                self.assertEqual(actual, apps)

    def test_bridges_exist(self):
        self.assertTrue(BRIDGES)

    def test_each_bridge_is_complete(self):
        for path in BRIDGES:
            with self.subTest(bridge=path.name):
                entry = read_entry(path)
                self.assertEqual(entry.get("Type"), "Application")
                self.assertTrue(entry.get("Name"))
                match = EXEC.match(entry.get("Exec", ""))
                self.assertIsNotNone(match, "Exec must be '/usr/bin/open -b <bundle id> %F'")
                # The file name is the bundle id, so each app has one bridge.
                self.assertEqual(path.stem, match["bundle"])
                types = entry.get("MimeType", "")
                self.assertTrue(types.endswith(";"))
                mimes = [t for t in types.split(";") if t]
                self.assertTrue(mimes)
                for mime in mimes:
                    self.assertRegex(mime, MIME)
                self.assertEqual(len(mimes), len(set(mimes)))
                # Hand-curated bridges include verified categories for grouped menus.
                self.assertTrue([c for c in entry.get("Categories", "").split(";") if c])
                self.assertEqual(entry.get("Terminal"), "false")

    def test_bridged_apps_are_installed(self):
        # Warn instead of failing: the bridges should not depend on what this
        # Mac has installed, but a typo in a bundle id should be visible.
        for path in BRIDGES:
            bundle = path.stem
            if installed_app(bundle) is None:
                warnings.warn(f"{path.name}: no installed app with bundle id {bundle}")


if __name__ == "__main__":
    unittest.main()
