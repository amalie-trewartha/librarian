#!/usr/bin/env bash
# test_thinkers_trajectory_swap.sh — the dispatcher must not replay history
# when the trajectory file is rewritten under its feeder.
#
# Usage:
#   tests/test_thinkers_trajectory_swap.sh
#
# 2026-09-12: a script did `grep -v X trajectory.jsonl > tmp && mv tmp
# trajectory.jsonl` on a live identity. The feeder is `tail -F`, which follows
# by name, so GNU tail reopened the new file and streamed the whole history
# through the dispatcher as if freshly appended; the responder answered
# month-old Slack threads for 22 hours. Two guards now cover this:
#   - the housekeeping tick notices a feeder whose file changed inode or
#     shrank, kills it, and respawns it at end of file;
#   - the dispatch loop skips any step older than the newest dispatched step
#     by more than THINKERS_REWIND_TOLERANCE seconds (a rewind of the feed),
#     without ever comparing against the clock, so old-but-new-to-us steps
#     still dispatch; and it skips any step_id it has already dispatched, for
#     the recent steps inside the tolerance window that tail re-emits before
#     the swap detector restarts the feeder.
# Uses a fake thinker that records its stdin; no LLM calls, no docker.
# Runtime ~25s.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
PATH="$REPO/bin:$PATH"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

TMP=$(mktemp -d)
TRAJ_ID="cafe0000-0000-0000-0000-000000000003"
TRAJ="$TMP/id/trajectories/$TRAJ_ID/trajectory.jsonl"
RUN="$TMP/id/run"

env_run() {
    IDENTITY_DIR="$TMP/id" IDENTITY_NAME=testid \
    TRAJ_DIR="$TMP/id/trajectories" TRAJ_ID="$TRAJ_ID" \
    THINKERS_DIR="$TMP/id/thinkers" MEM_DIR="$TMP/id/memories" \
    "$@"
}

cleanup() {
    env_run thinkers stop >/dev/null 2>&1 || true
    rm -rf "$TMP"
}
trap cleanup EXIT

# One fake thinker, "recorder": appends each trigger it receives to a file.
setup_identity() {
    env_run thinkers stop >/dev/null 2>&1 || true
    rm -rf "$TMP/id"
    mkdir -p "$TMP/id/thinkers/recorder" "$TMP/id/trajectories/$TRAJ_ID" "$TMP/id/memories"
    printf 'name=testid\ncreated=test\nroot_trajectory=%s\n' "$TRAJ_ID" > "$TMP/id/info.txt"
    : > "$TRAJ"
    cat > "$TMP/id/thinkers/recorder/step" <<'EOF'
#!/usr/bin/env bash
json=$(cat)
printf '%s\n' "$json" >> "$IDENTITY_DIR/record"
exit 0
EOF
    chmod +x "$TMP/id/thinkers/recorder/step"
    printf '{"types":["action"],"trigger_self":false}\n' > "$TMP/id/thinkers/recorder/subscriptions.jsonl"
}

# ISO UTC stamp for an epoch (GNU date, then BSD date).
iso_at() {
    date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
        || date -u -r "$1" +%Y-%m-%dT%H:%M:%SZ
}

# Raw step line with an explicit ts, so history can be back-dated.
step_line() {  # <content> <epoch>
    printf '{"type":"action","content":"%s","source":"test","step_id":"%s","ts":"%s"}' \
        "$1" "$(uuidgen 2>/dev/null || printf 'id-%s-%s' "$2" "$RANDOM")" "$(iso_at "$2")"
}

append_line() { printf '%s\n' "$1" >> "$TRAJ"; }

start_thinkers() { env_run thinkers start >/dev/null 2>&1; sleep 2; }
stop_thinkers()  { env_run thinkers stop >/dev/null 2>&1; }

record_count() {
    if [[ -f "$TMP/id/record" ]]; then wc -l < "$TMP/id/record" | tr -d ' '; else echo 0; fi
}

wait_for_record() {
    local want="$1" timeout="${2:-10}" i=0
    while [[ "$(record_count)" -lt "$want" && "$i" -lt "$timeout" ]]; do
        sleep 1; i=$((i+1))
    done
}

now() { date +%s; }

# ---------------------------------------------------------------------------
# Test 1: the file is rewritten under the running dispatcher (grep -v > tmp
# && mv, exactly the incident). Nothing from history fires again; a step
# appended to the NEW file afterwards is still dispatched; the log says why.
# ---------------------------------------------------------------------------
test_swap_does_not_replay() {
    setup_identity
    local t
    t=$(now)
    # Twenty steps of history, one hour old, all of a type the recorder wants.
    local i
    for i in $(seq 1 20); do
        append_line "$(step_line "hist-$i" $((t - 3600 - i)))"
    done
    start_thinkers

    append_line "$(step_line "live-1" "$t")"
    wait_for_record 1
    if [[ "$(record_count)" -eq 1 ]] && grep -q '"live-1"' "$TMP/id/record" 2>/dev/null; then
        ok "live step before the swap is dispatched once"
    else
        bad "live step before the swap is dispatched once" "record: $(record_count)"
    fi

    # The incident, verbatim: rewrite the file to a new inode.
    grep -v "no-such-marker" "$TRAJ" > "$TRAJ.clean" && mv "$TRAJ.clean" "$TRAJ"
    sleep 4

    append_line "$(step_line "live-2" "$(now)")"
    wait_for_record 2
    sleep 2
    if [[ "$(record_count)" -eq 2 ]] && grep -q '"live-2"' "$TMP/id/record" 2>/dev/null; then
        ok "live step appended to the new file is dispatched"
    else
        bad "live step appended to the new file is dispatched" "record: $(record_count)"
    fi
    if ! grep -q '"hist-' "$TMP/id/record" 2>/dev/null; then
        ok "no history step fired again after the swap"
    else
        bad "no history step fired again after the swap" "$(grep -c '"hist-' "$TMP/id/record") replayed"
    fi
    if grep -qE 'TRAJECTORY REPLACED|REWIND' "$RUN/logs/dispatcher.log" 2>/dev/null; then
        ok "dispatcher log names the swap or the rewind"
    else
        bad "dispatcher log names the swap or the rewind"
    fi
    if grep -q '"reason":"trajectory-re' "$TRAJ" 2>/dev/null; then
        ok "an error step marks the event in the trajectory"
    else
        bad "an error step marks the event in the trajectory"
    fi

    stop_thinkers
}

# ---------------------------------------------------------------------------
# Test 2: the rewind guard alone, deterministically. The cursor is seeded
# from the last line of the file at start. A step that is old by the clock
# but newer than the cursor (the agent was away) dispatches. A step older
# than the cursor by more than the tolerance is skipped as a rewind.
# ---------------------------------------------------------------------------
test_rewind_guard_is_relative_to_cursor() {
    setup_identity
    local t
    t=$(now)
    append_line "$(step_line "seed" $((t - 3 * 86400)))"     # three days ago
    # The dispatcher's own wake-up note (a fresh observation when the last
    # step is old) would legitimately move the cursor to now; keep it out so
    # this test exercises the cursor math alone.
    THINKERS_WAKE_NOTE_MIN_GAP=0 start_thinkers

    append_line "$(step_line "away-msg" $((t - 2 * 86400)))"  # two days ago: older than now, newer than cursor
    wait_for_record 1
    if [[ "$(record_count)" -eq 1 ]] && grep -q '"away-msg"' "$TMP/id/record" 2>/dev/null; then
        ok "a step older than the clock but newer than the cursor dispatches"
    else
        bad "a step older than the clock but newer than the cursor dispatches" "record: $(record_count)"
    fi

    append_line "$(step_line "rewound" $((t - 4 * 86400)))"   # four days ago: older than the cursor
    sleep 3
    if [[ "$(record_count)" -eq 1 ]]; then
        ok "a step older than the cursor is skipped"
    else
        bad "a step older than the cursor is skipped" "record: $(record_count)"
    fi
    if grep -q 'REWIND' "$RUN/logs/dispatcher.log" 2>/dev/null; then
        ok "rewind logged"
    else
        bad "rewind logged"
    fi

    append_line "$(step_line "after" "$t")"
    wait_for_record 2
    if [[ "$(record_count)" -eq 2 ]] && grep -q 'rewind over: skipped 1' "$RUN/logs/dispatcher.log" 2>/dev/null; then
        ok "dispatch resumes after the rewind and the skip count is logged"
    else
        bad "dispatch resumes after the rewind and the skip count is logged" "record: $(record_count)"
    fi

    stop_thinkers
}

# ---------------------------------------------------------------------------
# Test 3: THINKERS_REWIND_TOLERANCE=0 disables the guard (old behaviour).
# ---------------------------------------------------------------------------
test_tolerance_zero_disables() {
    setup_identity
    local t
    t=$(now)
    append_line "$(step_line "seed" "$t")"
    THINKERS_REWIND_TOLERANCE=0 start_thinkers
    append_line "$(step_line "ancient" $((t - 30 * 86400)))"
    wait_for_record 1
    if [[ "$(record_count)" -eq 1 ]]; then
        ok "tolerance 0 lets an old step through"
    else
        bad "tolerance 0 lets an old step through" "record: $(record_count)"
    fi
    stop_thinkers
}

test_swap_does_not_replay
test_rewind_guard_is_relative_to_cursor
test_tolerance_zero_disables

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
