#!/usr/bin/env python3
"""
init_outbound_run.py - create a phase-organized outbound run directory.

Usage:
    bash tools/run.sh init_outbound_run.py campaigns/name.json \
        --base-dir=review-stage/outbound \
        --name=adhd-founders

Writes:
    review-stage/outbound/runs/<timestamp>_<name>/
      00_campaign/
      01_discovery/
      02_enrichment/
      03_qualification/
      04_messages/per_prospect/
      05_verification/
      06_exports/
      traces/

The tool also copies the input campaign to 00_campaign/campaign.input.json
and updates review-stage/outbound/latest to point at the new run when the
platform supports symlinks.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAME = "init_outbound_run"
SCHEMA_VERSION = 2
DEFAULT_BASE_DIR = "review-stage/outbound"

PHASE_DIRS = [
    "00_campaign",
    "01_discovery",
    "02_enrichment",
    "03_qualification",
    "04_messages",
    "04_messages/per_prospect",
    "05_verification",
    "06_exports",
    "traces",
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "outbound"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str]) -> dict:
    if len(argv) < 2:
        raise SystemExit(
            "usage: init_outbound_run.py <campaign.json> "
            "[--base-dir=review-stage/outbound] [--name=...] [--timestamp=...]"
        )
    args = {
        "campaign_path": argv[1],
        "base_dir": DEFAULT_BASE_DIR,
        "name": None,
        "timestamp": now_stamp(),
        "update_latest": True,
    }
    for a in argv[2:]:
        if a.startswith("--base-dir="):
            args["base_dir"] = a.split("=", 1)[1]
        elif a.startswith("--name="):
            args["name"] = a.split("=", 1)[1]
        elif a.startswith("--timestamp="):
            args["timestamp"] = a.split("=", 1)[1]
        elif a == "--no-latest":
            args["update_latest"] = False
        else:
            raise SystemExit(f"unknown flag: {a}")
    return args


def update_latest_pointer(base_dir: Path, run_dir: Path) -> str:
    latest = base_dir / "latest"
    relative_target = os.path.relpath(run_dir, start=base_dir)
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(relative_target)
        return str(latest)
    except OSError:
        # Filesystems without symlink support still get a readable pointer.
        pointer = base_dir / "latest.txt"
        pointer.write_text(str(run_dir) + "\n", encoding="utf-8")
        return str(pointer)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
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

    campaign_path = Path(args["campaign_path"])
    base_dir = Path(args["base_dir"])
    if not campaign_path.exists():
        result = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "passed": False,
            "checks": [],
            "flags": ["campaign_missing"],
            "summary": f"campaign file not found: {campaign_path}",
        }
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 2

    try:
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        result = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "passed": False,
            "checks": [],
            "flags": ["campaign_invalid"],
            "summary": f"could not parse campaign JSON: {exc}",
        }
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 2

    name = slugify(args["name"] or campaign_path.stem)
    timestamp = slugify(args["timestamp"].replace("_", "-")).replace("-", "_", 1)
    run_id = f"{timestamp}_{name}"
    run_dir = base_dir / "runs" / run_id

    for phase in PHASE_DIRS:
        (run_dir / phase).mkdir(parents=True, exist_ok=True)

    input_campaign = run_dir / "00_campaign" / "campaign.input.json"
    shutil.copyfile(campaign_path, input_campaign)

    run_manifest = {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "skill": "linkedin-outbound",
        "status": "in_progress",
        "started_at": now_iso(),
        "run_id": run_id,
        "source_campaign": str(campaign_path),
        "campaign_name": campaign_path.stem,
        "max_prospects": campaign.get("max_prospects"),
        "paths": {
            "run_dir": str(run_dir),
            "campaign_dir": str(run_dir / "00_campaign"),
            "discovery_dir": str(run_dir / "01_discovery"),
            "enrichment_dir": str(run_dir / "02_enrichment"),
            "qualification_dir": str(run_dir / "03_qualification"),
            "messages_dir": str(run_dir / "04_messages"),
            "verification_dir": str(run_dir / "05_verification"),
            "exports_dir": str(run_dir / "06_exports"),
            "traces_dir": str(run_dir / "traces"),
        },
    }
    write_json(run_dir / "RUN.json", run_manifest)

    readme = (
        "# Outbound Run\n\n"
        f"Run ID: `{run_id}`\n\n"
        "Folders:\n"
        "- `00_campaign/`: input and generated campaign JSON\n"
        "- `01_discovery/`: search output, filters, discovered profile URLs\n"
        "- `02_enrichment/`: profile enrichment output\n"
        "- `03_qualification/`: qualified and rejected prospect lists\n"
        "- `04_messages/`: draft message artifacts\n"
        "- `05_verification/`: deterministic verifier output\n"
        "- `06_exports/`: user-facing CSV/JSONL exports\n"
        "- `traces/`: persona-review prompts and responses\n"
    )
    (run_dir / "README.md").write_text(readme, encoding="utf-8")

    latest_path = None
    if args["update_latest"]:
        latest_path = update_latest_pointer(base_dir, run_dir)

    result = {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "passed": True,
        "checks": [
            {
                "name": "run_dir_created",
                "passed": True,
                "detail": f"created phase folders under {run_dir}",
            },
            {
                "name": "campaign_copied",
                "passed": True,
                "detail": f"copied campaign to {input_campaign}",
            },
        ],
        "flags": [],
        "run_id": run_id,
        "run_dir": str(run_dir),
        "latest": latest_path,
        "paths": run_manifest["paths"],
        "summary": f"initialized outbound run {run_id}",
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
