"""auto-cv-review-loop run dir → ReportRun."""

from __future__ import annotations

from pathlib import Path

from . import register
from ._review_loop import ReviewLoopConfig, build_review_loop

SKILL_KEY = "cv"

_CONFIG = ReviewLoopConfig(
    skill=SKILL_KEY,
    verify_globs=("verify_cv*.json",),
    approved_glob="cv_approved_*.md",
    trace_subdir="cv",
)


@register(SKILL_KEY)
def build(run_dir: Path):
    return build_review_loop(run_dir, _CONFIG)
