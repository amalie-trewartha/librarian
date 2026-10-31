#!/usr/bin/env bash
# Start brief N as a fresh project in a kit (what scheduler.sh calls):
#   apply-brief.sh N --kit DIR [--dry-run]
# A thin wrapper over `launch.sh <kit> brief N`, which stops the mind, archives
# the current project out of the mind's reach, initializes a new project from
# briefs/brief-N.md (keeping the librarian store in the memory arm, nothing in
# the control arm) and starts the mind again. Exit 3 when already started.
set -euo pipefail
RB=$(cd "$(dirname "$(realpath "$0")")" && pwd)
KIT="" DRY=0 N=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --kit) KIT="${2:?--kit needs a dir}"; shift 2 ;;
        --identity|--backup-root) shift 2 ;;
        --dry-run) DRY=1; shift ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        -*) echo "apply-brief.sh: unknown option $1" >&2; exit 1 ;;
        *) N="$1"; shift ;;
    esac
done
[[ "$N" =~ ^[2-5]$ && -n "$KIT" ]] || { echo "usage: apply-brief.sh N (2..5) --kit DIR" >&2; exit 1; }
if (( DRY )); then echo "would run: launch.sh $(basename "$KIT") brief $N"; exit 0; fi
export TRIAL_ROOT; TRIAL_ROOT=$(dirname "$KIT")
exec "$RB/launch.sh" "$(basename "$KIT")" brief "$N"
