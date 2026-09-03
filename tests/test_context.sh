#!/usr/bin/env bash
# test_context.sh — golden + invariant tests for bin/context
#
# Usage:
#   tests/test_context.sh            Run all tests
#   tests/test_context.sh --regen    Regenerate golden outputs from bin/context
#
# Golden tests render fixture trajectories (tests/fixtures/) with a matrix of
# flags and diff the output against checked-in goldens (tests/golden/).
# Invariant tests assert structural properties of the output regardless of
# goldens: valid JSON, alternating roles, valid UTF-8.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
CONTEXT="${CONTEXT_BIN:-$REPO/bin/context}"
FIXTURES="$HERE/fixtures"
GOLDEN="$HERE/golden"

# context shells out to traj; make sure the repo's copy wins
PATH="$REPO/bin:$PATH"
unset TRAJ_DIR TRAJ_ID 2>/dev/null || true

REGEN=0
[[ "${1:-}" == "--regen" ]] && REGEN=1
WORK_BK=$(mktemp -d)
trap 'rm -rf "$WORK_BK"' EXIT

PROD='--assistant-types reasoning,final --user-types prompt,shell-output,feedback --exclude-types sub-run,shellm-run,run-summary'

# case_id | fixture | flags
cases() {
    cat <<'EOF'
prod_basic|basic|PRODFLAGS
default_basic|basic|
headtail_basic|basic|--head 3 --tail 10 PRODFLAGS
trunc_basic|basic|--prompt-limit 200 PRODFLAGS
budget_basic|basic|--max-bytes 4000 PRODFLAGS
elnone_basic|basic|--tail 5 --elision-style none PRODFLAGS
pin_basic|basic|--tail 3 --pin b-010 PRODFLAGS
prod_empty|empty|PRODFLAGS
prod_junk|junk|PRODFLAGS
default_junk|junk|
prod_multibyte|multibyte|PRODFLAGS
trunc_multibyte|multibyte|--prompt-limit 100 PRODFLAGS
prod_blobs|blobs|PRODFLAGS
trunc_blobs|blobs|--prompt-limit 30 PRODFLAGS
EOF
}

pass=0
fail=0
ok()   { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

run_case() {
    # run_case <fixture> <flags...> ; prints stdout, returns rc
    local fixture="$1"; shift
    "$CONTEXT" --traj_dir "$FIXTURES" "$fixture" "$@"
}

# ---------------------------------------------------------------------------
# Golden tests
# ---------------------------------------------------------------------------

mkdir -p "$GOLDEN"

while IFS='|' read -r case_id fixture flags; do
    [[ -z "$case_id" ]] && continue
    flags="${flags//PRODFLAGS/$PROD}"
    # shellcheck disable=SC2086
    out=$(run_case "$fixture" $flags 2>/dev/null)
    rc=$?

    if [[ "$REGEN" -eq 1 ]]; then
        printf '%s' "$out" > "$GOLDEN/$case_id.out"
        printf 'regen %s (rc=%s)\n' "$case_id" "$rc"
        continue
    fi

    if [[ "$rc" -ne 0 ]]; then
        bad "golden/$case_id" "exit code $rc"
        continue
    fi
    if [[ ! -f "$GOLDEN/$case_id.out" ]]; then
        bad "golden/$case_id" "missing golden (run --regen)"
        continue
    fi
    if diff -q <(printf '%s' "$out") "$GOLDEN/$case_id.out" >/dev/null 2>&1; then
        ok "golden/$case_id"
    else
        bad "golden/$case_id" "output differs from golden"
        diff <(printf '%s' "$out") "$GOLDEN/$case_id.out" | head -6 | sed 's/^/    /'
    fi
done < <(cases)

[[ "$REGEN" -eq 1 ]] && { printf 'goldens regenerated in %s\n' "$GOLDEN"; exit 0; }

# ---------------------------------------------------------------------------
# Invariant tests (golden-independent)
# ---------------------------------------------------------------------------

# 1. Output is a JSON array of {role, content} with alternating roles.
# shellcheck disable=SC2086
if run_case basic $PROD | jq -e '
        type == "array"
        and (map(.role) | all(. == "user" or . == "assistant"))
        and ([range(1; length) as $i | .[$i].role != .[$i-1].role] | all)
        and (map(.content | type == "string") | all)
    ' >/dev/null 2>&1; then
    ok "invariant/alternating-roles"
else
    bad "invariant/alternating-roles"
fi

# 2. Output is valid UTF-8 even when truncation hits multibyte characters.
# shellcheck disable=SC2086
if run_case multibyte --prompt-limit 100 $PROD 2>/dev/null | iconv -f UTF-8 -t UTF-8 >/dev/null 2>&1; then
    ok "invariant/valid-utf8-truncation"
else
    bad "invariant/valid-utf8-truncation"
fi

# 2b. Bookkeeping stamped on steps (token counts, latency, run id) never
# reaches the model; the thought and the code block do.
BK="$WORK_BK"
mkdir -p "$BK/bk"
cat > "$BK/bk/trajectory.jsonl" <<'EOF'
{"type": "prompt", "content": "Do the thing.", "step_id": "k-000", "ts": "2026-09-03T00:00:00Z"}
{"type": "reasoning", "thought": "Checking the log first.", "cmd": "tail -n 3 log.txt", "run_id": "run-1", "llm_s": 12, "in_tok": 31864, "out_tok": 337, "think_tok": 50, "cache_tok": 12000, "estimated": true, "step_id": "k-001", "ts": "2026-09-03T00:00:01Z"}
{"type": "shell-output", "stdout": "line a\nline b\n", "exit": 0, "exec_s": 1, "run_id": "run-1", "step_id": "k-002", "ts": "2026-09-03T00:00:02Z"}
EOF
# shellcheck disable=SC2086
bk_out=$("$CONTEXT" --traj_dir "$BK" bk $PROD 2>/dev/null)
if printf '%s' "$bk_out" | grep -q -e '\[in_tok\]' -e '\[out_tok\]' -e '\[think_tok\]' -e '\[cache_tok\]' -e '\[llm_s\]' -e '\[run_id\]' -e '\[estimated\]'; then
    bad "invariant/bookkeeping-hidden" "$(printf '%s' "$bk_out" | grep -o '\[[a-z_]*\]' | sort -u | tr '\n' ' ')"
elif printf '%s' "$bk_out" | grep -q 'Checking the log first' && printf '%s' "$bk_out" | grep -q 'tail -n 3 log.txt' \
     && printf '%s' "$bk_out" | grep -q '\[exit\]'; then
    ok "invariant/bookkeeping-hidden"
else
    bad "invariant/bookkeeping-hidden" "thought, cmd, or exit missing"
fi

# 3. Empty trajectory renders an empty array.
if [[ "$(run_case empty $PROD 2>/dev/null)" == "[]" ]]; then
    ok "invariant/empty-trajectory"
else
    bad "invariant/empty-trajectory"
fi

# 4. --max-bytes budget is respected.
# shellcheck disable=SC2086
budget_out=$(run_case basic --max-bytes 2000 $PROD 2>/dev/null)
if [[ "$(printf '%s' "$budget_out" | LC_ALL=C wc -c | tr -d ' ')" -le 2000 ]]; then
    ok "invariant/max-bytes-budget"
else
    bad "invariant/max-bytes-budget"
fi

# 5. Excluded types never appear in output.
# shellcheck disable=SC2086
if run_case basic $PROD | grep -q 'sub-run bookkeeping'; then
    bad "invariant/exclude-types"
else
    ok "invariant/exclude-types"
fi

# 6. Blob refs are loaded from disk; missing blobs keep inline content.
# shellcheck disable=SC2086
blob_out=$(run_case blobs $PROD 2>/dev/null)
if printf '%s' "$blob_out" | grep -q 'blob line one' \
   && printf '%s' "$blob_out" | grep -q 'inline kept'; then
    ok "invariant/blob-loading"
else
    bad "invariant/blob-loading"
fi

# 7. Process frugality: rendering must not fork per trajectory line.
#    (The old implementation forked ~10x per line; the rewrite is O(1).)
_p0=$(bash -c 'echo $$')
# shellcheck disable=SC2086
run_case basic $PROD >/dev/null 2>&1
_p1=$(bash -c 'echo $$')
_delta=$((_p1 - _p0))
if [[ "$_delta" -lt 0 ]]; then
    printf 'skip invariant/fork-count (pid wraparound)\n'
elif [[ "$_delta" -lt 150 ]]; then
    ok "invariant/fork-count ($_delta processes)"
else
    bad "invariant/fork-count" "$_delta processes spawned (expected < 150)"
fi

# ---------------------------------------------------------------------------

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
