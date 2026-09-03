"""auto-social-review-loop run dir → ReportRun."""

from __future__ import annotations

from pathlib import Path

from . import register
from ._review_loop import ReviewLoopConfig, build_review_loop

SKILL_KEY = "social"

_CONFIG = ReviewLoopConfig(
    skill=SKILL_KEY,
    verify_globs=("count_chars*.json", "verify_social*.json"),
    approved_glob="social_*_approved_*.txt",
    trace_subdir="social",
)


@register(SKILL_KEY)
def build(run_dir: Path):
    return build_review_loop(run_dir, _CONFIG)
