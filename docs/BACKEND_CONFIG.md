# Backend Configuration

The reviewer is a different model from the executor. The executor is
whatever LLM is driving Claude Code (Claude). The reviewer is GPT-5.4 via
the Codex MCP server, in v0.1. v0.2+ adds more options.

## Codex (default reviewer)

Codex (GPT-5.4) is the reviewer. The **Codex MCP server** (`mcp__codex__codex`) is the preferred transport. If the MCP is unavailable mid-run (e.g., a dead OAuth refresh token returning `401`), the skills fall back to the **Codex CLI** (`codex exec`) — see [Codex CLI fallback](#codex-cli-fallback). Both call the same model with the same prompts; only the transport differs. (Non-Codex reviewers remain v0.2+ roadmap — see below.)

### What you need

1. **Codex CLI** — `npm install -g @openai/codex`
2. **Codex configured for `gpt-5.4`** with `model_reasoning_effort: medium`
3. **Codex MCP server registered** with your agent harness (Claude Code, etc.)

### Setup

```bash
# 1. Install Codex CLI
npm install -g @openai/codex

# 2. Configure model
codex setup
#   When prompted, select: gpt-5.4
#   Set reasoning effort: medium
#
# Or edit ~/.codex/config.toml directly:
#
#   model = "gpt-5.4"
#   model_reasoning_effort = "medium"

# 3. Register the MCP server with Claude Code
claude mcp add codex -s user -- codex mcp-server

# 4. Verify
claude mcp list
#   Should show:
#   codex   codex mcp-server   running
```

### Verify the skill can reach it

```
> /auto-essay-review-loop tests/fixtures/blog/good_draft.md --max-rounds=1
```

If the loop runs and you see `traces/blog/.../persona-*.response.txt` files
populated with JSON, the backend is wired up. If you see "tool not found"
errors, re-check `claude mcp list`.

### What the skill calls

```
mcp__codex__codex(
  prompt=<rendered user prompt with <DRAFT>...</DRAFT>>,
  config={"model_reasoning_effort": "medium"},
  system=<persona system prompt>
)
```

Each persona, each round, gets a FRESH thread. The skill never calls
`mcp__codex__codex-reply` across rounds. See
[`shared-references/reviewer-independence.md`](../skills/shared-references/reviewer-independence.md)
for why.

### Codex CLI fallback

If `mcp__codex__codex` is unreachable, the skills run the same review through the Codex CLI — one call per persona per round:

```bash
codex exec --skip-git-repo-check -m gpt-5.4 -c model_reasoning_effort=medium -s read-only \
  --output-schema <persona_schema.json> \
  -o <trace>/persona-<name>-round-<N>.response.txt \
  < <trace>/persona-<name>-round-<N>.prompt.txt
```

- `--output-schema` forces the persona's JSON shape (no parse-retry loop needed).
- `-o` writes only the final assistant message (the JSON) to the trace file.
- The prompt file is the same system + user prompt used for the MCP path, with the draft inlined in `<DRAFT>` tags.
- Run the four persona calls concurrently (background + `wait`).

**Auth.** The CLI shares `~/.codex/auth.json` with the MCP, so a dead OAuth session breaks both. Recover with `codex login`, or switch to an API key: `printenv OPENAI_API_KEY | codex login --with-api-key` (back up `auth.json` first — this switches Codex to metered API billing rather than the ChatGPT subscription).

This is a transport fallback for the same Codex reviewer, not a new backend; the `--reviewer=` options below are separate v0.2+ work.

### Cost expectations (v0.1)

Codex calls aren't free. Order-of-magnitude estimates per round:

| Format | Personas | Avg input tokens / persona | Avg output / persona | Approx cost / round |
|--------|----------|---------------------------|----------------------|---------------------|
| social | 4 | 800 | 600 | $0.10 |
| linkedin | 4 | 1500 | 700 | $0.15 |
| blog | 4 | 4000 | 900 | $0.30 |
| business-plan | 5 | 6000 | 1200 | $0.60 |

Budget for ~4 rounds. A typical full blog loop costs around $1.20 in
reviewer spend. Numbers will shift as Codex pricing changes.

## Backend override syntax

```
/auto-blog-review-loop my_post.md --reviewer=codex
```

In v0.1, `--reviewer=codex` is the only valid value. Anything else triggers
a warning and falls back to `codex`. The umbrella dispatcher at
`skills/auto-essay-review-loop/SKILL.md` enforces this.

## v0.2+ roadmap (not shipped)

The format-specific skills are designed so the reviewer call is one
function — swapping backends is a single dispatch. Planned options:

### `--reviewer=llm-chat`

OpenAI direct via the `llm-chat` MCP server (port from ARIS). Good when you
want to point at a non-Codex OpenAI account, or use a different model
(o3, gpt-5.4-pro, etc.).

```toml
# ~/.config/llm-chat/config.toml (v0.2 hypothetical)
[reviewer]
provider = "openai"
model = "gpt-5.4"
api_key_env = "OPENAI_API_KEY"
reasoning_effort = "high"
```

### `--reviewer=deepseek`

DeepSeek-V3.5 via DeepSeek API. Cheaper for long-tail formats (social,
LinkedIn). Trade-off: less rigorous than medium, but adequate for char-limit-
bounded content.

### `--reviewer=minimax`

MiniMax-M3 via MiniMax API. Port of the ARIS `auto-review-loop-minimax`
adapter. Good Chinese-language support for CJK content.

### `--reviewer=ollama:<model>`

Local-only review via Ollama. Examples:

```
--reviewer=ollama:llama-4-70b
--reviewer=ollama:qwen-3-72b
```

Useful for offline / air-gapped runs and for drafts you can't send to a
hosted API. Quality drop expected vs GPT-5.4 medium — roughly the gap
between "median peer reviewer" and "your most rigorous editor."

### `--reviewer=oracle-pro`

GPT-5.4 Pro via the [Oracle MCP](https://github.com/steipete/oracle).
Strongest available reasoning. Recommended for business-plan reviews
before sending to actual VCs.

## Per-skill override

Each format skill accepts `--reviewer=...` and passes it through to its
loop. This is the granular knob — you can use `codex` for blog reviews and
(in v0.2) `oracle-pro` for business plans:

```
/auto-blog-review-loop blog.md                       # codex (default)
/auto-business-plan-review-loop pitch.md --reviewer=oracle-pro   # v0.2+
```

The umbrella dispatcher passes the flag through unchanged.

## Codex MCP troubleshooting

| Symptom | Fix |
|---------|-----|
| "MCP tool `codex` not found" | `claude mcp list` to verify registration; re-run `claude mcp add codex -s user -- codex mcp-server` |
| Reviewer responses are extremely fast and shallow | `~/.codex/config.toml` is missing `model_reasoning_effort = "medium"` — fix and restart Codex |
| Reviewer returns `{}` or empty JSON | Persona system prompt's JSON schema section may be too long; trim. Or the draft is malformed. Check `traces/.../*.prompt.txt`. |
| 429 / rate limits | Codex is rate-limited; the skill retries with backoff, but heavy parallel runs may need `--parallel-personas=false` (sequential) |
| 500 errors mid-round | Codex MCP is flaky on long prompts; reduce `effort` or split blog drafts >5000 words |

For backend-agnostic loop issues (state file corrupted, draft hash mismatch,
etc.), see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Why Codex MCP first

Three reasons we shipped v0.1 with Codex only:

1. **Same backend as ARIS.** This repo is the writing-side port of the ARIS
   research-paper loop. ARIS shipped on Codex first; we keep the
   correspondence so personas, prompt patterns, and trace formats are
   directly comparable.
2. **GPT-5.4 is a high-fidelity reviewer in 2026.** The point
   of cross-model adversarial review is the reviewer's bar being high.
   `medium` reasoning is the default — fast enough for tight loops, rigorous
   enough to catch the issues that matter. Bump to `high`/`xhigh` for a
   one-off rigorous pass when needed. Cheaper backends ship in v0.2 once the
   loop is proven on the strong one.
3. **One backend = one set of prompt-injection tests.** Each backend has
   different injection vulnerabilities; we want v0.1's defenses dialed in
   on one surface before fanning out.
