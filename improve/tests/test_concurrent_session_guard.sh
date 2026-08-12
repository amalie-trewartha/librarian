#!/usr/bin/env bash
# Unit test for the flock-based concurrent-session guard in session.sh.
# Spawns N parallel processes that race on run_num selection using the
# same flock pattern, then verifies each gets a unique sequential run_num.
# Includes a negative control (without flock) confirming the race exists.
set -eu

GEN_NUM=1
NUM_RACERS=10

run_test() {
    local use_lock="${1:-yes}"
    local tmp="$2"
    local lock_file="$tmp/.session.lock"
    local identities_dir="$tmp/identities"
    mkdir -p "$identities_dir"
    rm -rf "$identities_dir"/*

    local pids=()
    for i in $(seq 1 "$NUM_RACERS"); do
        (
            if [[ "$use_lock" == "yes" ]]; then
                flock 9
            fi
            run_num=1
            while [[ -d "$identities_dir/$(printf 'g%03dr%d' "$GEN_NUM" "$run_num")" ]]; do
                run_num=$(( run_num + 1 ))
            done
            run_name=$(printf 'g%03dr%d' "$GEN_NUM" "$run_num")
            # Atomic-ish claim: mkdir succeeds for only one racer
            mkdir "$identities_dir/$run_name" 2>/dev/null
            echo "$run_name"
        ) 9>"$lock_file" &
        pids+=($!)
    done
    wait "${pids[@]}" 2>/dev/null || true
}

main() {
    tmp=$(mktemp -d)
    trap 'rm -rf "${tmp:-}"' EXIT

    echo "--- Test 1: WITH flock guard ---"
    run_test yes "$tmp" | sort > "$tmp/results.txt"
    local got
    got=$(cat "$tmp/results.txt")
    local expected
    expected=$(seq 1 "$NUM_RACERS" | while read -r n; do printf 'g%03dr%d\n' "$GEN_NUM" "$n"; done | sort)

    if [[ "$got" == "$expected" ]]; then
        echo "PASS: all $NUM_RACERS racers got unique sequential slots"
    else
        echo "FAIL: collision detected"
        echo "--- expected ---"; echo "$expected"
        echo "--- got ---"; echo "$got"
        return 1
    fi

    echo
    echo "--- Test 2: WITHOUT flock (negative control) ---"
    run_test no "$tmp" | sort | uniq -c | sort -rn | head -3 > "$tmp/negative.txt"
    local dupes
    dupes=$(awk '$1 > 1' "$tmp/negative.txt" | wc -l)
    if [[ "$dupes" -gt 0 ]]; then
        echo "PASS: negative control shows collisions (race exists, test is meaningful)"
    else
        echo "WARN: no collisions in negative control (may need more racers; flock test still valid)"
    fi

    echo
    echo "All tests passed."
}

main "$@"
