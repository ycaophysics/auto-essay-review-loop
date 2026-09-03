# Report Model — adapter contract

Shared HTML report tool for all `auto-*-review-loop` skills. Adapters live in
`tools/report_adapters/{skill}.py` and implement `build(run_dir: Path) -> ReportRun`.

## Dependencies

```bash
pip install jinja2
```

Jinja2 is the only new runtime dependency. Templates live under `templates/report/`.

## CLI

```bash
bash tools/run.sh generate_run_report.py <run_dir>
bash tools/run.sh generate_run_report.py --index
bash tools/run.sh generate_run_report.py <run_dir> --update-golden
```

- Writes `<run_dir>/report.html` (atomic replace via same-dir temp + `os.replace`)
- Regenerates `review-stage/index.html` and `review-stage/.report-index.cache.json`
- Generator failure must not block pipelines — skills wrap with `|| echo WARN...`

## ReportRun model (`tools/report_adapters/model.py`)

| Field | Type | Notes |
|-------|------|-------|
| `run_id` | str | From RUN.json |
| `skill` | str | Registry key, e.g. `linkedin-outbound` |
| `campaign` | str | Display name |
| `status` | str | `in_progress`, `completed`, `stalled`, `partial` |
| `started_at` | str | ISO 8601 |
| `completed_at` | str \| None | |
| `funnel` | list[tuple[str, int]] | e.g. `[("enriched", 25), ("qualified", 18), ("approved", 3)]` |
| `items` | list[ReportItem] | Approved + in-progress |
| `rejected_items` | list[ReportItem] | Rejected prospects |
| `warnings` | list[str] | Missing files, parse skips |
| `rejection_patterns` | list[tuple[str, int]] | Top blockers for triage callout |
| `manifest_path` | str \| None | MANIFEST.md if present |
| `schema_version` | int | Default 1 |

`ReportItem` carries `slug`, `title`, `subtitle`, `status`, `final_message`,
`rounds[]`, `metadata`, `next_step_cta`.

## Adapter contract

1. Register with `@register("skill-key")` at module scope; auto-imported from `__init__.py`.
2. Use `load_json_strict` for required files, `load_json_safe` for optional (append errors to `warnings`).
3. Use `snapshot_read_jsonl` for in-flight JSONL (tolerates trailing partial line).
4. Use `truncate_trace` (5 KB cap) for inline traces; set `raw_path` for full file link.
5. **Never** call `html.escape()` — Jinja2 autoescape + `mask_secrets` in the escape pipeline is the single chokepoint.
6. Outbound: read `enriched_profiles.normalized.json` only, never `.raw.json`.
7. Path scope: `resolve_under(run_dir, path)` before reading `traces/`.

If `RUN.json` lacks `skill`, the generator infers from path (`review-stage/outbound/` → `linkedin-outbound`, etc.) and `migrate_run_json_add_skill.py` backfills existing runs.

## Secret masking

Patterns redacted to `[REDACTED]` after HTML escape:

- `Bearer\s+[A-Za-z0-9._-]{20,}`
- `sk-[A-Za-z0-9_-]{20,}`
- `apify_api_[A-Za-z0-9_-]{20,}`

## Size caps

| Surface | Cap |
|---------|-----|
| Inline trace | 5 KB |
| Traces per prospect | 12 |
| Inline prospect cards | 100 |

Over cap: show `[N more truncated — see <path>]` with link to raw folder.

## Aesthetic & visual specs (v1)

Light theme only. No dark mode. No animations. No external URLs or CDN assets — reports must render from `file://`.

### Color tokens

```css
--bg: #ffffff;
--bg-elev-1: #fafafa;
--bg-elev-2: #f4f4f4;
--border: #e4e4e4;
--text-primary: #1a1a1a;
--text-muted: #6e6e6e;
--status-ok: #0f7a3d;
--status-warn: #b3631a;
--status-bad: #b3261e;
--status-busy: #2a6db3;
```

Status badges: APPROVED (ok), REJECTED (bad), IN PROGRESS (busy), STALLED/PARTIAL (warn), INCONCLUSIVE (muted).

### Typography

- Body: 14px system UI stack
- Mono: 13px `ui-monospace` / `Menlo` fallback (no bundled web fonts)

### AI-slop do not use

- No gradients, no purple accents, no decorative SVG
- No `border-radius` > 4px (badges 2px)
- No emoji in headings (status glyphs ✓ ⏳ ⚠ ✗ only in banners)
- No colored left-border cards
- No hero marketing copy

### Per-prospect card order

1. CTA (copy / LinkedIn / retry CLI)
2. Final message
3. Profile one-liner
4. Fit / qualification
5. Persona scorecard table
6. Verification checks
7. Round diff (`<details>`, collapsed)
8. Persona traces (nested `<details>`)

Run-level sections (outbound): **Ready to send** (approved, cards open by default) → **In review** (in-progress) → **Rejected** (grouped by blocker). Header includes a one-line operator summary (“N ready to send · start with …”).

### Index sort

In-progress runs pinned top; within each tier, `started_at` descending.

## Tests

Extend `tests/run_tests.sh` — no pytest. Golden snapshot:
`tests/fixtures/runs/outbound_happy/expected_report.html` (byte-for-byte vs `report.html`).

Re-baseline: `bash tools/run.sh generate_run_report.py tests/fixtures/runs/outbound_happy --update-golden`
