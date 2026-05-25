"""auto-essay-review-loop (umbrella) run dir → ReportRun."""

from __future__ import annotations

from pathlib import Path

from . import register
from ._helpers import load_json_safe
from ._review_loop import ReviewLoopConfig, build_review_loop
from .model import ReportRun

SKILL_KEY = "essay"

_CONFIG = ReviewLoopConfig(
    skill=SKILL_KEY,
    verify_globs=(),
    approved_glob="*_approved_*.*",
    trace_subdir="",
)


@register(SKILL_KEY)
def build(run_dir: Path) -> ReportRun:
    """Umbrella dispatcher run — not outbound; reads shared review-stage artifacts."""
    run = build_review_loop(run_dir, _CONFIG)
    run.skill = SKILL_KEY

    manifest, _ = load_json_safe(Path(run_dir) / "RUN.json")
    if manifest and run.items:
        item = run.items[0]
        dispatched = (
            manifest.get("dispatched_format")
            or manifest.get("dispatched_skill")
            or manifest.get("format")
        )
        if dispatched:
            item.metadata["dispatched_format"] = str(dispatched)
            item.subtitle = f"dispatched → {dispatched}"
        if reason := manifest.get("detection_reason"):
            item.metadata["detection_reason"] = str(reason)
        if draft := manifest.get("source_draft") or manifest.get("input_draft"):
            run.campaign = str(draft)
    return run
