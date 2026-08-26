#!/usr/bin/env bash
# tests/test_responder_idempotency.sh — the responder's "already handled?"
# check, and the window it reads to answer it.
#
# Every inbound message runs this check before a reply is composed, so it sits
# on the latency path. It used to scan the whole root trajectory: measured at
# 0.98s over 40MB and 7.4s over 308MB, against ~0.08s for the tail, and
# design/monolith_run_health.md records real trajectories in that range.
#
# Reading a window is only sound because every record the check looks for (a
# stamped reply, a decision observation, a live claim, a later message to the
# same person) can only be appended AFTER the trigger step. So a window holding
# the trigger holds everything relevant to it; a window that does NOT is the
# case that must fall back to the full scan, or a redelivered old message gets
# answered twice.
#
# The six verdict cases are pinned first because they are the behaviour the
# bounded read must not change.

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$REPO/bin:$PATH"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found — the check needs it, so this proves nothing"; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

ME=ada
THEM=nick
TRIGGER=trig-1
FRESH=$(date -u +%Y-%m-%dT%H:%M:%S)
STALE=2000-01-01T00:00:00

# build <file> <filler-lines> <extra-json-lines...> — a trajectory whose
# trigger sits after <filler-lines> junk steps.
build() {
    local f="$1" filler="$2"; shift 2
    : > "$f"
    local i
    for ((i=0; i<filler; i++)); do
        printf '{"step_id":"pad-%d","type":"shellm-run","from":"%s","content":"pad"}\n' "$i" "$ME" >> "$f"
    done
    printf '{"step_id":"%s","type":"message","from":"%s","to":"%s","content":"hello"}\n' "$TRIGGER" "$THEM" "$ME" >> "$f"
    local line
    for line in "$@"; do printf '%s\n' "$line" >> "$f"; done
}

# verdict <trajectory-file> [tail-lines] — run the check, echo its answer
verdict() {
    local f="$1" tail_lines="${2:-5000}" d
    d="$WORK/run"; rm -rf "$d"; mkdir -p "$d/trajs/aaaaaaaa-t"
    cp "$f" "$d/trajs/aaaaaaaa-t/trajectory.jsonl"
    (
        export TRAJ_DIR="$d/trajs" ROOT_TRAJ_ID=aaaaaaaa TRAJ_ID=aaaaaaaa
        export IDENTITY_NAME="$ME" SHELLM_RAW_TAIL_LINES="$tail_lines"
        export RESPONDER_TRAJ_FILE="$d/trajs/aaaaaaaa-t/trajectory.jsonl"
        # shellcheck disable=SC1090  # the library under test
        source "$REPO/thinkers/_lib/common.sh"
        _responder_already_handled "$TRIGGER" "$THEM" "$(date -u -v-180S +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -d '180 seconds ago' +%Y-%m-%dT%H:%M:%S)"
    )
}

# check <name> <want> <got> — <want> is the exact step id expected (or
# "unhandled" for empty). Any non-empty comparison would let the sentinel
# escape _responder_already_handled and read as handled, which would skip
# every reply while the suite stayed green.
check() {
    local name="$1" want="$2" got="$3"
    if [[ "$got" == *$'\x01'* ]]; then
        bad "$name" "sentinel leaked: '$got'"
    elif [[ "$want" == unhandled && -z "$got" ]] || [[ "$want" != unhandled && "$got" == "$want" ]]; then
        ok "$name"
    else
        bad "$name" "wanted $want, got '${got:-<empty>}'"
    fi
}

# --- the six verdicts, which the bounded read must preserve ---------------
build "$WORK/a.jsonl" 3 "{\"step_id\":\"r1\",\"type\":\"message\",\"from\":\"$ME\",\"to\":\"$THEM\",\"reply_to\":\"$TRIGGER\",\"content\":\"hi\"}"
check "a stamped reply counts as handled"        r1        "$(verdict "$WORK/a.jsonl")"

build "$WORK/b.jsonl" 3 "{\"step_id\":\"o1\",\"type\":\"observation\",\"trigger_step\":\"$TRIGGER\",\"decision\":\"no-reply\"}"
check "a no-reply decision sticks"               o1        "$(verdict "$WORK/b.jsonl")"

build "$WORK/c.jsonl" 3 "{\"step_id\":\"c1\",\"type\":\"reply_claim\",\"trigger_step\":\"$TRIGGER\",\"ts\":\"$FRESH\"}"
check "a fresh claim counts as handled"          c1        "$(verdict "$WORK/c.jsonl")"

build "$WORK/d.jsonl" 3 "{\"step_id\":\"c2\",\"type\":\"reply_claim\",\"trigger_step\":\"$TRIGGER\",\"ts\":\"$STALE\"}"
check "a stale claim does NOT count"             unhandled "$(verdict "$WORK/d.jsonl")"

build "$WORK/e.jsonl" 3 "{\"step_id\":\"m1\",\"type\":\"message\",\"from\":\"$ME\",\"to\":\"$THEM\",\"content\":\"unstamped answer\"}"
check "an unstamped later message counts"        m1        "$(verdict "$WORK/e.jsonl")"

build "$WORK/f.jsonl" 3
check "nothing about the trigger is unhandled"   unhandled "$(verdict "$WORK/f.jsonl")"

# A message from us to them BEFORE the trigger must not count: that is the
# clause the trigger's position in the log decides.
: > "$WORK/g.jsonl"
printf '{"step_id":"old","type":"message","from":"%s","to":"%s","content":"earlier"}\n' "$ME" "$THEM" >> "$WORK/g.jsonl"
printf '{"step_id":"%s","type":"message","from":"%s","to":"%s","content":"hello"}\n' "$TRIGGER" "$THEM" "$ME" >> "$WORK/g.jsonl"
check "an earlier message does not count"        unhandled "$(verdict "$WORK/g.jsonl")"

# --- the window, and the case that must escape it ------------------------
# A `traj` shim records every subcommand, so "did this read the whole file?"
# is answered by what was invoked rather than by timing.
mkdir -p "$WORK/shim"
cat > "$WORK/shim/traj" <<SHIM
#!/usr/bin/env bash
printf '%s\n' "\$1" >> "$WORK/traj-calls"
case "\$1" in
    path) if [ -n "\${RESPONDER_SHIM_NO_PATH:-}" ]; then exit 1
          else printf '%s\n' "\$RESPONDER_TRAJ_FILE"; fi ;;
    cat)  cat -- "\$RESPONDER_TRAJ_FILE" ;;
esac
SHIM
chmod +x "$WORK/shim/traj"

# Trigger inside the window: the answer must come from the tail, with no full
# scan at all.
build "$WORK/h.jsonl" 20 "{\"step_id\":\"r1\",\"type\":\"message\",\"from\":\"$ME\",\"to\":\"$THEM\",\"reply_to\":\"$TRIGGER\",\"content\":\"hi\"}"
: > "$WORK/traj-calls"
got=$(PATH="$WORK/shim:$PATH" verdict "$WORK/h.jsonl" 50)
check "handled is still found inside the window" r1 "$got"
if grep -qx cat "$WORK/traj-calls"; then
    bad "no full scan when the trigger is in the window" "traj cat was called"
else
    ok "no full scan when the trigger is in the window"
fi

# Trigger older than the window: the tail cannot see it, so the check must fall
# back to the full scan rather than reporting an unanswered message.
build "$WORK/i.jsonl" 200 "{\"step_id\":\"r1\",\"type\":\"message\",\"from\":\"$ME\",\"to\":\"$THEM\",\"reply_to\":\"$TRIGGER\",\"content\":\"hi\"}"
# push the trigger and its reply far above the window
for i in $(seq 1 100); do
    printf '{"step_id":"after-%d","type":"thought","from":"%s","content":"pad"}\n' "$i" "$ME" >> "$WORK/i.jsonl"
done
: > "$WORK/traj-calls"
got=$(PATH="$WORK/shim:$PATH" verdict "$WORK/i.jsonl" 50)
check "an old handled trigger is still found"    r1 "$got"
if grep -qx cat "$WORK/traj-calls"; then
    ok "the full scan runs when the trigger is out of the window"
else
    bad "the full scan runs when the trigger is out of the window" "traj cat was never called"
fi

# No resolvable file at all: the check must degrade to exactly ONE full scan,
# not a --require-trigger scan whose sentinel buys a second identical one.
: > "$WORK/traj-calls"
got=$(RESPONDER_SHIM_NO_PATH=1 PATH="$WORK/shim:$PATH" verdict "$WORK/a.jsonl")
check "degraded path still finds the verdict"    r1 "$got"
cats=$(grep -cx cat "$WORK/traj-calls" || true)
if [[ "$cats" == 1 ]]; then
    ok "the degraded path runs exactly one full scan"
else
    bad "the degraded path runs exactly one full scan" "traj cat ran $cats times"
fi

echo
echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
