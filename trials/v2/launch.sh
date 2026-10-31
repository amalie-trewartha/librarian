#!/usr/bin/env bash
# Trial v2: two arms of the same five-brief program, side by side on one VM.
# Every brief is a fresh project in both arms (a new project/ directory from
# the brief as its spec; the previous project is archived out of the mind's
# reach). What carries across briefs:
#   kit-a  memory arm   the librarian store (facts, skills, decisions, lessons,
#                       the shared-values ledger) and nothing else
#   kit-b  control arm  nothing (librarian-project init --no-memory each time):
#                       five independent projects by, in effect, fresh agents
# Both: brief 1 at setup, briefs 2-5 from scheduler.sh at project days 1.5, 3,
# 4.25 and 5.5 from the kit's start; PROJECT_TIME_SCALE from TIME_SCALE
# (default 2.3333: a 7-day project week in 72 real hours; 84 for a 2-hour
# smoke trial); a stop at project day 7 (end-at.sh); Opus 5.5 main / Haiku 4.5
# delegate on Bedrock; $200 per rolling real 24 h, PROJECT_BUDGET_HOLD 0.8,
# pacing off. Each kit's container /tmp is a loop-mounted image of SCRATCH_GB
# (default 24) so a runaway scratch cannot fill the VM disk.
#
# Model access is Amazon Bedrock. Put the key in trials/v2/bedrock.env (gitignored).
#
#   launch.sh <kit-a|kit-b> check         offline preflight
#   launch.sh <kit> ping                  one tiny call per model to check the key
#   launch.sh <kit> setup                 snapshot the checkout, scratch image, identity, brief 1
#   launch.sh <kit> start | stop          the mind
#   launch.sh <kit> brief N               stop, start brief N as a fresh project, start (scheduler.sh calls this)
#   launch.sh <kit> status                project status, spend, scratch use
#   launch.sh <kit> answer Qn "text"      answer an open question
#   launch.sh <kit> env                   print the env exports, for poking around by hand
set -euo pipefail

RB=$(cd "$(dirname "$(realpath "$0")")" && pwd)
SRC=$(cd "$RB/../.." && pwd)
KITNAME="${1:-}"; CMD="${2:-}"; shift 2 2>/dev/null || true
case "$KITNAME" in
    kit-a) ARM=memory ;;
    kit-b) ARM=control ;;
    *) sed -n '2,27p' "$0"; exit 1 ;;
esac
KIT="${TRIAL_ROOT:-$HOME}/$KITNAME"
APP="$KIT/app"
NAME=cns
DAYS=14 TIME_SCALE=${TIME_SCALE:-2.3333} DAILY_USD=${DAILY_USD:-200} TOTAL_USD=0 SCRATCH_GB=${SCRATCH_GB:-24}
export HOME="$KIT/home"
export LIBRARIAN_HOME="$HOME/.librarian"
export LIBRARIAN_APP_DIR="$APP"
export PATH="$APP/bin:$APP/tools:$PATH"
export SHELLM_SCRATCH_DIR="$KIT/scratch"
ID="$APP/.identities/$NAME"
KEYS="$RB/bedrock.env"

die() { printf 'launch.sh: %s\n' "$*" >&2; exit 1; }
log() { mkdir -p "$KIT/trial"; printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$KIT/trial/launch.log" >&2; }
keyval() { ( set -a; . "$KEYS" >/dev/null 2>&1; set +a; printf '%s' "${!1:-}" ); }
need_key() {
    [[ -f "$KEYS" ]] || die "missing $KEYS (copy bedrock.env.example and fill in the key)"
    local t; t=$(keyval AWS_BEARER_TOKEN_BEDROCK)
    [[ -n "$t" && "$t" != *PASTE* ]] || die "put the Bedrock API key in $KEYS (AWS_BEARER_TOKEN_BEDROCK=...)"
    [[ -n "$(keyval AWS_REGION)" ]] || die "$KEYS has no AWS_REGION"
}
scratch_mount() {
    local img="$KIT/scratch.img" dir="$KIT/scratch"
    mkdir -p "$dir"
    if ! mountpoint -q "$dir"; then
        if [[ ! -f "$img" ]]; then
            truncate -s "${SCRATCH_GB}G" "$img"
            mkfs.ext4 -q -F "$img"
        fi
        sudo mount -o loop "$img" "$dir"
        sudo chown "$(id -u):$(id -g)" "$dir"
        chmod 1777 "$dir"
    fi
}
# Start brief N as a fresh project: the previous project directory leaves the
# mind's mounts (archived under <kit>/archive), project-pristine is rebuilt
# from the brief, and the store (memory arm) is kept by init.
init_brief() {
    local n="$1" spec="$RB/briefs/brief-$1.md" ts; ts=$(date -u +%Y%m%dT%H%M%SZ)
    [[ -f "$spec" ]] || die "no $spec"
    local nomem=(); [[ "$ARM" == control ]] && nomem=(--no-memory)
    local force=(); [[ -e "$ID/workdir/project/charter.md" ]] && force=(--force)
    (cd "$APP" && librarian-project init "$NAME" --spec "$spec" --preferences "$RB/preferences.md" \
        ${nomem[@]+"${nomem[@]}"} ${force[@]+"${force[@]}"} --days "$DAYS" --time-scale "$TIME_SCALE" \
        --daily-tokens 0 --daily-usd "$DAILY_USD" --total-usd "$TOTAL_USD")
    printf 'PROJECT_PACE=0\nPROJECT_BUDGET_HOLD=0.8\nSHELLM_SCRATCH_DIR=%s\n' "$KIT/scratch" >> "$ID/.env"
    mkdir -p "$KIT/archive"
    local old
    for old in "$ID"/workdir/project.old-*; do
        [[ -d "$old" ]] || continue
        mv "$old" "$KIT/archive/brief$(( n - 1 ))-$(basename "$old" | sed 's/^project\.old-//')"
    done
    rm -f "$ID/run/project_rest_checked" "$ID/run/project_idle_streak" 2>/dev/null || true
    printf '%s %s\n' "$n" "$(date +%s)" >> "$KIT/trial/applied"
    log "brief $n started as a fresh project ($ARM arm; project id $(cat "$ID/project-pristine/project_id"))"
}

case "$CMD" in
check)
    for c in git jq rsync python3 docker curl awk flock mkfs.ext4; do command -v "$c" >/dev/null || die "missing $c"; done
    docker info >/dev/null 2>&1 || die "docker is not usable by $USER"
    LIBRARIAN_SRC="$SRC/librarian/src" "$SRC/tools/librarian" --help >/dev/null || die "librarian does not run"
    sudo -n true 2>/dev/null || die "sudo without a password is needed for the scratch mount"
    echo "tools, docker, librarian, sudo: ok"
    need_key && echo "key file: filled in"
    ;;
ping)
    need_key
    region=$(keyval AWS_REGION) coldeyes=$(keyval COLDEYES_MODEL)
    for m in us.anthropic.claude-opus-5-5 us.anthropic.claude-haiku-4-5-20251001-v1:0 ${coldeyes:+"$coldeyes"}; do
        printf '%s: ' "$m"
        AWS_REGION="$region" AWS_BEARER_TOKEN_BEDROCK=$(keyval AWS_BEARER_TOKEN_BEDROCK) \
            LLM_USAGE_LEDGER=/dev/null LLM_MAX_RETRIES=0 "$SRC/bin/llm" --no-stream -t 16 -m "$m" \
            "Reply with the single word: ready" 2>&1 | tail -n 1 || true
    done ;;
setup)
    need_key
    [[ ! -d "$APP" ]] || die "$APP exists; remove $KIT to set up again"
    mkdir -p "$HOME" "$LIBRARIAN_HOME" "$KIT/trial"
    printf '%s\n' "$ARM" > "$KIT/trial/ARM"
    printf '%s\n' "$TIME_SCALE" > "$KIT/trial/scale"
    scratch_mount
    rsync -a --exclude .git --exclude .vagrant --exclude .identities --exclude node_modules \
        --exclude Vagrantfile --exclude .venv --exclude __pycache__ --exclude .pytest_cache \
        --exclude 'trials/v2/bedrock.env' "$SRC/" "$APP/"
    coldeyes=$(keyval COLDEYES_MODEL)
    "$APP/docs/librarian-bedrock-env" "$KEYS" --app "$APP" ${coldeyes:+--coldeyes "$coldeyes"}
    cd "$APP"
    IDENTITY_DIR="$APP/.identities" identity new "$NAME" >/dev/null
    mkdir -p "$ID/chat"; printf 'default_send_from=%s\n' "$NAME" > "$ID/chat/.chatrc"
    init_brief 1
    cp "$ID/project-pristine/started_at" "$KIT/trial/started_at"
    [[ "$ARM" == memory ]] && librarian-project librarian "$NAME" stats >/dev/null
    echo "setup done: $ID ($ARM arm, scale $TIME_SCALE, scratch $KIT/scratch)"
    echo "next: $0 $KITNAME start; nohup $RB/scheduler.sh --kit $KIT >/dev/null 2>&1 &; nohup setsid $RB/end-at.sh --kit $KIT >/dev/null 2>&1 &"
    ;;
brief)
    n="${1:-}"; [[ "$n" =~ ^[2-5]$ ]] || die "usage: launch.sh <kit> brief N (2..5)"
    [[ -f "$KIT/trial/started_at" ]] || die "no $KIT/trial/started_at: setup first"
    grep -q "^$n " "$KIT/trial/applied" 2>/dev/null && { echo "brief $n already started"; exit 3; }
    grep -q "^$(( n - 1 )) " "$KIT/trial/applied" 2>/dev/null || die "brief $(( n - 1 )) has not started yet"
    log "brief $n: stopping the mind"
    (cd "$APP" && persona "$NAME" stop) >> "$KIT/trial/launch.log" 2>&1 || true
    # Wait for the in-flight step to finish, so the old project's last commit lands.
    timeout 900 bash -c "until [ \"\$(ps -eo args | grep '$ID/thinkers/monolith/step' | grep -vc grep)\" = 0 ]; do sleep 5; done" \
        && log "drained" || log "WARNING: a step was still running after 15 min; continuing"
    init_brief "$n"
    scratch_mount
    (cd "$APP" && persona "$NAME" start) >> "$KIT/trial/launch.log" 2>&1
    log "brief $n: the mind is running"
    ;;
start)  scratch_mount; cd "$APP" && persona "$NAME" start ;;
stop)   cd "$APP" && persona "$NAME" stop ;;
status) cd "$APP" && librarian-project status "$NAME"; echo "scratch: $(df -h "$KIT/scratch" 2>/dev/null | tail -1)"; echo "briefs started: $(tr '\n' ' ' < "$KIT/trial/applied" 2>/dev/null)" ;;
answer) [[ $# -eq 2 ]] || die 'usage: launch.sh <kit> answer <Qn> "<answer>"'
        cd "$APP" && librarian-project answer "$NAME" "$1" "$2" ;;
env)    printf 'export HOME=%q LIBRARIAN_HOME=%q LIBRARIAN_APP_DIR=%q PATH=%q SHELLM_SCRATCH_DIR=%q\n' "$HOME" "$LIBRARIAN_HOME" "$APP" "$PATH" "$SHELLM_SCRATCH_DIR" ;;
*) sed -n '2,27p' "$0"; exit 1 ;;
esac
