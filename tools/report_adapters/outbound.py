"""LinkedIn outbound run directory → ReportRun (canonical adapter)."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import register
from ._helpers import (
    build_item_skeleton,
    load_json_safe,
    load_json_strict,
    resolve_under,
    snapshot_read_jsonl,
    truncate_trace,
)
from .model import ReportCheck, ReportItem, ReportRound, ReportRun, ReportScore, ReportTrace

SKILL_KEY = "linkedin-outbound"

DIR_ENRICHMENT = "02_enrichment"
DIR_QUALIFICATION = "03_qualification"
DIR_MESSAGES = "04_messages"
DIR_VERIFICATION = "05_verification"
DIR_EXPORTS = "06_exports"
DIR_TRACES = "traces"

NORMALIZED_FILE = "enriched_profiles.normalized.json"
QUALIFIED_FILE = "qualified_prospects.json"
REJECTED_QUAL_FILE = "rejected_prospects.json"
STATE_FILE = "prospect_state.jsonl"
CANDIDATE_MESSAGES = "candidate_messages.jsonl"
APPROVED_EXPORT = "approved_messages.jsonl"
REJECTED_EXPORT = "rejected_messages.jsonl"

PERSONAS = (
    "target-customer",
    "spam-filter",
    "sales-leader",
    "compliance-reviewer",
)

TRACE_NAME_RE = re.compile(
    r"^persona-(.+)-round-(\d+)\.(prompt|response)\.txt$",
    re.IGNORECASE,
)

RUN_ID_TS_RE = re.compile(r"^(\d{8})_(\d{6})_")


@register(SKILL_KEY)
def build(run_dir: Path) -> ReportRun:
    """Read an outbound run directory and produce a ReportRun model."""
    run_dir = Path(run_dir).resolve()
    warnings: list[str] = []

    run_json_path = run_dir / "RUN.json"
    run_data = load_json_strict(run_json_path)

    run_id = str(run_data.get("run_id") or run_dir.name)
    campaign = str(run_data.get("campaign_name") or run_dir.name)
    skill = str(run_data.get("skill") or SKILL_KEY)
    started_at = str(run_data.get("started_at") or _started_at_from_run_id(run_id))
    completed_at = run_data.get("completed_at")
    if completed_at is not None:
        completed_at = str(completed_at)

    profiles = _load_profiles(run_dir, warnings)
    qualified, qual_rejected = _load_qualification(run_dir, warnings)
    state_rows, state_warnings = snapshot_read_jsonl(run_dir / STATE_FILE)
    warnings.extend(state_warnings)

    messages_by_slug = _load_messages_by_slug(run_dir, warnings)
    verify_by_slug = _load_verification(run_dir, warnings)
    approved_export, rejected_export = _load_exports(run_dir, warnings)
    traces_by_slug = _load_traces(run_dir, warnings)

    profile_by_slug = {p.get("profile_slug"): p for p in profiles if p.get("profile_slug")}
    qualified_by_slug = {q.get("profile_slug"): q for q in qualified if q.get("profile_slug")}

    items: list[ReportItem] = []
    rejected_items: list[ReportItem] = []

    if state_rows:
        prospect_slugs = [r.get("profile_slug") for r in state_rows if r.get("profile_slug")]
    else:
        prospect_slugs = [q.get("profile_slug") for q in qualified if q.get("profile_slug")]
        if prospect_slugs:
            warnings.append(
                f"{STATE_FILE} missing or empty; showing qualified prospects only"
            )

    for slug in prospect_slugs:
        if not slug:
            continue
        state = next((r for r in state_rows if r.get("profile_slug") == slug), {})
        profile = profile_by_slug.get(slug, {})
        qual = qualified_by_slug.get(slug, {})
        item = _build_prospect_item(
            run_dir=run_dir,
            slug=slug,
            state=state,
            profile=profile,
            qual=qual,
            messages=messages_by_slug.get(slug, []),
            verify=verify_by_slug.get(slug),
            approved_row=approved_export.get(slug),
            rejected_row=rejected_export.get(slug),
            traces=traces_by_slug.get(slug, {}),
        )
        if item.status == "approved":
            items.append(item)
        elif item.status == "rejected":
            rejected_items.append(item)
        else:
            items.append(item)

    status = str(run_data.get("status") or _infer_run_status(state_rows))
    if status == "completed" and completed_at is None and state_rows:
        completed_at = _latest_timestamp(state_rows)

    enriched_count = len(profiles)
    qualified_count = len(qualified)
    approved_count = sum(1 for item in items if item.status == "approved")
    if approved_count == 0 and approved_export:
        approved_count = len(approved_export)

    funnel: list[tuple[str, int]] = [
        ("enriched", enriched_count),
        ("qualified", qualified_count),
        ("approved", approved_count),
    ]

    rejection_patterns = _compute_rejection_patterns(
        rejected_items,
        qual_rejected,
        approved_count,
    )

    manifest = run_dir / "MANIFEST.md"
    manifest_path = str(manifest) if manifest.exists() else None

    return ReportRun(
        run_id=run_id,
        skill=skill,
        campaign=campaign,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        funnel=funnel,
        items=items,
        rejected_items=rejected_items,
        warnings=warnings,
        manifest_path=manifest_path,
        schema_version=int(run_data.get("schema_version") or 1),
        rejection_patterns=rejection_patterns,
    )


def _started_at_from_run_id(run_id: str) -> str:
    m = RUN_ID_TS_RE.match(run_id)
    if not m:
        return ""
    date_part, time_part = m.group(1), m.group(2)
    try:
        dt = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S")
        return dt.isoformat() + "Z"
    except ValueError:
        return ""


def _infer_run_status(state_rows: list[dict]) -> str:
    if not state_rows:
        return "in_progress"
    terminal = {"approved", "rejected"}
    if all((r.get("status") or "qualified") in terminal for r in state_rows):
        return "completed"
    return "in_progress"


def _latest_timestamp(state_rows: list[dict]) -> str | None:
    stamps = [r.get("timestamp") for r in state_rows if r.get("timestamp")]
    return str(stamps[-1]) if stamps else None


def _load_profiles(run_dir: Path, warnings: list[str]) -> list[dict]:
    path = run_dir / DIR_ENRICHMENT / NORMALIZED_FILE
    data, err = load_json_safe(path)
    if err:
        warnings.append(err)
        return []
    if not isinstance(data, list):
        warnings.append(f"{path.name}: expected a JSON array")
        return []
    return [p for p in data if isinstance(p, dict)]


def _load_qualification(run_dir: Path, warnings: list[str]) -> tuple[list[dict], list[dict]]:
    qual_path = run_dir / DIR_QUALIFICATION / QUALIFIED_FILE
    rej_path = run_dir / DIR_QUALIFICATION / REJECTED_QUAL_FILE

    qualified, q_err = load_json_safe(qual_path)
    if q_err:
        warnings.append(q_err)
        qualified = []
    elif not isinstance(qualified, list):
        warnings.append(f"{QUALIFIED_FILE}: expected a JSON array")
        qualified = []

    rejected, r_err = load_json_safe(rej_path)
    if r_err:
        warnings.append(r_err)
        rejected = []
    elif not isinstance(rejected, list):
        warnings.append(f"{REJECTED_QUAL_FILE}: expected a JSON array")
        rejected = []

    return (
        [q for q in (qualified or []) if isinstance(q, dict)],
        [q for q in (rejected or []) if isinstance(q, dict)],
    )


def _load_messages_by_slug(run_dir: Path, warnings: list[str]) -> dict[str, list[dict]]:
    path = run_dir / DIR_MESSAGES / CANDIDATE_MESSAGES
    rows, row_warnings = snapshot_read_jsonl(path)
    warnings.extend(row_warnings)
    by_slug: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        slug = row.get("profile_slug") or row.get("profileUrl")
        if not slug:
            continue
        by_slug.setdefault(str(slug), []).append(row)

    per_dir = run_dir / DIR_MESSAGES / "per_prospect"
    if per_dir.is_dir():
        for msg_path in per_dir.glob("*_message.json"):
            resolved = resolve_under(run_dir, msg_path)
            if resolved is None:
                warnings.append(f"skipped message outside run_dir: {msg_path}")
                continue
            data, err = load_json_safe(resolved)
            if err:
                warnings.append(err)
                continue
            if not isinstance(data, dict):
                continue
            slug = data.get("profile_slug") or msg_path.stem.replace("_message", "")
            if slug:
                by_slug.setdefault(str(slug), []).append(data)
    return by_slug


def _load_verification(run_dir: Path, warnings: list[str]) -> dict[str, dict]:
    verify_dir = run_dir / DIR_VERIFICATION
    if not verify_dir.is_dir():
        warnings.append(f"missing phase dir: {DIR_VERIFICATION}/")
        return {}
    out: dict[str, dict] = {}
    for path in verify_dir.glob("*_verify.json"):
        resolved = resolve_under(run_dir, path)
        if resolved is None:
            warnings.append(f"skipped verify file outside run_dir: {path}")
            continue
        data, err = load_json_safe(resolved)
        if err:
            warnings.append(err)
            continue
        if not isinstance(data, dict):
            continue
        slug = data.get("profile_slug") or path.stem.replace("_verify", "")
        if slug:
            out[str(slug)] = data
    return out


def _load_exports(
    run_dir: Path,
    warnings: list[str],
) -> tuple[dict[str, dict], dict[str, dict]]:
    exports_dir = run_dir / DIR_EXPORTS
    if not exports_dir.is_dir():
        warnings.append(f"missing phase dir: {DIR_EXPORTS}/ (partial run)")
        return {}, {}

    approved_rows, aw = snapshot_read_jsonl(exports_dir / APPROVED_EXPORT)
    rejected_rows, rw = snapshot_read_jsonl(exports_dir / REJECTED_EXPORT)
    warnings.extend(aw)
    warnings.extend(rw)

    approved = {
        str(r.get("profile_slug") or r.get("profileUrl")): r
        for r in approved_rows
        if isinstance(r, dict) and (r.get("profile_slug") or r.get("profileUrl"))
    }
    rejected = {
        str(r.get("profile_slug") or r.get("profileUrl")): r
        for r in rejected_rows
        if isinstance(r, dict) and (r.get("profile_slug") or r.get("profileUrl"))
    }
    return approved, rejected


def _load_traces(
    run_dir: Path,
    warnings: list[str],
) -> dict[str, dict[int, dict[str, dict[str, object]]]]:
    """slug → round → persona → {prompt, response, prompt_path, response_path}."""
    traces_root = run_dir / DIR_TRACES
    if not traces_root.is_dir():
        return {}

    grouped: dict[str, dict[int, dict[str, dict[str, object]]]] = {}
    for path in traces_root.rglob("*.txt"):
        resolved = resolve_under(run_dir, path)
        if resolved is None:
            warnings.append(f"skipped trace outside run_dir: {path}")
            continue
        m = TRACE_NAME_RE.match(resolved.name)
        if not m:
            continue
        persona, round_s, kind = m.group(1), m.group(2), m.group(3)
        slug = resolved.parent.name
        round_n = int(round_s)
        text = resolved.read_text(encoding="utf-8", errors="replace")
        truncated, was_truncated = truncate_trace(text)
        rel_path = str(resolved.relative_to(run_dir)).replace("\\", "/")

        slug_rounds = grouped.setdefault(slug, {})
        persona_bucket = slug_rounds.setdefault(round_n, {}).setdefault(
            persona,
            {
                "prompt": "",
                "response": "",
                "prompt_truncated": False,
                "response_truncated": False,
                "prompt_path": "",
                "response_path": "",
            },
        )
        if kind == "prompt":
            persona_bucket["prompt"] = truncated
            persona_bucket["prompt_truncated"] = was_truncated
            persona_bucket["prompt_path"] = rel_path
        else:
            persona_bucket["response"] = truncated
            persona_bucket["response_truncated"] = was_truncated
            persona_bucket["response_path"] = rel_path
    return grouped


def _normalize_status(status: str) -> str:
    s = (status or "in_progress").lower()
    if s in ("reviewing", "qualified", "pending", "drafting"):
        return "in_progress"
    return s


def _build_prospect_item(
    *,
    run_dir: Path,
    slug: str,
    state: dict,
    profile: dict,
    qual: dict,
    messages: list[dict],
    verify: dict | None,
    approved_row: dict | None,
    rejected_row: dict | None,
    traces: dict[int, dict[str, dict[str, object]]],
) -> ReportItem:
    status = _normalize_status(
        str(
            state.get("status")
            or (approved_row and "approved")
            or (rejected_row and "rejected")
            or "in_progress"
        )
    )
    title = (
        profile.get("fullName")
        or qual.get("fullName")
        or profile.get("firstName")
        or qual.get("firstName")
        or slug
    )
    subtitle = _format_subtitle(profile, qual)
    final_message = _final_message(approved_row, rejected_row, messages)

    item = build_item_skeleton(slug, title=str(title), subtitle=subtitle, status=status)
    item.final_message = final_message
    item.rounds = _build_rounds(
        state=state,
        messages=messages,
        verify=verify,
        traces=traces,
    )
    item.metadata = _build_metadata(profile, qual, state, messages, verify)
    item.next_step_cta = _next_step_cta(status, slug, profile, state)
    if status == "rejected":
        item.metadata["retry_cli"] = (
            f"bash tools/run.sh outbound_state.py update {slug} - --out-dir=."
        )
    return item


def _format_subtitle(profile: dict, qual: dict) -> str:
    role = profile.get("currentRole") or qual.get("currentRole") or ""
    company = profile.get("company") or qual.get("company") or ""
    if role and company:
        return f"{role} · {company}"
    return role or company or profile.get("headline") or qual.get("headline") or ""


def _final_message(
    approved_row: dict | None,
    rejected_row: dict | None,
    messages: list[dict],
) -> str | None:
    if approved_row and approved_row.get("message"):
        return str(approved_row["message"])
    if messages:
        return str(messages[-1].get("message") or "")
    if rejected_row and rejected_row.get("message"):
        return str(rejected_row["message"])
    return None


def _build_rounds(
    *,
    state: dict,
    messages: list[dict],
    verify: dict | None,
    traces: dict[int, dict[str, dict[str, object]]],
) -> list[ReportRound]:
    max_round = max(
        [
            state.get("round") or 0,
            len(messages),
            max(traces.keys(), default=0),
        ]
    )
    if max_round <= 0 and (messages or traces or verify):
        max_round = 1

    rounds: list[ReportRound] = []
    last_scores = state.get("last_scores") or {}
    last_verdicts = state.get("last_verdicts") or {}

    for round_n in range(1, max_round + 1):
        message = ""
        if round_n <= len(messages):
            message = str(messages[round_n - 1].get("message") or "")

        scores = _scores_for_round(
            round_n=round_n,
            max_round=max_round,
            traces=traces,
            last_scores=last_scores,
            last_verdicts=last_verdicts,
        )
        checks: list[ReportCheck] = []
        if verify and round_n == max_round:
            checks = _checks_from_verify(verify)

        trace_objs = _traces_for_round(round_n, traces.get(round_n, {}))
        rounds.append(
            ReportRound(
                n=round_n,
                message=message,
                scores=scores,
                checks=checks,
                traces=trace_objs,
            )
        )
    return rounds


def _scores_for_round(
    *,
    round_n: int,
    max_round: int,
    traces: dict[int, dict[str, dict[str, object]]],
    last_scores: dict,
    last_verdicts: dict,
) -> list[ReportScore]:
    round_traces = traces.get(round_n, {})
    personas = set(PERSONAS) | set(round_traces.keys()) | set(last_scores.keys())
    scores: list[ReportScore] = []
    for persona in sorted(personas):
        parsed = _parse_persona_response(
            str(round_traces.get(persona, {}).get("response") or "")
        )
        score_val = parsed.get("score")
        verdict = str(parsed.get("verdict") or "inconclusive")
        weaknesses = _weakness_strings(parsed.get("weaknesses"))
        summary = str(parsed.get("summary") or "")
        if round_n == max_round:
            raw = last_scores.get(persona)
            if isinstance(raw, dict):
                if score_val is None:
                    score_val = _coerce_int(raw.get("score"))
                verdict = str(raw.get("verdict") or verdict)
                summary = str(raw.get("summary") or summary)
                if raw.get("weaknesses"):
                    weaknesses = _weakness_strings(raw.get("weaknesses"))
            elif score_val is None:
                score_val = _coerce_int(raw)
            if verdict == "inconclusive" and last_verdicts.get(persona):
                verdict = str(last_verdicts.get(persona))
        scores.append(
            ReportScore(
                persona=persona,
                score=_coerce_int(score_val),
                verdict=verdict,
                weaknesses=weaknesses,
                summary=summary,
            )
        )
    return scores


def _parse_persona_response(text: str) -> dict:
    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _weakness_strings(raw) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            issue = entry.get("issue") or entry.get("fix") or ""
            if issue:
                out.append(str(issue))
        elif entry:
            out.append(str(entry))
    return out


def _checks_from_verify(verify: dict) -> list[ReportCheck]:
    checks: list[ReportCheck] = []
    for raw in verify.get("checks") or []:
        if not isinstance(raw, dict):
            continue
        checks.append(
            ReportCheck(
                name=str(raw.get("name") or "check"),
                passed=bool(raw.get("passed")),
                detail=str(raw.get("detail") or ""),
            )
        )
    return checks


def _traces_for_round(
    round_n: int,
    persona_map: dict[str, dict[str, object]],
) -> list[ReportTrace]:
    traces: list[ReportTrace] = []
    for persona in sorted(persona_map.keys()):
        bucket = persona_map[persona]
        prompt = str(bucket.get("prompt") or "")
        response = str(bucket.get("response") or "")
        truncated = bool(
            bucket.get("prompt_truncated") or bucket.get("response_truncated")
        )
        raw_path = str(bucket.get("response_path") or bucket.get("prompt_path") or "")
        traces.append(
            ReportTrace(
                persona=persona,
                round=round_n,
                prompt=prompt,
                response=response,
                truncated=truncated,
                raw_path=raw_path,
            )
        )
    return traces


def _build_metadata(
    profile: dict,
    qual: dict,
    state: dict,
    messages: list[dict],
    verify: dict | None,
) -> dict[str, str]:
    meta: dict[str, str] = {}
    url = profile.get("profileUrl") or qual.get("profileUrl") or state.get("profileUrl")
    if url:
        meta["profileUrl"] = str(url)
    fit = qual.get("fitScore")
    if fit is not None:
        meta["fitScore"] = str(fit)
    reason = qual.get("reasonMatchedIcp") or (
        messages[-1].get("reasonMatchedIcp") if messages else None
    )
    if reason:
        meta["reasonMatchedIcp"] = str(reason)
    channel = (messages[-1].get("channel") if messages else None) or (
        verify.get("channel") if verify else None
    )
    if channel:
        meta["channel"] = str(channel)
    if state.get("round") is not None:
        meta["round"] = str(state.get("round"))
        meta["current_round"] = str(state.get("round"))
    meta["max_rounds"] = "3"
    if state.get("blockers"):
        meta["blockers"] = "; ".join(str(b) for b in state.get("blockers") or [])
    return meta


def _next_step_cta(
    status: str,
    slug: str,
    profile: dict,
    state: dict,
) -> str | None:
    if status == "approved":
        return "Copy the message below, then open their LinkedIn profile and send."
    if status == "rejected":
        blockers = state.get("blockers") or []
        if blockers:
            return f"Top blockers: {'; '.join(str(b) for b in blockers[:3])}."
        return "Review persona scorecard and traces, then retry or skip this prospect."
    round_n = state.get("round") or 0
    return f"Round {round_n} of 3 in flight — pipeline still reviewing this prospect."


def _qual_rejection_reason(row: dict) -> str:
    for key in ("disqualifiers", "missingEvidence"):
        values = row.get(key) or []
        if values:
            return str(values[0])
    return row.get("reasonMatchedIcp") or "did not qualify"


def _compute_rejection_patterns(
    rejected_items: list[ReportItem],
    qual_rejected: list[dict],
    approved_count: int,
) -> list[tuple[str, int]]:
    """Group rejection reasons; top 3 when approved_count == 0 (triage callout)."""
    counter: Counter[str] = Counter()
    for item in rejected_items:
        state_blockers = item.metadata.get("blockers")
        if state_blockers:
            counter[state_blockers.split(";")[0].strip()] += 1
        else:
            counter[_primary_blocker(item)] += 1

    for row in qual_rejected:
        counter[_qual_rejection_reason(row)] += 1

    if not counter:
        return []

    ranked = counter.most_common()
    if approved_count == 0:
        return ranked[:3]
    return ranked[:10]


def _primary_blocker(item: ReportItem) -> str:
    blockers_meta = item.metadata.get("blockers")
    if blockers_meta:
        return blockers_meta.split(";")[0].strip()
    for score in reversed(item.rounds[-1].scores if item.rounds else []):
        if score.verdict in ("not ready", "inconclusive") and score.persona:
            label = score.persona
            if score.weaknesses:
                return f"{label}: {score.weaknesses[0]}"
            return f"{label}: {score.verdict}"
    for check in reversed(item.rounds[-1].checks if item.rounds else []):
        if not check.passed:
            return f"verification: {check.name}"
    return "unknown blocker"
