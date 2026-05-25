#!/usr/bin/env python3
"""
generate_run_report.py — self-contained HTML report for auto-*-review-loop runs.

Usage:
    bash tools/run.sh generate_run_report.py <run_dir>
    bash tools/run.sh generate_run_report.py --index
    bash tools/run.sh generate_run_report.py <run_dir> --update-golden
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.report_adapters import get_adapter, infer_skill_from_path, make_jinja_env
from tools.report_adapters._helpers import atomic_write, load_json_safe, load_json_strict
from tools.report_adapters.model import ReportRun

TOOL_NAME = "generate_run_report"
SCHEMA_VERSION = 1
DEFAULT_REVIEW_STAGE = Path("review-stage")
CACHE_FILENAME = ".report-index.cache.json"
INDEX_FILENAME = "index.html"
REPORT_FILENAME = "report.html"


@dataclass
class IndexRow:
    run_id: str
    skill: str
    campaign: str
    status: str
    started_at: str
    run_dir: str
    report_path: str | None
    qualified: int
    approved: int
    enriched: int
    error: str | None = None


def repo_root() -> Path:
    return _REPO_ROOT


def templates_dir() -> Path:
    return repo_root() / "templates" / "report"


def review_stage_root() -> Path:
    return repo_root() / DEFAULT_REVIEW_STAGE


def cache_path() -> Path:
    return review_stage_root() / CACHE_FILENAME


def resolve_run_dir(path: Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"run directory not found: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"not a directory: {resolved}")
    return resolved


def read_skill(run_dir: Path) -> str:
    run_json = run_dir / "RUN.json"
    if not run_json.exists():
        raise FileNotFoundError(f"RUN.json not found in {run_dir}")
    data = load_json_strict(run_json)
    skill = data.get("skill")
    if skill:
        return str(skill)
    inferred = infer_skill_from_path(run_dir)
    if inferred:
        return inferred
    raise ValueError(f"RUN.json in {run_dir} has no skill field and path inference failed")


def render_run_html(run: ReportRun, env) -> str:
    template = env.get_template("run.html.j2")
    return template.render(run=run)


def render_index_html(rows: list[IndexRow], env) -> str:
    template = env.get_template("index.html.j2")
    return template.render(rows=rows, generated_at=_now_iso())


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _run_json_mtime(run_dir: Path) -> float:
    path = run_dir / "RUN.json"
    if not path.exists():
        return 0.0
    return path.stat().st_mtime


def _load_cache() -> dict:
    path = cache_path()
    if not path.exists():
        return {"entries": {}}
    data, err = load_json_safe(path)
    if err or not isinstance(data, dict):
        return {"entries": {}}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return {"entries": {}}
    return {"entries": entries}


def _save_cache(cache: dict) -> None:
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        cache_path(),
    )


def _funnel_count(funnel: list[tuple[str, int]], stage: str) -> int:
    for name, count in funnel:
        if name == stage:
            return count
    return 0


def _build_index_row(
    run_dir: Path,
    report: ReportRun | None,
    error: str | None,
    review_root: Path,
) -> IndexRow:
    run_json_path = run_dir / "RUN.json"
    manifest, _ = load_json_safe(run_json_path)
    manifest = manifest or {}
    funnel = report.funnel if report else []
    status = report.status if report else str(manifest.get("status", "error"))
    if error:
        status = "error"
    report_href = None
    report_file = run_dir / REPORT_FILENAME
    if report_file.exists():
        try:
            report_href = report_file.relative_to(review_root.resolve()).as_posix()
        except ValueError:
            report_href = str(report_file)
    return IndexRow(
        run_id=str(manifest.get("run_id") or run_dir.name),
        skill=str(report.skill if report else manifest.get("skill") or infer_skill_from_path(run_dir) or "unknown"),
        campaign=str(report.campaign if report else manifest.get("campaign_name") or run_dir.name),
        status=status,
        started_at=str(report.started_at if report else manifest.get("started_at") or ""),
        run_dir=str(run_dir),
        report_path=report_href,
        enriched=_funnel_count(funnel, "enriched") or _funnel_count(funnel, "init"),
        qualified=_funnel_count(funnel, "qualified"),
        approved=_funnel_count(funnel, "approved"),
        error=error,
    )


def scan_runs(review_root: Path, env, *, rebuild_all: bool = False) -> list[IndexRow]:
    cache = _load_cache()
    entries: dict = cache.setdefault("entries", {})
    rows: list[IndexRow] = []

    run_json_files = sorted(review_root.glob("**/RUN.json"))
    for run_json in run_json_files:
        run_dir = run_json.parent.resolve()
        key = str(run_dir)
        mtime = _run_json_mtime(run_dir)
        cached = entries.get(key)
        error: str | None = None
        report: ReportRun | None = None

        use_cache = (
            not rebuild_all
            and cached
            and cached.get("mtime") == mtime
            and cached.get("row")
            and not cached.get("error")
        )
        if use_cache:
            row_data = cached["row"]
            rows.append(IndexRow(**row_data))
            continue

        try:
            skill = read_skill(run_dir)
            adapter = get_adapter(skill)
            if adapter is None:
                raise ValueError(f"no adapter registered for skill: {skill}")
            report = adapter(run_dir)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        row = _build_index_row(run_dir, report, error, review_root.resolve())
        rows.append(row)
        entries[key] = {
            "mtime": mtime,
            "row": asdict(row),
            "error": error,
        }

    pinned: list[IndexRow] = []
    rest: list[IndexRow] = []
    busy = {"in_progress", "partial", "stalled"}
    for row in rows:
        (pinned if row.status in busy else rest).append(row)
    pinned.sort(key=lambda r: r.started_at or "", reverse=True)
    rest.sort(key=lambda r: r.started_at or "", reverse=True)
    rows = pinned + rest
    _save_cache(cache)
    return rows


def _index_sort_key(row: IndexRow) -> tuple:
    """Deprecated — sorting handled inline in scan_runs."""
    in_progress = 0 if row.status in {"in_progress", "partial", "stalled"} else 1
    started = row.started_at or ""
    return (in_progress, started)


def generate_single_run(
    run_dir: Path,
    env,
    *,
    update_golden: bool = False,
) -> ReportRun:
    skill = read_skill(run_dir)
    adapter = get_adapter(skill)
    if adapter is None:
        raise ValueError(f"no adapter registered for skill: {skill!r}")
    report = adapter(run_dir)
    html = render_run_html(report, env)
    target = run_dir / REPORT_FILENAME
    atomic_write(html, target)

    if update_golden:
        golden = run_dir / "expected_report.html"
        atomic_write(html, golden)

    return report


def write_index(review_root: Path, env) -> Path:
    rows = scan_runs(review_root, env)
    html = render_index_html(rows, env)
    index_path = review_root / INDEX_FILENAME
    atomic_write(html, index_path)
    return index_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate HTML run reports")
    parser.add_argument(
        "run_dir",
        nargs="?",
        help="Run directory containing RUN.json",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Regenerate review-stage/index.html only",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Write expected_report.html beside report.html (fixture re-baseline)",
    )
    parser.add_argument(
        "--review-root",
        default=str(DEFAULT_REVIEW_STAGE),
        help="Review stage root for index scan (default: review-stage)",
    )
    return parser.parse_args(argv[1:])


def emit_result(passed: bool, summary: str, **extra) -> None:
    payload = {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "passed": passed,
        "checks": extra.pop("checks", []),
        "flags": extra.pop("flags", []),
        "summary": summary,
        **extra,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    env = make_jinja_env(templates_dir())
    review_root = Path(args.review_root)
    if not review_root.is_absolute():
        review_root = repo_root() / review_root

    try:
        if args.index and not args.run_dir:
            index_path = write_index(review_root.resolve(), env)
            emit_result(
                True,
                f"wrote {index_path}",
                index_path=str(index_path),
            )
            return 0

        if not args.run_dir:
            emit_result(
                False,
                "usage: generate_run_report.py <run_dir> | --index",
                flags=["argument_error"],
            )
            return 2

        run_dir = resolve_run_dir(Path(args.run_dir))
        if not run_dir.is_absolute():
            run_dir = (repo_root() / run_dir).resolve()

        report = generate_single_run(run_dir, env, update_golden=args.update_golden)
        index_path = write_index(review_root.resolve(), env)
        emit_result(
            True,
            f"wrote {run_dir / REPORT_FILENAME} and {index_path}",
            run_dir=str(run_dir),
            report_path=str(run_dir / REPORT_FILENAME),
            index_path=str(index_path),
            skill=report.skill,
            status=report.status,
        )
        return 0

    except FileNotFoundError as exc:
        emit_result(False, str(exc), flags=["run_not_found"])
        return 2
    except ValueError as exc:
        emit_result(False, str(exc), flags=["adapter_error"])
        return 2
    except Exception as exc:
        emit_result(False, f"{type(exc).__name__}: {exc}", flags=["render_error"])
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
