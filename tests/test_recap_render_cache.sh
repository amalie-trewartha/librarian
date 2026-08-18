#!/usr/bin/env bash
# test_recap_render_cache.sh — the persistent render cache behind --context
#
# Usage: tests/test_recap_render_cache.sh
#
# Rendering the raw trajectory into the filtered TSV is the dominant
# --context cost on a long life (jq parses every byte of the log, most of
# which it discards), and the original build re-rendered from scratch on
# every call. These tests pin the cache: the TSV persists next to the
# blocks, later calls render only lines past the recorded high-water mark,
# stale rows from a crashed append are dropped, and a version/keep-set/
# truncation mismatch falls back to a full rebuild. Output must be
# byte-identical with and without a warm cache.
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
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$label"; else bad "$label"; fi; }
check_not() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then bad "$label"; else ok "$label"; fi; }

# --- stub llm: every call logged, canned rollup JSON back -------------------
mkdir -p "$WORK/bin"
cat > "$WORK/bin/llm" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
printf 'CALL\n%s\n---\n' "$input" >> "$LLM_LOG"
n=$(printf '%s' "$input" | wc -l | tr -d ' ')
printf '{"summary":"rollup of %s lines","themes":["testing"],"step_ids":["st000001"]}' "$n"
EOF
chmod +x "$WORK/bin/llm"
export PATH="$WORK/bin:$REPO/bin:$PATH"
export LLM_LOG="$WORK/llm.log"
unset TRAJ_DIR TRAJ_ID RECAP_MODEL SHELLM_FAST_MODEL SHELLM_MODEL 2>/dev/null || true

TRAJ_ROOT="$WORK/trajectories"

mk_traj() { # mk_traj <run-name> <n-signal-steps>
    local run="$TRAJ_ROOT/$1" i
    mkdir -p "$run"
    printf '{"type":"trajectory","step_id":"%s-0000-4000-8000-000000000000","ts":"t0"}\n' \
        "${1%%-*}" > "$run/trajectory.jsonl"
    for (( i = 1; i <= $2; i++ )); do
        printf '{"type":"thought","step_id":"st%06d","ts":"2026-07-17T10:%02d:00","source":"tester","content":"thinking about topic %d"}\n' \
            "$i" $((i % 60)) "$i" >> "$run/trajectory.jsonl"
    done
}

add_steps() { # add_steps <run-name> <from> <to> — append signal steps, plus one noise line
    local run="$TRAJ_ROOT/$1" i
    printf '{"type":"reasoning","step_id":"nz%06d","ts":"2026-07-17T11:00:00","content":"noise between appends"}\n' \
        "$2" >> "$run/trajectory.jsonl"
    for (( i = $2; i <= $3; i++ )); do
        printf '{"type":"thought","step_id":"st%06d","ts":"2026-07-17T10:%02d:00","source":"tester","content":"thinking about topic %d"}\n' \
            "$i" $((i % 60)) "$i" >> "$run/trajectory.jsonl"
    done
}

RUN="feed1111-root"
ROLLUPS="$TRAJ_ROOT/$RUN/rollups"
TSV="$ROLLUPS/rendered.tsv"
RMETA="$ROLLUPS/rendered.meta.json"
JSONL="$TRAJ_ROOT/$RUN/trajectory.jsonl"

# ---------------------------------------------------------------------------
# 1. First --context call writes the cache: TSV rows = signal steps, meta
#    records the raw line count and format version.
# ---------------------------------------------------------------------------
mk_traj "$RUN" 25
out1=$(recap feed1111 --traj_dir "$TRAJ_ROOT" --context --raw-tail 5 2>&1)
rc=$?
check "first: exits 0"              test "$rc" -eq 0
check "first: rendered.tsv exists"  test -f "$TSV"
check "first: meta exists"          test -f "$RMETA"
check "first: 25 signal rows"       test "$(wc -l < "$TSV" | tr -d ' ')" = "25"
check "first: meta raw_lines = 26"  test "$(jq -r .raw_lines "$RMETA")" = "26"

# ---------------------------------------------------------------------------
# 2. Incremental append: plant a sentinel in an early cached row, append new
#    steps (plus a noise line), rerun. The sentinel surviving proves the old
#    rows were NOT re-rendered; the new rows still appear, in order, with no
#    duplicate raw-line numbers, and the tail shows the newest step.
# ---------------------------------------------------------------------------
sed 's/thinking about topic 3/& CACHE-SENTINEL/' "$TSV" > "$TSV.sed" && mv "$TSV.sed" "$TSV"
add_steps "$RUN" 26 40
out2=$(recap feed1111 --traj_dir "$TRAJ_ROOT" --context --raw-tail 5 2>&1)
rc=$?
check "append: exits 0"             test "$rc" -eq 0
check "append: old rows kept"       grep -q 'CACHE-SENTINEL' "$TSV"
check "append: 40 signal rows"      test "$(wc -l < "$TSV" | tr -d ' ')" = "40"
check "append: newest row present"  grep -q 'topic 40' "$TSV"
check "append: newest step in tail" grep -q 'topic 40' <<<"$out2"
check "append: no duplicate lines"  test -z "$(cut -f1 "$TSV" | sort | uniq -d)"
check "append: meta advanced to 42" test "$(jq -r .raw_lines "$RMETA")" = "42"

# ---------------------------------------------------------------------------
# 3. Crash leftover: rows above the recorded high-water mark (an append that
#    died before its meta write) are dropped before the next append, so
#    nothing duplicates.
# ---------------------------------------------------------------------------
jq '.raw_lines = 41' "$RMETA" > "$RMETA.tmp" && mv "$RMETA.tmp" "$RMETA"   # pretend the last row was never recorded
out3=$(recap feed1111 --traj_dir "$TRAJ_ROOT" --context --raw-tail 5 2>&1)
rc=$?
check "crash: exits 0"              test "$rc" -eq 0
check "crash: still 40 signal rows" test "$(wc -l < "$TSV" | tr -d ' ')" = "40"
check "crash: no duplicate lines"   test -z "$(cut -f1 "$TSV" | sort | uniq -d)"
check "crash: old rows kept"        grep -q 'CACHE-SENTINEL' "$TSV"

# ---------------------------------------------------------------------------
# 4. Version mismatch: a stale format version forces a full rebuild (the
#    sentinel vanishes), and the row count is right afterwards.
# ---------------------------------------------------------------------------
jq '.version = 0' "$RMETA" > "$RMETA.tmp" && mv "$RMETA.tmp" "$RMETA"
out4=$(recap feed1111 --traj_dir "$TRAJ_ROOT" --context --raw-tail 5 2>&1)
rc=$?
check "version: exits 0"            test "$rc" -eq 0
check_not "version: cache rebuilt"  grep -q 'CACHE-SENTINEL' "$TSV"
check "version: 40 signal rows"     test "$(wc -l < "$TSV" | tr -d ' ')" = "40"

# ---------------------------------------------------------------------------
# 5. Shrunken log (recorded lines > file lines — append-only says this
#    cannot happen): full rebuild rather than a corrupt incremental pass.
# ---------------------------------------------------------------------------
sed 's/thinking about topic 5/& CACHE-SENTINEL/' "$TSV" > "$TSV.sed" && mv "$TSV.sed" "$TSV"
jq '.raw_lines = 99999' "$RMETA" > "$RMETA.tmp" && mv "$RMETA.tmp" "$RMETA"
out5=$(recap feed1111 --traj_dir "$TRAJ_ROOT" --context --raw-tail 5 2>&1)
rc=$?
check "shrink: exits 0"             test "$rc" -eq 0
check_not "shrink: cache rebuilt"   grep -q 'CACHE-SENTINEL' "$TSV"
check "shrink: 40 signal rows"      test "$(wc -l < "$TSV" | tr -d ' ')" = "40"

# ---------------------------------------------------------------------------
# 6. Equivalence: the staircase a warm cache produces is byte-identical to a
#    cold full render of the same trajectory.
# ---------------------------------------------------------------------------
warm=$(recap feed1111 --traj_dir "$TRAJ_ROOT" --context --raw-tail 5 2>&1)
rm -f "$TSV" "$RMETA"
cold=$(recap feed1111 --traj_dir "$TRAJ_ROOT" --context --raw-tail 5 2>&1)
check "equiv: warm == cold output"  test "$warm" = "$cold"

printf '\n%s passed, %s failed\n' "$pass" "$fail"
exit $(( fail > 0 ))
