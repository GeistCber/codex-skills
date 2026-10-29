"""Record already-sent notices and freeze a functional test plan; sends no input."""

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path


CONTROLS = {"inventory": "background", "planning": "background", "preflight": "background",
            "desktop": "desktop", "supplement": "background", "fixing": "background",
            "reporting": "released", "paused": "paused", "finished": "released"}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def plan_payload(data):
    return {"project": data["project"], "inventory": data["inventory"], "inputs": data["inputs"],
            "build": data["build"], "coverage": data["coverage"],
            "cases": [{key: case.get(key) for key in
                       ("id", "title", "purpose", "method", "parameters", "preconditions", "steps", "expected")}
                      for case in data["cases"]]}


def event(data, phase, notice, resume_authorized=False):
    if phase not in CONTROLS or not notice.strip():
        raise ValueError("A known phase and an already-sent notice are required")
    if data.get("phase") == "finished":
        raise ValueError("Finished runs are immutable; start a linked run")
    if data.get("control") == "paused" and phase not in {"paused", "finished"} and not resume_authorized:
        raise ValueError("Resume needs an explicit user instruction or agreed condition")
    if phase == "desktop" and not data.get("desktop", {}).get("authorization", "").strip():
        raise ValueError("Desktop authorization is missing")
    item = {"at": now(), "phase": phase, "control": CONTROLS[phase], "notice": notice}
    if resume_authorized:
        item["resume_authorized"] = True
    data.setdefault("events", []).append(item)
    data.update(phase=phase, control=CONTROLS[phase])
    return item


def freeze(run_path, data):
    if data.get("profile") != "functional-v1":
        raise ValueError("Freeze is for profile=functional-v1")
    if data.get("plan") or any(c.get("attempts") for c in data["cases"]):
        raise ValueError("Freeze before execution; existing plans cannot be replaced")
    if not any(e["phase"] == "planning" for e in data.get("events", [])):
        raise ValueError("Record the planning notice before freezing")
    target = Path(run_path).parent / "plan.json"
    if target.exists():
        raise ValueError("Plan already exists")
    frozen_at = now()
    atomic_json(target, {"frozen_at": frozen_at, "payload": plan_payload(data)})
    data["plan"] = {"path": "plan.json", "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "frozen_at": frozen_at}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    transition = sub.add_parser("event")
    transition.add_argument("--phase", choices=CONTROLS, required=True)
    transition.add_argument("--notice", required=True, help="Summary of a notice already sent in chat")
    transition.add_argument("--resume-authorized", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.run.read_text(encoding="utf-8-sig"))
        if args.command == "freeze":
            freeze(args.run, data)
        else:
            event(data, args.phase, args.notice, args.resume_authorized)
        atomic_json(args.run, data)
        print(json.dumps({"phase": data["phase"], "control": data["control"],
                          "plan": data.get("plan")}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
