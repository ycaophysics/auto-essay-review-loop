"""auto-business-plan-review-loop run dir → ReportRun."""

from __future__ import annotations

from pathlib import Path

from . import register
from ._review_loop import ReviewLoopConfig, build_review_loop

SKILL_KEY = "business-plan"

_CONFIG = ReviewLoopConfig(
    skill=SKILL_KEY,
    verify_globs=("market_size*.json",),
    approved_glob="business-plan_approved_*.md",
    trace_subdir="business-plan",
)


@register(SKILL_KEY)
def build(run_dir: Path):
    return build_review_loop(run_dir, _CONFIG)
