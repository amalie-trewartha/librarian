#!/usr/bin/env bash
# End a kit's run at project day N (default 7) of the kit's clock (trial/started_at,
# trial/scale): start + N*86400/scale real seconds plus any scheduler shift. Stops the scheduler and
# the mind, and waits for the in-flight step to finish. Nothing is moved or
# deleted; the snapshot is taken from the project git history afterwards.
#   nohup setsid trials/v2/end-at.sh --kit ~/kit-a >/dev/null 2>&1 &
set -euo pipefail
RB=$(cd "$(dirname "$(realpath "$0")")" && pwd)
. "$RB/lib.sh"
KIT="" NAME=cns DAYS=7
while [[ $# -gt 0 ]]; do
    case "$1" in
        --kit) KIT="${2:?}"; shift 2 ;;
        --identity) NAME="${2:?}"; shift 2 ;;
        --days) DAYS="${2:?}"; shift 2 ;;
        *) rb_die "unknown argument $1" ;;
    esac
done
[[ -n "$KIT" ]] || rb_die "--kit DIR is required"
ID=$KIT/app/.identities/$NAME
LOG=$KIT/trial/end-at.log
mkdir -p "$KIT/trial"
START=$(rb_kit_start "$KIT") SCALE=$(rb_kit_scale "$KIT")
SHIFT=$(cat "$KIT/trial/scheduler.log.shift" 2>/dev/null || true); [[ "$SHIFT" =~ ^[0-9]+$ ]] || SHIFT=0
END_S=$(( START + $(rb_real_span $(awk -v d="$DAYS" 'BEGIN { printf "%d", d * 86400 }') "$SCALE") + SHIFT ))
END=$(date -u -d "@$END_S" +%FT%TZ)
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }

log "armed: ending $KIT at project day $DAYS = $END real (pid $$, scale $SCALE, shift ${SHIFT}s)"
while (( $(date -u +%s) < END_S )); do
    # A scheduler pause detected later extends the end by the same shift.
    S2=$(cat "$KIT/trial/scheduler.log.shift" 2>/dev/null || true); [[ "$S2" =~ ^[0-9]+$ ]] || S2=0
    if (( S2 != SHIFT )); then SHIFT=$S2; END_S=$(( START + $(rb_real_span $(awk -v d="$DAYS" 'BEGIN { printf "%d", d * 86400 }') "$SCALE") + SHIFT )); log "shift now ${SHIFT}s; end moved to $(date -u -d "@$END_S" +%FT%TZ)"; fi
    sleep 30
done
log "day $DAYS reached"
for p in $(pgrep -f "scheduler.sh --kit $KIT" || true); do kill "$p" && log "stopped scheduler pid $p"; done
TRIAL_ROOT=$(dirname "$KIT") "$RB/launch.sh" "$(basename "$KIT")" stop >> "$LOG" 2>&1 || log "launch.sh stop returned non-zero"
if timeout 900 bash -c "until [ \"\$(ps -eo args | grep '$ID/thinkers/monolith/step' | grep -vc grep)\" = 0 ]; do sleep 5; done"; then
    log "drained: no step running"
else
    log "WARNING: a step was still running after 15 min"
fi
log "last project commit: $(git -C "$ID/workdir/project" log -1 --format='%cI %s' | cut -c1-160)"
log "run ended"
