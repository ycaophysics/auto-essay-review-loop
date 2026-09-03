# Persona Library

This index lists every persona shipped with v0.1. Each persona is a markdown
file in `personas/{format}/{name}.md` with a fixed schema (see
[persona-schema](#persona-schema) below).

## Index

### Blog (`personas/blog/`)
- [mobile-first-reader](../../personas/blog/mobile-first-reader.md) — reads on a phone, 300×600 viewport, will scroll
- [seo-skeptic](../../personas/blog/seo-skeptic.md) — checks H-tag structure, keyword density, meta-description
- [h2-skimmer](../../personas/blog/h2-skimmer.md) — only reads H2s; if H2s don't tell the story, fails
- [target-icp](../../personas/blog/target-icp.md) — target reader for the post (configurable per run)

### Social (`personas/social/`)
- [scroller-08s](../../personas/social/scroller-08s.md) — 0.8s of attention; would they stop scrolling?
- [reply-guy](../../personas/social/reply-guy.md) — looking for ratios, contradictions, easy dunks
- [algorithm-ranker](../../personas/social/algorithm-ranker.md) — predicts engagement signals (replies > likes > shares)
- [domain-expert](../../personas/social/domain-expert.md) — knows the topic; checks for cringe, errors, oversimplification

### LinkedIn (`personas/linkedin/`)

LinkedIn uses **intent-selected panels** (like slides' scenario-selected panels). The LinkedIn skill picks one panel via `--intent`:

| Intent | Panel | Gatekeeper |
|--------|-------|------------|
| `career` (default) | executive-recruiter, cynical-scroller, growth-hacker, target-icp | executive-recruiter (`would_engage`) |
| `thought-leadership` | op-ed-editor, general-reader, domain-critic, persuadable-skeptic | op-ed-editor (`would_run`) |

Career panel:
- [executive-recruiter](../../personas/linkedin/executive-recruiter.md) — hiring manager; would they DM? (gatekeeper, `would_engage`)
- [cynical-scroller](../../personas/linkedin/cynical-scroller.md) — sees through "broetry" and humble-brags
- [growth-hacker](../../personas/linkedin/growth-hacker.md) — measures hook strength + engagement bait quality
- [target-icp](../../personas/linkedin/target-icp.md) — your actual audience (configurable)

Thought-leadership panel (op-ed / civic / analysis):
- [op-ed-editor](../../personas/linkedin/op-ed-editor.md) — opinion editor; would they run it? (gatekeeper, `would_run`)
- [general-reader](../../personas/linkedin/general-reader.md) — the intelligent non-specialist the argument is for (configurable)
- [domain-critic](../../personas/linkedin/domain-critic.md) — sympathetic field expert; demands accuracy, not both-sides balance
- [persuadable-skeptic](../../personas/linkedin/persuadable-skeptic.md) — the reader who does not already agree; did it move them?

### Business plan (`personas/business-plan/`)
- [vc-partner](../../personas/business-plan/vc-partner.md) — Sequoia/a16z partner voice; pattern-match to fundable
- [unit-economics-skeptic](../../personas/business-plan/unit-economics-skeptic.md) — CAC, LTV, payback, gross margin
- [technical-cofounder](../../personas/business-plan/technical-cofounder.md) — devil's advocate on technical claims
- [target-customer](../../personas/business-plan/target-customer.md) — would they actually buy this?
- [competitor](../../personas/business-plan/competitor.md) — incumbent CEO; how do they kill this?

### Slides (`personas/slides/`)

Loaded as a four-persona panel chosen by `--scenario`:

| Scenario | Panel |
|----------|-------|
| `pitch` | vc-partner-skim, exec-30s-skim, density-skeptic, presenter-coach |
| `academic` | program-committee-skim, back-of-room-reader, density-skeptic, presenter-coach |
| `internal` | exec-30s-skim, back-of-room-reader, density-skeptic, presenter-coach |

- [vc-partner-skim](../../personas/slides/vc-partner-skim.md) — early-stage VC partner; 90-second skim; veto: would they forward internally?
- [program-committee-skim](../../personas/slides/program-committee-skim.md) — senior researcher / PC member; veto: contribution + evidence + limitations all hold?
- [exec-30s-skim](../../personas/slides/exec-30s-skim.md) — title-sequence-only audit; would the titles alone deliver the thesis?
- [back-of-room-reader](../../personas/slides/back-of-room-reader.md) — audience member in row 14 of a conference hall; can the room read each slide?
- [density-skeptic](../../personas/slides/density-skeptic.md) — Death-by-PowerPoint detector; words/bullets/titles density auditor
- [presenter-coach](../../personas/slides/presenter-coach.md) — speaker's dry-run partner; hook, arc, notes, close

## Persona schema

Every persona file uses this YAML frontmatter + body structure:

```markdown
---
name: vc-partner
format: business-plan
schema_version: 1
weight: 1.0
veto: ["fantasy_tam", "no_unit_economics"]
requires_verification: ["market_size_check"]
---

# {Persona Name}

## Background
One paragraph: who is this persona, what's their context, what do they care about.

## What they look for
Bullet list of concrete signals.

## What makes them reject
Bullet list of dealbreakers.

## System prompt
The full system prompt to send to the reviewer model.

## User prompt template
The user prompt template (uses `{{DRAFT}}`, `{{FORMAT}}`, `{{ROUND}}`, etc. as placeholders).

## Output format
The exact JSON schema this persona must return:
\`\`\`json
{
  "score": 7,
  "verdict": "almost",
  "weaknesses": [
    {"severity": "CRITICAL", "issue": "...", "fix": "..."}
  ],
  "summary": "..."
}
\`\`\`
```

## Schema fields

- `name` — kebab-case, must match filename
- `format` — `blog` / `social` / `linkedin` / `business-plan` / `application` / `cv` / `slides`
- `schema_version` — currently `1`
- `weight` — used in weighted-consensus calculations (default 1.0)
- `veto` — array of verification flags this persona auto-fails on (e.g., `vc-partner` vetoes if market_size_check returns "fantasy")
- `requires_verification` — verification checks that must run before this persona reviews

## Authoring new personas

See [docs/PERSONA_AUTHORING.md](../../docs/PERSONA_AUTHORING.md) for guidance.

Rule of thumb: a good persona is **specific** ("Series A SaaS investor in
B2B horizontal tools, prefers PLG, allergic to enterprise sales pitches")
not generic ("a VC"). Specificity is the moat.
