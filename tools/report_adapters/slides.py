"""auto-slides-review-loop run dir → ReportRun."""

from __future__ import annotations

from pathlib import Path

from . import register
from ._review_loop import ReviewLoopConfig, build_review_loop

SKILL_KEY = "slides"

_CONFIG = ReviewLoopConfig(
    skill=SKILL_KEY,
    verify_globs=("verify_slides*.json",),
    approved_glob="slides_approved_*.*",
    trace_subdir="slides",
)


@register(SKILL_KEY)
def build(run_dir: Path):
    return build_review_loop(run_dir, _CONFIG)
