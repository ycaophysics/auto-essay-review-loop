#!/usr/bin/env python3
"""One-shot script to synthesize outbound report test fixtures. Run from repo root."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "runs"
OUTBOUND = REPO / "tests" / "fixtures" / "outbound"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows) + "\n",
        encoding="utf-8",
    )


def profile(slug: str, first: str, company: str, headline: str) -> dict:
    return {
        "profileUrl": f"https://www.linkedin.com/in/{slug}/",
        "profile_slug": slug,
        "firstName": first,
        "fullName": f"{first} Example",
        "headline": headline,
        "currentRole": "Founder",
        "company": company,
        "location": "San Francisco",
        "about": "Building B2B SaaS.",
        "recentExperience": [],
        "education": [],
        "email": None,
        "phone": None,
        "source": "fixture",
    }


def message_row(slug: str, first: str, msg: str, round_n: int = 3) -> dict:
    return {
        "profileUrl": f"https://www.linkedin.com/in/{slug}/",
        "profile_slug": slug,
        "firstName": first,
        "channel": "linkedin_connection",
        "round": round_n,
        "personalizationEvidence": ["headline says Founder"],
        "message": msg,
    }


def verify_json(slug: str, passed: bool = True) -> dict:
    return {
        "tool": "verify_outbound_message",
        "profile_slug": slug,
        "passed": passed,
        "checks": [
            {"name": "message_length", "passed": passed, "detail": "232/300"},
            {"name": "evidence_count", "passed": passed, "detail": "2"},
            {"name": "forbidden_claims", "passed": passed, "detail": "none"},
            {"name": "channel_authorized", "passed": passed, "detail": "ok"},
        ],
    }


def persona_scores(ready: bool = True) -> dict:
    verdict = "ready" if ready else "not ready"
    return {
        "target-customer": {"score": 9 if ready else 4, "verdict": verdict, "would_reply": "yes" if ready else "no", "weaknesses": [], "summary": "ok"},
        "spam-filter": {"score": 8, "verdict": "ready", "spam_risk": "low", "weaknesses": [], "summary": "ok"},
        "sales-leader": {"score": 7 if ready else 5, "verdict": verdict, "weaknesses": [], "summary": "ok"},
        "compliance-reviewer": {"score": 9, "verdict": "ready", "approved": ready, "veto": [], "weaknesses": [], "summary": "ok"},
    }


def build_happy(base: Path) -> None:
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)

    write_json(
        base / "RUN.json",
        {
            "tool": "init_outbound_run",
            "schema_version": 2,
            "skill": "linkedin-outbound",
            "status": "completed",
            "run_id": "20260513_141200_outbound-happy",
            "campaign_name": "outbound-happy",
            "started_at": "2026-05-13T14:12:00Z",
            "completed_at": "2026-05-13T15:00:00Z",
        },
    )

    (base / "00_campaign").mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUTBOUND / "campaign.json", base / "00_campaign" / "campaign.input.json")

    profiles = [
        profile("example-founder", "Chris", "Amiara", "Founder at Amiara — remote staffing for franchise systems"),
        profile("example-rejected", "Alex", "BetaCo<script>alert(1)</script>", "CEO at BetaCo"),
        profile("example-progress", "Sam", "GammaInc", "Founder at GammaInc"),
    ]
    write_json(base / "02_enrichment" / "enriched_profiles.normalized.json", profiles)

    qualified = [
        {"profile_slug": "example-founder", "score": 8, "reasonMatchedIcp": "Founder; B2B SaaS ICP match", "evidence": ["Founder"]},
        {"profile_slug": "example-rejected", "score": 7, "reasonMatchedIcp": "CEO match", "evidence": ["CEO"]},
        {"profile_slug": "example-progress", "score": 8, "reasonMatchedIcp": "Founder match", "evidence": ["Founder"]},
    ]
    write_json(base / "03_qualification" / "qualified_prospects.json", qualified)
    write_json(base / "03_qualification" / "rejected_prospects.json", [])

    approved_msg = "Hi Chris, your remote staffing work at Amiara caught my eye. Open to a 10-min call next week?"
    rejected_msg = "Hi Alex — generic pitch that failed spam-filter."
    progress_msg = "Hi Sam — draft in review round 2."

    write_jsonl(
        base / "04_messages" / "candidate_messages.jsonl",
        [
            message_row("example-founder", "Chris", approved_msg),
            message_row("example-rejected", "Alex", rejected_msg),
            message_row("example-progress", "Sam", progress_msg, round_n=2),
        ],
    )
    for slug, first, msg in [
        ("example-founder", "Chris", approved_msg),
        ("example-rejected", "Alex", rejected_msg),
        ("example-progress", "Sam", progress_msg),
    ]:
        write_json(base / "04_messages" / "per_prospect" / f"{slug}_message.json", message_row(slug, first, msg))

    write_json(base / "05_verification" / "example-founder_verify.json", verify_json("example-founder", True))
    write_json(base / "05_verification" / "example-rejected_verify.json", verify_json("example-rejected", False))
    write_json(base / "05_verification" / "example-progress_verify.json", verify_json("example-progress", True))

    write_jsonl(
        base / "06_exports" / "approved_messages.jsonl",
        [message_row("example-founder", "Chris", approved_msg)],
    )
    write_jsonl(
        base / "06_exports" / "rejected_messages.jsonl",
        [message_row("example-rejected", "Alex", rejected_msg)],
    )

    state_rows = [
        {
            "profile_slug": "example-founder",
            "status": "approved",
            "round": 3,
            "timestamp": "2026-05-13T14:45:00Z",
            "last_scores": persona_scores(True),
            "blockers": [],
        },
        {
            "profile_slug": "example-rejected",
            "status": "rejected",
            "round": 3,
            "timestamp": "2026-05-13T14:50:00Z",
            "last_scores": persona_scores(False),
            "blockers": ["spam-filter: weak CTA", "target-customer: would_reply=no"],
        },
        {
            "profile_slug": "example-progress",
            "status": "reviewing",
            "round": 2,
            "timestamp": "2026-05-13T14:55:00Z",
            "last_scores": persona_scores(True),
            "blockers": [],
        },
    ]
    write_jsonl(base / "prospect_state.jsonl", state_rows)

    trace_dir = base / "traces" / "20260513_run01" / "example-founder"
    trace_dir.mkdir(parents=True, exist_ok=True)
    prompt = "Review this message for target-customer persona."
    response = "Score 9/10 — would reply maybe. Bearer sk-abc123456789012345678901234 in trace should redact."
    (trace_dir / "persona-target-customer-round-3.prompt.txt").write_text(prompt, encoding="utf-8")
    (trace_dir / "persona-target-customer-round-3.response.txt").write_text(response, encoding="utf-8")

    xss_profile = profile("example-xss", "Eve", "Evil", "<script>alert(1)</script> CEO")
    write_json(base / "02_enrichment" / "enriched_profiles.normalized.json", profiles)  # no xss in happy


def clone_partial(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    exports = dest / "06_exports"
    if exports.exists():
        shutil.rmtree(exports)


def clone_in_progress(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    run = json.loads((dest / "RUN.json").read_text(encoding="utf-8"))
    run["status"] = "in_progress"
    run.pop("completed_at", None)
    write_json(dest / "RUN.json", run)


def clone_completed(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    run = json.loads((dest / "RUN.json").read_text(encoding="utf-8"))
    run["status"] = "completed"
    run["completed_at"] = "2026-05-13T15:00:00Z"
    write_json(dest / "RUN.json", run)


def build_essay_happy(base: Path) -> None:
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    write_json(
        base / "RUN.json",
        {
            "schema_version": 2,
            "skill": "essay",
            "run_id": "essay-happy",
            "campaign_name": "why-i-build",
            "status": "completed",
            "started_at": "2026-05-13T09:33:00Z",
            "completed_at": "2026-05-13T10:00:00Z",
            "draft_path": "draft.md",
        },
    )
    (base / "draft.md").write_text("# Why I Build\n\nEssay draft fixture.\n", encoding="utf-8")
    (base / "AUTO_REVIEW.md").write_text("# Auto Review\n\nRound 1 passed.\n", encoding="utf-8")
    write_json(
        base / "REVIEW_STATE.json",
        {"format": "essay", "round": 2, "status": "approved", "timestamp": "2026-05-13T10:00:00Z"},
    )


def main() -> None:
    happy = FIXTURES / "outbound_happy"
    build_happy(happy)
    clone_partial(happy, FIXTURES / "outbound_partial")
    clone_in_progress(happy, FIXTURES / "outbound_in_progress")
    clone_completed(happy, FIXTURES / "outbound_completed")
    build_essay_happy(FIXTURES / "essay_happy")
    print("fixtures written under", FIXTURES)


if __name__ == "__main__":
    main()
