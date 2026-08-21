#!/usr/bin/env bash
# tests/run-all.sh — run every tests/test_*.sh and summarize.
#
# Usage: tests/run-all.sh [pattern]
#   pattern   only run scripts whose name contains this substring
#             (e.g. `tests/run-all.sh recap`)
#
# Each test script is self-contained and prints its own ok/FAIL lines; this
# runner just executes them in turn, records the exit code and wall time,
# and exits non-zero if any script failed. CI calls this; locally you can
# still run a single script directly.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
pattern="${1:-}"

pass=() fail=()
for t in "$HERE"/test_*.sh; do
    name=$(basename "$t")
    [[ -z "$pattern" || "$name" == *"$pattern"* ]] || continue
    printf '\n===== %s =====\n' "$name"
    start=$SECONDS
    if bash "$t"; then
        pass+=("$name ($((SECONDS - start))s)")
    else
        fail+=("$name ($((SECONDS - start))s)")
    fi
done

printf '\n===== summary =====\n'
printf 'passed: %d\n' "${#pass[@]}"
for p in "${pass[@]+"${pass[@]}"}"; do printf '  ok   %s\n' "$p"; done
printf 'failed: %d\n' "${#fail[@]}"
for f in "${fail[@]+"${fail[@]}"}"; do printf '  FAIL %s\n' "$f"; done

[[ "${#fail[@]}" -eq 0 ]]
