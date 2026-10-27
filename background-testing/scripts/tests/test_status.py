"""Switch checks use temporary config files, never the user's real switch."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "status.py"
SPEC = importlib.util.spec_from_file_location("background_testing_status", SCRIPT)
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)
TARGET = r"C:\Users\Laptop\.codex\skills\background-testing\SKILL.md"


def entry(enabled, path=TARGET):
    return f"[[skills.config]]\npath = '{path}'\nenabled = {enabled}\n"


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "config.toml"

    def read(self, content):
        self.config.write_text(content, encoding="utf-8")
        before = self.config.read_bytes()
        result = status.read_status(self.config, TARGET)
        self.assertEqual(before, self.config.read_bytes())
        return result

    def test_enabled_and_disabled(self):
        for value in (True, False):
            with self.subTest(value=value):
                result = self.read(entry(str(value).lower()))
                self.assertIs(result["enabled"], value)
                self.assertTrue(result["configured"])

    def test_missing_entry_uses_default(self):
        self.assertEqual(self.read(""), {
            "skill": "background-testing", "configured": False, "enabled": True,
        })

    def test_unrelated_git_switch_is_ignored_and_not_disclosed(self):
        content = entry("false", TARGET.replace("background-testing", "github-sync-on-complete"))
        content += "\n[private]\ncredential = 'do-not-disclose'\n"
        result = self.read(content)
        self.assertFalse(result["configured"])
        self.assertTrue(result["enabled"])
        self.assertNotIn("do-not-disclose", json.dumps(result))

    def test_windows_path_variants(self):
        variant = TARGET.upper().replace("\\", "/").replace("/SKILL.MD", "/./SKILL.MD")
        self.assertFalse(self.read(entry("false", variant))["enabled"])

    def test_duplicate_windows_paths_fail(self):
        content = entry("true") + entry("false", TARGET.lower().replace("\\", "/"))
        with self.assertRaisesRegex(status.StateError, "Duplicate"):
            self.read(content)

    def test_missing_and_non_boolean_enabled_fail(self):
        for content in (entry("'false'"), entry("1"), entry("true").replace("enabled = true\n", "")):
            with self.subTest(content=content), self.assertRaisesRegex(status.StateError, "boolean"):
                self.read(content)

    def test_invalid_table_shapes_fail(self):
        for content in ("skills = 1", "[skills]\nconfig = 'bad'", "[skills]\nconfig = [1]"):
            with self.subTest(content=content), self.assertRaises(status.StateError):
                self.read(content)

    def test_invalid_toml_does_not_disclose_content(self):
        with self.assertRaises(status.StateError) as caught:
            self.read("credential = do-not-disclose")
        self.assertNotIn("do-not-disclose", str(caught.exception))

    def test_missing_and_invalid_encoding_fail(self):
        with self.assertRaises(status.StateError):
            status.read_status(self.config, TARGET)
        self.config.write_bytes(b"\xff\xfe")
        with self.assertRaises(status.StateError):
            status.read_status(self.config, TARGET)

    def test_utf8_bom(self):
        self.config.write_text(entry("false"), encoding="utf-8-sig")
        self.assertFalse(status.read_status(self.config, TARGET)["enabled"])

    def test_cli_reports_json_and_failure_exit(self):
        for content, expected_code in ((entry("false"), 0), ("secret = invalid-secret", 2)):
            self.config.write_text(content, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = status.main(["--config", str(self.config), "--main-skill", TARGET])
            self.assertEqual(expected_code, code)
            self.assertNotIn("invalid-secret", out.getvalue() + err.getvalue())
            result = json.loads(out.getvalue() if code == 0 else err.getvalue())
            self.assertEqual("background-testing", result["skill"])
            if code == 0:
                self.assertFalse(result["enabled"])
                self.assertEqual("", err.getvalue())
            else:
                self.assertIn("error", result)
                self.assertEqual("", out.getvalue())


if __name__ == "__main__":
    unittest.main()
