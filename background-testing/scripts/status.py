"""Read only this skill's native Codex switch; never print other config values."""

import argparse
import json
import ntpath
from pathlib import Path
import sys
import tomllib


class StateError(ValueError):
    """The switch cannot be determined unambiguously."""


def normalize_path(value):
    return ntpath.normcase(ntpath.normpath(str(value)))


def read_status(config_path, main_skill):
    try:
        config = tomllib.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raise StateError("Cannot read valid UTF-8 TOML config.") from None
    skills = config.get("skills", {})
    if not isinstance(skills, dict):
        raise StateError("Invalid skills config table.")
    entries = skills.get("config", [])
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        raise StateError("Invalid skills.config entries.")
    target = normalize_path(main_skill)
    matches = [
        e for e in entries
        if isinstance(e.get("path"), str) and normalize_path(e["path"]) == target
    ]
    if len(matches) > 1:
        raise StateError("Duplicate entries for background-testing.")
    enabled = True
    if matches:
        enabled = matches[0].get("enabled")
        if type(enabled) is not bool:
            raise StateError("Skill enabled must be a boolean.")
    return {"skill": "background-testing", "configured": bool(matches), "enabled": enabled}


def main(argv=None):
    installed_script = Path(__file__).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=installed_script.parents[3] / "config.toml")
    parser.add_argument("--main-skill", type=Path, default=installed_script.parents[1] / "SKILL.md")
    args = parser.parse_args(argv)
    try:
        result = read_status(args.config, args.main_skill)
    except StateError as error:
        print(json.dumps({"skill": "background-testing", "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
