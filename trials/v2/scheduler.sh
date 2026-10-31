#!/usr/bin/env bash
# Brief scheduler: a long-running host loop that starts briefs 2..5 as fresh
# projects at fixed offsets in PROJECT time from the kit's start (trial/started_at), then
# exits after the last one. Pause-safe (a gap between polls longer than the
# poll interval plus PAUSE_SLACK moves every unapplied item later by the gap;
# the shift is kept in <log>.shift, the last poll in <log>.tick); never two
# items in one poll; an item is never due sooner after the previous one than
# the schedule's own gap. Survives restarts: what is applied is read from the
# kit's trial/applied file every loop.
#
#   scheduler.sh --kit DIR [--identity NAME] [--backup-root DIR] [--log FILE]
#                [--poll SECONDS] [--dry-run [--start EPOCH] [--scale K]]
#
# Offsets are project days from the start (the trial's schedule: 1.5, 3.0,
# 4.25, 5.5). With PROJECT_TIME_SCALE=k an item is due at real time
# start + ceil(offset / k).
# Start with:  nohup trials/v2/scheduler.sh --kit ~/kit-a >/dev/null 2>&1 &
set -euo pipefail
RB=$(cd "$(dirname "$(realpath "$0")")" && pwd)
. "$RB/lib.sh"
KIT="" NAME=cns BROOT="" LOG="" POLL=60 DRY=0 OSTART="" OSCALE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --kit) KIT="${2:?--kit needs a dir}"; shift 2 ;;
        --identity) NAME="${2:?--identity needs a name}"; shift 2 ;;
        --backup-root) BROOT="${2:?--backup-root needs a dir}"; shift 2 ;;
        --log) LOG="${2:?--log needs a file}"; shift 2 ;;
        --poll) POLL="${2:?--poll needs seconds}"; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        --start) OSTART="${2:?--start needs an epoch}"; shift 2 ;;
        --scale) OSCALE="${2:?--scale needs a number}"; shift 2 ;;
        -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
        *) rb_die "unknown argument $1" ;;
    esac
done
[[ -n "$KIT" ]] || rb_die "--kit DIR is required"
[[ -n "$BROOT" ]] || BROOT="$KIT-old"
[[ -n "$LOG" ]] || LOG="$KIT/trial/scheduler.log"
[[ "$POLL" =~ ^[1-9][0-9]*$ ]] || rb_die "--poll must be a positive number of seconds"
ID=$KIT/app/.identities/$NAME
APPLIED=$KIT/trial/applied

# item, project seconds after start
SCHEDULE=(
    "2  129600"
    "3  259200"
    "4  367200"
    "5  475200"
)

PAUSE_SLACK=${PAUSE_SLACK:-300}
SHIFT_F="$LOG.shift" TICK_F="$LOG.tick" APPLIED_F="$LOG.applied"
utc() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
num() { local v; v=$(cat "$1" 2>/dev/null || true); [[ "$v" =~ ^[0-9]+$ ]] && printf '%s' "$v" || printf '0'; }
prev_applied() {  # prev_applied <item> -> "offset epoch" of the item before it, if applied by this scheduler
    local prev="" row i o
    for row in "${SCHEDULE[@]}"; do read -r i o <<<"$row"; [[ "$i" == "$1" ]] && break; prev="$i $o"; done
    [[ -n "$prev" ]] || return 0
    read -r i o <<<"$prev"
    local t; t=$(awk -v i="$i" '$1 == i { t = $2 } END { if (t) print t }' "$APPLIED_F" 2>/dev/null)
    [[ -n "$t" ]] && printf '%s %s' "$o" "$t"
    return 0
}
due_at() { printf '%s' $(( $2 + $(rb_real_span "$1" "$3") )); }  # due_at <offset> <start> <scale> -> real epoch
item_due() {  # item_due <item> <offset> -> real epoch: the offset, plus pauses, and at least the schedule's gap after the previous item
    local due p po pt gap
    due=$(( $(due_at "$2" "$START" "$SCALE") + $(num "$SHIFT_F") ))
    p=$(prev_applied "$1")
    if [[ -n "$p" ]]; then
        read -r po pt <<<"$p"
        gap=$(rb_real_span $(( $2 - po )) "$SCALE")
        (( pt + gap > due )) && due=$(( pt + gap ))
    fi
    printf '%s' "$due"
}
span() { local s=$1; printf '%dd %02dh%02dm%02ds' $(( s / 86400 )) $(( s % 86400 / 3600 )) $(( s % 3600 / 60 )) $(( s % 60 )); }
log() { local l; l="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; printf '%s\n' "$l" >> "$LOG"; printf '%s\n' "$l"; }
now_real() {
    if [[ -n "${TRIAL_REAL_NOW_FILE:-}" ]]; then cat "$TRIAL_REAL_NOW_FILE"; else printf '%s' "${TRIAL_REAL_NOW:-$(date +%s)}"; fi
}
applied() { grep -q "^$1 " "$APPLIED" 2>/dev/null; }

if [[ "$DRY" == 1 ]]; then
    START=${OSTART:-$(rb_kit_start "$KIT")}
    SCALE=${OSCALE:-$(rb_kit_scale "$KIT")}
    [[ "$START" =~ ^[0-9]+$ ]] || rb_die "bad --start"
    END=$(cat "$ID/project-pristine/end_at" 2>/dev/null || true)
    NOW=$(now_real)
    printf 'kit %s, identity %s\nstart %s (epoch %s), PROJECT_TIME_SCALE %s%s\n\n' "$KIT" "$NAME" "$(utc "$START")" "$START" "$SCALE" \
        "${END:+, end $(utc "$END") (project)}"
    printf '%-6s %-13s %-22s %-22s %s\n' item offset project-time-UTC real-time-UTC status
    for row in "${SCHEDULE[@]}"; do
        read -r item off <<<"$row"
        due=$(item_due "$item" "$off")
        if applied "$item"; then st=applied; elif (( NOW >= due )); then st="DUE now ($(span $(( NOW - due ))) late)"; else st="in $(span $(( due - NOW )))"; fi
        printf '%-6s %-13s %-22s %-22s %s\n' "$item" "$(span "$off")" "$(utc $(( START + off )))" "$(utc "$due")" "$st"
    done
    exit 0
fi

mkdir -p "$(dirname "$LOG")"
exec 9>"$LOG.lock"
flock -n 9 || rb_die "another scheduler holds $LOG.lock"
log "scheduler start: kit $KIT identity $NAME pid $$"
waited=0
while [[ ! -f "$KIT/trial/started_at" ]]; do
    (( waited )) || log "waiting for $KIT/trial/started_at (setup not done yet)"
    waited=1; sleep "$POLL"
done
last_note=""
while true; do
    START=$(rb_kit_start "$KIT") SCALE=$(rb_kit_scale "$KIT") NOW=$(now_real)
    tick=$(num "$TICK_F")
    if (( tick > 0 && NOW - tick > POLL + PAUSE_SLACK )); then
        gap=$(( NOW - tick - POLL ))
        printf '%s\n' $(( $(num "$SHIFT_F") + gap )) > "$SHIFT_F"
        log "pause detected: $(span $(( NOW - tick ))) since the last poll; items not yet applied move $(span "$gap") later (total shift $(span "$(num "$SHIFT_F")"))"
    fi
    printf '%s\n' "$NOW" > "$TICK_F"
    note="clock: start $(utc "$START"), scale $SCALE"
    [[ "$note" == "$last_note" ]] || { log "$note"; last_note=$note; }
    next="" wait_s=0 failed=0
    for row in "${SCHEDULE[@]}"; do
        read -r item off <<<"$row"
        applied "$item" && continue
        due=$(item_due "$item" "$off")
        if (( NOW < due )); then next=$item wait_s=$(( due - NOW )); break; fi
        late=$(( NOW - due ))
        log "applying $item (due $(utc "$due"), project +$(span "$off"); late by $(span "$late"))"
        rc=0
        out=$("$RB/apply-brief.sh" "$item" --kit "$KIT" 2>&1) || rc=$?
        while IFS= read -r l; do log "  $l"; done <<<"$out"
        if (( rc == 0 || rc == 3 )); then
            log "applied $item (rc $rc)"
            printf '%s %s\n' "$item" "$(now_real)" >> "$APPLIED_F"
            now_real > "$TICK_F"; echo >> "$TICK_F"
            next=pending
            break
        else
            log "FAILED $item (rc $rc); retrying in ${POLL}s, later items wait"
            failed=1; break
        fi
    done
    if [[ -z "$next" && "$failed" == 0 ]]; then
        log "all items applied; scheduler exits"
        exit 0
    fi
    if [[ "$next" == pending ]]; then next="" wait_s=0; sleep 1; continue; fi
    if [[ -n "$next" && "$failed" == 0 && "$wait_s" -gt 0 ]]; then
        [[ "${logged_next:-}" == "$next" ]] || { log "next: $next at $(utc $(( NOW + wait_s ))) (in $(span "$wait_s"))"; logged_next=$next; }
    fi
    s=$POLL; (( failed == 0 && wait_s > 0 && wait_s < s )) && s=$wait_s
    sleep "$s"
done
