"""Shared helpers for report adapters."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .model import ReportItem

TRACE_TRUNCATE_BYTES = 5 * 1024

_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"apify_api_[A-Za-z0-9_-]{20,}"),
]


def load_json_strict(path: Path) -> dict:
    """Raises FileNotFoundError or JSONDecodeError. Use for required files."""
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def load_json_safe(path: Path) -> tuple[dict | None, str | None]:
    """Returns (data, None) on success, (None, error_msg) on miss/malformed."""
    p = Path(path)
    if not p.exists():
        return None, f"FileNotFoundError: {p}"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError: line {exc.lineno} col {exc.colno}: {exc.msg}"


def build_item_skeleton(
    slug: str,
    *,
    title: str = "",
    subtitle: str = "",
    status: str = "in_progress",
) -> ReportItem:
    """Minimal ReportItem scaffold adapters fill in."""
    return ReportItem(
        slug=slug,
        title=title or slug,
        subtitle=subtitle,
        status=status,
    )


def mask_secrets(text: str) -> str:
    """Redact known secret patterns. Applied after HTML escape in the template pipeline."""
    if not text:
        return text
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def truncate_trace(content: str, *, max_bytes: int = TRACE_TRUNCATE_BYTES) -> tuple[str, bool]:
    """Truncate trace text to max_bytes (UTF-8). Returns (text, was_truncated)."""
    if not content:
        return content, False
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content, False
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + "\n[truncated]", True


def snapshot_read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    """
    Copy file to tmp, parse JSONL. Drop trailing partial line WITHOUT warning
    (in-flight write). Warn on malformed full lines.
    """
    p = Path(path)
    if not p.exists():
        return [], [f"FileNotFoundError: {p}"]

    snap = p.with_suffix(p.suffix + ".snap.tmp")
    shutil.copy2(p, snap)
    try:
        raw = snap.read_text(encoding="utf-8", errors="replace")
    finally:
        snap.unlink(missing_ok=True)

    has_trailing_newline = raw.endswith("\n")
    lines = raw.splitlines()
    rows: list[dict] = []
    warnings: list[str] = []
    for i, line in enumerate(lines):
        is_last = i == len(lines) - 1
        if is_last and not has_trailing_newline:
            continue
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            warnings.append(f"{p.name}:{i + 1}: {exc}")
    return rows, warnings


def atomic_write(content: str, target: Path) -> None:
    """Same-dir temp file + fsync + os.replace for atomic replacement."""
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target.parent,
        delete=False,
        suffix=".tmp",
        prefix=target.name + ".",
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        tmp_path = Path(handle.name)
    os.replace(tmp_path, target)


def resolve_under(base: Path, candidate: Path) -> Path | None:
    """Resolve candidate; return None if it escapes base (path traversal guard)."""
    base_resolved = base.resolve()
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        return None
    return resolved
