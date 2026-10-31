#!/usr/bin/env bash
# Disk and liveness guard for the trial VM. Every POLL seconds (default 300):
# logs root-disk and scratch use; at WARN_PCT (85) of the root disk it prunes
# exited containers and dangling images; at STOP_PCT (95) it stops both arms'
# minds (launch.sh stop) rather than let them corrupt their files; and it
# notes any kit whose last model call is older than STALL_MIN minutes (90)
# while the mind is running. Nothing is deleted from a kit.
#   nohup trials/v2/guard.sh >/dev/null 2>&1 &
set -uo pipefail
RB=$(cd "$(dirname "$(realpath "$0")")" && pwd)
ROOT="${TRIAL_ROOT:-$HOME}"
LOG="$ROOT/trial-guard.log"
POLL=${POLL:-300} WARN_PCT=${WARN_PCT:-85} STOP_PCT=${STOP_PCT:-95} STALL_MIN=${STALL_MIN:-90}
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }
log "guard start pid $$ (warn ${WARN_PCT}%, stop ${STOP_PCT}%, stall ${STALL_MIN}m)"
while true; do
    use=$(df --output=pcent / | tail -1 | tr -dc '0-9')
    line="root ${use}%"
    for k in kit-a kit-b; do
        [[ -d "$ROOT/$k/scratch" ]] && line+=" $k/scratch $(df --output=pcent "$ROOT/$k/scratch" 2>/dev/null | tail -1 | tr -dc '0-9')%"
        led="$ROOT/$k/app/.identities/cns/usage/llm.jsonl"
        if [[ -f "$led" ]] && pgrep -f "$ROOT/$k/app/bin/thinkers start" >/dev/null; then
            last=$(tail -1 "$led" | sed -n 's/.*"ts":"\([^"]*\)".*/\1/p')
            if [[ -n "$last" ]]; then
                age=$(( ( $(date +%s) - $(date -d "$last" +%s) ) / 60 ))
                (( age > STALL_MIN )) && line+=" $k: NO MODEL CALL FOR ${age}m"
            fi
        fi
    done
    log "$line"
    if (( use >= STOP_PCT )); then
        log "root disk at ${use}%: stopping both arms"
        for k in kit-a kit-b; do [[ -d "$ROOT/$k/app" ]] && "$RB/launch.sh" "$k" stop >> "$LOG" 2>&1; done
    elif (( use >= WARN_PCT )); then
        log "root disk at ${use}%: pruning exited containers and dangling images"
        docker container prune -f >> "$LOG" 2>&1; docker image prune -f >> "$LOG" 2>&1
    fi
    sleep "$POLL"
done
