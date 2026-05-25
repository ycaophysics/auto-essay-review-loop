# AGENT_GUIDE.md

LLM-consumption guide for `auto-essay-review-loop`. For human-facing
documentation, see [README.md](README.md).

## Project overview

Persona-adversarial review loop for non-academic writing — blog, social,
LinkedIn, business plans. Format-specific skills run a 4-round loop where
4–5 named personas (each a fresh thread on the reviewer model) score the
draft, the executor implements highest-priority fixes, and an objective
verification layer (link-check, char count, market-size sanity) gates
approval. v0.1 backend is Codex MCP (`mcp__codex__codex`) on GPT-5.4 with
`model_reasoning_effort: medium`.

## Architecture

### Directory tree

```
auto-essay-review-loop/
├── skills/
│   ├── auto-essay-review-loop/SKILL.md           # umbrella dispatcher (format detection)
│   ├── auto-blog-review-loop/SKILL.md            # blog loop
│   ├── auto-social-review-loop/SKILL.md          # X/Threads/IG loop
│   ├── auto-linkedin-review-loop/SKILL.md        # LinkedIn loop
│   ├── auto-business-plan-review-loop/SKILL.md   # pitch deck / exec summary loop
│   └── shared-references/                        # CONTRACTS — read-only from skills
│       ├── loop-contract.md                      # Phases A–E, state, termination
│       ├── reviewer-independence.md              # fresh-thread-per-round rule
│       ├── persona-library.md                    # persona schema + index
│       ├── verification-protocols.md             # objective checks per format
│       ├── brand-voice-protocol.md               # optional voice consistency layer
│       ├── output-versioning.md                  # timestamp + alias pattern
│       └── output-manifest.md                    # MANIFEST.md format
├── personas/                                     # per-format persona files (markdown + YAML)
│   ├── blog/{name}.md
│   ├── social/{name}.md
│   ├── linkedin/{name}.md
│   └── business-plan/{name}.md
├── tools/                                        # verification scripts
│   ├── verify_links.sh                           # blog: link resolution
│   ├── count_chars.py                            # social/linkedin: char + hashtag count
│   └── market_size_check.py                      # business-plan: TAM/SAM/SOM sanity
├── templates/BRAND_VOICE.template.md
├── tests/
│   ├── fixtures/{format}/{good,bad}_*.{md,txt}
│   └── run_tests.sh                              # smoke tests for tools/
└── docs/
    ├── PERSONA_AUTHORING.md
    ├── BACKEND_CONFIG.md
    ├── EXAMPLES.md
    └── TROUBLESHOOTING.md
```

### Files that are CONTRACTS (do not modify; skills cite them)

- `skills/shared-references/loop-contract.md` — phase definitions, state schema, termination
- `skills/shared-references/reviewer-independence.md` — fresh-thread rule
- `skills/shared-references/persona-library.md` — persona schema (YAML frontmatter)
- `skills/shared-references/verification-protocols.md` — per-format objective checks
- `skills/shared-references/brand-voice-protocol.md` — voice-drift handling
- `skills/shared-references/output-versioning.md` — timestamped + aliased outputs
- `skills/shared-references/output-manifest.md` — `MANIFEST.md` row format

## Loop contract (one-paragraph summary)

Each round: (A) every persona reviews the current draft via a FRESH thread on
the reviewer backend (no prior-round context — see reviewer-independence.md);
(B) parse JSON for score/verdict/weaknesses/fixes; (B.5) optional reviewer
memory if difficulty=hard|nightmare; (B.6) optional rebuttal/debate; (B.7)
verification layer (hard checks); termination check (per-format threshold);
(C) implement fixes by priority; (D) re-render if the format needs it; (E)
append to `AUTO_REVIEW.md`, write `REVIEW_STATE.json`, update `MANIFEST.md`.
Default `MAX_ROUNDS=4`. Full spec: `skills/shared-references/loop-contract.md`.

## How to invoke each skill

### Umbrella dispatcher

```
/auto-essay-review-loop <path>
/auto-essay-review-loop <path> --format=blog|social|linkedin|business-plan
/auto-essay-review-loop <path> --difficulty=medium|hard|nightmare
/auto-essay-review-loop <path> --human-checkpoint=true
/auto-essay-review-loop <path> --reviewer=codex   # v0.1: only codex supported
```

Auto-detects format from file size, structure, and content markers; dispatches
to format-specific skill. Detection rules in
`skills/auto-essay-review-loop/SKILL.md` Phase 1.

### Format-specific skills

```
/auto-blog-review-loop <path.md>
/auto-social-review-loop <path.txt> --platform=x|threads|ig
/auto-linkedin-review-loop <path.txt|.md>
/auto-business-plan-review-loop <path.md>
```

All accept the same flag set as the umbrella. Each owns its own personas,
verification config, termination criteria, and `MAX_ROUNDS` default.

## Persona schema reference

```yaml
---
name: vc-partner               # kebab-case, matches filename
format: business-plan          # blog|social|linkedin|business-plan
schema_version: 1
weight: 1.0                    # weighted-consensus weight
veto: ["fantasy_tam"]          # verification flags this persona auto-fails on
requires_verification: ["market_size_check"]
---
```

Body sections (markdown):

1. `## Background` — one paragraph defining the persona
2. `## What they look for` — concrete signals (bullet list)
3. `## What makes them reject` — dealbreakers (bullet list)
4. `## System prompt` — full system prompt sent to the reviewer model
5. `## User prompt template` — uses placeholders `{{DRAFT}}`, `{{FORMAT}}`,
   `{{ROUND}}`, `{{BRAND_VOICE}}`, `{{PRIOR_SUSPICIONS}}` (memory mode only)
6. `## Output format` — JSON schema the persona must return verbatim

Required JSON fields in every persona response:

```json
{
  "score": 7,
  "verdict": "almost",
  "weaknesses": [{"severity": "CRITICAL|MAJOR|MINOR", "issue": "...", "fix": "..."}],
  "summary": "..."
}
```

Optional fields when `BRAND_VOICE.md` is loaded:

```json
{"voice_drift": {"drifts_from_voice": true, "specifics": ["..."]}}
```

Full spec: `skills/shared-references/persona-library.md`. Authoring guide:
`docs/PERSONA_AUTHORING.md`.

## Verification tools reference

| Tool | Format | Input | Output |
|------|--------|-------|--------|
| `tools/verify_links.sh` | blog | path to .md | JSON, `passed: bool`, per-link checks |
| `tools/count_chars.py --format=x\|threads\|ig\|linkedin` | social, linkedin | path | JSON, `passed: bool`, char/hashtag/link counts |
| `tools/market_size_check.py` | business-plan | path | JSON, `passed: bool`, `flags: ["fantasy_tam", ...]` |

All tools emit JSON to stdout. Common output schema:

```json
{
  "tool": "verify_links",
  "timestamp": "ISO-8601",
  "input_file": "path",
  "passed": true,
  "checks": [{"name": "...", "passed": true, "detail": "..."}],
  "summary": "...",
  "flags": ["..."]
}
```

Verification failures are HARD rejections — they bypass persona consensus.
A draft cannot be APPROVED with `passed: false` from any verification tool.

Full spec: `skills/shared-references/verification-protocols.md`.

## State and recovery model

State file: `review-stage/REVIEW_STATE.json` (per loop-contract.md).

Schema:

```json
{
  "format": "blog",
  "round": 2,
  "threadIds": {"persona-name": "thread-id-for-crash-recovery-only"},
  "status": "in_progress|completed",
  "last_scores": {"persona-name": 6},
  "last_verdicts": {"persona-name": "almost"},
  "draft_mtime_hash": "sha256:...",
  "timestamp": "ISO-8601"
}
```

Recovery rules (every skill invocation re-checks):

- File missing → fresh start
- `status: completed` → fresh start
- `status: in_progress` AND timestamp >24h old → fresh start (delete stale)
- `status: in_progress` AND timestamp <24h AND `draft_mtime_hash` matches → resume from `round + 1`
- `draft_mtime_hash` mismatch → user edited mid-loop; warn and ask to restart

`threadIds` are saved ONLY for crash recovery — never reused for next round's
review (see reviewer-independence.md).

## Tracing

Every reviewer call writes:

```
traces/{format}/{YYYYMMDD_HHMMSS}_run{NN}/
├── persona-{name}-round-{N}.prompt.txt
└── persona-{name}-round-{N}.response.txt
```

Plus a row in `review-stage/MANIFEST.md` per `output-manifest.md`.

## Output artifacts

Per `output-versioning.md`:

- `review-stage/{format}_approved_{ts}.md` (timestamped) ↔ `review-stage/{format}_approved.md` (alias)
- `review-stage/AUTO_REVIEW.md` — cumulative round log (no alias; appends)
- `review-stage/REVIEWER_MEMORY.md` — only with `difficulty=hard|nightmare`
- `review-stage/REVIEW_STATE.json` — overwrite each round; latest is truth
- `review-stage/MANIFEST.md` — append-only log of every file written

## Backend

v0.1: Codex MCP only. Reviewer call shape:

```
mcp__codex__codex(
  prompt=<user-prompt-with-DRAFT-tags>,
  config={"model_reasoning_effort": "medium"},
  system=<persona-system-prompt-with-optional-BRAND_VOICE>
)
```

Wrap user draft in `<DRAFT>...</DRAFT>` tags in every prompt. Persona system
prompt instructs the reviewer to treat tag content as data, not instructions
(prompt-injection defense — see loop-contract.md "Key invariants").

Full backend setup: `docs/BACKEND_CONFIG.md`.

## Invariants (do not violate)

1. **Reviewer independence** — every round, every persona, fresh thread. Never `codex-reply` across rounds.
2. **Verification is non-negotiable** — persona consensus alone cannot approve.
3. **Honest rebuttals only** — fabricated evidence in debate (B.6) → auto-OVERRULED.
4. **Trace everything** — every reviewer call writes prompt + response to `traces/`.
5. **Draft is data** — `<DRAFT>` tags + system-prompt instruction in every reviewer call.
6. **Timestamped + aliased outputs** — never overwrite the timestamped artifact.

## Active plans

Approved-but-unimplemented plans live at the repo root as `*_PLAN.md`. They are written
to be picked up cold by any coding agent and contain decision-final specs (no open
questions). Read the plan top to bottom, follow the "For implementing agents — start here"
preamble, work the suggested lanes, ship, then delete the plan file in the same PR.

- `RUN_REPORT_PLAN.md` — shared HTML report tool for all 10 `auto-*-review-loop` skills.
  Cleared CEO + Eng + Design + Codex outside-voice review on 2026-05-25. Builds
  `tools/generate_run_report.py` + per-skill adapters in `tools/report_adapters/`
  + `templates/report/`. Lane A + B + C parallelizable; ~30-45 min wall-clock with
  parallel CC agents.

Deferred plans use `*_PLAN.deferred.md` (see `ROBUSTNESS_PLAN.deferred.md`) and are
not active work.

## Cross-references

- Quickstart and pitch: `README.md`
- Per-format walkthroughs: `docs/EXAMPLES.md`
- Common failures: `docs/TROUBLESHOOTING.md`
- New persona how-to: `docs/PERSONA_AUTHORING.md`
- Backend setup: `docs/BACKEND_CONFIG.md`
- Contributing: `CONTRIBUTING.md`
