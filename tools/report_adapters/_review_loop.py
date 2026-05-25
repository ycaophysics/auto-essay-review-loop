"""Shared build logic for auto-*-review-loop format adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import infer_skill_from_path
from .model import ReportCheck, ReportItem, ReportRound, ReportRun, ReportTrace
from ._helpers import load_json_safe, truncate_trace

_TRACE_RE = re.compile(
    r"persona-(.+)-round-(\d+)\.(prompt|response)\.txt$", re.IGNORECASE
)


@dataclass(frozen=True)
class ReviewLoopConfig:
    skill: str
    verify_globs: tuple[str, ...]
    approved_glob: str
    trace_subdir: str


def _search_roots(run_dir: Path, manifest: dict) -> list[Path]:
    roots: list[Path] = [run_dir]
    paths = manifest.get("paths") or {}
    for key in ("review_stage", "output_dir", "stage_dir"):
        if paths.get(key):
            roots.append(Path(paths[key]))
    if run_dir.name == "runs" and run_dir.parent.exists():
        roots.append(run_dir.parent.parent)
    parent = run_dir.parent
    if parent.name == "runs" and parent.parent.exists():
        roots.append(parent.parent)
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = str(root.resolve())
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def _find_first(roots: list[Path], names: tuple[str, ...]) -> tuple[Path | None, str | None]:
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return candidate, None
    return None, f"not found under {roots[0]}: {', '.join(names)}"


def _glob_verify(roots: list[Path], patterns: tuple[str, ...]) -> list[Path]:
    if not patterns:
        return []
    found: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        matches: list[Path] = []
        for root in roots:
            matches.extend(p for p in root.glob(pattern) if p.is_file())
        if not matches:
            continue
        chosen = max(matches, key=lambda p: p.stat().st_mtime)
        key = str(chosen.resolve())
        if key not in seen:
            seen.add(key)
            found.append(chosen)
    return found


def _checks_from_verify(path: Path) -> list[ReportCheck]:
    data, _ = load_json_safe(path)
    if not data:
        return []
    checks: list[ReportCheck] = []
    if isinstance(data.get("checks"), list):
        for row in data["checks"]:
            if not isinstance(row, dict):
                continue
            checks.append(
                ReportCheck(
                    name=str(row.get("name", "check")),
                    passed=bool(row.get("passed", False)),
                    detail=str(row.get("detail", row.get("summary", ""))),
                )
            )
    elif "passed" in data:
        checks.append(
            ReportCheck(
                name=str(data.get("tool", path.stem)),
                passed=bool(data.get("passed")),
                detail=str(data.get("summary", "")),
            )
        )
    return checks


def _title_from_review_doc(path: Path | None) -> str | None:
    if not path or not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None


def _collect_traces(roots: list[Path], trace_subdir: str) -> tuple[list[ReportTrace], list[str]]:
    warnings: list[str] = []
    pairs: dict[tuple[str, int], dict[str, Path]] = {}
    for root in roots:
        for base in (root / "traces" / trace_subdir, root / "traces"):
            if not base.is_dir():
                continue
            for path in base.rglob("persona-*-round-*.*.txt"):
                match = _TRACE_RE.search(path.name)
                if not match:
                    continue
                persona, round_s, kind = match.group(1), int(match.group(2)), match.group(3)
                pairs.setdefault((persona, round_s), {})[kind] = path
    traces: list[ReportTrace] = []
    for (persona, round_n), files in sorted(pairs.items()):
        for kind in ("prompt", "response"):
            path = files.get(kind)
            if not path:
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                warnings.append(f"{path}: {exc}")
                continue
            text, truncated = truncate_trace(raw)
            traces.append(
                ReportTrace(
                    persona=persona,
                    round=round_n,
                    prompt=text if kind == "prompt" else "",
                    response=text if kind == "response" else "",
                    truncated=truncated,
                    raw_path=str(path),
                )
            )
    return traces, warnings


def _status_from_state(state: dict | None, manifest: dict | None) -> str:
    for src in (state, manifest):
        if not src:
            continue
        for key in ("status", "termination_status"):
            val = str(src.get(key, "")).lower()
            if "approv" in val or val == "completed":
                return "approved"
            if "reject" in val or "fail" in val:
                return "rejected"
            if val in {"in_progress", "running", "stalled"}:
                return val
    return "in_progress"


def build_review_loop(run_dir: Path, config: ReviewLoopConfig) -> ReportRun:
    run_dir = Path(run_dir).resolve()
    warnings: list[str] = []

    manifest, err = load_json_safe(run_dir / "RUN.json")
    if err:
        warnings.append(err)
        manifest = manifest or {}

    skill = manifest.get("skill") or infer_skill_from_path(run_dir) or config.skill
    roots = _search_roots(run_dir, manifest)

    state_path, state_miss = _find_first(roots, ("REVIEW_STATE.json",))
    if state_miss:
        for root in roots:
            matches = sorted(root.glob("REVIEW_STATE*.json"))
            if matches:
                state_path = matches[0]
                state_miss = None
                break
    if state_miss:
        warnings.append(state_miss)

    state, state_err = load_json_safe(state_path) if state_path else (None, None)
    if state_err:
        warnings.append(state_err)

    review_doc, review_miss = _find_first(roots, ("AUTO_REVIEW.md",))
    if review_miss:
        warnings.append(review_miss)

    manifest_path, _ = _find_first(roots, ("MANIFEST.md",))

    draft_path = None
    for src in (manifest, state):
        if not src:
            continue
        for key in ("draft_path", "input_draft", "source_draft", "draft"):
            if src.get(key):
                draft_path = Path(str(src[key]))
                break
        if draft_path:
            break
    if draft_path is None:
        draft_path, draft_miss = _find_first(roots, ("draft.md", "draft.txt"))
        if draft_miss:
            warnings.append(draft_miss)

    slug = manifest.get("run_id") or run_dir.name
    if draft_path and draft_path.exists():
        slug = draft_path.stem

    title = (
        manifest.get("draft_title")
        or _title_from_review_doc(review_doc)
        or (draft_path.name if draft_path else slug)
    )
    subtitle = str(state.get("format", config.skill)) if state else config.skill
    status = _status_from_state(state, manifest)

    checks: list[ReportCheck] = []
    for verify_path in _glob_verify(roots, config.verify_globs):
        checks.extend(_checks_from_verify(verify_path))
    if not checks and config.verify_globs:
        warnings.append(f"no verify JSON matched {config.verify_globs}")

    traces, trace_warnings = _collect_traces(roots, config.trace_subdir)
    warnings.extend(trace_warnings)

    round_n = int(state.get("round", 0)) if state else 0
    rounds = [
        ReportRound(
            n=round_n or 1,
            message=str(state.get("final_message", "")) if state else "",
            checks=checks,
            traces=traces,
        )
    ]

    metadata: dict[str, str] = {}
    if draft_path:
        metadata["draft_path"] = str(draft_path)
    if review_doc:
        metadata["review_doc"] = str(review_doc)
    if state_path:
        metadata["state_file"] = str(state_path)
    if state and state.get("format"):
        metadata["format"] = str(state["format"])
    for src in (state, manifest):
        if not src:
            continue
        for meta_key in ("target", "platform", "scenario"):
            if src.get(meta_key) and meta_key not in metadata:
                metadata[meta_key] = str(src[meta_key])

    if metadata.get("target"):
        subtitle = f"{subtitle} / {metadata['target']}"
    elif metadata.get("platform"):
        subtitle = f"{subtitle} / {metadata['platform']}"
    elif metadata.get("scenario"):
        subtitle = f"{subtitle} / {metadata['scenario']}"

    item = ReportItem(
        slug=str(slug),
        title=str(title),
        subtitle=subtitle,
        status=status,
        rounds=rounds,
        metadata=metadata,
        next_step_cta=manifest.get("next_step_cta"),
    )

    run_id = str(manifest.get("run_id") or run_dir.name)
    campaign = str(
        manifest.get("campaign")
        or manifest.get("draft_name")
        or manifest.get("source_draft")
        or title
    )
    started = str(
        manifest.get("started_at")
        or (state or {}).get("timestamp")
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    completed = manifest.get("completed_at")
    if status == "approved" and not completed:
        completed = (state or {}).get("timestamp")

    funnel: list[tuple[str, int]] = [("init", 1)]
    if round_n:
        funnel.append((f"round_{round_n}", round_n))
    if status == "approved":
        funnel.append(("approved", 1))

    return ReportRun(
        run_id=run_id,
        skill=str(skill),
        campaign=campaign,
        status="completed" if status == "approved" else status,
        started_at=started,
        completed_at=str(completed) if completed else None,
        funnel=funnel,
        items=[item],
        warnings=warnings,
        manifest_path=str(manifest_path) if manifest_path else None,
        schema_version=int(manifest.get("schema_version", 1)),
    )
