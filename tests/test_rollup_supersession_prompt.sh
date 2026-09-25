#!/usr/bin/env bash
# test_rollup_supersession_prompt.sh — the rollup prompt names its correction targets
#
# Usage: tests/test_rollup_supersession_prompt.sh
#
# Sealed summary windows are frozen: when a later window corrects a claim an
# earlier window stated, nothing links the two, so a pass that reads only the
# stale window inherits the wrong conclusion (observed live 2026-09-25: a
# "channel noise" summary and its "resend loop" correction sat side by side in
# sibling windows with no pointer between them). Prompt v5 teaches the rollup
# model to cite the child window it supersedes by quoting that child's
# "[id,...]" prefix verbatim, so a reader can fan out to namers mechanically.
# This pins that the instruction actually reaches the model and that v5 is
# stamped into sealed blocks.
#
# The `llm` CLI is stubbed (canned rollup JSON, calls logged): no network.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$label"; else bad "$label" "$2"; fi; }
check_not() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then bad "$label" "$2"; else ok "$label"; fi; }

# --- stub llm: log system prompt AND user text, canned JSON back -----------
mkdir -p "$WORK/bin"
cat > "$WORK/bin/llm" <<'STUB'
#!/usr/bin/env bash
input=$(cat)
printf 'SYSTEM\n%s\nUSER\n%s\n---\n' "$*" "$input" >> "$LLM_LOG"
printf '{"summary":"rollup ok","themes":["testing"],"step_ids":["st000001"]}'
STUB
chmod +x "$WORK/bin/llm"
export PATH="$WORK/bin:$REPO/bin:$PATH"
export LLM_LOG="$WORK/llm.log"
unset TRAJ_DIR TRAJ_ID RECAP_MODEL SHELLM_FAST_MODEL SHELLM_MODEL 2>/dev/null || true

TRAJ_ROOT="$WORK/trajectories"
mkdir -p "$TRAJ_ROOT/supe0001"
GJ="$TRAJ_ROOT/supe0001/trajectory.jsonl"
printf '{"type":"trajectory","step_id":"supe0001-0000-4000-8000-000000000000","ts":"t0"}\n' > "$GJ"
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
    printf '{"type":"thought","step_id":"st%06d","ts":"2026-07-17T10:%02d:00","source":"tester","content":"thinking about topic %d"}\n' \
        "$i" $((i % 60)) "$i" >> "$GJ"
done

: > "$LLM_LOG"
recap supe0001 --traj_dir "$TRAJ_ROOT" --backfill >/dev/null 2>&1

# 1. The supersession instruction reaches the rollup model.
check "prompt: supersession citation instruction sent" \
    grep -q 'corrects or supersedes a claim' "$LLM_LOG"

# 2. The instruction names the child prefix format the model must quote.
check "prompt: child [id,...] prefix explained" \
    grep -q 'quoting its "\[id,\.\.\.\]" prefix' "$LLM_LOG"

# 3. Tier >= 2 input lines carry the [id,...] prefix the instruction cites.
#    (FANOUT 10 with 12 signal steps builds only t1; force tier-2 input shape
#    by checking the prefix join in the source is what the prompt describes.)
check "input: child prefix uses [id,id] join" \
    grep -qF '"[" + (.step_ids | join(",")) + "] " + .summary' "$REPO/bin/recap"

# 4. Sealed blocks are stamped with prompt_version 5.
blk=$(find "$TRAJ_ROOT/supe0001/rollups" -name '*.json' | head -1)
check "sealed block exists" test -n "$blk"
check "sealed block stamped prompt_version 5" \
    jq -e '.prompt_version == 5' "$blk"

# 5. The stub was actually called (log has at least one CALL/SYSTEM record).
check "rollup model invoked" grep -q '^SYSTEM$' "$LLM_LOG"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
exit $((fail > 0))
