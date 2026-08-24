#!/usr/bin/env bash
# test_thinkers_pending.sh — pending re-trigger tests for the thinkers dispatcher
#
# Usage:
#   tests/test_thinkers_pending.sh
#
# Builds a throwaway identity with a single slow fake thinker ("slowpoke",
# step = record stdin + sleep 3) and drives the dispatcher through the
# busy/pending/replay lifecycle. No LLM calls, no docker — pure dispatcher
# mechanics. Total runtime ~45s (dominated by slowpoke sleeps + 1s ticks).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
PATH="$REPO/bin:$PATH"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

TMP=$(mktemp -d)
TRAJ_ID="cafe0000-0000-0000-0000-000000000001"

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

setup_identity() {
    env_run thinkers stop >/dev/null 2>&1 || true
    rm -rf "$TMP/id"
    mkdir -p "$TMP/id/thinkers/slowpoke" "$TMP/id/trajectories/$TRAJ_ID" "$TMP/id/memories"
    printf 'name=testid\ncreated=test\nroot_trajectory=%s\n' "$TRAJ_ID" > "$TMP/id/info.txt"
    : > "$TMP/id/trajectories/$TRAJ_ID/trajectory.jsonl"

    cat > "$TMP/id/thinkers/slowpoke/step" <<'EOF'
#!/usr/bin/env bash
json=$(cat)
printf '%s\n' "$json" >> "$IDENTITY_DIR/record"
sleep 3
EOF
    chmod +x "$TMP/id/thinkers/slowpoke/step"
    printf '{"types":["action","message","observation"]}\n' > "$TMP/id/thinkers/slowpoke/subscriptions.jsonl"
}

append_step() {
    printf '%s\n' "$1" >> "$TMP/id/trajectories/$TRAJ_ID/trajectory.jsonl"
}

start_thinkers() { env_run thinkers start >/dev/null 2>&1; sleep 2; }
stop_thinkers()  { env_run thinkers stop >/dev/null 2>&1; }

record_count() {
    if [[ -f "$TMP/id/record" ]]; then wc -l < "$TMP/id/record" | tr -d ' '; else echo 0; fi
}

# Wait until the record file has at least N lines (or timeout seconds elapse)
wait_for_record() {
    local want="$1" timeout="${2:-15}" i=0
    while [[ "$(record_count)" -lt "$want" && "$i" -lt "$timeout" ]]; do
        sleep 1; i=$((i+1))
    done
}

# Wait until a pending flag matching the glob exists (or timeout seconds
# elapse). Delivery latency from append to dispatch is platform-dependent
# (GNU tail -F polls once a second where inotify is unavailable, e.g. in
# some containers; BSD tail on macOS is near-instant), so the tests wait on
# observable state rather than fixed sleeps. Polls fast: the flag is removed
# again when the queued step fires.
wait_for_pending() {
    local glob="$1" timeout="${2:-5}" i=0
    while ! compgen -G "$TMP/id/run/pending/$glob" >/dev/null && [[ "$i" -lt $((timeout * 10)) ]]; do
        sleep 0.1; i=$((i+1))
    done
}

# ---------------------------------------------------------------------------
# Test 1: a step arriving while the thinker is busy is replayed exactly once,
# with its payload, after the thinker frees up
# ---------------------------------------------------------------------------
test_pending_replay() {
    setup_identity
    start_thinkers

    append_step '{"type":"action","content":"A","source":"test"}'
    wait_for_record 1   # slowpoke picks up A and sleeps
    append_step '{"type":"action","content":"B","source":"test"}'
    wait_for_pending "slowpoke.action.*"

    if compgen -G "$TMP/id/run/pending/slowpoke.action.*" >/dev/null; then
        ok "pending trigger queued while thinker busy"
    else
        bad "pending trigger queued while thinker busy"
    fi

    wait_for_record 2
    if [[ "$(record_count)" -eq 2 ]] && tail -1 "$TMP/id/record" | grep -q '"B"'; then
        ok "busy step replayed once with stored payload"
    else
        bad "busy step replayed once with stored payload" "record: $(cat "$TMP/id/record" 2>/dev/null | tr '\n' ' ')"
    fi

    sleep 1
    if ! compgen -G "$TMP/id/run/pending/slowpoke.action.*" >/dev/null; then
        ok "pending trigger cleared after fire"
    else
        bad "pending trigger cleared after fire"
    fi

    stop_thinkers
}

# ---------------------------------------------------------------------------
# Test 2: several same-type steps while busy queue up and ALL replay, in
# arrival order (FIFO — nothing is silently dropped)
# ---------------------------------------------------------------------------
test_fifo_replay() {
    setup_identity
    start_thinkers

    append_step '{"type":"action","content":"A","source":"test"}'
    wait_for_record 1   # slowpoke picks up A and sleeps
    append_step '{"type":"action","content":"B","source":"test"}'
    sleep 1
    append_step '{"type":"action","content":"C","source":"test"}'

    # A (~3s) then B (~3s) then C (~3s), fired by 1s ticks in between
    wait_for_record 3 25
    local rec
    rec=$(cat "$TMP/id/record" 2>/dev/null)
    if [[ "$(record_count)" -eq 3 ]] \
        && sed -n 1p "$TMP/id/record" | grep -q '"A"' \
        && sed -n 2p "$TMP/id/record" | grep -q '"B"' \
        && sed -n 3p "$TMP/id/record" | grep -q '"C"'; then
        ok "same-type steps all replay in arrival order (A, B, C)"
    else
        bad "same-type steps all replay in arrival order" "record: $(printf '%s' "$rec" | tr '\n' ' ')"
    fi

    if grep -q 'queued=' "$TMP/id/run/logs/dispatcher.log" 2>/dev/null; then
        ok "queueing logged"
    else
        bad "queueing logged"
    fi

    stop_thinkers
}

# ---------------------------------------------------------------------------
# Test 3: pending flags are per-type — an action and a message arriving while
# busy BOTH replay
# ---------------------------------------------------------------------------
test_per_type_flags() {
    setup_identity
    start_thinkers

    append_step '{"type":"action","content":"A","source":"test"}'
    wait_for_record 1   # slowpoke picks up A and sleeps
    append_step '{"type":"action","content":"B","source":"test"}'
    append_step '{"type":"message","content":"M","from":"andy","to":"testid","source":"chat"}'
    wait_for_pending "slowpoke.action.*"
    wait_for_pending "slowpoke.message.*"

    local flags
    flags=$(ls "$TMP/id/run/pending" 2>/dev/null | sed -E 's/^slowpoke\.([^.]+)\..*/\1/' | sort -u | tr '\n' ' ')
    if [[ "$flags" == "action message " ]]; then
        ok "per-type pending queues set (action + message)"
    else
        bad "per-type pending queues set" "flags: $flags"
    fi

    # A (~3s) then B (~3s) then M (~3s), fired by 1s ticks in between
    wait_for_record 3 20
    local rec
    rec=$(cat "$TMP/id/record" 2>/dev/null)
    if [[ "$(record_count)" -eq 3 ]] && printf '%s' "$rec" | grep -q '"B"' && printf '%s' "$rec" | grep -q '"M"'; then
        ok "action and message both replayed"
    else
        bad "action and message both replayed" "record: $(printf '%s' "$rec" | tr '\n' ' ')"
    fi

    stop_thinkers
}

# ---------------------------------------------------------------------------
# Test 3a: self-wake step types (observation, idle, ...) coalesce last-wins
# while busy — only the LATEST replays, so perpetual-loop thinkers never
# build a backlog of stale wakeups (message/action still queue FIFO)
# ---------------------------------------------------------------------------
test_selfwake_coalesce() {
    setup_identity
    start_thinkers

    append_step '{"type":"action","content":"A","source":"test"}'
    wait_for_record 1   # slowpoke picks up A and sleeps
    append_step '{"type":"observation","content":"O1","source":"test"}'
    append_step '{"type":"observation","content":"O2","source":"test"}'
    wait_for_pending "slowpoke.observation.*"
    sleep 0.5   # let O2's supersede land too

    local obs_files
    obs_files=$(compgen -G "$TMP/id/run/pending/slowpoke.observation.*" | wc -l | tr -d ' ')
    if [[ "$obs_files" -eq 1 ]]; then
        ok "self-wake observations coalesce to one pending file"
    else
        bad "self-wake observations coalesce to one pending file" "count: $obs_files"
    fi

    wait_for_record 2
    local rec
    rec=$(cat "$TMP/id/record" 2>/dev/null)
    if [[ "$(record_count)" -eq 2 ]] && printf '%s' "$rec" | grep -q '"O2"' && ! printf '%s' "$rec" | grep -q '"O1"'; then
        ok "only latest self-wake replays (O1 superseded by O2)"
    else
        bad "only latest self-wake replays" "record: $(printf '%s' "$rec" | tr '\n' ' ')"
    fi

    if grep -q 'superseded' "$TMP/id/run/logs/dispatcher.log" 2>/dev/null; then
        ok "supersede logged"
    else
        bad "supersede logged"
    fi

    stop_thinkers
}

# ---------------------------------------------------------------------------
# Test 3b: the per-(thinker,type) queue is capped at 16 — overflow drops the
# oldest entry and logs it, instead of growing without bound
# ---------------------------------------------------------------------------
test_queue_cap() {
    setup_identity
    start_thinkers

    append_step '{"type":"action","content":"A","source":"test"}'
    wait_for_record 1   # slowpoke picks up A and sleeps
    local i
    for i in $(seq 1 18); do
        append_step "{\"type\":\"action\",\"content\":\"Q$i\",\"source\":\"test\"}"
    done
    # Wait for the cap to be hit rather than a fixed sleep: the dispatcher
    # queues one step per feeder line, and on a slow runner (the CI macOS
    # box) 18 arrivals take longer than 2s to land, so a fixed sleep saw a
    # short queue and no drop.
    i=0
    while ! grep -q 'queue full' "$TMP/id/run/logs/dispatcher.log" 2>/dev/null && [[ "$i" -lt 200 ]]; do
        sleep 0.1; i=$((i+1))
    done

    local count
    count=$(compgen -G "$TMP/id/run/pending/slowpoke.action.*" | wc -l | tr -d ' ')
    if [[ "$count" -le 16 ]]; then
        ok "pending queue capped at 16 (got $count)"
    else
        bad "pending queue capped at 16" "count: $count"
    fi

    if grep -q 'queue full' "$TMP/id/run/logs/dispatcher.log" 2>/dev/null; then
        ok "queue-full drop logged"
    else
        bad "queue-full drop logged"
    fi

    stop_thinkers
}

# ---------------------------------------------------------------------------
# Test 4: pending flags are cleared on thinkers stop
# ---------------------------------------------------------------------------
test_cleared_on_stop() {
    setup_identity
    start_thinkers

    append_step '{"type":"action","content":"A","source":"test"}'
    sleep 1
    append_step '{"type":"action","content":"B","source":"test"}'
    sleep 1

    stop_thinkers
    if [[ ! -d "$TMP/id/run/pending" ]]; then
        ok "pending dir removed on stop"
    else
        bad "pending dir removed on stop" "contents: $(ls "$TMP/id/run/pending" 2>/dev/null | tr '\n' ' ')"
    fi
}

# ---------------------------------------------------------------------------
# Test 5: dispatcher singleton — an instance that loses the ownership token
# exits on its next heartbeat instead of double-dispatching forever
# ---------------------------------------------------------------------------
test_singleton_token() {
    setup_identity
    start_thinkers

    local pid
    pid=$(cat "$TMP/id/run/dispatcher.pid" 2>/dev/null)
    if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
        bad "singleton: dispatcher running before token steal"
        stop_thinkers
        return
    fi

    # Simulate a newer instance claiming ownership
    printf 'stolen-token' > "$TMP/id/run/dispatcher.token"

    local i=0
    while kill -0 "$pid" 2>/dev/null && [[ "$i" -lt 5 ]]; do
        sleep 1; i=$((i+1))
    done
    if ! kill -0 "$pid" 2>/dev/null; then
        ok "dispatcher exits after losing ownership token"
    else
        bad "dispatcher exits after losing ownership token" "still alive after 5s"
    fi

    # Its tails must be gone too (no zombie feeders)
    sleep 1
    if ! pgrep -f "tail -n 0 -F $TMP/id/trajectories" >/dev/null 2>&1; then
        ok "orphan tails killed on ownership loss"
    else
        bad "orphan tails killed on ownership loss"
    fi

    # Steps appended now must NOT be dispatched (no live dispatcher)
    append_step '{"type":"action","content":"GHOST","source":"test"}'
    sleep 3
    if ! grep -q '"GHOST"' "$TMP/id/record" 2>/dev/null; then
        ok "no dispatch after ownership loss"
    else
        bad "no dispatch after ownership loss"
    fi

    rm -f "$TMP/id/run/dispatcher.pid"
    stop_thinkers
}

# ---------------------------------------------------------------------------
# Test 8: a killed feeder pipeline is respawned by the housekeeping tick and
# steps appended after the kill still dispatch (the 2026-08-14 outage class)
# ---------------------------------------------------------------------------
test_feeder_respawn() {
    setup_identity
    start_thinkers

    local traj="$TMP/id/trajectories/$TRAJ_ID/trajectory.jsonl"
    if ! pgrep -f "tail -n 0 -F $traj" >/dev/null 2>&1; then
        bad "feeder respawn: feeder running before kill"
        stop_thinkers
        return
    fi

    # Kill the feeder the way the incident did: TERM the tail directly
    pkill -f "tail -n 0 -F $traj" 2>/dev/null
    sleep 3

    if pgrep -f "tail -n 0 -F $traj" >/dev/null 2>&1; then
        ok "feeder respawned after kill"
    else
        bad "feeder respawned after kill" "no tail -F running 3s after kill"
    fi

    if grep -q 'feeder for .* died — respawning' "$TMP/id/run/logs/dispatcher.log" 2>/dev/null; then
        ok "feeder respawn logged"
    else
        bad "feeder respawn logged"
    fi

    # The respawned feeder must actually deliver: append a step and expect
    # a dispatch to the thinker
    append_step '{"type":"action","content":"AFTER_RESPAWN","source":"test"}'
    wait_for_record 1 10
    if grep -q '"AFTER_RESPAWN"' "$TMP/id/record" 2>/dev/null; then
        ok "step dispatched via respawned feeder"
    else
        bad "step dispatched via respawned feeder"
    fi

    stop_thinkers
}

# ---------------------------------------------------------------------------

printf 'test_thinkers_pending: using tmp dir %s\n' "$TMP"
test_pending_replay
test_fifo_replay
test_per_type_flags
test_selfwake_coalesce
test_queue_cap
test_cleared_on_stop
test_singleton_token
test_feeder_respawn

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
