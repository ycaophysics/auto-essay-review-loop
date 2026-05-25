#!/usr/bin/env bash
# auto-essay-review-loop v0.1 smoke tests
#
# Verifies that the verification tools in tools/ correctly pass good
# fixtures and reject bad ones. Does NOT run the full skill loops —
# that requires Codex MCP and a live Claude Code session.
#
# Run from repo root:
#   bash tests/run_tests.sh
#
# Designed to work on Git Bash on Windows. No GNU-specific flags.

set -uo pipefail

# Resolve repo root (this script is at <repo>/tests/run_tests.sh)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

PASS=0
FAIL=0
RESULTS=()

# Pick a python invocation that works on Windows (py launcher) or Unix (python3/python)
PYTHON=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "ERROR: no python interpreter found on PATH (tried python3, python, py)"
  exit 2
fi

# Parse the top-level "passed" field from a tool's JSON output via Python.
# We can't use grep — nested per-check "passed":true/false inside the
# checks[] array would false-match a top-level grep.
extract_passed() {
  local out="$1"
  "$PYTHON" -c '
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print("true" if data.get("passed") else "false")
except Exception:
    print("error")
' <<< "$out"
}

# assert_passed <name> <expected_passed_true_or_false> <command...>
assert_passed() {
  local name="$1"; shift
  local expected="$1"; shift
  local out
  out="$("$@" 2>&1)" || true
  local got
  got="$(extract_passed "$out")"
  if [ "$got" = "error" ]; then
    RESULTS+=("FAIL  $name  (could not parse JSON top-level 'passed')")
    FAIL=$((FAIL+1))
    return
  fi
  if [ "$got" = "$expected" ]; then
    RESULTS+=("PASS  $name")
    PASS=$((PASS+1))
  else
    RESULTS+=("FAIL  $name  (expected passed=$expected, got passed=$got)")
    FAIL=$((FAIL+1))
  fi
}

# assert_flag_contains <name> <flag> <command...>
# Parses the top-level "flags" array via Python.
assert_flag_contains() {
  local name="$1"; shift
  local flag="$1"; shift
  local out
  out="$("$@" 2>&1)" || true
  local has
  has="$("$PYTHON" -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    flags = data.get('flags', [])
    # Also search nested checks[].flag in case schema differs across tools
    for c in data.get('checks', []):
        if isinstance(c, dict) and c.get('flag'):
            flags.append(c['flag'])
    print('yes' if '$flag' in flags else 'no')
except Exception:
    print('error')
" <<< "$out")"
  if [ "$has" = "yes" ]; then
    RESULTS+=("PASS  $name  (flag '$flag' present)")
    PASS=$((PASS+1))
  elif [ "$has" = "error" ]; then
    RESULTS+=("FAIL  $name  (could not parse JSON for flag check)")
    FAIL=$((FAIL+1))
  else
    RESULTS+=("FAIL  $name  (expected flag '$flag' in output.flags)")
    FAIL=$((FAIL+1))
  fi
}

# assert_metric <name> <metric.dot.path> <expected_value> <command...>
# Pulls a numeric/string metric out of the tool's JSON. Supports dotted paths like
# "metrics.slide_count", "checks.2.value" (int index into list), or top-level keys.
assert_metric() {
  local name="$1"; shift
  local path="$1"; shift
  local expected="$1"; shift
  local out
  out="$("$@" 2>&1)" || true
  local got
  got="$("$PYTHON" -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    cur = data
    for part in '$path'.split('.'):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    print(cur)
except Exception as e:
    print('error:'+str(e))
" <<< "$out")"
  if [ "$got" = "$expected" ]; then
    RESULTS+=("PASS  $name  ($path=$expected)")
    PASS=$((PASS+1))
  else
    RESULTS+=("FAIL  $name  (expected $path=$expected, got $got)")
    FAIL=$((FAIL+1))
  fi
}

echo "Running auto-essay-review-loop v0.1 smoke tests"
echo "================================================"
echo

# --- Blog: link verification ---
assert_passed "verify_links good draft" "true" \
  bash tools/verify_links.sh tests/fixtures/blog/good_draft.md
assert_passed "verify_links bad draft" "false" \
  bash tools/verify_links.sh tests/fixtures/blog/bad_draft.md

# --- Social: char count ---
assert_passed "count_chars good X post" "true" \
  "$PYTHON" tools/count_chars.py tests/fixtures/social/good_x_post.txt --format=x
assert_passed "count_chars over-limit X post" "false" \
  "$PYTHON" tools/count_chars.py tests/fixtures/social/over_limit_x.txt --format=x
assert_passed "count_chars good Threads post" "true" \
  "$PYTHON" tools/count_chars.py tests/fixtures/social/good_threads_post.txt --format=threads

# --- LinkedIn: char/link/hashtag count ---
assert_passed "count_chars good LinkedIn post (3 hashtags, 0 links)" "true" \
  "$PYTHON" tools/count_chars.py tests/fixtures/linkedin/good_post.md --format=linkedin
assert_passed "count_chars LinkedIn broetry slop (8 hashtags, 2 links)" "false" \
  "$PYTHON" tools/count_chars.py tests/fixtures/linkedin/broetry_slop.md --format=linkedin
# Surface the specific failures so a regression that drops one check still trips.
assert_metric "broetry slop hashtag_count value" "checks.2.value" "8" \
  "$PYTHON" tools/count_chars.py tests/fixtures/linkedin/broetry_slop.md --format=linkedin
assert_metric "broetry slop link_count value" "checks.1.value" "2" \
  "$PYTHON" tools/count_chars.py tests/fixtures/linkedin/broetry_slop.md --format=linkedin

# --- Business plan: market sizing ---
assert_passed "market_size_check fantasy TAM" "false" \
  "$PYTHON" tools/market_size_check.py tests/fixtures/business-plan/fantasy_tam.md
assert_flag_contains "market_size_check fantasy TAM flag" "fantasy_tam" \
  "$PYTHON" tools/market_size_check.py tests/fixtures/business-plan/fantasy_tam.md
assert_passed "market_size_check strong plan" "true" \
  "$PYTHON" tools/market_size_check.py tests/fixtures/business-plan/strong.md

# --- Market research: plan + validate ---
# `plan` always exits 0 with no top-level `passed` field. Assert the JSON shape
# instead so a regression that breaks subcommand wiring trips the test.
assert_metric "market_research_fetch plan emits tool name" "tool" "market_research_fetch" \
  bash tools/run.sh market_research_fetch.py plan --input "AI code review for startups" --depth=lite
assert_metric "market_research_fetch plan emits phase=plan" "phase" "plan" \
  bash tools/run.sh market_research_fetch.py plan --input "AI code review for startups" --depth=lite
# `validate` against a fixture missing 7 of 8 required sections must fail
# with the canonical `missing_section` flag.
assert_passed "market_research_fetch validate thin doc" "false" \
  bash tools/run.sh market_research_fetch.py validate --input tests/fixtures/market-research/thin.md
assert_flag_contains "market_research_fetch validate thin doc flag" "missing_section" \
  bash tools/run.sh market_research_fetch.py validate --input tests/fixtures/market-research/thin.md

# --- Application: per-answer verification ---
assert_passed "verify_application strong draft" "true" \
  "$PYTHON" tools/verify_application.py tests/fixtures/application/strong.md
assert_passed "verify_application weak draft" "false" \
  "$PYTHON" tools/verify_application.py tests/fixtures/application/weak.md

# --- Regression: count_chars must not crash on unknown platform.
# Before the fix, --format=mastodon raised ValueError and produced a
# Python traceback (no JSON), breaking Phase B verification when a
# typo'd platform reached the tool. Should now produce passed:false JSON.
assert_passed "count_chars bad platform yields JSON error (not traceback)" "false" \
  "$PYTHON" tools/count_chars.py tests/fixtures/social/good_x_post.txt --format=mastodon

# --- Regression: tools/run.sh wrapper picks the right interpreter and
# forwards arguments. Before this wrapper, SKILL.md hardcoded
# `python tools/...` and broke on Windows boxes where only `py` is on
# PATH. Verify the wrapper produces equivalent JSON for a known-good
# input — same fixture as the count_chars test above.
assert_passed "tools/run.sh wraps count_chars correctly" "true" \
  bash tools/run.sh count_chars.py tests/fixtures/social/good_x_post.txt --format=x

# --- CV: structural verification ---
assert_passed "verify_cv strong CV" "true" \
  bash tools/run.sh verify_cv.py tests/fixtures/cv/strong.md --target-pages=1
assert_passed "verify_cv weak CV (cliches, weak verbs, no numbers, mixed dates)" "false" \
  bash tools/run.sh verify_cv.py tests/fixtures/cv/weak.md --target-pages=1

# --- Slides: structural verification ---
assert_passed "verify_slides strong deck (Marp markdown)" "true" \
  bash tools/run.sh verify_slides.py tests/fixtures/slides/strong.md
assert_passed "verify_slides weak deck (walls of text, dup titles, no notes, no close)" "false" \
  bash tools/run.sh verify_slides.py tests/fixtures/slides/weak.md
assert_passed "verify_slides weak deck fails under pitch tighter limits" "false" \
  bash tools/run.sh verify_slides.py tests/fixtures/slides/weak.md --max-words-per-slide=40 --slide-count-max=15 --claim-title-target=40

# Regression: pitch deck with positioning-style titles ("Stripe for X", "From X to Y",
# "X: Y" colon claims) should pass under pitch-tightened thresholds. Before
# expanding is_claim_title(), this fixture would fail claim_title_ratio.
assert_passed "verify_slides good pitch deck under pitch limits" "true" \
  bash tools/run.sh verify_slides.py tests/fixtures/slides/pitch_strong.md --max-words-per-slide=40 --slide-count-max=15 --claim-title-target=40

# Regression: code-fence-aware splitting. The fixture has 3 `---` lines inside
# fenced YAML/python blocks AND 4 real slide separators (5 slides total). Without
# fence masking, the parser would have produced 8 slides.
assert_metric "verify_slides ignores fenced-block --- lines (code_fence fixture)" "metrics.slide_count" "5" \
  bash tools/run.sh verify_slides.py tests/fixtures/slides/code_fence.md

# Regression: a deck whose first content is a slide separator (no real frontmatter)
# must NOT have its first slide consumed as YAML frontmatter. Before the fix,
# strip_frontmatter() ate any opening `---...---` block; now it requires a YAML
# key:value line inside.
assert_metric "verify_slides preserves first slide when no real frontmatter" "metrics.slide_count" "5" \
  bash tools/run.sh verify_slides.py tests/fixtures/slides/no_frontmatter.md

# Regression: verify_slides handles non-UTF8 markdown gracefully.
_BAD_ENC_SLIDES="$(mktemp -t auto-essay-bad-slides-enc.XXXXXX 2>/dev/null || mktemp)"
printf '\xff\xfe\x00garbage\xff' > "$_BAD_ENC_SLIDES"
assert_passed "verify_slides handles non-UTF8 input gracefully" "false" \
  bash tools/run.sh verify_slides.py "$_BAD_ENC_SLIDES"
rm -f "$_BAD_ENC_SLIDES" 2>/dev/null || true

# --- Slides: edit_pptx round-trip (v0.2 writer) ---
# Builds a tiny .pptx fixture, applies a fix list, and checks that the
# expected text/notes changes landed. Skipped if python-pptx is missing.
HAS_PPTX="$("$PYTHON" -c 'import pptx; print("yes")' 2>/dev/null || true)"
if [ "$HAS_PPTX" = "yes" ]; then
  _ROUND_TRIP_DIR="$(mktemp -d -t auto-essay-pptx-rt.XXXXXX 2>/dev/null || mktemp -d)"
  _RT_INPUT="$_ROUND_TRIP_DIR/round_trip_input.pptx"
  _RT_OUTPUT="$_ROUND_TRIP_DIR/round_trip_output.pptx"

  "$PYTHON" tests/fixtures/slides/build_pptx_fixture.py "$_RT_INPUT" >/dev/null 2>&1
  if [ ! -f "$_RT_INPUT" ]; then
    RESULTS+=("FAIL  edit_pptx round-trip  (fixture builder did not produce input deck)")
    FAIL=$((FAIL+1))
  else
    assert_passed "edit_pptx applies fix list and reports passed" "false" \
      bash tools/run.sh edit_pptx.py --input "$_RT_INPUT" --output "$_RT_OUTPUT" --fixes tests/fixtures/slides/round_trip_fixes.json

    # The fix list intentionally includes one warning case (target text not
    # found) and one unsupported action. We assert specific outcomes by
    # inspecting the output deck rather than the writer's own report.
    _RT_CHECK="$("$PYTHON" - "$_RT_OUTPUT" <<'PYEOF'
import sys
from pptx import Presentation
prs = Presentation(sys.argv[1])
slides = list(prs.slides)
errors = []

# Slide 1: notes set
n1 = slides[0].notes_slide.notes_text_frame.text
if "30 seconds" not in n1:
    errors.append("slide 1 notes missing the new content")

# Slide 2: wordy line replaced, redundant line deleted
text2 = "\n".join(
    sh.text_frame.text for sh in slides[1].shapes if sh.has_text_frame
)
if "$432K wasted per year" not in text2:
    errors.append("slide 2 replacement text not present")
if "$432K per year on duplicated work and abandoned projects" in text2:
    errors.append("slide 2 original wordy text was not replaced")
if "wordy descriptor we plan to cut" in text2:
    errors.append("slide 2 deletion did not happen")

# Slide 3: title replaced + notes appended
title3 = slides[2].shapes.title.text
if title3 != "We are raising $1.5M":
    errors.append(f"slide 3 title not replaced (got: {title3!r})")
n3 = slides[2].notes_slide.notes_text_frame.text
if "Close on the ask" not in n3:
    errors.append("slide 3 appended notes missing")

print("OK" if not errors else "; ".join(errors))
PYEOF
)"
    if [ "$_RT_CHECK" = "OK" ]; then
      RESULTS+=("PASS  edit_pptx round-trip applies all 5 supported actions")
      PASS=$((PASS+1))
    else
      RESULTS+=("FAIL  edit_pptx round-trip  ($_RT_CHECK)")
      FAIL=$((FAIL+1))
    fi

    # Verify the writer's own report classifies the unsupported + missing-target
    # fixes correctly: the unsupported action should be skipped (not warning),
    # and the missing-target fix should be a warning (not crash).
    _RT_REPORT="$(bash tools/run.sh edit_pptx.py --input "$_RT_INPUT" --output "$_RT_OUTPUT" --fixes tests/fixtures/slides/round_trip_fixes.json --dry-run 2>/dev/null || true)"
    _RT_SKIP_COUNT="$("$PYTHON" -c "import sys, json; d=json.loads(sys.stdin.read()); print(len(d['skipped']))" <<<"$_RT_REPORT" 2>/dev/null || echo error)"
    _RT_WARN_COUNT="$("$PYTHON" -c "import sys, json; d=json.loads(sys.stdin.read()); print(len(d['warnings']))" <<<"$_RT_REPORT" 2>/dev/null || echo error)"
    if [ "$_RT_SKIP_COUNT" = "1" ] && [ "$_RT_WARN_COUNT" = "1" ]; then
      RESULTS+=("PASS  edit_pptx classifies unsupported as skipped, missing target as warning")
      PASS=$((PASS+1))
    else
      RESULTS+=("FAIL  edit_pptx classification  (skipped=$_RT_SKIP_COUNT expected 1, warnings=$_RT_WARN_COUNT expected 1)")
      FAIL=$((FAIL+1))
    fi
  fi
  rm -rf "$_ROUND_TRIP_DIR" 2>/dev/null || true
else
  RESULTS+=("SKIP  edit_pptx round-trip  (python-pptx not installed)")
fi

# Regression: edit_pptx fails fast with a JSON error if python-pptx missing.
# We can't easily simulate "missing" here without uninstalling, so instead
# assert that calling without --input produces a JSON error (not a traceback).
assert_passed "edit_pptx errors cleanly on missing args" "false" \
  bash tools/run.sh edit_pptx.py --output /tmp/x.pptx --fixes /tmp/x.json

# --- LinkedIn outbound: enrich_profiles, qualify_prospect, verify_outbound_message, outbound_state ---
#
# These four tools form the outbound pipeline. We don't hit Apify in tests —
# enrich_profiles is exercised only for its argument validation + missing-token
# path. The rest run end-to-end against tests/fixtures/outbound/.

# enrich_profiles: missing APIFY_TOKEN flags `missing_apify_token`.
# The fixture campaign includes one spoofed non-LinkedIn URL so we also
# verify the `invalid_profile_url` flag fires.
#
# Don't run this inside a subshell — assert_*'s RESULTS / PASS / FAIL state
# would be lost on subshell exit. Save and restore APIFY_TOKEN around the
# block instead, distinguishing unset-from-empty using ${VAR+set} so we
# don't accidentally turn an originally-unset variable into an empty
# exported one for tests further down.
if [ "${APIFY_TOKEN+set}" = "set" ]; then
  _APIFY_TOKEN_WAS_SET=1
  _SAVED_APIFY_TOKEN="$APIFY_TOKEN"
else
  _APIFY_TOKEN_WAS_SET=0
fi
unset APIFY_TOKEN
_ENRICH_OUT="/tmp/auto_outbound_test_enrich"
assert_passed "enrich_profiles flags missing token + invalid URL" "false" \
  bash tools/run.sh enrich_profiles.py tests/fixtures/outbound/campaign.json --out-dir="$_ENRICH_OUT"
assert_flag_contains "enrich_profiles surfaces missing_apify_token" "missing_apify_token" \
  bash tools/run.sh enrich_profiles.py tests/fixtures/outbound/campaign.json --out-dir="$_ENRICH_OUT"
assert_flag_contains "enrich_profiles surfaces invalid_profile_url" "invalid_profile_url" \
  bash tools/run.sh enrich_profiles.py tests/fixtures/outbound/campaign.json --out-dir="$_ENRICH_OUT"
if [ "$_APIFY_TOKEN_WAS_SET" = "1" ]; then
  export APIFY_TOKEN="$_SAVED_APIFY_TOKEN"
fi
unset _SAVED_APIFY_TOKEN _APIFY_TOKEN_WAS_SET
rm -rf "$_ENRICH_OUT" 2>/dev/null || true

# qualify_prospect: strong fixture qualifies (Founder + B2B SaaS + hiring SDRs
# in about), weak fixture (no headline/role/company) is disqualified.
# Repo-relative temp dir: Git-Bash mktemp paths (/tmp/...) are invisible to Windows Python.
_QUALIFY_OUT="$REPO_ROOT/tests/tmp/qualify_$$"
mkdir -p "$_QUALIFY_OUT"
assert_passed "qualify_prospect scores the strong fixture as qualified" "true" \
  bash tools/run.sh qualify_prospect.py tests/fixtures/outbound/normalized.json tests/fixtures/outbound/campaign.json --out-dir="$_QUALIFY_OUT"
assert_metric "qualify_prospect emits qualified_count=1" "qualified_count" "1" \
  bash tools/run.sh qualify_prospect.py tests/fixtures/outbound/normalized.json tests/fixtures/outbound/campaign.json --out-dir="$_QUALIFY_OUT"
assert_metric "qualify_prospect emits rejected_count=1" "rejected_count" "1" \
  bash tools/run.sh qualify_prospect.py tests/fixtures/outbound/normalized.json tests/fixtures/outbound/campaign.json --out-dir="$_QUALIFY_OUT"
# qualified_prospects.json should contain the founder row at slug 'example-founder'.
_QUAL_SLUG="$(QUALIFY_OUT="$_QUALIFY_OUT" "$PYTHON" -c "import json, os, pathlib; p = pathlib.Path(os.environ['QUALIFY_OUT']) / 'qualified_prospects.json'; rows = json.loads(p.read_text(encoding='utf-8')); print(rows[0].get('profile_slug', 'none') if rows else 'none')")"
if [ "$_QUAL_SLUG" = "example-founder" ]; then
  RESULTS+=("PASS  qualify_prospect: example-founder qualifies (slug present in qualified_prospects.json)")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  qualify_prospect: expected example-founder in qualified_prospects.json, got '$_QUAL_SLUG'")
  FAIL=$((FAIL+1))
fi
rm -rf "$_QUALIFY_OUT" 2>/dev/null || true

# verify_outbound_message: 4 fixtures, each exercising a different check.
assert_passed "verify_outbound_message good message passes" "true" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_good.json tests/fixtures/outbound/campaign.json
assert_passed "verify_outbound_message creepy message fails" "false" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_creepy.json tests/fixtures/outbound/campaign.json
assert_flag_contains "verify_outbound_message flags surveillance_phrasing" "surveillance_phrasing" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_creepy.json tests/fixtures/outbound/campaign.json
assert_flag_contains "verify_outbound_message flags sensitive_trait (marital_status)" "sensitive_trait" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_creepy.json tests/fixtures/outbound/campaign.json
assert_flag_contains "verify_outbound_message flags fake_familiarity ('as we discussed')" "fake_familiarity" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_creepy.json tests/fixtures/outbound/campaign.json
assert_passed "verify_outbound_message too-long message fails" "false" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_too_long.json tests/fixtures/outbound/campaign.json
assert_flag_contains "verify_outbound_message flags message_too_long" "message_too_long" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_too_long.json tests/fixtures/outbound/campaign.json
assert_passed "verify_outbound_message email channel fails when campaign.channels.email=false" "false" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_email_unauthorized.json tests/fixtures/outbound/campaign.json
assert_flag_contains "verify_outbound_message flags channel_unauthorized" "channel_unauthorized" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_email_unauthorized.json tests/fixtures/outbound/campaign.json

# False-positive regression: v0.1 sensitive-trait patterns fired on common
# business terms ("single source of truth", "race condition", "black box",
# "white paper", "age of X"). v0.2 tightened the patterns to require
# demographic context. This fixture exercises all of those tokens — they
# must NOT trip sensitive_trait now.
assert_passed "verify_outbound_message does not false-positive on common business terms" "true" \
  bash tools/run.sh verify_outbound_message.py tests/fixtures/outbound/message_business_terms.json tests/fixtures/outbound/campaign.json

# outbound_state: init from a fixture qualified-prospects file, then update,
# then resume. Validates that:
#   - init creates a state file with the right number of rows
#   - update mutates the named row (and rejects unknown slugs)
#   - resume classifies approved rows into to_skip and untouched rows into to_continue
_STATE_DIR="$(mktemp -d -t auto-essay-state.XXXXXX 2>/dev/null || mktemp -d)"
# Build a tiny qualified fixture inline so the state tests don't depend on
# qualify_prospect's output ordering.
cat > "$_STATE_DIR/qualified.json" <<'EOF'
[
  {"profileUrl": "https://www.linkedin.com/in/alice/", "profile_slug": "alice"},
  {"profileUrl": "https://www.linkedin.com/in/bob/",   "profile_slug": "bob"}
]
EOF
assert_passed "outbound_state init creates 2-row state file" "true" \
  bash tools/run.sh outbound_state.py init "$_STATE_DIR/qualified.json" --out-dir="$_STATE_DIR"
assert_metric "outbound_state init emits prospect_count=2" "prospect_count" "2" \
  bash tools/run.sh outbound_state.py init "$_STATE_DIR/qualified.json" --out-dir="$_STATE_DIR"

# Update alice to approved via stdin patch.
echo '{"status":"approved","round":2,"last_scores":{"target-customer":8}}' | \
  bash tools/run.sh outbound_state.py update alice - --out-dir="$_STATE_DIR" >/dev/null
# Resume should now report 1 to_skip (alice) and 1 to_continue (bob).
_STATE_RESUME="$(bash tools/run.sh outbound_state.py resume --out-dir="$_STATE_DIR" 2>&1)"
_TO_SKIP="$("$PYTHON" -c "import sys,json; print(len(json.loads(sys.stdin.read())['to_skip']))" <<<"$_STATE_RESUME")"
_TO_CONT="$("$PYTHON" -c "import sys,json; print(len(json.loads(sys.stdin.read())['to_continue']))" <<<"$_STATE_RESUME")"
if [ "$_TO_SKIP" = "1" ] && [ "$_TO_CONT" = "1" ]; then
  RESULTS+=("PASS  outbound_state resume classifies approved=skip, qualified=continue")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  outbound_state resume  (to_skip=$_TO_SKIP expected 1, to_continue=$_TO_CONT expected 1)")
  FAIL=$((FAIL+1))
fi

# Negative: update against an unknown slug must report passed:false with
# the slug_not_found flag (not crash).
assert_passed "outbound_state update on missing slug fails cleanly" "false" \
  bash -c "echo '{}' | bash tools/run.sh outbound_state.py update no-such-slug - --out-dir=$_STATE_DIR"
assert_flag_contains "outbound_state surfaces slug_not_found" "slug_not_found" \
  bash -c "echo '{}' | bash tools/run.sh outbound_state.py update no-such-slug - --out-dir=$_STATE_DIR"

# Corruption surfacing: a malformed JSONL row must be reported in resume
# output (`corrupted_state_rows` flag, `malformed_rows` count), not
# silently skipped. The good row still feeds the resume plan.
_CORRUPT_DIR="$(mktemp -d -t auto-essay-state-corrupt.XXXXXX 2>/dev/null || mktemp -d)"
cat > "$_CORRUPT_DIR/prospect_state.jsonl" <<'EOF'
{"profileUrl": "https://www.linkedin.com/in/alice/", "profile_slug": "alice", "status": "qualified", "round": 0, "timestamp": "2026-05-12T00:00:00Z"}
not-actually-json-at-all
{"profileUrl": "https://www.linkedin.com/in/bob/", "profile_slug": "bob", "status": "approved", "round": 2, "timestamp": "2026-05-12T00:00:00Z"}
EOF
assert_passed "outbound_state resume reports corruption (not silent)" "false" \
  bash tools/run.sh outbound_state.py resume --out-dir="$_CORRUPT_DIR"
assert_flag_contains "outbound_state flags corrupted_state_rows" "corrupted_state_rows" \
  bash tools/run.sh outbound_state.py resume --out-dir="$_CORRUPT_DIR"
assert_metric "outbound_state malformed_rows=1" "malformed_rows" "1" \
  bash tools/run.sh outbound_state.py resume --out-dir="$_CORRUPT_DIR"
rm -rf "$_CORRUPT_DIR" 2>/dev/null || true

rm -rf "$_STATE_DIR" 2>/dev/null || true

# --- Skill-shape linter ---
# Cross-refs from SKILL.md files resolve, the umbrella dispatcher table
# matches the on-disk format skills, every persona file is referenced by
# at least one SKILL.md (or persona-library.md), and every SKILL.md has
# the name+description frontmatter the harness needs.
assert_passed "lint_skills clean run" "true" \
  bash tools/run.sh lint_skills.py

# Negative test: drop an unreferenced persona file into personas/blog/ and
# verify the linter catches it. Without this, the linter could silently
# regress to "always passed=true" and the green-path test alone wouldn't
# notice. Cleanup is unconditional via trap so a mid-test crash doesn't
# leave the fake persona behind.
_LINT_ORPHAN="personas/blog/_lint_test_orphan.md"
trap 'rm -f "$_LINT_ORPHAN" 2>/dev/null || true' EXIT
cat > "$_LINT_ORPHAN" <<'EOF'
---
name: _lint_test_orphan
role: temporary fixture; should never be referenced by any SKILL.md
---
This file exists only while tests/run_tests.sh is running.
EOF
assert_passed "lint_skills detects orphan persona" "false" \
  bash tools/run.sh lint_skills.py
assert_flag_contains "lint_skills orphan flag" "orphan_persona" \
  bash tools/run.sh lint_skills.py
rm -f "$_LINT_ORPHAN" 2>/dev/null || true
trap - EXIT

# Negative test: create a fake sibling skill dir that the umbrella does not
# reference. The umbrella_mentions_siblings check should fire sibling_drift.
# Mirrors the orphan-persona pattern with unconditional trap cleanup.
_LINT_SIBLING_DIR="skills/auto-lint-test-sibling-loop"
trap 'rm -rf "$_LINT_SIBLING_DIR" 2>/dev/null || true' EXIT
mkdir -p "$_LINT_SIBLING_DIR"
cat > "$_LINT_SIBLING_DIR/SKILL.md" <<'EOF'
---
name: auto-lint-test-sibling-loop
description: Temporary fixture; should never be referenced by the umbrella SKILL.md while tests/run_tests.sh is running.
---

# auto-lint-test-sibling-loop

This file exists only while tests/run_tests.sh is running.
EOF
assert_passed "lint_skills detects unreferenced sibling skill" "false" \
  bash tools/run.sh lint_skills.py
assert_flag_contains "lint_skills sibling_drift flag" "sibling_drift" \
  bash tools/run.sh lint_skills.py
rm -rf "$_LINT_SIBLING_DIR" 2>/dev/null || true
trap - EXIT

# --- Regression: verification tools must not crash on non-UTF8 input.
# Before this fix, count_chars.py and verify_application.py raised
# UnicodeDecodeError and printed a Python traceback when handed a cp1252
# or otherwise non-UTF8 draft. Should now produce passed:false JSON like
# verify_cv.py already did.
_BAD_ENC_FILE="$(mktemp -t auto-essay-bad-enc.XXXXXX 2>/dev/null || mktemp)"
printf '\xff\xfe\x00garbage\xff' > "$_BAD_ENC_FILE"
assert_passed "count_chars handles non-UTF8 input gracefully" "false" \
  "$PYTHON" tools/count_chars.py "$_BAD_ENC_FILE" --format=x
assert_passed "verify_application handles non-UTF8 input gracefully" "false" \
  "$PYTHON" tools/verify_application.py "$_BAD_ENC_FILE"
assert_passed "verify_cv handles non-UTF8 input gracefully" "false" \
  "$PYTHON" tools/verify_cv.py "$_BAD_ENC_FILE" --target-pages=1
rm -f "$_BAD_ENC_FILE" 2>/dev/null || true

# assert_python_ok <name> <python -c script>
assert_python_ok() {
  local name="$1"; shift
  if "$PYTHON" -c "$@" >/dev/null 2>&1; then
    RESULTS+=("PASS  $name")
    PASS=$((PASS+1))
  else
    RESULTS+=("FAIL  $name")
    FAIL=$((FAIL+1))
  fi
}

# --- Report adapter helpers (Phase 1 foundations) ---
assert_python_ok "mask_secrets redacts Bearer sk-*" \
  "from tools.report_adapters._helpers import mask_secrets; t='Bearer sk-abc123456789012345678901234'; assert mask_secrets(t) == '[REDACTED]', repr(mask_secrets(t))"

assert_python_ok "truncate_trace caps at 5KB" \
  "from tools.report_adapters._helpers import truncate_trace; big='x' * 100_000; out, trunc = truncate_trace(big); assert trunc; assert '[truncated]' in out; assert len(out.encode('utf-8')) <= 5200"

assert_python_ok "load_json_safe missing returns FileNotFoundError" \
  "from pathlib import Path; from tools.report_adapters._helpers import load_json_safe; data, err = load_json_safe(Path('tests/fixtures/__no_such_file__.json')); assert data is None and err and 'FileNotFoundError' in err"

assert_python_ok "load_json_safe malformed returns JSONDecodeError" \
  "import tempfile, os; from pathlib import Path; from tools.report_adapters._helpers import load_json_safe; fd, p = tempfile.mkstemp(suffix='.json'); os.write(fd, b'{not json'); os.close(fd); data, err = load_json_safe(Path(p)); os.unlink(p); assert data is None and err and 'JSONDecodeError' in err"

assert_python_ok "atomic_write creates target file" \
  "import tempfile, os; from pathlib import Path; from tools.report_adapters._helpers import atomic_write; d = Path(tempfile.mkdtemp()); t = d / 'out.txt'; atomic_write('hello', t); assert t.read_text(encoding='utf-8') == 'hello'; import shutil; shutil.rmtree(d)"

assert_python_ok "snapshot_read_jsonl drops trailing partial line silently" \
  "import tempfile, os; from pathlib import Path; from tools.report_adapters._helpers import snapshot_read_jsonl; d = Path(tempfile.mkdtemp()); p = d / 'state.jsonl'; p.write_text('{\"a\":1}\n{\"b\":2', encoding='utf-8'); rows, warns = snapshot_read_jsonl(p); import shutil; shutil.rmtree(d); assert len(rows) == 1 and rows[0]['a'] == 1 and not warns"

assert_python_ok "report adapter registry imports cleanly" \
  "from tools.report_adapters import make_jinja_env, list_adapters; from pathlib import Path; env = make_jinja_env(Path('templates/report')); assert env.autoescape is not None"

# --- RUN.json migration + init_outbound_run schema v2 (Phase 2) ---
_MIGRATE_DIR="$(mktemp -d -t auto-essay-migrate.XXXXXX 2>/dev/null || mktemp -d)"
mkdir -p "$_MIGRATE_DIR/review-stage/outbound/runs/20260525_test-run"
cat > "$_MIGRATE_DIR/review-stage/outbound/runs/20260525_test-run/RUN.json" <<'EOF'
{
  "tool": "init_outbound_run",
  "schema_version": 1,
  "run_id": "20260525_test-run"
}
EOF

_MIGRATE_OUT="$("$PYTHON" tools/migrate_run_json_add_skill.py --root="$_MIGRATE_DIR/review-stage" 2>&1)" || true
_MIGRATE_PASSED="$(extract_passed "$_MIGRATE_OUT")"
if [ "$_MIGRATE_PASSED" = "true" ]; then
  RESULTS+=("PASS  migrate_run_json adds skill to fixture without skill")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  migrate_run_json adds skill to fixture without skill  (expected passed=true, got passed=$_MIGRATE_PASSED)")
  FAIL=$((FAIL+1))
fi

_MIGRATE_SKILL="$("$PYTHON" -c "
import sys, json
data = json.loads(sys.stdin.read())
for check in data.get('checks', []):
    if check.get('name') == 'skill_backfilled':
        print(check.get('skill', ''))
        break
else:
    print('')
" <<< "$_MIGRATE_OUT")"
if [ "$_MIGRATE_SKILL" = "linkedin-outbound" ]; then
  RESULTS+=("PASS  migrate_run_json wrote skill=linkedin-outbound")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  migrate_run_json skill  (expected linkedin-outbound, got '$_MIGRATE_SKILL')")
  FAIL=$((FAIL+1))
fi

assert_metric "migrate_run_json idempotent on already-migrated" "skipped" "1" \
  "$PYTHON" tools/migrate_run_json_add_skill.py --root="$_MIGRATE_DIR/review-stage"
rm -rf "$_MIGRATE_DIR" 2>/dev/null || true

_INIT_OUT="$(mktemp -d -t auto-essay-init-outbound.XXXXXX 2>/dev/null || mktemp -d)"
_INIT_OUT_JSON="$("$PYTHON" tools/init_outbound_run.py tests/fixtures/outbound/campaign.json --base-dir="$_INIT_OUT/outbound" --no-latest --name=test-init --timestamp=20260525_120000 2>&1)" || true
_INIT_PASSED="$(extract_passed "$_INIT_OUT_JSON")"
if [ "$_INIT_PASSED" = "true" ]; then
  RESULTS+=("PASS  init_outbound_run creates run directory")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  init_outbound_run creates run directory  (expected passed=true, got passed=$_INIT_PASSED)")
  FAIL=$((FAIL+1))
fi

_INIT_TOOL_SCHEMA="$("$PYTHON" -c "import sys, json; print(json.loads(sys.stdin.read()).get('schema_version', ''))" <<<"$_INIT_OUT_JSON")"
if [ "$_INIT_TOOL_SCHEMA" = "2" ]; then
  RESULTS+=("PASS  init_outbound_run tool stdout schema_version=2")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  init_outbound_run tool stdout schema_version=2  (expected 2, got '$_INIT_TOOL_SCHEMA')")
  FAIL=$((FAIL+1))
fi

_INIT_RUN_DIR="$("$PYTHON" -c "import sys, json; print(json.loads(sys.stdin.read()).get('run_dir', ''))" <<<"$_INIT_OUT_JSON")"
_INIT_MANIFEST="$("$PYTHON" -c '
import json, sys
from pathlib import Path
run_dir = Path(sys.argv[1])
print(json.dumps(json.loads((run_dir / "RUN.json").read_text(encoding="utf-8"))))
' "$_INIT_RUN_DIR")"
_INIT_SKILL="$("$PYTHON" -c "import sys, json; print(json.loads(sys.stdin.read()).get('skill', ''))" <<<"$_INIT_MANIFEST")"
_INIT_SCHEMA="$("$PYTHON" -c "import sys, json; print(json.loads(sys.stdin.read()).get('schema_version', ''))" <<<"$_INIT_MANIFEST")"
if [ "$_INIT_SCHEMA" = "2" ]; then
  RESULTS+=("PASS  init_outbound_run RUN.json schema_version=2")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  init_outbound_run RUN.json schema_version=2  (expected 2, got '$_INIT_SCHEMA')")
  FAIL=$((FAIL+1))
fi
if [ "$_INIT_SKILL" = "linkedin-outbound" ]; then
  RESULTS+=("PASS  init_outbound_run RUN.json skill=linkedin-outbound")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  init_outbound_run RUN.json skill=linkedin-outbound  (expected linkedin-outbound, got '$_INIT_SKILL')")
  FAIL=$((FAIL+1))
fi
rm -rf "$_INIT_OUT" 2>/dev/null || true

# assert_grep_file <name> <pattern> <file>
assert_grep_file() {
  local name="$1"; shift
  local pattern="$1"; shift
  local file="$1"; shift
  if [ ! -f "$file" ]; then
    RESULTS+=("FAIL  $name  (file missing: $file)")
    FAIL=$((FAIL+1))
    return
  fi
  if grep -qE "$pattern" "$file" 2>/dev/null; then
    RESULTS+=("PASS  $name")
    PASS=$((PASS+1))
  else
    RESULTS+=("FAIL  $name  (pattern '$pattern' not in $file)")
    FAIL=$((FAIL+1))
  fi
}

# assert_no_grep_file <name> <pattern> <file>
assert_no_grep_file() {
  local name="$1"; shift
  local pattern="$1"; shift
  local file="$1"; shift
  if [ ! -f "$file" ]; then
    RESULTS+=("FAIL  $name  (file missing: $file)")
    FAIL=$((FAIL+1))
    return
  fi
  if grep -qE "$pattern" "$file" 2>/dev/null; then
    RESULTS+=("FAIL  $name  (unexpected pattern '$pattern' in $file)")
    FAIL=$((FAIL+1))
  else
    RESULTS+=("PASS  $name")
    PASS=$((PASS+1))
  fi
}

# --- generate_run_report (Phase 3) ---
_OUT_HAPPY="tests/fixtures/runs/outbound_happy"
_GEN_OUT="$("$PYTHON" tools/generate_run_report.py "$_OUT_HAPPY" 2>&1)" || true
_GEN_PASSED="$(extract_passed "$_GEN_OUT")"
if [ "$_GEN_PASSED" = "true" ] && [ -f "$_OUT_HAPPY/report.html" ]; then
  RESULTS+=("PASS  generate_run_report on outbound_happy writes report.html")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  generate_run_report on outbound_happy writes report.html")
  FAIL=$((FAIL+1))
fi

assert_grep_file "report.html contains funnel counts" "qualified" "$_OUT_HAPPY/report.html"
assert_grep_file "report.html contains copy buttons with aria-label" 'aria-label="Copy message' "$_OUT_HAPPY/report.html"
assert_no_grep_file "report.html has no external http URLs" 'http://' "$_OUT_HAPPY/report.html"
assert_grep_file "report.html escapes script from profile" '&lt;script&gt;' "$_OUT_HAPPY/report.html" || assert_no_grep_file "report.html no raw script tag" '<script>alert' "$_OUT_HAPPY/report.html"
assert_grep_file "report.html masks secrets in trace" '\[REDACTED\]' "$_OUT_HAPPY/report.html"

_GEN_PROG="$("$PYTHON" tools/generate_run_report.py tests/fixtures/runs/outbound_in_progress 2>&1)" || true
assert_grep_file "outbound_in_progress has meta refresh" 'http-equiv="refresh"' "tests/fixtures/runs/outbound_in_progress/report.html"

_GEN_DONE="$("$PYTHON" tools/generate_run_report.py tests/fixtures/runs/outbound_completed 2>&1)" || true
assert_no_grep_file "outbound_completed has NO meta refresh" 'http-equiv="refresh"' "tests/fixtures/runs/outbound_completed/report.html"

_GEN_PART="$("$PYTHON" tools/generate_run_report.py tests/fixtures/runs/outbound_partial 2>&1)" || true
_PART_PASSED="$(extract_passed "$_GEN_PART")"
if [ "$_PART_PASSED" = "true" ]; then
  RESULTS+=("PASS  generate_run_report on outbound_partial exits 0")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  generate_run_report on outbound_partial exits 0")
  FAIL=$((FAIL+1))
fi

_GEN_ESSAY="$("$PYTHON" tools/generate_run_report.py tests/fixtures/runs/essay_happy 2>&1)" || true
_ESSAY_PASSED="$(extract_passed "$_GEN_ESSAY")"
if [ "$_ESSAY_PASSED" = "true" ]; then
  RESULTS+=("PASS  generate_run_report on essay_happy succeeds")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  generate_run_report on essay_happy succeeds")
  FAIL=$((FAIL+1))
fi

if [ -f "$_OUT_HAPPY/expected_report.html" ] && [ -f "$_OUT_HAPPY/report.html" ]; then
  if cmp -s "$_OUT_HAPPY/expected_report.html" "$_OUT_HAPPY/report.html" 2>/dev/null; then
    RESULTS+=("PASS  report.html matches expected_report.html golden snapshot")
    PASS=$((PASS+1))
  else
    RESULTS+=("FAIL  report.html golden snapshot mismatch (re-run with --update-golden)")
    FAIL=$((FAIL+1))
  fi
else
  RESULTS+=("FAIL  expected_report.html golden snapshot missing")
  FAIL=$((FAIL+1))
fi

_GEN_MISSING="$("$PYTHON" tools/generate_run_report.py "$REPO_ROOT/tests/fixtures/__no_such_run_dir__" 2>&1)" || _GEN_MISSING_EXIT=$?
if [ "${_GEN_MISSING_EXIT:-0}" = "2" ]; then
  RESULTS+=("PASS  generate_run_report missing run_dir exits 2")
  PASS=$((PASS+1))
else
  RESULTS+=("FAIL  generate_run_report missing run_dir exits 2  (exit=${_GEN_MISSING_EXIT:-0})")
  FAIL=$((FAIL+1))
fi

# --- Summary ---
echo
echo "Results:"
echo "--------"
for line in "${RESULTS[@]}"; do
  echo "  $line"
done
echo
echo "Total: $((PASS+FAIL))   PASSED: $PASS   FAILED: $FAIL"
echo

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
