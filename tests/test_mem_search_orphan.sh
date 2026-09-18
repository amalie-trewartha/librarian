#!/usr/bin/env bash
# test_mem_search_orphan.sh — a failed/cancelled `mem search` must not keep
# a result pipeline open via an orphaned heartbeat.
#
# Why: the search's stderr heartbeat was an infinite
#   ( while :; do sleep; printf ... >&2; done ) &
# loop backgrounded from the search. When the model call failed (set -e exits
# before the cleanup line) or the search was signalled, the loop was
# orphaned — reparented to init, still holding the write end of the
# `mem search | head` pipe, so the reader never saw EOF and hung (issue
# #119). The heartbeat now self-terminates when the search dies, and the
# search runs in a subshell whose EXIT/TERM/INT traps reap it.
#
# Usage: tests/test_mem_search_orphan.sh

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

pass=0 fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; [[ -n "${2:-}" ]] && printf '     %s\n' "$2"; }

# A bounded runner: timeout is GNU coreutils (gtimeout on a stock Mac).
TIMEOUT=""
for _t in timeout gtimeout; do
    command -v "$_t" >/dev/null 2>&1 && { TIMEOUT="$_t"; break; }
done

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/mem"
printf -- '---\nsummary: capture race\ntype: fact\n---\ncapture race\n' \
    > "$WORK/mem/2026-09-08-00-00-00_abcd_capture.md"

# run_search <stub-body>: point `llm` at a stub that sleeps 1s (so the
# heartbeat is established) then does <stub-body>. Run the search through a
# reader (`head -5`) under a 5s bound. Sets RC and FINISHED (1 = the search
# closed its pipeline on its own, 0 = the bound fired = the pipe stayed open).
run_search() {
    printf '%s\n' '#!/bin/bash' 'cat >/dev/null' "$1" > "$WORK/bin/llm"
    chmod +x "$WORK/bin/llm"
    cat > "$WORK/search.sh" <<EOF
#!/bin/bash
set -o pipefail
export PATH="$WORK/bin:$REPO/bin:\$PATH"
export MEM_DIR="$WORK/mem"
export MEM_SEARCH_HEARTBEAT_S=2
"$REPO/bin/mem" search "capture race" | head -5
EOF
    chmod +x "$WORK/search.sh"
    RC=$("$TIMEOUT" 5 "$WORK/search.sh" 2>"$WORK/err")
    RC=$?
    FINISHED=0
    [[ $RC -ne 124 ]] && FINISHED=1
}

if [[ -z "$TIMEOUT" ]]; then
    echo "skip: no timeout/gtimeout; the orphan-hang check needs a bounded runner"
    printf '\n%d passed, %d failed (skipped)\n' "$pass" "$fail"
    exit 0
fi

# 1. A failed model call must close the pipeline and preserve the exit code.
run_search 'sleep 1; exit 42'
if [[ $FINISHED -eq 1 && $RC -eq 42 ]]; then
    ok "failed search closes its pipeline and preserves exit 42"
else
    bad "failed search closes its pipeline and preserves exit 42" \
        "finished=$FINISHED rc=$RC (orphan heartbeat kept the pipe open)"
fi

# 2. A signalled search must close the pipeline and exit 143.
run_search 'sleep 1; kill -TERM "$PPID"; exit 0'
if [[ $FINISHED -eq 1 && $RC -eq 143 ]]; then
    ok "cancelled search closes its pipeline and exits 143"
else
    bad "cancelled search closes its pipeline and exits 143" \
        "finished=$FINISHED rc=$RC (orphan heartbeat kept the pipe open)"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
