#!/usr/bin/env bash
# Librarian names are canonical; Headlong spellings still work (same mapping as bin/librarian-env).
if [[ -z "${LIBRARIAN_MEMORY+x}" && -n "${HEADLONG_LIBRARIAN+x}" ]]; then export LIBRARIAN_MEMORY="$HEADLONG_LIBRARIAN"; fi
if [[ -z "${LIBRARIAN_SRC+x}" && -n "${HEADLONG_LIBRARIAN_SRC+x}" ]]; then export LIBRARIAN_SRC="$HEADLONG_LIBRARIAN_SRC"; fi
for _le_hv in $(compgen -A variable HEADLONG_ 2>/dev/null); do
    case "$_le_hv" in HEADLONG_LIBRARIAN|HEADLONG_LIBRARIAN_SRC) continue ;; esac
    _le_lv="LIBRARIAN_${_le_hv#HEADLONG_}"
    if [[ -z "${!_le_lv+x}" ]]; then export "$_le_lv=${!_le_hv}"; fi
done
unset _le_hv _le_lv
if [[ -z "${LIBRARIAN_HOME:-}" && -n "${HOME:-}" && ! -d "$HOME/.librarian" && -d "$HOME/.headlong" ]]; then
    export LIBRARIAN_HOME="$HOME/.headlong"
fi
if [[ -z "${LIBRARIAN_THINKERS_TEMPLATES:-}" && -n "${HOME:-}" ]]; then
    if [[ ! -d "$HOME/.librarian-thinkers" && -d "$HOME/.headlong-thinkers" ]]; then
        export LIBRARIAN_THINKERS_TEMPLATES="$HOME/.headlong-thinkers"
    fi
fi

set -euo pipefail

# deploy/thinkers-failure-alert.sh — OnFailure= hook for
# librarian-thinkers@<identity>.service (fired via librarian-thinkers-alert@).
# With Restart=on-failure on the unit, OnFailure fires only when the start
# limit is exhausted, so this alert means "died repeatedly, auto-restart
# gave up, the mind is STAYING DOWN". Per-death and recovery notices are
# deploy/thinkers-death-alert.sh's job.
#
# Usage: thinkers-failure-alert.sh APP_DIR IDENTITY
#
# Config (APP_DIR/.env): SLACK_BOT_TOKEN (already present for the bridge)
# and LIBRARIAN_ALERT_CHANNEL (legacy SHELLM_ALERT_CHANNEL) — the channel ID to post to (e.g. #shellm-bot's
# ID; the bot must be a member). Missing config degrades to a line in
# /var/tmp/librarian-thinkers-alert.log, never a unit failure: the alert path
# must not add its own failure mode on top of a dead mind.

APP_DIR="${1:?usage: thinkers-failure-alert.sh APP_DIR IDENTITY}"
IDENT="${2:?identity name required}"

FALLBACK_LOG="/var/tmp/librarian-thinkers-alert.log"

# Belt-and-suspenders: the unit's EnvironmentFile= already loads this (as
# root); sourcing here covers manual runs. Never fatal — the alert must not
# add its own failure mode.
if [[ -r "$APP_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$APP_DIR/.env" 2>/dev/null || true
    set +a
fi

# Framework var: LIBRARIAN_ first, legacy SHELLM_ fallback (the box .env still
# carries the old name until it is rewritten).
ALERT_CHANNEL="${LIBRARIAN_ALERT_CHANNEL:-${SHELLM_ALERT_CHANNEL:-}}"
# Posting token: LIBRARIAN_ALERT_TOKEN (seeded by deploy/split-bridge-env.sh;
# ideally a dedicated alert-only app). The bridge's own token is in
# .env.bridge, which this script cannot read inside the thinkers sandbox.
ALERT_TOKEN="${LIBRARIAN_ALERT_TOKEN:-${SLACK_BOT_TOKEN:-}}"

unit="librarian-thinkers@${IDENT}.service"
info=$(systemctl show "$unit" \
    -p Result,ExecMainStatus,ExecMainExitTimestampMonotonic,ExecMainExitTimestamp 2>/dev/null || true)
log_tail=$(tail -n 8 "$APP_DIR/.identities/$IDENT/run/logs/dispatcher.log" 2>/dev/null || true)

text=":rotating_light: *${unit} failed and auto-restart GAVE UP* — the ${IDENT} dispatcher died repeatedly (start limit: 3 unclean deaths in 15 min) and is STAYING DOWN.
\`\`\`
${info}
--- dispatcher.log tail ---
${log_tail}
\`\`\`
Investigate first, then restart: \`sudo librarian-thinkersctl start ${IDENT}\` on the box."

if [[ -z "$ALERT_TOKEN" || -z "$ALERT_CHANNEL" ]]; then
    printf '%s [thinkers-alert] %s failed; Slack not configured (need LIBRARIAN_ALERT_TOKEN + LIBRARIAN_ALERT_CHANNEL in %s/.env)\n' \
        "$(date -u +%FT%TZ)" "$unit" "$APP_DIR" >> "$FALLBACK_LOG"
    exit 0
fi

payload=$(jq -nc --arg ch "$ALERT_CHANNEL" --arg text "$text" \
    '{channel: $ch, text: $text}')
resp=$(curl -sS -m 15 -X POST https://slack.com/api/chat.postMessage \
    -H "Authorization: Bearer $ALERT_TOKEN" \
    -H "Content-Type: application/json; charset=utf-8" \
    --data "$payload" 2>&1 || true)
if ! printf '%s' "$resp" | jq -e '.ok == true' >/dev/null 2>&1; then
    printf '%s [thinkers-alert] Slack post for %s failed: %s\n' \
        "$(date -u +%FT%TZ)" "$unit" "$resp" >> "$FALLBACK_LOG"
fi
