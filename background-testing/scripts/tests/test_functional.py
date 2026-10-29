"""Functional profile and cancellation invariants, using synthetic files only."""

from copy import deepcopy
import base64
import contextlib
import io
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location("testing_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report, session, desktop = load("report"), load("session"), load("desktop_guard")


class FunctionalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "功能检查"
        shutil.copytree(SCRIPTS.parent / "assets" / "report-example", self.root)
        self.path = self.root / "run.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.data.update(profile="functional-v1", phase="inventory", control="background", events=[])
        self.data["inventory"]["dimensions"] = [{"id": "width", "title": "宽度",
            "strategy": "synthetic boundary", "selected": [{"value": "2400", "case_ids": ["UI-01"]}], "uncovered": []}]
        for case in self.data["cases"]:
            case["attempts"] = []
            case["expected"]["checks"] = [{"id": "width", "description": "总宽", "target": 2400,
                                             "unit": "mm", "tolerance": .01}]
        session.event(self.data, "inventory", "synthetic inventory notice")
        session.event(self.data, "planning", "synthetic planning notice")
        session.freeze(self.path, self.data)
        session.event(self.data, "preflight", "synthetic preflight notice")
        session.event(self.data, "finished", "synthetic final notice")

    def attempt(self, case=None):
        case = case or self.data["cases"][0]
        value = {"id": "A1", "at": session.now(), "status": "Passed", "observed": "synthetic numeric width",
                 "evidence": ["expected"], "review": {"outcome": "matched", "note": "synthetic criteria check"},
                 "checks": [{"id": "width", "value": 2400, "status": "Passed"}]}
        case["attempts"] = [value]
        return value

    def test_valid_profile_and_readable_criteria(self):
        self.attempt()
        report.validate(self.data, self.root)
        self.assertIn("| 总宽 | 2400 mm | 2400 | 通过 |", report.render_markdown(self.data))
        self.assertIn("<th>检查点</th>", report.render_html(self.data))

    def test_changed_expected_or_parameters_is_rejected(self):
        for field, value in (("parameters", {"width_mm": 1650}),
                             ("expected", {"source": "changed", "description": "changed", "checks": []})):
            original = deepcopy(self.data["cases"][0][field])
            self.data["cases"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(report.ReportError, "Plan changed"):
                report.validate(self.data, self.root)
            self.data["cases"][0][field] = original

    def test_plan_cannot_be_replaced_or_frozen_after_execution(self):
        with self.assertRaises(ValueError):
            session.freeze(self.path, self.data)
        self.data.pop("plan")
        self.attempt()
        with self.assertRaisesRegex(ValueError, "before execution"):
            session.freeze(self.path, self.data)

    def test_numeric_mismatch_cannot_be_labelled_passed(self):
        actual = self.attempt()
        for value in (1650, True, float("nan")):
            actual["checks"][0]["value"] = value
            with self.subTest(value=value), self.assertRaisesRegex(report.ReportError, "differs from target"):
                report.validate(self.data, self.root)

    def test_missing_or_failed_criterion_cannot_pass(self):
        actual = self.attempt()
        actual["checks"] = []
        with self.assertRaisesRegex(report.ReportError, "missing criteria"):
            report.validate(self.data, self.root)
        actual["checks"] = [{"id": "width", "value": 1650, "status": "Failed"}]
        with self.assertRaisesRegex(report.ReportError, "non-passing"):
            report.validate(self.data, self.root)

    def test_incomplete_lifecycle_cannot_be_accepted(self):
        self.data["events"] = self.data["events"][1:]
        with self.assertRaisesRegex(report.ReportError, "Missing lifecycle"):
            report.validate(self.data, self.root)

    def test_pause_requires_explicit_resume_and_finish_is_terminal(self):
        data = {"phase": "desktop", "control": "desktop", "events": [],
                "desktop": {"authorization": "synthetic"}}
        session.event(data, "paused", "pause notice")
        with self.assertRaisesRegex(ValueError, "Resume"):
            session.event(data, "desktop", "not authorized")
        session.event(data, "desktop", "explicit resume notice", True)
        session.event(data, "finished", "release notice")
        with self.assertRaisesRegex(ValueError, "Finished"):
            session.event(data, "desktop", "reopen")

    def test_historical_evidence_is_labelled(self):
        actual = self.attempt()
        actual.update(evidence_origin="historical", evidence_run="prior-run", reuse_reason="matched input and build")
        report.validate(self.data, self.root)
        self.assertIn("历史证据：prior-run", report.render_markdown(self.data))

    def test_markdown_metadata_remains_json_not_html_entities(self):
        markdown = report.render_markdown(self.data)
        self.assertIn('```json\n{\n  "width_mm": 2400', markdown)
        self.assertNotIn("&quot;", markdown)


class FakeBackend:
    def __init__(self):
        self.focus = 20
        self.active = True
        self.ticks = 123
        self.sent = []
        self.after_down = None

    def start_ticks(self, pid): return self.ticks
    def is_window(self, hwnd): return self.active
    def window_pid(self, hwnd): return 10 if hwnd == 20 else 99
    def enabled(self, hwnd): return True
    def minimized(self, hwnd): return False
    def window_at(self, x, y): return 20
    def title(self, hwnd): return "fixture"
    def foreground(self): return self.focus
    def root(self, hwnd): return hwnd
    def activate(self, hwnd): self.focus = hwnd
    def mouse(self, x, y, up=False): self.sent.append(("mouse", up))

    def send_key(self, key, up=False, unicode=False):
        self.sent.append((key, up, unicode))
        if not up and self.after_down:
            self.after_down()


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.json"
        self.backend = FakeBackend()
        self.guard = desktop.DesktopGuard({"pid": 10, "start_ticks": 123, "root_hwnd": 20}, self.path, self.backend)
        self.state("desktop", "desktop")

    def state(self, phase, control):
        session.atomic_json(self.path, {"phase": phase, "control": control})

    def test_pause_mid_text_stops_next_character_and_releases_first(self):
        self.backend.after_down = lambda: self.state("paused", "paused")
        with self.assertRaises(desktop.InputStopped):
            self.guard.text("abc", 0)
        self.assertEqual([(97, False, True), (97, True, True)], self.backend.sent)

    def test_lost_focus_stops_without_reactivation(self):
        self.backend.focus = 99
        with self.assertRaisesRegex(desktop.InputStopped, "Focus"):
            self.guard.text("abc", 0)
        self.assertEqual([], self.backend.sent)
        self.assertEqual(99, self.backend.focus)

    def test_held_modifier_released_when_guard_stops(self):
        self.backend.after_down = lambda: self.state("paused", "paused")
        with self.assertRaises(desktop.InputStopped):
            self.guard.key(65, (17,))
        self.assertEqual([(17, False, False), (17, True, False)], self.backend.sent)

    def test_wrong_identity_or_missing_state_refuses_input(self):
        self.backend.ticks = 456
        with self.assertRaisesRegex(desktop.InputStopped, "identity"):
            self.guard.check()
        self.path.unlink()
        with self.assertRaisesRegex(desktop.InputStopped, "state unavailable"):
            self.guard.check()

    def test_unknown_modal_refuses_input(self):
        self.backend.enabled = lambda hwnd: False
        with self.assertRaisesRegex(desktop.InputStopped, "modal"):
            self.guard.check()
        self.assertEqual([], self.backend.sent)

    def test_minimized_window_refuses_input(self):
        self.backend.minimized = lambda hwnd: True
        with self.assertRaisesRegex(desktop.InputStopped, "minimized"):
            self.guard.text("abc", 0)
        self.assertEqual([], self.backend.sent)

    def test_off_target_click_is_not_sent(self):
        self.backend.window_at = lambda x, y: 99
        with self.assertRaisesRegex(desktop.InputStopped, "outside"):
            self.guard.click(10, 10)
        self.assertEqual([], self.backend.sent)

    def test_cli_payload_preserves_quotes_unicode_and_newlines(self):
        value = '(setvar "FILEDIA" 0)\n中文 \\ path "quoted"'
        payload = base64.b64encode(value.encode("utf-8")).decode("ascii")
        with patch.object(desktop, "DesktopGuard") as adapter, contextlib.redirect_stdout(io.StringIO()):
            result = desktop.main([str(self.path), str(self.path), "text", "--value-base64=" + payload])
        self.assertEqual(0, result)
        adapter.return_value.text.assert_called_once_with(value)

    def test_cli_stop_stays_paused_across_calls_without_faking_notice(self):
        with patch.object(desktop, "DesktopGuard") as adapter, contextlib.redirect_stdout(io.StringIO()):
            adapter.return_value.text.side_effect = desktop.InputStopped("simulated focus loss")
            self.assertEqual(2, desktop.main([str(self.path), str(self.path), "text", "abc"]))
        data = json.loads(self.path.read_text())
        self.assertEqual(("paused", "paused"), (data["phase"], data["control"]))
        self.assertFalse(data["input_stops"][0]["chat_notice_recorded"])
        self.assertNotIn("events", data)
        with self.assertRaisesRegex(desktop.InputStopped, "paused"):
            self.guard.acquire()


if __name__ == "__main__":
    unittest.main()
