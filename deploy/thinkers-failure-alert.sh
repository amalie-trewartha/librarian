#!/usr/bin/env bash
set -euo pipefail

# deploy/thinkers-failure-alert.sh — OnFailure= hook for
# shellm-thinkers@<identity>.service (fired via shellm-thinkers-alert@).
# Gathers how the dispatcher died and posts it to Slack so a dead mind is
# noticed in minutes instead of when someone pings the persona.
#
# Usage: thinkers-failure-alert.sh APP_DIR IDENTITY
#
# Config (APP_DIR/.env): SLACK_BOT_TOKEN (already present for the bridge)
# and SHELLM_ALERT_CHANNEL — the channel ID to post to (e.g. #shellm-bot's
# ID; the bot must be a member). Missing config degrades to a line in
# /var/tmp/shellm-thinkers-alert.log, never a unit failure: the alert path
# must not add its own failure mode on top of a dead mind.

APP_DIR="${1:?usage: thinkers-failure-alert.sh APP_DIR IDENTITY}"
IDENT="${2:?identity name required}"

FALLBACK_LOG="/var/tmp/shellm-thinkers-alert.log"

# Belt-and-suspenders: the unit's EnvironmentFile= already loads this (as
# root); sourcing here covers manual runs. Never fatal — the alert must not
# add its own failure mode.
if [[ -r "$APP_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$APP_DIR/.env" 2>/dev/null || true
    set +a
fi

unit="shellm-thinkers@${IDENT}.service"
info=$(systemctl show "$unit" \
    -p Result,ExecMainStatus,ExecMainExitTimestampMonotonic,ExecMainExitTimestamp 2>/dev/null || true)
log_tail=$(tail -n 8 "$APP_DIR/.identities/$IDENT/run/logs/dispatcher.log" 2>/dev/null || true)

text=":rotating_light: *${unit} failed* — the ${IDENT} dispatcher died and nothing restarts it automatically (by design).
\`\`\`
${info}
--- dispatcher.log tail ---
${log_tail}
\`\`\`
Investigate first, then restart: \`sudo shellm-thinkersctl start ${IDENT}\` on the box."

if [[ -z "${SLACK_BOT_TOKEN:-}" || -z "${SHELLM_ALERT_CHANNEL:-}" ]]; then
    printf '%s [thinkers-alert] %s failed; Slack not configured (need SLACK_BOT_TOKEN + SHELLM_ALERT_CHANNEL in %s/.env)\n' \
        "$(date -u +%FT%TZ)" "$unit" "$APP_DIR" >> "$FALLBACK_LOG"
    exit 0
fi

payload=$(jq -nc --arg ch "$SHELLM_ALERT_CHANNEL" --arg text "$text" \
    '{channel: $ch, text: $text}')
resp=$(curl -sS -m 15 -X POST https://slack.com/api/chat.postMessage \
    -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
    -H "Content-Type: application/json; charset=utf-8" \
    --data "$payload" 2>&1 || true)
if ! printf '%s' "$resp" | jq -e '.ok == true' >/dev/null 2>&1; then
    printf '%s [thinkers-alert] Slack post for %s failed: %s\n' \
        "$(date -u +%FT%TZ)" "$unit" "$resp" >> "$FALLBACK_LOG"
fi
