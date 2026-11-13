import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).with_name("check-quicklook-selection.py")
spec = importlib.util.spec_from_file_location("quicklook_selection_check", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ExtractMethodTests(unittest.TestCase):
    def test_extracts_only_the_requested_method(self):
        source = """void DolphinMainWindow::closeQuickLook()
{
    if (true) {
        close();
    }
}

void DolphinMainWindow::anotherMethod()
{
    unrelated();
}
#endif
"""
        result = check.extract_method(source, "closeQuickLook")
        self.assertTrue(result.endswith("\n}"))
        self.assertIn("close();", result)
        self.assertNotIn("anotherMethod", result)
        self.assertNotIn("#endif", result)

    def test_missing_method_reports_which_method_was_expected(self):
        with self.assertRaisesRegex(RuntimeError, "DolphinMainWindow::closeQuickLook"):
            check.extract_method("#endif\n", "closeQuickLook")


if __name__ == "__main__":
    unittest.main()
