"""Exercise report honesty and portability using isolated, synthetic fixtures."""

import contextlib
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("controlled_testing_report", SKILL / "scripts" / "report.py")
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "中文 path"
        shutil.copytree(SKILL / "assets" / "report-example", self.root)
        self.run = self.root / "run.json"
        self.data = json.loads(self.run.read_text(encoding="utf-8"))
        self.prototype = deepcopy(self.data["cases"][0]["attempts"][0])

    def real(self):
        self.data["is_demo"] = False
        self.data["build"]["artifact_sha256"] = "0" * 64
        self.data["desktop"] = {"authorization": "synthetic unit fixture", "target": "no live process",
                                "limits": "no real input", "stop": "no real input"}
        self.data["attachments"][0]["kind"] = "desktop_screenshot"
        return self.data

    def all_pass(self):
        self.real()
        for case in self.data["cases"]:
            case["attempts"] = [deepcopy(self.prototype)]
        return self.data

    def call(self, *extra):
        self.run.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = report.main([str(self.run), *extra])
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_demo_never_passes_acceptance(self):
        self.assertEqual("Demo", report.conclusion(self.data))
        self.assertEqual(1, self.call("--require-pass")[0])

    def test_diagnosis_success_does_not_hide_product_failure(self):
        self.real()
        report.validate(self.data, self.root)
        self.assertEqual("Failed", report.conclusion(self.data))
        self.assertEqual({"passed": 0, "total": 1, "outside": 0}, report.summary(self.data)["coverage"]["combination"])

    def test_required_cases_are_conjunctive(self):
        self.real()
        self.data["coverage"][0]["required_case_ids"] = ["UI-01", "UI-03"]
        self.assertEqual(0, report.summary(self.data)["coverage"]["requirement"]["passed"])

    def test_deferred_remains_visible_and_limits_claim(self):
        self.all_pass()
        report.validate(self.data, self.root)
        self.assertEqual("PassedWithinScope", report.conclusion(self.data))
        self.assertEqual({"passed": 1, "total": 1, "outside": 1}, report.summary(self.data)["coverage"]["resource"])
        self.assertEqual(0, self.call("--require-pass")[0])

    def test_complete_scope_can_pass_and_counts_keep_diagnosis_separate(self):
        self.all_pass()
        self.data["coverage"] = [i for i in self.data["coverage"] if i["scope"] == "in"]
        report.validate(self.data, self.root)
        info = report.summary(self.data)
        self.assertEqual("Passed", info["conclusion"])
        self.assertEqual({"Passed": 3}, info["acceptance"])
        self.assertEqual({"Passed": 1}, info["diagnostic"])
        self.assertEqual(0, self.call("--require-pass")[0])

    def test_missing_case_or_incomplete_inventory_is_incomplete(self):
        self.all_pass()
        self.data["cases"][2]["attempts"] = []
        self.assertEqual("Incomplete", report.conclusion(self.data))
        self.all_pass()
        self.data["inventory"]["complete"] = False
        self.assertEqual("Incomplete", report.conclusion(self.data))

    def test_empty_acceptance_is_not_success(self):
        self.all_pass()
        self.data["coverage"] = []
        self.data["cases"] = []
        self.assertEqual("Incomplete", report.conclusion(self.data))

    def test_blocked_error_and_notrun_do_not_pass(self):
        for value, expected in (("Blocked", "Incomplete"), ("Error", "Failed"), ("NotRun", "Incomplete")):
            with self.subTest(value=value):
                self.all_pass()
                attempt = self.data["cases"][0]["attempts"][0]
                attempt.update(status=value, reason="synthetic cause")
                report.validate(self.data, self.root)
                self.assertEqual(expected, report.conclusion(self.data))

    def test_last_success_keeps_previous_failure_and_blocks_clean_pass(self):
        self.all_pass()
        case = self.data["cases"][0]
        failed = deepcopy(case["attempts"][0])
        failed.update(id="A0", status="Failed", reason="first observation differs")
        case["attempts"].insert(0, failed)
        report.validate(self.data, self.root)
        self.assertEqual("Passed", report.state(case))
        self.assertEqual("Incomplete", report.conclusion(self.data))
        self.assertEqual(0, report.summary(self.data)["coverage"]["requirement"]["passed"])
        self.assertIn("稳定性待复核", report.render_html(self.data))
        self.assertIn("first observation differs", report.render_markdown(self.data))

    def test_diagnostic_cannot_satisfy_coverage(self):
        self.data["coverage"][0]["required_case_ids"] = ["DIAG-01"]
        with self.assertRaisesRegex(report.ReportError, "Diagnostic"):
            report.validate(self.data, self.root)

    def test_duplicate_and_unknown_ids_are_invalid(self):
        original = deepcopy(self.data)
        self.data["cases"].append(deepcopy(self.data["cases"][0]))
        with self.assertRaisesRegex(report.ReportError, "Duplicate"):
            report.validate(self.data, self.root)
        self.data = original
        self.data["coverage"][0]["required_case_ids"] = ["MISSING"]
        with self.assertRaisesRegex(report.ReportError, "Unknown"):
            report.validate(self.data, self.root)

    def test_missing_evidence_rejected(self):
        (self.root / "images" / "expected.svg").unlink()
        self.assertEqual(2, self.call()[0])

    def test_absolute_traversal_and_hash_mismatch_rejected(self):
        original = self.data["attachments"][0]["path"]
        for value in ("../outside.png", "C:/Windows/win.ini", "//host/share/a.png"):
            with self.subTest(value=value), self.assertRaises(report.ReportError):
                self.data["attachments"][0]["path"] = value
                report.validate(self.data, self.root)
        self.data["attachments"][0]["path"] = original
        self.data["attachments"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(report.ReportError, "hash mismatch"):
            report.validate(self.data, self.root)

    def test_export_is_not_real_desktop_evidence(self):
        self.real()
        self.data["attachments"][0]["kind"] = "native_export"
        with self.assertRaisesRegex(report.ReportError, "real screenshot"):
            report.validate(self.data, self.root)

    def test_pass_requires_actual_review_and_evidence(self):
        original = deepcopy(self.data)
        for update in ({"evidence": []}, {"review": {"outcome": "matched", "note": ""}}, {"review": {"outcome": "different", "note": "diff"}}):
            self.data = deepcopy(original)
            self.data["cases"][0]["attempts"][0].update(update)
            with self.subTest(update=update), self.assertRaises(report.ReportError):
                report.validate(self.data, self.root)

    def test_real_fingerprints_and_takeover_records_required(self):
        self.real()
        self.data["build"]["artifact_sha256"] = "unknown"
        with self.assertRaisesRegex(report.ReportError, "SHA256"):
            report.validate(self.data, self.root)
        self.data["build"]["artifact_sha256"] = "0" * 64
        self.data["events"] = []
        with self.assertRaisesRegex(report.ReportError, "notification"):
            report.validate(self.data, self.root)

    def test_dates_and_status_must_be_valid(self):
        self.data["cases"][0]["attempts"][0]["status"] = "unknown"
        with self.assertRaisesRegex(report.ReportError, "status"):
            report.validate(self.data, self.root)
        self.data["cases"][0]["attempts"][0]["status"] = "Passed"
        self.data["events"][0]["at"] = "2026-10-29T10:00:00"
        with self.assertRaisesRegex(report.ReportError, "timezone"):
            report.validate(self.data, self.root)

    def test_lifecycle_must_release_desktop_before_final_pass(self):
        self.all_pass()
        self.data["control"] = "desktop"
        self.assertEqual("Incomplete", report.conclusion(self.data))

    def test_reports_escape_text_and_encode_portable_paths(self):
        self.data["title"] = '<script>alert("bad")</script>'
        old = self.root / self.data["attachments"][0]["path"]
        new = old.with_name("参考 #1.svg")
        old.rename(new)
        self.data["attachments"][0]["path"] = "images/参考 #1.svg"
        report.validate(self.data, self.root)
        html = report.render_html(self.data)
        self.assertNotIn(self.data["title"], html)
        self.assertIn("%23", html)
        self.assertIn("%23", report.render_markdown(self.data))

    def test_check_is_read_only_and_generation_is_repeatable(self):
        self.run.write_text(json.dumps(self.data), encoding="utf-8")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, report.main([str(self.run), "--check"]))
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(0, self.call()[0])
        rendered = (self.root / "report.html").read_bytes()
        self.assertEqual(0, self.call()[0])
        self.assertEqual(rendered, (self.root / "report.html").read_bytes())


if __name__ == "__main__":
    unittest.main()
