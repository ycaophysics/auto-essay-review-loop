"""Report model dataclasses — no logic, types only."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReportScore:
    persona: str
    score: int | None
    verdict: str
    weaknesses: list[str]
    summary: str


@dataclass
class ReportCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class ReportTrace:
    persona: str
    round: int
    prompt: str
    response: str
    truncated: bool
    raw_path: str


@dataclass
class ReportRound:
    n: int
    message: str
    scores: list[ReportScore] = field(default_factory=list)
    checks: list[ReportCheck] = field(default_factory=list)
    traces: list[ReportTrace] = field(default_factory=list)


@dataclass
class ReportItem:
    slug: str
    title: str
    subtitle: str
    status: str
    final_message: str | None = None
    rounds: list[ReportRound] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    next_step_cta: str | None = None


@dataclass
class ReportRun:
    run_id: str
    skill: str
    campaign: str
    status: str
    started_at: str
    completed_at: str | None = None
    funnel: list[tuple[str, int]] = field(default_factory=list)
    items: list[ReportItem] = field(default_factory=list)
    rejected_items: list[ReportItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest_path: str | None = None
    schema_version: int = 1
    rejection_patterns: list[tuple[str, int]] = field(default_factory=list)
