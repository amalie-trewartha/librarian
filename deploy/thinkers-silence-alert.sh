#!/usr/bin/env bash
set -euo pipefail

# deploy/thinkers-silence-alert.sh — "the mind has gone quiet" Slack notice
# for headlong-thinkers@<identity>.service. Run every few minutes by
# headlong-thinkers-silence@<identity>.timer.
#
# The death and failure alerts fire when the dispatcher UNIT dies. This one
# covers the other way a mind stops: the unit is up, the dispatcher ticks,
# and nothing happens. 2026-09-14: a wedged monolith step left Audel with no
# trajectory step for six hours while every unit reported active, and
# nobody noticed until someone went looking.
#
# Signal: age of the root trajectory file. Every wake, idle, thought and
# message appends to it, so at rest it is touched at least every
# MONOLITH_BACKOFF_CAP seconds (300 by default). HEADLONG_SILENCE_SECS
# (default 1800) is six times that.
#
#   age >= threshold, no marker → post the alert, write run/silent_since
#   age <  threshold, marker    → post the recovery, remove the marker
#   dispatcher not running      → say nothing (the death alert owns that)
#
# One alert per silence, not one per tick. Same failure-open contract as
# the other alert scripts: missing config degrades to a line in
# /var/tmp/headlong-thinkers-alert.log, never a unit failure.
#
# Usage: thinkers-silence-alert.sh APP_DIR IDENTITY

APP_DIR="${1:?usage: thinkers-silence-alert.sh APP_DIR IDENTITY}"
IDENT="${2:?identity name required}"

FALLBACK_LOG="${HEADLONG_ALERT_FALLBACK_LOG:-/var/tmp/headlong-thinkers-alert.log}"
ID_DIR="$APP_DIR/.identities/$IDENT"
RUN_DIR="$ID_DIR/run"
MARKER="$RUN_DIR/silent_since"
unit="headlong-thinkers@${IDENT}.service"

if [[ -r "$APP_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$APP_DIR/.env" 2>/dev/null || true
    set +a
fi
if [[ -r "$ID_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ID_DIR/.env" 2>/dev/null || true
    set +a
fi

THRESHOLD="${HEADLONG_SILENCE_SECS:-1800}"
ALERT_CHANNEL="${HEADLONG_ALERT_CHANNEL:-${SLACK_ALERT_CHANNEL:-${SHELLM_ALERT_CHANNEL:-}}}"
# Posting token: HEADLONG_ALERT_TOKEN (seeded by deploy/split-bridge-env.sh;
# ideally a dedicated alert-only app). The bridge's own token is in
# .env.bridge, which this script cannot read inside the thinkers sandbox.
ALERT_TOKEN="${HEADLONG_ALERT_TOKEN:-${SLACK_BOT_TOKEN:-}}"

post_slack() {
    local text="$1"
    if [[ -z "$ALERT_TOKEN" || -z "$ALERT_CHANNEL" ]]; then
        printf '%s [thinkers-silence-alert] %s: %s; Slack not configured (need HEADLONG_ALERT_TOKEN + HEADLONG_ALERT_CHANNEL in %s/.env)\n' \
            "$(date -u +%FT%TZ)" "$unit" "$text" "$APP_DIR" >> "$FALLBACK_LOG"
        return 0
    fi
    local payload resp
    payload=$(jq -nc --arg ch "$ALERT_CHANNEL" --arg text "$text" \
        '{channel: $ch, text: $text}')
    resp=$(curl -sS -m 15 -X POST https://slack.com/api/chat.postMessage \
        -H "Authorization: Bearer $ALERT_TOKEN" \
        -H "Content-Type: application/json; charset=utf-8" \
        --data "$payload" 2>&1 || true)
    if ! printf '%s' "$resp" | jq -e '.ok == true' >/dev/null 2>&1; then
        printf '%s [thinkers-silence-alert] Slack post for %s failed: %s\n' \
            "$(date -u +%FT%TZ)" "$unit" "$resp" >> "$FALLBACK_LOG"
    fi
}

# Only judge a mind that is supposed to be awake. A dead or stopped
# dispatcher is the death alert's business, and a stop marker means an
# operator did it on purpose.
dpid=$(cat "$RUN_DIR/dispatcher.pid" 2>/dev/null || true)
if [[ ! "$dpid" =~ ^[0-9]+$ ]] || ! kill -0 "$dpid" 2>/dev/null; then
    exit 0
fi
[[ -f "$RUN_DIR/deliberate_stop" ]] && exit 0

# Root trajectory: info.txt names the id; the directory is either the full
# id or <first segment>-root. Fall back to the newest *-root file.
root_id=$(sed -n 's/^root_trajectory=//p' "$ID_DIR/info.txt" 2>/dev/null | head -n 1 || true)
traj=""
for cand in "$ID_DIR/trajectories/$root_id/trajectory.jsonl" \
            "$ID_DIR/trajectories/${root_id%%-*}-root/trajectory.jsonl"; do
    [[ -n "$root_id" && -f "$cand" ]] && { traj="$cand"; break; }
done
if [[ -z "$traj" ]]; then
    traj=$(ls -t "$ID_DIR"/trajectories/*-root/trajectory.jsonl 2>/dev/null | head -n 1 || true)
fi
[[ -n "$traj" && -f "$traj" ]] || exit 0

now=$(date +%s)
mtime=$(stat -c %Y "$traj" 2>/dev/null || stat -f %m "$traj" 2>/dev/null || echo "$now")
age=$(( now - mtime ))
fmt() { printf '%dh%02dm' $(( $1 / 3600 )) $(( ($1 % 3600) / 60 )); }

if (( age >= THRESHOLD )); then
    [[ -f "$MARKER" ]] && exit 0
    printf '%s' "$mtime" > "$MARKER"
    last_ts=$(date -u -d "@$mtime" +%FT%TZ 2>/dev/null || date -u -r "$mtime" +%FT%TZ 2>/dev/null || echo "$mtime")
    log_tail=$(tail -n 4 "$RUN_DIR/logs/dispatcher.log" 2>/dev/null | cut -c1-200 || true)
    steps=$(cat "$RUN_DIR/step_pids" 2>/dev/null | tr '\n' ' ' || true)
    post_slack ":zzz: *${IDENT} has gone quiet* — no trajectory step for $(fmt "$age") (last at ${last_ts}) while ${unit} is up. The wake loop is stuck, not dead: check for a step that never exited (\`run/step_pids\`: ${steps:-none}) or a dispatcher with nothing to fire.
\`\`\`
${log_tail}
\`\`\`"
else
    [[ -f "$MARKER" ]] || exit 0
    since=$(cat "$MARKER" 2>/dev/null || echo "$now")
    rm -f "$MARKER"
    [[ "$since" =~ ^[0-9]+$ ]] || since=$now
    post_slack ":sunrise: *${IDENT} is back* — quiet for $(fmt $(( mtime - since ))), steps are landing again."
fi
