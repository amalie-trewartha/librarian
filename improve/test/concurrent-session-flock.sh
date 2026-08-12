#!/usr/bin/env bash
# Integration test: flock-guarded concurrent session numbering.
# Verifies two (or N) simultaneous sessions get distinct run_nums with no collision.
# Extracts the EXACT lock logic from session.sh lines 94-118, replacing `identity new`
# with `mkdir` (the race is on the identity dir itself — `identity new` dies if dir exists).
#
# Usage: improve/test/concurrent-session-flock.sh [WORKERS]
#   WORKERS: number of concurrent workers (default: 8)
set -euo pipefail

WORKERS="${1:-8}"
TMP_ROOT=$(mktemp -d)
GEN_NUM=1
GEN_DIR=$(printf '%s/gen-%03d' "$TMP_ROOT" "$GEN_NUM")
mkdir -p "$GEN_DIR/identities"

# Worker: acquires flock, finds next free slot, creates the dir, releases lock.
# Simulates session.sh's slot-assignment block (without model/API dependency).
worker() {
    local wid="$1"
    local LOCK_FILE="$GEN_DIR/.session.lock"
    local run_num run_name
    {
        flock 9
        run_num=1
        while [[ -d "$GEN_DIR/identities/$(printf 'g%03dr%d' "$GEN_NUM" "$run_num")" ]]; do
            run_num=$(( run_num + 1 ))
        done
        run_name=$(printf 'g%03dr%d' "$GEN_NUM" "$run_num")
        # Simulate `identity new` — create the dir (the thing being raced on)
        mkdir -p "$GEN_DIR/identities/$run_name"
        # Small delay to widen the race window (makes a broken lock fail reliably)
        sleep 0.05
    } 9>"$LOCK_FILE"
    printf '%s\n' "$run_num"
}

echo "Running $WORKERS concurrent workers against $GEN_DIR ..."
pids=()
results=()
for i in $(seq 1 "$WORKERS"); do
    worker "$i" > "$TMP_ROOT/result_$i.txt" &
    pids+=($!)
done

# Wait for all
fail=0
for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
done

if [[ "$fail" -ne 0 ]]; then
    echo "FAIL: one or more workers exited non-zero"
    rm -rf "$TMP_ROOT"
    exit 1
fi

# Collect run_nums
mapfile -t run_nums < <(cat "$TMP_ROOT"/result_*.txt | sort -n)
echo "Assigned run_nums: ${run_nums[*]}"

# Check: all distinct
unique_count=$(printf '%s\n' "${run_nums[@]}" | sort -u | wc -l)
total_count=${#run_nums[@]}

if [[ "$unique_count" -ne "$total_count" ]]; then
    echo "FAIL: $total_count workers, only $unique_count unique run_nums — COLLISION DETECTED"
    dupes=$(printf '%s\n' "${run_nums[@]}" | sort | uniq -d)
    echo "Duplicate run_nums: $dupes"
    rm -rf "$TMP_ROOT"
    exit 1
fi

# Check: run_nums are 1..N (no gaps, no skips)
expected=1
for rn in "${run_nums[@]}"; do
    if [[ "$rn" -ne "$expected" ]]; then
        echo "FAIL: expected run_num $expected, got $rn (gap or out-of-order)"
        rm -rf "$TMP_ROOT"
        exit 1
    fi
    expected=$(( expected + 1 ))
done

echo "PASS: $WORKERS concurrent workers got distinct, contiguous run_nums (1..$WORKERS)"
echo "Dirs created:"
ls -1 "$GEN_DIR/identities/" | head -20
rm -rf "$TMP_ROOT"
