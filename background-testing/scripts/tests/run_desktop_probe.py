"""Explicit opt-in live Windows guard tests against owned, disposable test windows."""

import argparse
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from desktop_guard import DesktopGuard, InputStopped, WindowsBackend
from session import atomic_json, event, now


def until(read, accept, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = read()
            if accept(value):
                return value
        except (OSError, ValueError):
            pass
        time.sleep(.07)
    raise TimeoutError("Probe state did not reach the expected condition")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-desktop", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.allow_desktop:
        parser.error("Explicit --allow-desktop and a desktop notice are required")
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    plan = ["normal input", "quoted Unicode transport", "minimized input refused", "off-target click refused", "pause mid-input", "unauthorized resume rejected", "explicit resume",
            "unexpected same-process window", "unknown modal", "identity mismatch", "target exit"]
    atomic_json(root / "control-plan.json", {"at": now(), "expected": plan,
                "scope": "Synthetic fault injection into owned real windows; no user apps"})
    state_path = root / "control.json"
    state = {"phase": "desktop", "control": "desktop", "events": [],
             "desktop": {"authorization": "Explicit skill-control rehearsal; simulated pause/resume"}}
    atomic_json(state_path, state)
    log = (root / "probe-host.log").open("w", encoding="utf-8")
    process = subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-File",
                 str(Path(__file__).with_name("desktop_probe.ps1")), "-OutputDirectory", str(root)],
                 stdout=log, stderr=log, creationflags=0x08000000)
    backend = WindowsBackend()
    results = []

    def read():
        return json.loads((root / "probe-state.json").read_text(encoding="utf-8-sig"))

    def command(action):
        token = str(time.monotonic_ns())
        atomic_json(root / "probe-command.json", {"id": token, "action": action})
        if action == "close":
            process.wait(timeout=8)
            return
        until(lambda: (root / "probe-ack.txt").read_text(), lambda value: value == token)

    def screenshot(name):
        from PIL import ImageGrab
        time.sleep(.4)
        ImageGrab.grab().save(root / (name + ".png"))

    def record(name, passed, detail):
        results.append({"id": name, "passed": passed, "detail": detail, "at": now()})
        atomic_json(root / "control-results.json", results)
        print(name + " " + str(passed), flush=True)

    def refuses(action):
        try:
            action()
        except InputStopped as error:
            return str(error)
        raise AssertionError("Expected input refusal")

    try:
        snapshot = until(read, lambda value: bool(value.get("Root")))
        manifest = {"pid": process.pid, "start_ticks": backend.start_ticks(process.pid),
                    "root_hwnd": snapshot["Root"], "title_contains": "Controlled testing probe"}
        atomic_json(root / "target.json", manifest)
        guard = DesktopGuard(manifest, state_path, backend)
        guard.acquire()
        guard.text("Normal-123", .02)
        value = until(read, lambda value: value["Text"] == "Normal-123")
        screenshot("01-normal")
        record("normal", True, value["Text"])

        payload = 'Quotes: "资源" \\ path'
        command("clear-text")
        until(read, lambda value: value["Text"] == "")
        done = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(SCRIPTS / "windows_uia.ps1"), "-Action", "Type", "-Manifest", str(root / "target.json"),
            "-State", str(state_path), "-ValueBase64", base64.b64encode(payload.encode("utf-8")).decode("ascii"),
            "-AllowDesktopInput"], capture_output=True, timeout=15, creationflags=0x08000000)
        value = until(read, lambda value: value["Text"] == payload)
        record("transport", done.returncode == 0, value["Text"])
        command("clear-text")
        until(read, lambda value: value["Text"] == "")
        guard.text("Normal-123")
        until(read, lambda value: value["Text"] == "Normal-123")

        backend.user.ShowWindow(manifest["root_hwnd"], 6)
        reason = refuses(lambda: guard.text("MINIMIZED"))
        record("minimized", read()["Text"] == "Normal-123", reason)
        guard.acquire()
        reason = refuses(lambda: guard.click(0, 0))
        record("off-target", read()["Text"] == "Normal-123", reason)

        def pause():
            # Fault injection, not a claim that the human issued a pause request.
            event(state, "paused", "Simulated pause during an input sequence")
            atomic_json(state_path, state)

        timer = threading.Timer(.12, pause)
        timer.start()
        reason = refuses(lambda: guard.text("X" * 100, .025))
        timer.join()
        time.sleep(.2)
        paused_text = read()["Text"]
        refuses(lambda: guard.text("SHOULD-NOT-APPEAR"))
        time.sleep(.1)
        record("pause", paused_text == read()["Text"] and len(paused_text) < 110, reason)
        try:
            event(state, "desktop", "No resume authority")
            record("resume-gate", False, "Unexpected resume")
        except ValueError as error:
            record("resume-gate", True, str(error))
        event(state, "desktop", "Simulated explicit resume for the control test", True)
        atomic_json(state_path, state)
        guard.acquire()
        guard.text("-Resumed")
        until(read, lambda value: value["Text"].endswith("-Resumed"))
        screenshot("02-resumed")
        record("resume", True, read()["Text"])

        command("focus-other")
        original = read()["Text"]
        reason = refuses(lambda: guard.text("WRONG-WINDOW"))
        screenshot("03-focus-refused")
        record("focus", read()["Text"] == original and backend.foreground() != manifest["root_hwnd"], reason)
        command("restore")
        guard.acquire()
        command("modal")
        reason = refuses(lambda: guard.text("UNKNOWN-MODAL"))
        screenshot("04-modal-refused")
        record("modal", read()["Text"] == original, reason)
        command("restore")
        guard.acquire()
        manifest["start_ticks"] += 1
        reason = refuses(lambda: guard.text("WRONG-PROCESS"))
        manifest["start_ticks"] -= 1
        record("identity", read()["Text"] == original, reason)
        command("close")
        process.wait(timeout=8)
        reason = refuses(lambda: guard.text("AFTER-EXIT"))
        record("exit", True, reason)
        event(state, "finished", "Control rehearsal finished; owned windows closed")
        atomic_json(state_path, state)
    except Exception as error:
        try:
            snapshot = read()
        except Exception:
            snapshot = "unavailable"
        record("executor", False, repr(error) + "; snapshot=" + str(snapshot))
    finally:
        if process.poll() is None:
            try:
                command("close")
                process.wait(timeout=5)
            except Exception:
                # Popen owns this exact child; never terminate by process name.
                process.terminate()
        log.close()
    return int(len(results) != 11 or not all(item["passed"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
