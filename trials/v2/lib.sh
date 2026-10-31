#!/usr/bin/env bash
# Shared helpers for the trial's host-side scripts (sourced, not run).
# The project clock follows thinkers/_lib/project.sh: started_at (epoch) in
# project-pristine/, PROJECT_TIME_SCALE=k (a positive number, fractions
# allowed; else 1) runs the project clock k times faster than real time:
#   project = start + (real - start) * k      real = start + (project - start) / k
# The scale is read from the identity's .env (where `librarian-project init
# --time-scale` writes it), else project-pristine/time_scale, else 1.

rb_die() { printf '%s: %s\n' "$(basename "$0")" "$*" >&2; exit 1; }

rb_scale() {  # rb_scale <identity dir>
    local id="$1" k=""
    if [[ -f "$id/.env" ]]; then
        k=$(sed -n 's/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}PROJECT_TIME_SCALE=["'\'']\{0,1\}\([^"'\'' ]*\).*/\2/p' "$id/.env" | tail -n 1)
    fi
    if [[ -z "$k" && -f "$id/project-pristine/time_scale" ]]; then
        k=$(tr -d '[:space:]' < "$id/project-pristine/time_scale")
    fi
    [[ "$k" =~ ^[0-9]+([.][0-9]+)?$ ]] && awk -v k="$k" 'BEGIN { exit !(k > 0) }' || k=1
    printf '%s' "$k"
}

rb_started_at() {  # rb_started_at <identity dir>
    local s; s=$(cat "$1/project-pristine/started_at" 2>/dev/null) || s=""
    [[ "$s" =~ ^[0-9]+$ ]] || rb_die "no valid started_at in $1/project-pristine"
    printf '%s' "$s"
}

# Real seconds for a span of project seconds, rounded up.
rb_real_span() { awk -v s="$1" -v k="$2" 'BEGIN { r = s / k; printf "%d", (r == int(r)) ? r : int(r) + 1 }'; }
# Project epoch for a real epoch.
rb_project_now() { awk -v s="$1" -v r="$2" -v k="$3" 'BEGIN { printf "%d", s + (r - s) * k }'; }

# LIBRARIAN_TZ changes the calendar the mind sees; the briefs render in UTC.
rb_tz_warn() {  # rb_tz_warn <identity dir>
    local tz; tz=$(sed -n 's/^[[:space:]]*LIBRARIAN_TZ=["'\'']\{0,1\}\([^"'\'' ]*\).*/\1/p' "$1/.env" 2>/dev/null | tail -n 1)
    if [[ -n "$tz" && "$tz" != UTC ]]; then
        printf 'warning: %s/.env sets LIBRARIAN_TZ=%s; brief dates are rendered in UTC\n' "$1" "$tz" >&2
    fi
    return 0
}

# The kit's own clock: trial/started_at (the run's start, not the current
# project's, since every brief is a fresh project) and trial/scale.
rb_kit_start() { local s; s=$(cat "$1/trial/started_at" 2>/dev/null) || s=""; [[ "$s" =~ ^[0-9]+$ ]] || rb_die "no valid $1/trial/started_at (setup not done?)"; printf '%s' "$s"; }
rb_kit_scale() { local k; k=$(cat "$1/trial/scale" 2>/dev/null | tr -d '[:space:]') || k=""; [[ "$k" =~ ^[0-9]+([.][0-9]+)?$ ]] || k=1; printf '%s' "$k"; }
