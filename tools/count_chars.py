#!/usr/bin/env python3
"""
count_chars.py — verification tool for social-post character/link/hashtag/mention checks.

Stdlib-only. Cross-platform (Windows + Unix). No external deps.

Usage (from a skill):
    bash tools/run.sh count_chars.py <draft_path> --format=<x|threads|ig|linkedin>

Direct invocation (Windows uses `py`; Unix uses `python3`):
    py  tools/count_chars.py <draft_path> --format=<x|threads|ig|linkedin>
    python3 tools/count_chars.py <draft_path> --format=<x|threads|ig|linkedin>

Emits a JSON object to stdout matching the schema in
shared-references/verification-protocols.md.

X-specific quirk: X counts every URL as 23 chars regardless of actual length
(the t.co shortener wraps all URLs to length 23). This tool implements that.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAME = "count_chars"
SCHEMA_VERSION = 1

# Per-platform thresholds.
PLATFORMS = {
    "x": {
        "char_limit": 280,
        "hashtag_limit": 3,
        "link_limit": 1,
        "url_weight": 23,   # t.co shortener fixed-width
        "aliases": ("twitter",),
    },
    "threads": {
        "char_limit": 500,
        "hashtag_limit": 5,
        "link_limit": 1,
        "url_weight": None,  # count actual URL length
        "aliases": (),
    },
    "ig": {
        "char_limit": 2200,
        "hashtag_limit": 30,
        "link_limit": 0,     # link-in-bio convention; clickable links don't render anyway
        "url_weight": None,
        "aliases": ("instagram",),
    },
    "linkedin": {
        "char_limit": 3000,
        "hashtag_limit": 5,
        "link_limit": 1,
        "url_weight": None,
        "hook_limit": 210,   # first 2 lines must fit the mobile "…see more" cutoff
        "aliases": (),
    },
}

# URL detection: http(s) only — bare-domain links are explicitly NOT counted (matches X behavior).
URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
# Hashtag: # followed by a unicode word char run; rejects "#" alone, "# space", and pure-digit tags ("#1" is not a hashtag on X).
HASHTAG_RE = re.compile(r"(?<![\w&])#([A-Za-z_][\w]*)", re.UNICODE)
# Mention: @ followed by handle. Reject if preceded by a word char (email "foo@bar.com").
MENTION_RE = re.compile(r"(?<![\w])@([A-Za-z0-9_]{1,15})")
# Mention validity: a malformed candidate is "@" followed by something that isn't a clean handle (emoji, space, > 15 chars, dot, etc.).
# We surface them by finding "@<non-handle>" patterns that LOOK intended.
BAD_MENTION_RE = re.compile(r"(?<![\w])@(?![\s])([^\s@]{0,40})")


def resolve_platform(arg: str) -> str:
    """Map raw --format=... value to canonical platform key."""
    arg = arg.strip().lower()
    if arg in PLATFORMS:
        return arg
    for canonical, spec in PLATFORMS.items():
        if arg in spec["aliases"]:
            return canonical
    raise ValueError(
        f"Unknown platform '{arg}'. Valid: {sorted(PLATFORMS)} "
        f"(aliases: twitter, instagram)."
    )


def count_x_chars(text: str, url_weight: int) -> tuple[int, int]:
    """
    Compute char count under X's t.co rule: each URL counts as `url_weight`
    chars regardless of true length. Returns (effective_chars, raw_chars).
    """
    raw_chars = len(text)
    if url_weight is None:
        return raw_chars, raw_chars
    # Replace each URL match with a placeholder of the weight length.
    # We don't actually need a placeholder string — just compute the delta.
    effective = raw_chars
    for m in URL_RE.finditer(text):
        true_len = len(m.group(0))
        effective += url_weight - true_len
    return effective, raw_chars


def find_hashtags(text: str) -> list[str]:
    return [m.group(1) for m in HASHTAG_RE.finditer(text)]


def find_mentions(text: str) -> list[str]:
    return [m.group(1) for m in MENTION_RE.finditer(text)]


def find_bad_mentions(text: str) -> list[str]:
    """Detect '@'-prefixed tokens that look like intended mentions but aren't well-formed."""
    bad: list[str] = []
    for m in BAD_MENTION_RE.finditer(text):
        candidate = m.group(1)
        # Skip if it actually IS a valid handle (we'd already match via MENTION_RE).
        if re.fullmatch(r"[A-Za-z0-9_]{1,15}", candidate):
            continue
        # Skip empty (just `@` followed by space — already filtered by lookahead, but be safe).
        if not candidate:
            continue
        # Skip email-like (preceding char check already done by lookbehind).
        bad.append(candidate)
    return bad


def find_urls(text: str) -> list[str]:
    return [m.group(0) for m in URL_RE.finditer(text)]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_result(
    *,
    input_file: str,
    platform: str,
    text: str,
) -> dict:
    spec = PLATFORMS[platform]
    effective_chars, raw_chars = count_x_chars(text, spec["url_weight"])
    hashtags = find_hashtags(text)
    mentions = find_mentions(text)
    bad_mentions = find_bad_mentions(text)
    urls = find_urls(text)

    checks: list[dict] = []

    # 1. char_count
    char_passed = effective_chars <= spec["char_limit"]
    char_detail = (
        f"{effective_chars}/{spec['char_limit']} chars"
        + (f" (raw: {raw_chars}; URLs counted as {spec['url_weight']} each)"
           if spec["url_weight"] is not None else "")
    )
    checks.append({
        "name": "char_count",
        "passed": char_passed,
        "detail": char_detail,
        "value": effective_chars,
        "limit": spec["char_limit"],
    })

    # 2. link_count
    link_passed = len(urls) <= spec["link_limit"]
    checks.append({
        "name": "link_count",
        "passed": link_passed,
        "detail": f"{len(urls)} link(s); platform limit {spec['link_limit']}",
        "value": len(urls),
        "limit": spec["link_limit"],
        "links": urls,
    })

    # 3. hashtag_count
    hashtag_passed = len(hashtags) <= spec["hashtag_limit"]
    checks.append({
        "name": "hashtag_count",
        "passed": hashtag_passed,
        "detail": f"{len(hashtags)} hashtag(s); platform limit {spec['hashtag_limit']}",
        "value": len(hashtags),
        "limit": spec["hashtag_limit"],
        "hashtags": hashtags,
    })

    # 4. platform-specific fourth check.
    #    LinkedIn: hook_length (first 2 lines vs the mobile "…see more" cutoff).
    #    X/Threads/IG: mention_validity (well-formed @handles).
    #    The index stays at 3 either way so positional test assertions hold.
    if "hook_limit" in spec:
        hook_text = "\n".join(text.splitlines()[:2])
        hook_len = len(hook_text)
        hook_limit = spec["hook_limit"]
        hook_passed = hook_len <= hook_limit
        checks.append({
            "name": "hook_length",
            "passed": hook_passed,
            "detail": (
                f"first 2 lines = {hook_len} chars; limit {hook_limit}"
                + ("" if hook_passed else "; mobile preview will cut off mid-sentence")
            ),
            "value": hook_len,
            "limit": hook_limit,
        })
    else:
        mention_passed = len(bad_mentions) == 0
        checks.append({
            "name": "mention_validity",
            "passed": mention_passed,
            "detail": (
                f"{len(mentions)} valid mention(s); {len(bad_mentions)} malformed"
                + (f": {bad_mentions}" if bad_mentions else "")
            ),
            "valid_mentions": mentions,
            "malformed": bad_mentions,
        })

    passed = all(c["passed"] for c in checks)
    summary = (
        "all checks passed"
        if passed
        else "; ".join(
            f"{c['name']} FAIL ({c['detail']})" for c in checks if not c["passed"]
        )
    )

    return {
        "tool": TOOL_NAME,
        "schema_version": SCHEMA_VERSION,
        "timestamp": now_iso(),
        "input_file": input_file,
        "platform": platform,
        "passed": passed,
        "checks": checks,
        "summary": summary,
    }


def parse_args(argv: list[str]) -> tuple[str, str]:
    if len(argv) < 3:
        raise SystemExit(
            "usage: count_chars.py <draft_path> --format=<x|threads|ig|linkedin>"
        )
    draft_path = argv[1]
    fmt_arg = argv[2]
    if not fmt_arg.startswith("--format="):
        # Allow positional too: count_chars.py draft.txt x
        if fmt_arg.startswith("--"):
            raise SystemExit(f"unknown flag: {fmt_arg}")
        platform = resolve_platform(fmt_arg)
    else:
        platform = resolve_platform(fmt_arg.split("=", 1)[1])
    return draft_path, platform


def main(argv: list[str]) -> int:
    try:
        draft_path, platform = parse_args(argv)
    except (ValueError, SystemExit) as exc:
        err = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "timestamp": now_iso(),
            "input_file": argv[1] if len(argv) > 1 else "",
            "platform": "",
            "passed": False,
            "checks": [],
            "summary": str(exc).strip() or "argument error",
            "error": type(exc).__name__,
        }
        sys.stdout.write(json.dumps(err, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return 2
    p = Path(draft_path)
    if not p.exists():
        err = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "timestamp": now_iso(),
            "input_file": draft_path,
            "platform": platform,
            "passed": False,
            "checks": [],
            "summary": f"input file not found: {draft_path}",
            "error": "FileNotFoundError",
        }
        sys.stdout.write(json.dumps(err, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return 2

    # Use utf-8 explicitly for cross-platform consistency (Windows defaults to cp1252).
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        err = {
            "tool": TOOL_NAME,
            "schema_version": SCHEMA_VERSION,
            "timestamp": now_iso(),
            "input_file": draft_path,
            "platform": platform,
            "passed": False,
            "checks": [],
            "summary": f"could not read draft: {exc}",
            "error": type(exc).__name__,
        }
        sys.stdout.write(json.dumps(err, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return 2
    result = build_result(input_file=str(p), platform=platform, text=text)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
