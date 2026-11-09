"""Smoke test: every shell and Python script must at least parse, without running it."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL_SCRIPTS = sorted(ROOT.glob("*.sh"))
PYTHON_SCRIPTS = sorted([*ROOT.glob("*.py"), *(ROOT / "tools").glob("*.py"), *(ROOT / "tests").glob("*.py")])


class ScriptSyntaxTests(unittest.TestCase):
    def test_shell_scripts_parse_with_their_own_interpreter(self):
        self.assertTrue(SHELL_SCRIPTS)
        for script in SHELL_SCRIPTS:
            with self.subTest(script=script.name):
                interpreter = Path(script.read_text().splitlines()[0].removeprefix("#!").split()[0]).name
                self.assertIn(interpreter, ("zsh", "bash", "sh"))
                shell = shutil.which(interpreter)
                self.assertIsNotNone(shell, f"{interpreter} is not installed")
                result = subprocess.run([shell, "-n", str(script)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_scripts_compile(self):
        self.assertTrue(PYTHON_SCRIPTS)
        for script in PYTHON_SCRIPTS:
            with self.subTest(script=script.name):
                # compile() does not write a __pycache__ file or run the script.
                compile(script.read_text(), str(script), "exec")


if __name__ == "__main__":
    unittest.main()
