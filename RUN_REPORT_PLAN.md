# Plan: Shared HTML Report Tool for auto-*-review-loop Skills

> **Status:** approved · cleared CEO + Eng + Design + Codex outside-voice review · ready to implement.
> **Plan file lifecycle:** delete this file when the work is shipped (PR merged + smoke tests green on `master`).

## For implementing agents — start here

1. **Read this whole file once.** All decisions are settled — there are no open AskUserQuestions. Every section reflects a choice the user already made; do not re-litigate.
2. **Source of truth for what to build:** the "File-level plan" table (24 new files + ~5 edits), the "Engineering Specifications" section (atomic write contract, `load_json` contract, snapshot read, secret-mask placement, etc.), and the "Design Specifications" section (color tokens, typography, component specs, AI-slop do-not-use list).
3. **Suggested execution order:** the "Implementation order — revised with parallel lanes" subsection inside Engineering Specifications. Lane A (critical path) + Lane B (migration, independent) + Lane C (9 adapters, parallelizable after foundations land). With CC + parallel agents the whole thing fits in ~30–45 minutes wall-clock.
4. **Tests:** extend `tests/run_tests.sh` (the existing bash-assertion framework). Do NOT introduce pytest — the "Test plan" subsection lists every assertion to add and every fixture to commit. Include a `tests/fixtures/runs/outbound_happy/expected_report.html` golden snapshot for byte-for-byte regression protection.
5. **Verification:** the "Verification (end-to-end test plan after implementation)" section near the bottom lists 12 smoke checks (including the manual `/design-review` items for browser-only behaviors).
6. **Cross-references in the existing codebase:** `skills/auto-linkedin-outbound-loop/SKILL.md` describes the outbound pipeline whose Phase 6 you wire into. `shared-references/verification-protocols.md` + `output-manifest.md` define the JSON shapes the outbound adapter reads. `tools/run.sh` is the existing wrapper convention.
7. **Real fixture corpus:** redact + commit a copy of the existing run at `/Users/ycao/Documents/GitHub/tacite-source-of-truth/2_URGENT/ADHD_founder_outreach/20260513_141200_adhd-founders/` into `tests/fixtures/runs/outbound_happy/`. Strip real LinkedIn URLs and proper names; keep the schema.
8. **When done:** run `bash tests/run_tests.sh` (all green), open one generated `report.html` in Chrome (0 console errors), then `/ship`. Delete this plan file in the same PR.

## Context

**Problem.** The `auto-linkedin-outbound-loop` skill (and 9 sibling auto-*-review-loop skills) produce ~30-50 fragmented JSON/JSONL/CSV/MD files per run, spread across 7 numbered phase directories (`00_campaign/` → `06_exports/` + `traces/`). To answer "what happened in this run?", the user must open 5+ files (`AUTO_REVIEW.md`, `06_exports/approved_messages.csv`, `05_verification/<slug>_verify.json`, `03_qualification/qualified_prospects.json`, profile JSON, persona trace .txt files). No single view shows per-prospect outcome end-to-end.

**Intended outcome.** One self-contained `report.html` per run, plus a cross-run `review-stage/index.html`, that the user opens from disk (`open report.html`). Per-prospect drill-down inline. Generated automatically as the last phase of every loop, and runnable standalone on any past run dir. Solves the pain for outbound *and* for the other nine sibling skills via the same tool with thin per-skill adapters.

**Mode chosen during CEO review.** SELECTIVE EXPANSION + Approach C (shared report tool). Six expansion candidates surfaced; all six accepted (E1 trace viewer, E2 round diff, E3 funnel, E4 live-watch, E5 all 9 adapters now, E6 next-step CTAs).

**Non-goals.** No server. No SPA. No real-time WebSocket. No mobile-first responsive design. No auth. No multi-user. No external CDN dependencies — every report.html must `open file://` and render fully without network.

---

## Architecture

```
            ┌─────────────────────────────────────────────────┐
            │  Existing pipeline (outbound, essay, blog, ...) │
            │  writes RUN.json + phase dirs to run_dir/       │
            └────────────────────┬────────────────────────────┘
                                 │ Phase N (last) invokes
                                 ▼
            ┌─────────────────────────────────────────────────┐
            │  tools/generate_run_report.py <run_dir>         │
            │  ─────────────────────────────────────────────  │
            │  1. Read RUN.json → skill key                   │
            │  2. Registry lookup: tools/report_adapters/...  │
            │  3. Adapter reads phase dirs → ReportRun model  │
            │  4. Render templates/report/run.html.j2         │
            │  5. Atomic write: run_dir/report.html           │
            │  6. Scan review-stage/**/RUN.json               │
            │  7. Render templates/report/index.html.j2       │
            │  8. Atomic write: review-stage/index.html       │
            └─────────────────────────────────────────────────┘
```

Per-skill adapter contract: a `build(run_dir: Path) -> ReportRun` function. Adapters live in `tools/report_adapters/{skill}.py` (centralized; matches the existing `tools/qualify_prospect.py`-style layout). The registry is a dict in `tools/report_adapters/__init__.py` keyed by skill name.

**Coupling.** Adapters depend on each skill's output schema. Each adapter declares expected phase-dir names as module-level constants; a missing dir yields a "partial run" warning, not a crash.

**Failure isolation.** The cross-run index scanner wraps each adapter call in a try/except — one broken run does not break the index; that row shows an ERROR badge with a link to the raw run dir.

---

## Report Model (typed dataclasses)

Defined in `tools/report_adapters/__init__.py`:

```python
@dataclass
class ReportScore:
    persona: str            # "target-customer" | "spam-filter" | ...
    score: int | None       # 0-10, None if inconclusive
    verdict: str            # "ready" | "almost" | "not ready" | "inconclusive"
    weaknesses: list[str]
    summary: str

@dataclass
class ReportCheck:
    name: str               # "message_length" | "evidence_count" | ...
    passed: bool
    detail: str

@dataclass
class ReportTrace:
    persona: str
    round: int
    prompt: str             # truncated to 5KB
    response: str           # truncated to 5KB
    truncated: bool
    raw_path: str           # link target for full file

@dataclass
class ReportRound:
    n: int                  # 1, 2, 3
    message: str            # the candidate message at this round
    scores: list[ReportScore]
    checks: list[ReportCheck]
    traces: list[ReportTrace]

@dataclass
class ReportItem:
    slug: str               # profile_slug / essay_slug / cv_slug
    title: str              # display name
    subtitle: str           # role/company/etc.
    status: str             # "approved" | "rejected" | "in_progress" | ...
    final_message: str | None
    rounds: list[ReportRound]
    metadata: dict[str, str]    # adapter-specific extras
    next_step_cta: str | None   # E6

@dataclass
class ReportFunnel:
    stages: list[tuple[str, int]]   # [("discovered", 25), ("qualified", 18), ...]

@dataclass
class ReportRun:
    schema_version: int = 1
    run_id: str
    skill: str
    campaign: str
    status: str             # "in_progress" | "completed" | "stalled"
    started_at: str         # ISO 8601
    completed_at: str | None
    funnel: ReportFunnel
    items: list[ReportItem]
    rejected_items: list[ReportItem]
    warnings: list[str]     # adapter warnings (missing files, skipped rows, etc.)
    manifest_path: str | None
```

The Report Model is the source-of-truth contract documented in `shared-references/report-model.md` and tested against fixtures per adapter.

---

## File-level plan

| # | File | Purpose | LOC est | New/Edit |
|---|------|---------|---------|----------|
| 1 | `tools/generate_run_report.py` | CLI entry; argparse; atomic write; secret masking; index scan | ~150 | New |
| 2 | `tools/report_adapters/__init__.py` | ReportRun dataclasses; registry; `load_json` helper; secret regex masker | ~120 | New |
| 3 | `tools/report_adapters/outbound.py` | Outbound run dir → ReportRun (canonical adapter) | ~140 | New |
| 4 | `tools/report_adapters/essay.py` | auto-essay-review-loop adapter | ~80 | New |
| 5 | `tools/report_adapters/blog.py` | auto-blog-review-loop adapter | ~60 | New |
| 6 | `tools/report_adapters/cv.py` | auto-cv-review-loop adapter | ~60 | New |
| 7 | `tools/report_adapters/slides.py` | auto-slides-review-loop adapter | ~80 | New |
| 8 | `tools/report_adapters/business_plan.py` | auto-business-plan-review-loop adapter | ~60 | New |
| 9 | `tools/report_adapters/application.py` | auto-application-review-loop adapter | ~60 | New |
| 10 | `tools/report_adapters/social.py` | auto-social-review-loop adapter | ~60 | New |
| 11 | `tools/report_adapters/linkedin.py` | auto-linkedin-review-loop adapter | ~60 | New |
| 12 | `tools/report_adapters/market_research.py` | market-research adapter | ~80 | New |
| 13 | `templates/report/run.html.j2` | Single-run template; inline CSS; vanilla JS for sort/filter and copy buttons | ~280 | New |
| 14 | `templates/report/index.html.j2` | Cross-run index; one row per run | ~100 | New |
| 15 | `templates/report/_css.html.j2` | Inline CSS partial (terse/dense aesthetic per S11-1) | ~150 | New |
| 16 | `templates/report/_js.html.j2` | Inline vanilla JS (copy, sort, filter, auto-refresh helpers) | ~70 | New |
| 17 | `shared-references/report-model.md` | Report Model schema spec; adapter contract; aesthetic guidelines | ~120 | New |
| 18 | `tools/migrate_run_json_add_skill.py` | Walks existing run dirs, adds `skill` field to RUN.json (idempotent) | ~60 | New |
| 19 | `tests/test_report_outbound.py` | Outbound adapter + template tests, fixture-based | ~200 | New |
| 20 | `tests/test_report_index.py` | Cross-run index aggregation + isolation | ~100 | New |
| 21 | `tests/test_report_security.py` | XSS autoescape, secret masking, path traversal, self-containment | ~120 | New |
| 22 | `tests/fixtures/runs/outbound_happy/` | Redacted real outbound run | corpus | New |
| 23 | `tests/fixtures/runs/outbound_partial/` | Missing 06_exports — mid-flight | corpus | New |
| 24 | `tests/fixtures/runs/essay_happy/` | Canary fixture for essay adapter | corpus | New |
| 25 | `tools/init_outbound_run.py` | Bump schema_version to 2; write `skill: "linkedin-outbound"` field | edit | Edit |
| 26 | All other `tools/init_*_run.py` (if they exist) or skill bootstrap docs | Same `skill` field bump | edit | Edit |
| 27 | `skills/auto-linkedin-outbound-loop/SKILL.md` | Add Phase 6 step calling `generate_run_report.py`; document live-watch behavior | edit | Edit |
| 28 | Other `skills/auto-*-review-loop/SKILL.md` | Add equivalent generator call at end of each pipeline | edit | Edit |

**Total: 24 new files + ~4-10 edits depending on how many sibling skills have their own init tools.** Rough LOC: ~2,200 across new files (heavily dominated by templates and fixtures).

---

## Key decisions captured (CEO review)

| ID | Decision | Choice |
|----|----------|--------|
| Approach | Implementation shape | C — shared report tool for all 10 loops |
| Mode | Review posture | SELECTIVE EXPANSION |
| E1 | Persona-trace viewer inline | ACCEPTED — collapsed `<details>` per persona-round |
| E2 | Per-round message diff | ACCEPTED — stdlib `difflib.HtmlDiff`; only when message changed |
| E3 | Funnel chart at top | ACCEPTED — pure-CSS bar chart |
| E4 | Live-watch auto-refresh | ACCEPTED — main pipeline writes after each prospect; `<meta refresh>` while in_progress |
| E5 | All 9 sibling adapters now | ACCEPTED — boil-the-lake |
| E6 | Per-state next-step CTAs | ACCEPTED — copy + LinkedIn deep link / retry CLI / round-N status |
| D-0E-1 | Run identifier | RUN.json `skill` field (schema_version 2) |
| D-0E-2 | Untrusted content | Jinja2 autoescape + `html.escape()` on trace files |
| D-0E-3 | Live-watch writer | Main pipeline writes after each prospect (sync) |
| D-0E-4 | Index regeneration trigger | Every run-report write also rewrites index.html |
| S1-1 | Report Model representation | Python `@dataclass` with type hints |
| S1-2 | Adapter location | `tools/report_adapters/{skill}.py` (centralized) |
| S3-1 | Secret masking regex | YES — defense in depth; `sk-*`, `apify_api_*`, `Bearer *` → `[REDACTED]` |
| S6-1 | Headless Chromium test | SKIP — string snapshots only; revisit if visual regressions appear |
| S9-1 | RUN.json migration | Update init tools + ship one-shot migration script |
| S11-1 | Aesthetic direction | Terse/dense — monospace headings, minimal chrome, signal-first |

---

## Error & rescue map (Section 2 summary)

13 failure paths identified; all rescued with named exception classes and user-visible messages. **No CRITICAL GAPS.** Key patterns:
- Missing/malformed `RUN.json` → exit code 2 with actionable message
- Missing phase dir → warning banner + render proceeds (partial run)
- Malformed JSONL row → skip + record in `model.warnings[]`
- Trace > 50KB → truncate to 5KB + link to raw file
- Per-run adapter failure during cross-run scan → isolated; index shows ERROR badge
- Template `UndefinedError` → fail loudly (dev bug, not user error)

No catch-all `except Exception:` blocks anywhere.

---

## Security (Section 3 summary)

| Threat | Mitigation |
|--------|------------|
| XSS from Apify-scraped profile content | Jinja2 `autoescape=True` + `html.escape()` for trace files |
| XSS from LLM trace content | Same |
| Path traversal via CLI arg | `Path.resolve()` + assert under run_dir |
| Symlink escape during `traces/` walk | `Path.resolve()` + scope check |
| Email/phone leak via raw enrichment | Adapter reads only `enriched_profiles.normalized.json`, never `.raw.json` (enforced + documented invariant) |
| Future credential leak via trace content | Regex pass for `sk-*`, `apify_api_*`, `Bearer *` → `[REDACTED]` (S3-1) |

---

## Test plan (Section 6 summary)

| Test | Type | Covers |
|------|------|--------|
| `test_outbound_adapter_happy_path` | Unit | Canonical fixture → expected ReportRun |
| `test_outbound_adapter_partial_run` | Unit | Missing `06_exports/` → warning, no crash |
| `test_outbound_adapter_malformed_jsonl` | Unit | Truncated row skipped + warning |
| `test_outbound_adapter_traces_too_large` | Unit | 100KB trace → truncated to 5KB + raw_path link |
| `test_outbound_adapter_strips_secrets` | Unit | `Bearer sk-abc123` in trace → `[REDACTED]` |
| `test_template_renders_with_minimum_model` | Unit | 0 prospects → "0 qualified" message |
| `test_template_autoescapes_xss` | Unit | `<script>` in profile → escaped |
| `test_template_self_contained` | Unit | No `http://`, no `<link rel="stylesheet">`, no `<script src=`, no external font URLs |
| `test_index_aggregates_multiple_runs` | Integration | 3 fake runs → 3 rows |
| `test_index_isolates_broken_run` | Integration | 1 broken RUN.json → others render + ERROR badge |
| `test_cli_exits_2_on_no_run_json` | Integration | `generate_run_report.py /tmp/empty` → exit 2 |
| `test_atomic_write_no_partial_file` | Unit | Simulated mid-write kill → no `.tmp` leftover |
| `test_essay_adapter_happy_path` | Unit | Canary against a 2nd skill — catches Report Model overfitting to outbound |

Headless Chromium render test deliberately deferred (S6-1).

---

## Reuse map (existing code to leverage)

- `RUN.json` — already exists; just add `skill` field (D-0E-1).
- `prospect_state.jsonl` and `outbound_state.py` — state machine the adapter consumes.
- `MANIFEST.md` (per `shared-references/output-manifest.md`) — append one line per report write.
- `verify_outbound_message.py` JSON schema — adapter maps directly to `ReportCheck`.
- `shared-references/verification-protocols.md` — already defines verification JSON shape; refer to it from the Report Model spec.
- `tools/run.sh` — invocation wrapper for the new tool.
- Real run at `/Users/ycao/Documents/GitHub/tacite-source-of-truth/2_URGENT/ADHD_founder_outreach/20260513_141200_adhd-founders/` — copy + redact for fixture.

---

## Implementation order (suggested)

1. **Hour 1 — foundations:** Report Model dataclasses + `tools/report_adapters/__init__.py` registry + `load_json` helper + secret-mask regex. Tests for these primitives.
2. **Hour 2 — outbound adapter (canonical):** `tools/report_adapters/outbound.py` reading the existing run fixture; assert ReportRun shape with a fixture test.
3. **Hour 3 — templates:** `templates/report/run.html.j2` + `_css.html.j2` + `_js.html.j2`. Terse/dense aesthetic (S11-1). Render outbound fixture → eyeball.
4. **Hour 4 — security:** XSS autoescape test; secret-mask test; path-traversal test; self-containment test.
5. **Hour 5 — index + cross-run scan:** `templates/report/index.html.j2` + scan logic in `generate_run_report.py`. Integration tests for aggregation and broken-run isolation.
6. **Hour 6 — migration:** `tools/migrate_run_json_add_skill.py` + edit `init_outbound_run.py` to write `skill` field on new runs.
7. **Hour 7 — wire outbound skill:** Edit `skills/auto-linkedin-outbound-loop/SKILL.md` to call `generate_run_report.py` after Phase 5 export, and after each prospect when E4 live-watch is enabled (default on).
8. **Hour 8-10 — other 9 adapters:** essay, blog, cv, slides, business_plan, application, social, linkedin, market_research. Canary test against essay early (Hour 8) to validate the Report Model against a 2nd skill shape before doing the rest.
9. **Hour 11 — polish:** stale-run detection (10min no state change → "stalled" banner); funnel rendering tuning; copy-button JS.
10. **Hour 12 — docs:** `shared-references/report-model.md` finalized with the canonical adapter walkthrough.

Estimates: human team ~3-4 days; CC + gstack ~90 minutes total. Boil-the-lake delta over outbound-only ~30-45 min.

---

## Engineering Specifications

Added during `/plan-eng-review` + codex outside-voice challenge. These supersede the looser language used in earlier sections of this plan.

### Module structure

`tools/report_adapters/` is split into three focused modules (not one god-module):

- `tools/report_adapters/__init__.py` — thin: only the `@register(skill_name)` decorator + auto-import loop + the registry dict + Jinja environment setup with custom filters.
- `tools/report_adapters/model.py` — all `@dataclass` definitions (`ReportRun`, `ReportItem`, `ReportRound`, `ReportScore`, `ReportCheck`, `ReportTrace`). No logic. `ReportFunnel` dropped — funnel is a bare `list[tuple[str, int]]` on `ReportRun.funnel`.
- `tools/report_adapters/_helpers.py` — `load_json_strict`, `load_json_safe`, `build_item_skeleton`, `truncate_trace`, `mask_secrets`, `snapshot_read_jsonl`.

### Adapter registration

`@register("outbound")` decorator at module scope. `tools/report_adapters/__init__.py` runs `for f in os.listdir(__path__): importlib.import_module(...)` at import time. Each adapter self-registers. No manual edit per new adapter. ~15 LOC in `__init__.py`.

### Atomic write contract

```python
def atomic_write(content: str, target: Path) -> None:
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=target.parent,   # same FS as target → os.replace is atomic
        delete=False, suffix=".tmp", prefix=target.name + "."
    ) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
        tmp_path = Path(f.name)
    os.replace(tmp_path, target)
```

### load_json contract (two functions, explicit semantics)

```python
def load_json_strict(path: Path) -> dict:
    """Raises FileNotFoundError or JSONDecodeError. Use for required files."""

def load_json_safe(path: Path) -> tuple[dict | None, str | None]:
    """Returns (data, None) on success, (None, error_msg) on miss/malformed.
    Caller appends error_msg to model.warnings as desired. Use for optional files."""
```

### Secret masking — single chokepoint (codex X1 fix)

Jinja2 `autoescape=True` + a custom filter `mask_secrets` registered in the **default escape pipeline**:

```python
env = Environment(autoescape=True, ...)
env.filters["mask_secrets"] = mask_secrets
# Override the default html escape to chain mask_secrets after escape:
env.policies["html.autoescape"] = lambda s: Markup(mask_secrets(escape(str(s))))
```

**Do NOT call `html.escape()` in adapter or helper code.** Autoescape is the single chokepoint. Calling escape twice produces `&amp;lt;` instead of `&lt;`. (Codex caught this in cross-model tension.) `truncate_trace` returns raw text; the template render path handles escape + mask in one pass.

Patterns masked: `sk-[A-Za-z0-9_-]{20,}`, `apify_api_[A-Za-z0-9_-]{20,}`, `Bearer\s+[A-Za-z0-9._-]{20,}` → `[REDACTED]`. Anchored to avoid false positives.

### Snapshot-read with partial-line tolerance (codex X3 fix)

```python
def snapshot_read_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    """
    Copy file to tmp, parse JSONL. Drop trailing partial line WITHOUT warning
    (it's an in-flight write, not corruption). Warn on malformed full lines.
    Returns (rows, warnings).
    """
    snap = shutil.copy2(path, path.with_suffix(path.suffix + ".snap.tmp"))
    try:
        raw = Path(snap).read_text(encoding="utf-8", errors="replace")
    finally:
        Path(snap).unlink(missing_ok=True)
    has_trailing_newline = raw.endswith("\n")
    lines = raw.splitlines()
    rows, warnings = [], []
    for i, line in enumerate(lines):
        is_last = (i == len(lines) - 1)
        if is_last and not has_trailing_newline:
            continue  # partial in-flight write; silently drop
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            warnings.append(f"prospect_state.jsonl:{i+1}: {e}")
    return rows, warnings
```

### Cross-run scan — per-repo cache (codex X2 fix)

Cache lives at `review-stage/.report-index.cache.json` (NOT `~/.gstack/cache/...` — that was a reproducibility hazard across branches/repos). Each entry keyed by absolute path; invalidated when RUN.json mtime differs. `.gitignore` adds `.report-index.cache.json`. Idempotent re-build on cache miss.

### Phase 6 generator failure semantics (codex X4 fix)

Report generation **never blocks the pipeline**. Skill files invoke the generator with:

```bash
bash tools/run.sh generate_run_report.py "$RUN_DIR" 2>&1 | tee -a "$RUN_DIR/MANIFEST.md" || \
    echo "WARN: report generation failed (exit $?); run artifacts still at $RUN_DIR"
```

A Jinja template typo at the end of a 30-minute outbound run does NOT lose the run. User can re-invoke the generator standalone any time.

### Migration safety (Finding 1.5 fix)

`tools/report_adapters/__init__.py` includes a path-inference fallback: if `RUN.json` lacks the `skill` key, infer from path segment matching `review-stage/{skill}/runs/...`. Adapter-side belt-and-suspenders against the in-flight-pipeline-during-migration race. Migration script ships as well, but is no longer load-bearing for correctness.

### Implementation order — revised with parallel lanes

```
Lane A (critical path, ~8 hours human / ~50 min CC):
  hr1: foundations (model.py + __init__.py + _helpers.py + tests for primitives)
  hr2: outbound adapter (build outbound.py against existing fixture)
  hr3: templates (run.html.j2 + _css + _js, terse aesthetic per Design Specs)
  hr4: security tests (XSS escape, secret mask, path-traversal, self-containment)
  hr5: index + cross-run scan + per-repo cache (X2)
  hr6: wire outbound SKILL.md (Phase 6 call with log-and-continue)
  hr7: polish (stalled-run detection, copy-button JS, deep-link auto-expand)
  hr8: docs (shared-references/report-model.md = Report Model + Design Specs)

Lane B (independent from Lane A, ~1 hour human / ~5 min CC):
  - migrate_run_json_add_skill.py (idempotent walk)
  - init_outbound_run.py edit (schema_version=2 + skill field)
  - run after foundations land so registry exists

Lane C (parallel after foundations, ~3 hours human / ~10 min CC each):
  3 sub-lanes of 3 adapters each:
    C1: essay, blog, cv
    C2: slides, business_plan, application
    C3: social, linkedin, market_research
  Essay first as canary fixture to validate Report Model against a 2nd skill.

Merge order: A's hr1 → all lanes start. B merges at hr2. C merges at hr5.
A continues hr6-8 with C's adapters available.

Total wall-clock: ~5-8 hours human / ~30-45 min CC with parallel agents.
```

### Test plan — extended bash framework (run_tests.sh additions)

~150 LOC added to `tests/run_tests.sh`, ~50 LOC inline doctests in `_helpers.py`. Test names below match the existing `assert_*` style.

**CLI exit codes (5 tests):**
- `generate_run_report missing run_dir exits 2` (passed=false expected)
- `generate_run_report invalid path exits 2`
- `generate_run_report on RUN.json without skill field falls back to path inference` (per 1.5)
- `generate_run_report on RUN.json with unknown skill exits 2`
- `generate_run_report --index alone produces only index.html`

**Outbound happy fixture (6 tests):**
- `generate_run_report on outbound_happy writes report.html`
- `report.html contains funnel counts` (grep)
- `report.html contains [copy] buttons with aria-label`
- `report.html has no external URLs` (self-containment)
- `report.html escapes <script> from profile`
- `report.html masks [REDACTED] when fixture trace has Bearer sk-xyz`

**Live-watch (2 tests, per 3.2):**
- `report.html on outbound_in_progress fixture has <meta http-equiv="refresh">`
- `report.html on outbound_completed fixture has NO <meta refresh>`

**Partial/error (4 tests):**
- `generate_run_report on outbound_partial shows PARTIAL banner; exit 0`
- `generate_run_report on outbound with malformed-tail JSONL drops partial silently; no warning row` (X3)
- `generate_run_report on outbound with malformed-middle JSONL warns + continues`
- `generate_run_report on broken-template fixture exit 1 with traceback`

**Index aggregation (4 tests):**
- `index aggregates 3 fixture runs`
- `index isolates broken RUN.json with ERROR badge` (other runs render fine)
- `index pins in-progress run to top` (per U7)
- `index mtime cache: 2nd invocation re-uses cache for unchanged runs`

**Migration (3 tests):**
- `migrate_run_json_add_skill on fixture without skill field writes skill correctly`
- `migrate_run_json_add_skill on already-migrated run is no-op` (idempotent)
- `init_outbound_run produces RUN.json with skill='linkedin-outbound' + schema_version=2`

**Adapter canary (1 test):**
- `generate_run_report on essay_happy fixture succeeds without modifying generator logic` (catches Report Model overfit)

**Helpers via inline Python (4 doctests):**
- `mask_secrets("Bearer sk-abc...") == "[REDACTED]"`
- `truncate_trace(100KB) → 5KB + "[truncated]"`
- `load_json_safe(missing) → (None, "FileNotFoundError")`
- `load_json_safe(malformed) → (None, "JSONDecodeError: line N col M")`

**Golden HTML snapshot (1 test, per codex X5):**
- `tests/fixtures/runs/outbound_happy/expected_report.html` committed; assert byte-for-byte match against `generate_run_report` output. Single regression guard catches template + CSS + adapter regressions in one go. Re-baseline with explicit `--update-golden` flag.

**Manual /design-review smoke checklist (5 items, per 3.3):**
- focus ring visible on Tab on all interactive elements
- copy button aria-label correct per prospect ("Copy message to Chris at Amiara")
- funnel chart aria-label present + visually-hidden table renders
- localStorage persists across reload (click 3 copies → reload → 3 buttons show `[✓ copied]`)
- print stylesheet expands all `<details>` and hides copy buttons

**Total:** 30 new bash assertions + 5 manual smoke items. 0 critical gaps in failure modes registry.

### Failure modes registry — 20 paths, 0 critical gaps

See "Failure modes registry" table inserted during eng review (lives in the conversation, transcribed here for the record). Every failure has: rescue + named exception + user-visible signal + test (auto or manual smoke).

### Per-surface size caps (codex X6)

```
inline trace truncation cap   5 KB per trace file
trace count per prospect      12 (4 personas × 3 rounds max)
round diff visible cap        20 KB (falls out from 5KB trace truncation × 2)
inline prospect cards cap     100 per report.html
when over cap                 visible "[N more truncated — see <path>]" marker
                              with a link to the raw artifact folder
```

### Eng decisions captured (Section 1-4 + codex)

| ID | Decision | Choice |
|----|----------|--------|
| Eng-D1 | Scope reconfirm at complexity check | Proceed as-is with Approach C (boil-the-lake) |
| 1.1 | Adapter registry | `@register` decorator + auto-import via `importlib` |
| 1.2 | Atomic write | Same-dir `NamedTemporaryFile` + `os.replace` + `os.fsync` |
| 1.3 | Cross-run scan growth | Lazy mtime cache (location amended in X2) |
| 1.4 | Live-watch race | Snapshot copy + tolerant parser (amended in X3) |
| 1.5 | Migration sequencing | Init tools + migration script + adapter-side path-inference fallback |
| 2.1 | Adapter scaffolding | Module-level helpers in `_helpers.py`; no base class |
| 2.2 | Split `__init__.py` | 3 modules: `__init__.py` + `model.py` + `_helpers.py` |
| 2.3 | `load_json` contract | Two functions: `load_json_strict` (raises) + `load_json_safe` (returns tuple) |
| 2.4 | Secret-mask placement | Jinja2 custom filter via escape pipeline (single chokepoint) |
| 2.5 | `ReportFunnel` dataclass | Drop — use bare `list[tuple[str, int]]` |
| 3.1 | Test framework | Extend `tests/run_tests.sh` (no pytest) |
| 3.2 | Live-watch meta-refresh test | Two-state fixture pattern (in_progress vs completed) |
| 3.3 | Browser-only behavior tests | Manual `/design-review` smoke checklist post-impl |
| X1 (codex) | Double-escape fix | Autoescape ON; drop manual `html.escape` from helpers |
| X2 (codex) | Cache location | `review-stage/.report-index.cache.json` (per-repo) |
| X3 (codex) | Partial-line race | Drop trailing partial line silently; warn only on full malformed lines |
| X4 (codex) | Generator failure semantics | Log + continue; never block the pipeline |
| X5 (codex) | Golden HTML snapshot | Add as 1 test (byte-for-byte match against committed expected_report.html) |
| X6 (codex) | Per-surface size caps | Document caps + visible truncation marker |

---

## Design Specifications

Added during `/plan-design-review`. These specs ship to the implementer as a copy-paste contract — `shared-references/report-model.md` should embed the same content verbatim under an "Aesthetic & visual specs" section so it survives as the de facto design system for any future report UI.

### Information architecture — per-prospect card (expanded)

Order is descending-priority for the developer's actual question on an approved card ("send it now"). Profile and fit are context; persona scorecard and verification defend the approval; traces and round-diff are debugging-tier, collapsed by default.

```
┌─ Card header: slug · status badge · channel · message length ──────────┐
│ [collapse arrow]                                                       │
├────────────────────────────────────────────────────────────────────────┤
│ NEXT STEP CTA                          (always above the fold)         │
│   approved → [copy message] [open LinkedIn profile ↗]                  │
│   rejected → top 3 blockers + [retry CLI command (copy)]               │
│   in_progress → round N of 3 in flight                                 │
├────────────────────────────────────────────────────────────────────────┤
│ FINAL MESSAGE                          (the thing they're going to send)│
│   [232/300 chars · linkedin_connection]                                │
│   ───────────────────────────────────────────────────────────────────  │
│   Hi Chris, your remote staffing work...                               │
├────────────────────────────────────────────────────────────────────────┤
│ PROFILE                                (one-line context)              │
│   Chris Kille · Remote staffing for franchise systems · LinkedIn ↗     │
├────────────────────────────────────────────────────────────────────────┤
│ FIT (qualification)                                                    │
│   score 8/10 — Founder of remote-staffing co; matched B2B SaaS ICP     │
├────────────────────────────────────────────────────────────────────────┤
│ PERSONA SCORECARD (table, 4 rows × 3 cols)                             │
│   target-customer  9/10  would_reply=maybe   ready                     │
│   spam-filter      8/10  spam_risk=low       ready                     │
│   sales-leader     7/10  —                    almost                    │
│   compliance       9/10  —                    ready                     │
├────────────────────────────────────────────────────────────────────────┤
│ VERIFICATION (compact row)                                             │
│   ✓ length 232/300   ✓ evidence 2   ✓ forbidden=none   ✓ channel ok    │
├────────────────────────────────────────────────────────────────────────┤
│ ▶ Round diff (1 → 3)               <details>, collapsed by default     │
│ ▶ Persona traces                   <details>, nested:                  │
│   ▶ Round 1   →   (4 personas as inner <details>)                      │
│   ▶ Round 2   →   (4 personas as inner <details>)                      │
└────────────────────────────────────────────────────────────────────────┘
```

### Information architecture — index.html

```
review-stage/index.html
═══════════════════════════════════════════════════════════════════════════
review-stage / index                                       47 runs · 4 skills
─────────────────────────────────────────────────────────── filter: [skill ▾]
                                                                   [search: ░]

  when             skill                     campaign            stat  qual  appr
  ───────────────  ────────────────────────  ──────────────────  ────  ────  ────
  2026-05-13 14:12 linkedin-outbound         adhd-founders        ⏳    8/25  3   ← in-progress pinned
  2026-05-13 09:33 essay                     why-i-build          ✓    1/1    1
  2026-05-12 18:02 linkedin-outbound         saas-cfos            ✗    0/12   0
  2026-05-11 23:55 cv                        yuxuan-2026          ⚠    1/1    0  (partial)
  ...
═══════════════════════════════════════════════════════════════════════════
```

Default sort: in-progress runs pinned to the top; within each tier, `started_at` descending.

### Interaction state treatments

```
EMPTY (0 prospects qualified)
───────────────────────────────────────────────────────────────
0 prospects qualified out of 12 enriched.
The top rejection reasons were:
  • headline didn't match ICP titles (×7)
  • company stage mismatch (×3)
  • no public posts in last 12 months (×2)
Either widen the ICP or recheck the URL list.
  → review-stage/.../03_qualification/rejected_prospects.json

PARTIAL (run mid-flight)
───────────────────────────────────────────────────────────────
⏳  Run in progress — last updated 14s ago. This page refreshes every 5s.
    8 of 25 prospects complete · est. ~6m remaining

STALLED (no state change > 10m)
───────────────────────────────────────────────────────────────
⚠  No state changes in 12 minutes. The pipeline may have crashed.
    Last completed prospect: chriskille at 14:23:01
    → tail review-stage/.../prospect_state.jsonl
    → check Apify / Codex MCP availability

ERROR (adapter failed)
───────────────────────────────────────────────────────────────
✗  Could not generate report for this run.
    Adapter: outbound · Exception: FileNotFoundError
    'review-stage/.../00_campaign/campaign.input.json' missing
    Raw artifacts are intact at: review-stage/.../
    → file a bug if this was a clean pipeline run

INDEX: 0 runs ever
───────────────────────────────────────────────────────────────
No runs yet. Run a skill to generate your first report.
    /auto-linkedin-outbound-loop campaigns/<name>.json
    /auto-essay-review-loop drafts/<name>.md
```

Principles applied: no decorative empty illustrations — text plus a real next action. Every error states what to do next, not just what failed. Emoji prefix is the only decoration, used as status signal not ornament.

### User journeys (storyboards)

```
JOURNEY A — happy run
  STEP                              USER FEELS              PLAN SUPPORTS?
  ──────────────────────────────── ─────────────────────── ─────────────────
  1. Pipeline finishes              relief                  ✓ (terminal prints path)
  2. Opens report.html              curiosity              ✓ (funnel + CTA at top)
  3. Sees 9 approved messages       satisfaction           ✓
  4. Reads top message              quick assessment        ✓
  5. Copies + opens LinkedIn        flow state              ✓ (E6 CTA + copy state)
  6. Sends, returns for next        return loop             ✓ (localStorage [copied] cue)
  7. Closes tab                     done                    ✓

JOURNEY B — debugging arc
  STEP                              USER FEELS              PLAN SUPPORTS?
  ──────────────────────────────── ─────────────────────── ─────────────────
  1. Pipeline finishes with errors  worry                   ✓ (terminal summary)
  2. Opens report.html              uncertainty             ✓ (header banner)
  3. Sees 0 approved / 12 rejected  frustration             ✓ (triage callout at top)
  4. Looks for "why"                hunting                 ✓ (rejection-pattern grouping)
  5. Drills into one rejection      forensic               ✓ (E1 traces, nested)
  6. Decides retry vs ICP tweak     wants guidance         ✓ (top-blocker counts + retry CLI)
  7. Closes, edits campaign         action                  ✓
```

Three new behaviors land in v1 because of Journey B:
- **Triage callout:** when `approved_count == 0`, the header renders a banner above the (empty) Approved section linking to the top 3 rejection patterns. Cheap.
- **Rejection-pattern grouping:** the rejected list is sorted by primary blocker with a one-line count header per group (`"5 rejected for spam-filter: weak CTA"`). ~10 LOC in the adapter.
- **Copy-state persistence:** copy buttons toggle to `[copied]` for 2s, AND record the prospect slug in `localStorage` so a `[✓ copied]` mark persists across reloads. Enables the return-loop ("which did I already send?"). ~10 LOC vanilla JS.

### Design tokens (light theme, v1)

```css
/* COLOR */
--bg:               #ffffff;
--bg-elev-1:        #fafafa;  /* table-row zebra, card hover */
--bg-elev-2:        #f4f4f4;  /* collapsed <details> headers */
--border:           #e4e4e4;  /* 1px hairlines */
--border-strong:    #c8c8c8;  /* table outer borders */
--text-primary:    #1a1a1a;  /* body, headings, message text */
--text-muted:      #6e6e6e;  /* metadata, timestamps, labels */
--text-faint:      #a8a8a8;  /* placeholders only (paired with label) */
--status-ok:       #0f7a3d;  /* ✓ approved, ✓ verification passed */
--status-ok-bg:    #e5f4eb;
--status-warn:     #b3631a;  /* ⚠ partial, stalled, almost-ready */
--status-warn-bg:  #fbf0e2;
--status-bad:      #b3261e;  /* ✗ rejected, verification failed */
--status-bad-bg:   #f9e6e4;
--status-busy:     #2a6db3;  /* ⏳ in_progress */
--status-busy-bg:  #e7f0fa;
--code-bg:         #f4f4f4;  /* inline code, <pre>, trace bodies */

/* SPACING */
--space-0:  0;
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;   /* base unit */
--space-6:  24px;
--space-8:  32px;
--space-12: 48px;   /* section separation */
```

All color pairs verified against WCAG 2.1 AA (4.5:1 body text):
text-primary on bg ~17:1 (AAA) · text-muted on bg ~5.7:1 (AA) · text-faint on bg ~2.8:1 (placeholders only, paired with label) · status-ok on status-ok-bg ~4.9:1 · status-warn on status-warn-bg ~4.6:1 · status-bad on status-bad-bg ~5.0:1 · status-busy on status-busy-bg ~4.8:1.

### Typography

```
body         14px / 20px  -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
mono         13px / 18px  "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace
heading-1    18px / 24px  semibold, body family
heading-2    15px / 22px  semibold, body family
label        11px / 14px  mono, uppercase, letter-spacing 0.04em, --text-muted
badge        11px / 14px  mono, uppercase, letter-spacing 0.04em
```

JetBrains Mono not bundled — falls through to `ui-monospace` / `SFMono-Regular` / `Menlo` so the report stays self-contained (no web font, no CDN).

### Component specs

```
card                  border 1px --border, no radius, padding --space-4
card-header           padding --space-3 --space-4, bg --bg-elev-2, font-weight 500
table                 border-collapse, --border 1px hairlines, no zebra by default
                      (zebra --bg-elev-1 only on > 5 rows)
table-cell            padding --space-2 --space-3
                      numbers right-aligned, text left-aligned, labels --text-muted
badge                 padding 2px 6px, border 1px <status>, bg <status-bg>,
                      color <status>, border-radius 2px, font: label spec
                      INCONCLUSIVE badge: bg --bg-elev-2, color --text-faint, no border
button (copy)         padding --space-1 --space-3, border 1px --border, bg --bg,
                      hover bg --bg-elev-1, font: body
                      focus: outline 2px --status-busy, outline-offset 1px
button success state  text "[copied]" for 2s, bg --status-ok-bg, color --status-ok
                      then decays back to default
                      AND records slug in localStorage; subsequent loads show
                      a small "[✓ copied]" suffix on the button label
funnel-bar            height 14px, bg --bg-elev-2, segment fill --text-primary
                      label inline (count + %), no border-radius
                      role="img" aria-label="Funnel: discovered N, qualified N, ..."
                      visually-hidden <table> with same data for screen readers
details / summary     summary: padding --space-2 --space-3, bg --bg-elev-2,
                      font: label, cursor pointer, marker visible (default ▶)
                      no transition (snap open/closed)
trace nesting         outer <details> per round; inner <details> per persona
                      (Round 1 ▸ contains target-customer ▸, spam-filter ▸, ...)
round diff            difflib.ndiff unified style, NOT side-by-side
                      lines prefixed " " / "+" / "-", color-coded backgrounds
                      override default difflib.HtmlDiff CSS entirely (mono 13px,
                      change=--status-warn-bg, add=--status-ok-bg, del=--status-bad-bg)
status badges (4)     [APPROVED]     ok palette
                      [REJECTED]     bad palette
                      [IN PROGRESS]  busy palette, suffix " · round N/3"
                      [STALLED]      warn palette
                      [INCONCLUSIVE] muted (per U1)
                      [PARTIAL]      warn palette (for index.html runs missing exports)
deep-link affordance  every card has id="prospect-<slug>"; slug rendered with a
                      tiny "#" next to it; clicking copies file://...#prospect-<slug>
                      to clipboard; ~10 LOC JS auto-expands the matching <details>
                      on page load if location.hash is present
```

### Layout

```
max-width             1280px on body
report grid           single column, sections separated by --space-12
card spacing          --space-2 between collapsed cards, --space-4 around expanded
no media queries v1   acceptable < 800px width with horizontal scroll on wide tables
```

### Responsive (v1 scope)

```
breakpoint           none — horizontal scroll on tables below 800px
                     (acceptable for a developer laptop tool)
prospect cards       collapse-on-click works at any width
index.html columns   when < 640px, hide [stat] [qual] [appr] columns;
                     show only [when][skill][campaign] with status icon
                     baked into the row left edge
report.html cards    no responsive layout change; single-column native
```

### Accessibility (target: WCAG 2.1 AA)

```
headings             one <h1> per page, sections use <h2>, no skipped levels
landmarks            <header>, <main>, <footer>; each section
                     <section aria-labelledby="...">
focus                visible 2px outline on all interactive elements
                     (--status-busy, offset 1px)
copy buttons         aria-label="Copy message to <firstName> at <company>"
                     so screen readers don't hear "copy, copy, copy"
funnel chart         role="img" + aria-label + visually-hidden <table>
status badges        text inside badge ALWAYS readable (uppercase, no icon-only)
details/summary      browser-native, no JS override (keyboard-accessible by default)
trace .txt content   wrapped in <pre><code>; prevents screen-reader narration
contrast             every text/bg pair ≥ 4.5:1 (AA) per palette above
                     --text-faint only on placeholders (never alone)
print                @media print expands all <details>, removes copy buttons,
                     break-inside: avoid on cards
no motion            zero transitions/animations in v1; prefers-reduced-motion
                     compliant by construction
```

### AI-slop "do not use" list (mandatory; goes in `shared-references/report-model.md`)

The report tool is classified **APP UI** (data-dense, internal). The following patterns are forbidden:

- No gradients of any kind (background, badge, button)
- No `text-align: center` (except numeric table cells, which right-align)
- No `border-radius` > 4px (status badges 2px, buttons sharp)
- No decorative SVG (blobs, waves, dividers, illustrations)
- No emoji in headings or body text (status prefix glyphs ✓ ⏳ ⚠ ✗ only)
- No colored left-border on cards (use top-aligned status badge instead)
- No shadows beyond `box-shadow: 0 1px 0 rgb(0 0 0 / 0.08)` (single-row table separator)
- No icon-in-colored-circle decoration
- No purple / violet / indigo accents
- No bundled web fonts (system stack + JetBrains Mono fallback only)
- No 3-column feature grids
- No hero copy ("Welcome to...", "Unlock the power of...")

### Design decisions captured (CEO + design review)

| ID | Decision | Choice |
|----|----------|--------|
| P1-1 | Per-card + index IA blocks | Accept both ASCII layouts verbatim |
| P2-1 | Five state treatments (empty/partial/stalled/error/index-empty) | Accept all five |
| P3-1 | Journey storyboards + 3 fixes (return-loop, triage callout, rejection grouping) | Accept all three |
| P4-1 | Typography | System UI body + JetBrains Mono mono (no bundled fonts) |
| P4-2 | "Do not use" list + status badge spec | Accept both verbatim |
| P5-1 | Full design system spec (color/spacing/typography/components) | Accept (light theme v1) |
| P6-1 | Responsive + a11y spec | Accept full (WCAG 2.1 AA, ARIA on funnel + copy buttons, print-friendly) |
| U1 | Inconclusive verdict | Muted [INCONCLUSIVE] badge on `--text-faint` + `--bg-elev-2`, score cell `—` |
| U2 | Multi-round trace nesting | Outer `<details>` per round, inner per persona |
| U3 | Round diff layout | Unified inline (`difflib.ndiff` style), narrow |
| U4 | Copy success state | `[copied]` for 2s, localStorage persist, `[✓ copied]` on reload |
| U5 | Per-card live state | Status badge only (`[IN PROGRESS · round 2/3]`); no spinner |
| U6 | Deep-linking | Fragment IDs + click-slug-to-copy-URL + auto-expand on hash |
| U7 | Index default sort | In-progress pinned top; within tier, `started_at` desc |

---

## NOT in scope (deferred to TODOS.md or future work)

- LinkedIn-style message preview (visual fidelity to LinkedIn input box)
- Cross-run trends page (last N runs side-by-side per skill — qualify rate, approve rate trends)
- Inline pipeline diagram with phase timings
- Re-run/replay buttons that execute commands directly (only the copyable CLI string ships in v1)
- Slack/email "run complete" notifications
- Notion/Google Drive export
- Mobile-responsive layout
- Headless Chromium render tests (S6-1)
- Dark mode (Apple/system dark may render the white background harshly — note for visual polish phase)
- Pagination beyond ~100 inline cards (rare; cap and recommend `max_prospects ≤ 100`)
- Timestamp-collision handling for parallel runs in the same second (rare)
- Live-watch via WebSocket / Server-Sent Events (we explicitly chose `<meta refresh>`)

---

## What already exists (Section 0B summary)

- All outputs structured (JSON/JSONL/CSV/MD) with stable schemas per `shared-references/verification-protocols.md` and `output-manifest.md`. The Report Model maps cleanly.
- `RUN.json` is the existing paths-manifest; we only need to add the `skill` field.
- `outbound_state.py` exposes per-prospect state as JSONL the adapter can stream.
- 9 sibling skills follow the same loop contract → adapters are mostly mechanical.

---

## Dream-state delta (Section 0C summary)

```
CURRENT STATE                    THIS PLAN                       12-MONTH IDEAL
30-50 fragmented files,   ─▶   1 self-contained report.html  ─▶  Same tool feeds
user opens 5+ to answer        per run + cross-run index;        cross-run trends,
"what happened?"               per-prospect drill-down            Slack notifs,
                               inline; works for all 10           Notion exports,
                               sibling skills.                    re-run buttons.
```

This plan lands ~70% of the 12-month ideal in one PR; the remaining 30% is opt-in additions on top of the stable Report Model contract.

---

## Verification (end-to-end test plan after implementation)

1. **Unit + integration tests** (Section 6 list) — all pass.
2. **Outbound smoke:** copy real outbound run dir to a sandbox, run `python tools/generate_run_report.py <run_dir>`. Verify:
   - `report.html` exists in run_dir
   - `review-stage/index.html` exists and lists the run
   - Both open in Chrome with 0 console errors
   - All approved messages have working copy buttons
   - Every persona-trace `<details>` expands cleanly
3. **Migration smoke:** run `tools/migrate_run_json_add_skill.py` against a copy of the existing `review-stage/outbound/` (and the historical run in `tacite-source-of-truth/`). Confirm every RUN.json gains `skill` field; re-run is a no-op.
4. **Partial-run smoke:** rename `06_exports/` to hide it; re-run generator. Verify "partial run" banner and no crash.
5. **XSS smoke:** edit a fixture profile to include `<script>alert(1)</script>`; render; confirm escaped output and no JS execution.
6. **Cross-run isolation:** corrupt one RUN.json in a sandbox; run generator on another run; verify index shows ERROR badge for the corrupt one and renders the other normally.
7. **Live-watch smoke:** start an outbound run with E4 enabled; open `report.html` in browser; verify `<meta refresh>` is present while status=in_progress and removed when status=completed.
8. **Sibling adapters:** run `generate_run_report.py` against one fixture per other skill; verify all 10 produce valid HTML without modifying adapter logic per-run.
9. **Visual smoke:** open a fully-rendered outbound report in Chrome; eyeball-check against the Design Specifications section (typography, color tokens, badge shapes, funnel geometry, card IA order, state banners, no AI-slop patterns).
10. **A11y smoke:** keyboard-only tab through the report; verify focus ring visible on every interactive element; verify `<details>` opens/closes with Enter; VoiceOver/NVDA spot-check on the copy button (should hear "Copy message to Chris at <company>", not "copy").
11. **Deep-link smoke:** click the `#` next to a prospect slug; paste the resulting `file://...#prospect-<slug>` URL in a fresh tab; verify the page auto-scrolls to that card AND auto-expands the matching `<details>`.
12. **Return-loop smoke:** click `[copy]` on three approved messages; reload the report; verify all three buttons show `[✓ copied]` from `localStorage`.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR | mode=SELECTIVE_EXPANSION, 6 proposals proposed, 6 accepted, 0 deferred-to-TODOs, 0 critical gaps |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 15 issues found (5 arch + 5 quality + 3 test + 0 perf + 2 other), 0 critical gaps, scope reconfirmed |
| Codex Review | `/codex review` | Outside voice on plan | 1 (via eng review) | issues_found | 23 raised, 6 with real merit, 4 amendments applied (X1-X4), 2 added inline (X5-X6) |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR | score 6/10 → 9/10; 14 decisions added (P1-P6 + U1-U7); 0 unresolved |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not run (not user-facing API or SDK; skip is correct) |

- **CODEX:** 23 raised, 6 substantive: double-escape bug (X1), user-global cache hazard (X2), partial-line race in snapshot read (X3), missing generator-failure semantics (X4), golden HTML snapshot test (X5), per-surface size caps (X6). All 6 amendments applied to plan. The other 17 either re-litigated already-settled CEO/Design/Eng decisions or were judgment-call disagreements (kept original direction).
- **CROSS-MODEL:** Claude eng-review caught architecture/test-framework/code-quality gaps (15 findings); Codex caught implementation-correctness gaps (4 real bugs) that the three-skill chain missed. Two reviewers in agreement on: security mitigation chain, snapshot-read pattern, schema versioning need.
- **UNRESOLVED:** 0 decisions outstanding across CEO + Design + Eng + Codex.
- **VERDICT:** CEO + ENG + DESIGN + CODEX all CLEARED. Plan is ready to implement.
