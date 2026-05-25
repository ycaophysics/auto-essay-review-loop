"""market-research run dir → ReportRun."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import infer_skill_from_path, register
from ._helpers import build_item_skeleton, load_json_safe
from .model import ReportCheck, ReportItem, ReportRound, ReportRun

SKILL_KEY = "market-research"

_ARTIFACTS = (
    "MARKET_RESEARCH.json",
    "MARKET_RESEARCH.md",
    "RESEARCH_PLAN.json",
)


def _search_roots(run_dir: Path, manifest: dict) -> list[Path]:
    roots: list[Path] = [run_dir]
    for key in ("output_dir", "research_dir", "market_research_dir"):
        if manifest.get(key):
            roots.append(Path(str(manifest[key])))
    if run_dir.name == "runs" and run_dir.parent.exists():
        roots.append(run_dir.parent.parent)
    parent = run_dir.parent
    if parent.name == "runs" and parent.parent.exists():
        roots.append(parent.parent)
    if (run_dir / "market-research").is_dir():
        roots.append(run_dir / "market-research")
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = str(root.resolve())
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def _find_artifact(roots: list[Path], name: str) -> tuple[Path | None, str | None]:
    for root in roots:
        candidate = root / name
        if candidate.is_file():
            return candidate, None
        nested = root / "market-research" / name
        if nested.is_file():
            return nested, None
    return None, f"not found: {name}"


def _title_from_md(path: Path | None) -> str | None:
    if not path or not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None


def _checks_from_json(path: Path) -> list[ReportCheck]:
    data, _ = load_json_safe(path)
    if not data:
        return []
    checks: list[ReportCheck] = []
    for row in data.get("flags") or data.get("checks") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("flag") or "flag")
        passed = row.get("passed")
        if passed is None:
            passed = not bool(row.get("severity") in ("critical", "error"))
        checks.append(
            ReportCheck(
                name=name,
                passed=bool(passed),
                detail=str(row.get("detail") or row.get("message") or ""),
            )
        )
    if not checks and "passed" in data:
        checks.append(
            ReportCheck(
                name=str(data.get("tool", path.stem)),
                passed=bool(data.get("passed")),
                detail=str(data.get("summary", "")),
            )
        )
    return checks


@register(SKILL_KEY)
def build(run_dir: Path) -> ReportRun:
    run_dir = Path(run_dir).resolve()
    warnings: list[str] = []

    manifest, err = load_json_safe(run_dir / "RUN.json")
    if err:
        warnings.append(err)
        manifest = manifest or {}

    skill = str(manifest.get("skill") or infer_skill_from_path(run_dir) or SKILL_KEY)
    roots = _search_roots(run_dir, manifest)

    json_path, json_miss = _find_artifact(roots, "MARKET_RESEARCH.json")
    if json_miss:
        warnings.append(json_miss)
    md_path, md_miss = _find_artifact(roots, "MARKET_RESEARCH.md")
    if md_miss:
        warnings.append(md_miss)
    plan_path, plan_miss = _find_artifact(roots, "RESEARCH_PLAN.json")
    if plan_miss:
        warnings.append(plan_miss)

    research_data, _ = load_json_safe(json_path) if json_path else (None, None)
    plan_data, _ = load_json_safe(plan_path) if plan_path else (None, None)

    topic = (
        (research_data or {}).get("topic")
        or (plan_data or {}).get("topic")
        or manifest.get("topic")
        or manifest.get("campaign")
        or run_dir.name
    )
    title = _title_from_md(md_path) or str(topic)
    slug = str(manifest.get("run_id") or run_dir.name)

    checks: list[ReportCheck] = []
    if json_path:
        checks.extend(_checks_from_json(json_path))

    status = "approved" if md_path and json_path else "in_progress"
    if research_data and research_data.get("status"):
        raw = str(research_data["status"]).lower()
        if "complete" in raw or raw == "done":
            status = "approved"

    metadata: dict[str, str] = {"topic": str(topic)}
    if md_path:
        metadata["research_doc"] = str(md_path)
    if json_path:
        metadata["research_json"] = str(json_path)
    if plan_path:
        metadata["research_plan"] = str(plan_path)
    raw_dir = next(
        (r / "market-research" / "raw" for r in roots if (r / "market-research" / "raw").is_dir()),
        None,
    )
    if raw_dir:
        metadata["raw_sources"] = str(len(list(raw_dir.glob("*.json"))))

    item = build_item_skeleton(slug, title=title, subtitle=SKILL_KEY, status=status)
    item.rounds = [ReportRound(n=1, message="", checks=checks)]
    item.metadata = metadata

    run_id = str(manifest.get("run_id") or run_dir.name)
    started = str(
        manifest.get("started_at")
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )

    return ReportRun(
        run_id=run_id,
        skill=skill,
        campaign=str(topic),
        status="completed" if status == "approved" else status,
        started_at=started,
        completed_at=str(manifest["completed_at"]) if manifest.get("completed_at") else None,
        funnel=[("gathered", 1 if json_path else 0), ("synthesized", 1 if md_path else 0)],
        items=[item],
        warnings=warnings,
        manifest_path=str(run_dir / "MANIFEST.md") if (run_dir / "MANIFEST.md").exists() else None,
        schema_version=int(manifest.get("schema_version", 1)),
    )
