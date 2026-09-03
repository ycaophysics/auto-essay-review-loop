---
name: auto-essay-review-loop
description: Umbrella dispatcher for persona-adversarial review loops on non-academic writing. Auto-detects format (blog, social, LinkedIn, business plan, application, CV, slides) from the input file and dispatches to the format-specific skill. Use when user says "review my draft", "auto review my post", "run the loop on this", or invokes /auto-essay-review-loop with a file path. v0.1 backend = Codex MCP (gpt-5.4, model_reasoning_effort=medium).
allowed-tools: Skill, Read, Bash, Glob, Grep
---

# auto-essay-review-loop — umbrella dispatcher

This is the front door. The user hands you a draft. You decide which format
it is, then dispatch to the format-specific loop skill. You do not run the
loop yourself.

The seven format-specific skills are:

- `auto-blog-review-loop` — markdown long-form (500–4000 words, H2/H3 structure)
- `auto-social-review-loop` — X / Threads / IG-caption short posts (≤2200 chars)
- `auto-linkedin-review-loop` — LinkedIn posts (≤3000 chars, hook + hashtags)
- `auto-business-plan-review-loop` — pitch decks (text), executive summaries, full plans
- `auto-application-review-loop` — job, YC/accelerator, grant, fellowship, grad-school, MBA, undergrad applications (Q&A markdown). Requires `--target=<type>`.
- `auto-cv-review-loop` — CVs and resumes (markdown)
- `auto-slides-review-loop` — slide decks: pitch decks, academic talks, internal presentations (markdown slides via Marp/Slidev convention OR `.pptx` files). Requires `--scenario=pitch|academic|internal`.

All four follow the same loop contract — see
`skills/shared-references/loop-contract.md`. v0.1 backend is Codex MCP
(`mcp__codex__codex` / `mcp__codex__codex-reply`) on `gpt-5.4` with
`model_reasoning_effort: medium`. v0.2+ adds DeepSeek, MiniMax, OpenAI direct,
local Ollama — see `docs/BACKEND_CONFIG.md`.

## Invocation

```
/auto-essay-review-loop <path/to/draft>
/auto-essay-review-loop <path/to/draft> --format=blog
/auto-essay-review-loop <path/to/draft> --format=social --platform=x
/auto-essay-review-loop <path/to/draft> --format=application --target=yc
/auto-essay-review-loop <path/to/draft> --format=cv
/auto-essay-review-loop <path/to/deck.md> --format=slides --scenario=pitch --stage=seed
/auto-essay-review-loop <path/to/deck.pptx> --format=slides --scenario=academic --talk-length=15
/auto-essay-review-loop <path/to/draft> --difficulty=hard
/auto-essay-review-loop <path/to/draft> --reviewer=codex      # v0.1 default and only option
```

Flags pass through to the dispatched skill verbatim. The umbrella does not
interpret `--difficulty`, `--reviewer`, `--max-rounds`, or any other loop knob —
the format skill owns those.

## Phase 0 — collect input

1. Read the path the user provided. If no path, ask once: "Which file?"
2. Read the first 8KB of the file — that is enough to detect format.
3. Capture the file extension (`.md`, `.txt`, `.tex`, `.pdf`).
4. Capture the byte size and approximate word count (`wc -w` via Bash).

Refuse politely if:

- Path doesn't exist.
- File is binary AND extension is not `.pptx` — we handle markdown / plain text and (for slides only) PowerPoint in v0.1. Tell the user: "v0.1 handles `.md`, `.txt`, and `.pptx`. For `.pdf` / `.docx`, convert first."
- File is empty.

For `.pptx` input: skip the first-8KB peek; the file is a zip. Detection short-circuits to `slides` (see Rule 2.3 below).

## Phase 1 — format detection

Run the rules in order. First match wins.

### Rule 1 — explicit override

If the user passed `--format=blog|social|linkedin|business-plan|application|cv|slides`,
skip detection and use it. This is the escape hatch for misclassification.

### Rule 2.3 — slides signals (run before all others)

Match if ANY of these:

- File extension is `.pptx`. Hard match — the file is a PowerPoint, no other format matches.
- Filename matches `(?i)(slides?|deck|presentation|talk|pitch[_-]?deck|keynote)` AND extension is `.md` or `.txt`.
- The file (markdown) contains 3+ thematic-break separators (`^---\s*$` outside YAML frontmatter) — Marp / Slidev / reveal.js convention.
- The file contains a Marp / Slidev frontmatter marker (`marp: true` or `theme:` inside the YAML frontmatter, or a `## Slide` repeating heading pattern).

→ dispatch `auto-slides-review-loop`. The slides skill REQUIRES a `--scenario=pitch|academic|internal` flag — if the user did not pass one, the umbrella forwards `--scenario=<missing>` and the format skill asks the user once before dispatching personas. For `--scenario=pitch`, also forward `--stage=` if provided. For `--scenario=academic`, forward `--talk-length=` and `--venue=` if provided.

### Rule 2 — business-plan signals

Match if ANY of these:

- Contains a heading line matching `(?i)^#+ *(executive summary|problem|solution|market|business model|go.to.market|unit economics|financial(s)?|traction|team)`
- Contains the literal regex `\$\d+(\.\d+)?\s*[BMK]?\s*(TAM|SAM|SOM)` (e.g., "$5B TAM", "$200M SAM")
- Contains both "TAM" and "SAM" anywhere
- Filename matches `(?i)(business[_-]?plan|pitch|deck|exec[_-]?summary|memo)`

→ dispatch `auto-business-plan-review-loop`

### Rule 2.5 — application signals (Q&A document)

Match if ANY of these:

- File contains 2+ headings matching `(?i)^## *Q: ` (the application Q&A pattern). This is the strongest signal — the user has already structured their draft as questions and answers.
- Filename matches `(?i)(application|app[_-]?(yc|ycombinator|grant|fellowship|grad|mba|undergrad|scholarship)?|cover[_-]?letter|sop|statement[_-]?of[_-]?purpose|personal[_-]?statement|essay[_-]?(common[_-]?app|hbs|gsb))`

→ dispatch `auto-application-review-loop`. The application skill REQUIRES a `--target` flag (job, yc, accelerator, grant, fellowship, grad-school, mba, undergrad, scholarship) — if the user did not pass one, the umbrella forwards `--target=<missing>` and the format skill asks the user once before dispatching personas. Do not guess the target from filename heuristics; an `app_yc.md` filename hint is suggestive but not authoritative (a user might be reusing the file for a different target).

### Rule 2.7 — CV / resume signals

Match if ANY of these:

- Filename matches `(?i)(resume|cv|curriculum[_-]?vitae)`
- File contains at least 2 of these H2 sections (case-insensitive): `## Experience`, `## Education`, `## Skills`, `## Summary`, `## Profile`, `## Work History`, `## Employment`, `## Publications`, `## Projects` (where projects co-occurs with at least one of Experience or Education, to avoid matching a generic blog with a Projects heading)
- File starts with a name + contact-line pattern (line 1: `# <Name>`; line 2: short contact line containing email or phone)

→ dispatch `auto-cv-review-loop`.

### Rule 3 — social signals

Match if ALL of these:

- File size < 500 chars OR word count < 80
- No markdown headings (no `^#+ ` lines)
- Filename matches `(?i)(tweet|x[_-]?post|thread|threads|ig[_-]?caption|social)` OR has none of those but is `.txt`

→ dispatch `auto-social-review-loop`. Default `--platform=x` unless filename
hints `threads` or `ig`.

### Rule 4 — LinkedIn signals

Match if ALL of these:

- File size between 500 and 3500 chars (LinkedIn 3000-char limit + frontmatter slack)
- Has at least one `#hashtag` token (regex `(?:^|\s)#[A-Za-z][A-Za-z0-9_]+`)
- No markdown H1/H2 structure (or at most one H1)
- Filename matches `(?i)(linkedin|li[_-]?post)` OR hashtag count ≥ 2

→ dispatch `auto-linkedin-review-loop`. LinkedIn hosts distinct genres under one format (career/personal-brand vs. impersonal op-ed/civic/analysis), and the right persona panel differs. If the user passed `--intent=career|thought-leadership`, forward it verbatim. Otherwise do **not** guess — forward `--intent=<missing>` and let the LinkedIn skill ask once, exactly as slides forwards `--scenario=<missing>` and applications forward `--target=<missing>`. (The umbrella stays a pure dispatcher; it does not run intent-detection heuristics.)

### Rule 5 — blog signals

Match if ALL of these:

- Word count between 400 and 5000 (loose around the 500–4000 spec)
- Has at least one `^## ` H2 heading
- No business-plan signals (already excluded by rule 2)

→ dispatch `auto-blog-review-loop`

### Rule 6 — ambiguous

If nothing matched, ask the user once:

```
Couldn't auto-detect format. This file is N words, has H headings, K hashtags.
Which is it?
  1. blog
  2. social (X/Threads/IG)
  3. LinkedIn
  4. business-plan
  5. application (job/YC/grant/fellowship/grad-school/MBA/undergrad)
  6. cv / resume
  7. slides (pitch deck / academic talk / internal presentation)
```

Accept `1`/`2`/`3`/`4`/`5`/`6`/`7` or the literal name. If the user types `cancel`
or `stop`, exit cleanly. If they pick `5`, ask the follow-up: "Application target?
job, yc, accelerator, grant, fellowship, grad-school, mba, undergrad, scholarship?"
and pass through as `--target=<value>`. If they pick `7`, ask: "Slides scenario?
pitch (startup deck), academic (talk/defense), or internal (corporate)?" and
pass through as `--scenario=<value>`.

## Phase 2 — dispatch

Once format is decided, invoke the matching skill via the Skill tool:

| Format | Skill name |
|--------|-----------|
| blog | `auto-blog-review-loop` |
| social | `auto-social-review-loop` |
| linkedin | `auto-linkedin-review-loop` (also pass `--intent=career\|thought-leadership`, or `--intent=<missing>` if unclear) |
| business-plan | `auto-business-plan-review-loop` |
| application | `auto-application-review-loop` (also pass `--target=<type>`) |
| cv | `auto-cv-review-loop` |
| slides | `auto-slides-review-loop` (also pass `--scenario=<type>`) |

Pass through the original draft path AND any user-provided flags. Example:

```
User invoked: /auto-essay-review-loop my_post.md --difficulty=hard
You detected:  blog
You dispatch:  Skill auto-blog-review-loop with args "my_post.md --difficulty=hard"
```

The format skill handles everything from there: it owns the loop, the
personas, the verification, the state file, the manifest. You return
control to it and stop.

## What you do NOT do

- Do not call `mcp__codex__codex` yourself. Only the format skill does that.
- Do not write to `review-stage/`. Only the format skill does that.
- Do not load personas. The format skill knows its own personas.
- Do not fix the draft. Only the format skill does that.
- Do not debate the user about the detected format. Show your detection
  reasoning in one sentence, then dispatch. If they disagree, they can
  re-run with `--format=...`.

## Detection-reasoning output (one line, before dispatching)

Print exactly one line to the user before calling the Skill tool:

```
Detected: blog (1842 words, 5 H2s, no business-plan markers) — dispatching to auto-blog-review-loop.
```

This gives the user a chance to Ctrl-C if you got it wrong.

## State and recovery

You hold no state. The format skill manages its own
`review-stage/REVIEW_STATE.json` per the loop contract. If the user re-invokes
the umbrella mid-loop, you re-detect the format and dispatch again — the
format skill's recovery logic will pick up where it left off (24h window,
draft hash check; see `loop-contract.md`).

## Brand voice

If `BRAND_VOICE.md` exists in the working directory, mention it in the
detection-reasoning line:

```
Detected: linkedin (2 hashtags, 2841 chars). Brand voice loaded. Dispatching to auto-linkedin-review-loop.
```

The format skill picks it up via `brand-voice-protocol.md` — you do not
parse it.

## Backends (v0.1)

Only `--reviewer=codex` is supported. If the user passes anything else,
warn and fall back:

```
v0.1 only supports reviewer=codex (gpt-5.4 via Codex MCP).
v0.2+ will add deepseek, minimax, llm-chat, ollama. Falling back to codex.
```

Then dispatch normally. Do not block.

## Sibling workflows

These are review-loop-adjacent skills that do **not** take a single draft
document as input and are **not** auto-detected by this umbrella. They
invoke directly. Mention them when the user describes the matching
workflow shape, but do not dispatch to them from here.

| Skill | Invocation | Input | Output |
|-------|------------|-------|--------|
| [`auto-linkedin-outbound-loop`](../auto-linkedin-outbound-loop/SKILL.md) | `/auto-linkedin-outbound-loop campaigns/<name>.json` | Campaign JSON (`icp` + `offer` + `profileUrls`) | `review-stage/outbound/approved_messages.csv` — persona-reviewed, qualified, approved-for-human-send LinkedIn outbound messages. Never auto-sends. |

## Examples

### Example 1 — blog post, .md

```
User: /auto-essay-review-loop posts/2026-04-shipping-fast.md
You read: 1842 words, 5 H2s, opens with "I shipped 3 features in 4 days. Here's how."
You print: Detected: blog (1842 words, 5 H2s) — dispatching to auto-blog-review-loop.
You call:  Skill auto-blog-review-loop with args "posts/2026-04-shipping-fast.md"
```

### Example 2 — tweet, .txt

```
User: /auto-essay-review-loop tweet.txt
You read: 247 chars, no headings, no hashtags
You print: Detected: social/x (247 chars) — dispatching to auto-social-review-loop.
You call:  Skill auto-social-review-loop with args "tweet.txt --platform=x"
```

### Example 3 — pitch deck memo

```
User: /auto-essay-review-loop investor_memo.md
You read: contains "## Problem", "## Solution", "$2B TAM"
You print: Detected: business-plan ($2B TAM, exec-summary structure) — dispatching to auto-business-plan-review-loop.
You call:  Skill auto-business-plan-review-loop with args "investor_memo.md"
```

### Example 3.5 — YC application

```
User: /auto-essay-review-loop yc_w26.md --target=yc
You read: 4 headings starting with "## Q:", 1842 words
You print: Detected: application/yc (5 questions, Q&A structure) — dispatching to auto-application-review-loop.
You call:  Skill auto-application-review-loop with args "yc_w26.md --target=yc"
```

### Example 3.7 — resume

```
User: /auto-essay-review-loop my_resume.md
You read: name + contact line, ## Experience, ## Education, ## Skills sections
You print: Detected: cv (resume sections present) — dispatching to auto-cv-review-loop.
You call:  Skill auto-cv-review-loop with args "my_resume.md"
```

### Example 3.8 — application without target

```
User: /auto-essay-review-loop common_app.md
You read: 6 headings starting with "## Q:"
You print: Detected: application (Q&A structure). Application target?
            job, yc, accelerator, grant, fellowship, grad-school, mba, undergrad, scholarship?
User: undergrad
You call:  Skill auto-application-review-loop with args "common_app.md --target=undergrad"
```

### Example 3.9 — pitch deck (markdown slides)

```
User: /auto-essay-review-loop drafts/seed_deck.md --scenario=pitch --stage=seed
You read: 11 thematic breaks, "marp: true" in frontmatter, filename hints "deck"
You print: Detected: slides (Marp deck, 12 slides) — dispatching to auto-slides-review-loop with --scenario=pitch.
You call:  Skill auto-slides-review-loop with args "drafts/seed_deck.md --scenario=pitch --stage=seed"
```

### Example 3.95 — PowerPoint file

```
User: /auto-essay-review-loop drafts/q4_review.pptx --scenario=internal
You read: extension is .pptx (binary; skip 8KB peek)
You print: Detected: slides (.pptx) — dispatching to auto-slides-review-loop with --scenario=internal.
You call:  Skill auto-slides-review-loop with args "drafts/q4_review.pptx --scenario=internal"
```

### Example 3.97 — academic talk without scenario

```
User: /auto-essay-review-loop drafts/talk.md
You read: 14 thematic breaks, no "marp" frontmatter, filename "talk"
You print: Detected: slides (14 thematic breaks, filename hint). Slides scenario?
            pitch (startup deck), academic (talk/defense), or internal (corporate)?
User: academic
You call:  Skill auto-slides-review-loop with args "drafts/talk.md --scenario=academic"
```

### Example 4 — explicit override

```
User: /auto-essay-review-loop notes.md --format=linkedin
You skip detection.
You print: Format=linkedin (user override) — dispatching to auto-linkedin-review-loop.
You call:  Skill auto-linkedin-review-loop with args "notes.md --format=linkedin"
```

### Example 5 — ambiguous

```
User: /auto-essay-review-loop draft.md
You read: 320 words, 1 H2, no hashtags, no business-plan markers
You print: Couldn't auto-detect (320 words is borderline, no hashtags, 1 H2). Which is it?
            1) blog  2) social  3) linkedin  4) business-plan
User: 1
You call:  Skill auto-blog-review-loop with args "draft.md --format=blog"
```

## Cross-references

- Loop contract: `skills/shared-references/loop-contract.md`
- Reviewer independence: `skills/shared-references/reviewer-independence.md`
- Persona library: `skills/shared-references/persona-library.md`
- Verification protocols: `skills/shared-references/verification-protocols.md`
- Brand voice: `skills/shared-references/brand-voice-protocol.md`
- Backend setup: `docs/BACKEND_CONFIG.md`
- Examples: `docs/EXAMPLES.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
