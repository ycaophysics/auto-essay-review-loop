#!/usr/bin/env python3
"""
migrate_run_json_add_skill.py - backfill skill field on RUN.json manifests.

Idempotent walk of review-stage/**/RUN.json. Infers skill from run directory
path when missing (same patterns as infer_skill_from_path) and writes it back.
No-op when skill is already present.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.report_adapters import infer_skill_from_path

TOOL_NAME = "migrate_run_json_add_skill"
SCHEMA_VERSION = 1
DEFAULT_ROOT = "review-stage"


def find_run_json_files(root: Path) -> list[Path]:
    return sorted(root.glob("**/RUN.json"))


def migrate_file(run_json: Path) -> dict:
    """Migrate one RUN.json. Returns a check record."""
    run_dir = run_json.parent

    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return {
            "name": "parse_run_json",
            "passed": False,
            "path": str(run_json),
            "detail": str(exc),
            "flag": "invalid_run_json",
        }

    existing = data.get("skill")
    if existing:
        return {
            "name": "skill_already_present",
            "passed": True,
            "path": str(run_json),
            "detail": f"skill={existing!r} (no-op)",
            "skill": existing,
        }

    inferred = infer_skill_from_path(run_dir)
    if not inferred:
        return {
            "name": "skill_not_inferred",
            "passed": False,
            "path": str(run_json),
            "detail": f"could not infer skill from {run_dir}",
            "flag": "skill_not_inferred",
        }

    data["skill"] = inferred
    run_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "name": "skill_backfilled",
        "passed": True,
        "path": str(run_json),
        "detail": f"wrote skill={inferred!r}",
        "skill": inferred,
    }


def parse_args(argv: list[str]) -> Path:
    root = Path(DEFAULT_ROOT)
    for arg in argv[1:]:
        if arg.startswith("--root="):
            root = Path(arg.split("=", 1)[1])
        elif arg in ("-h", "--help"):
            raise SystemExit(
                "usage: migrate_run_json_add_skill.py [--root=review-stage]"
            )
    return root


def main(argv: list[str]) -> int:
    try:
        root = parse_args(argv)
    except SystemExit as exc:
        result = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "passed": False,
            "checks": [],
            "flags": ["argument_error"],
            "summary": str(exc),
        }
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 2

    if not root.exists():
        result = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "passed": True,
            "checks": [],
            "flags": [],
            "summary": f"root {root} does not exist (nothing to migrate)",
            "migrated": 0,
            "skipped": 0,
            "failed": 0,
        }
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0

    checks: list[dict] = []
    flags: list[str] = []
    migrated = 0
    skipped = 0
    failed = 0

    for run_json in find_run_json_files(root):
        check = migrate_file(run_json)
        checks.append(check)
        if check.get("name") == "skill_already_present":
            skipped += 1
        elif check.get("name") == "skill_backfilled":
            migrated += 1
        elif not check.get("passed"):
            failed += 1
            flag = check.get("flag")
            if flag:
                flags.append(flag)

    passed = failed == 0
    result = {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "passed": passed,
        "checks": checks,
        "flags": list(dict.fromkeys(flags)),
        "summary": f"migrated {migrated}, skipped {skipped}, failed {failed}",
        "migrated": migrated,
        "skipped": skipped,
        "failed": failed,
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
