#!/usr/bin/env bash
# Build per-scenario vitals matrix: aggregates vitals.csv by scenario×generation.
#
# Joins sessions.csv (run→scenario) with vitals.csv (per-run metrics),
# computes per-scenario means within each generation, emits improve/metrics.csv.
#
# Joins on (label, steps) because run labels are not always unique
# (e.g. g001r10 has two sessions with different step counts).
#
# Usage: build_matrix.sh [gen-dir ...]
#   Default: all improve/generations/gen-* dirs
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$APP_DIR/improve/metrics.csv"

if [[ $# -gt 0 ]]; then
    GENS=("$@")
else
    mapfile -t GENS < <(find "$APP_DIR/improve/generations" -maxdepth 1 -type d -name 'gen-*' | sort)
fi

HEADER='generation,scenario,n_runs,mean_steps,mean_thoughts,mean_actions,mean_observations,mean_dup_rate,mean_follow_through,mean_cmd_fail_rate,mean_mem_files'

# Write header once
printf '%s\n' "$HEADER" > "$OUT"

for gdir in "${GENS[@]}"; do
    [[ -d "$gdir" ]] || continue
    gen="$(basename "$gdir")"
    sessions="$gdir/sessions.csv"
    vitals="$gdir/vitals.csv"
    if [[ ! -f "$sessions" || ! -f "$vitals" ]]; then
        echo "WARN: missing csv in $gdir" >&2
        continue
    fi

    # sessions.csv columns: run,scenario,seconds,model,started,ended,steps,traj_file
    # vitals.csv columns:   label,steps,thoughts,actions,observations,messages,
    #                       dup_thoughts,dup_rate,follow_through,cmd_fail,max_gap,
    #                       mem_files,log_err,spm
    awk -F, -v OFS=, -v GEN="$gen" '
    # Phase 1: load sessions (label, steps) → scenario
    FNR == NR {
        if (FNR == 1) next           # skip header
        label = $1
        scenario = $2
        stp = $7
        map[label SUBSEP stp] = scenario
        next
    }
    # Phase 2: vitals rows
    {
        if (FNR == 1) next           # skip header
        label = $1
        stp = $2
        key = label SUBSEP stp
        if (!(key in map)) next      # no matching session
        s = map[key]
        n[s]++
        _add(s, "steps", $2)
        _add(s, "thoughts", $3)
        _add(s, "actions", $4)
        _add(s, "observations", $5)
        _add(s, "dup_rate", $8)
        _add(s, "follow", $9)
        _add(s, "cmd_fail", $10)
        _add(s, "mem_files", $12)
    }
    END {
        for (s in n) {
            print GEN, s, n[s],
                  _mean(s, "steps"), _mean(s, "thoughts"), _mean(s, "actions"),
                  _mean(s, "observations"), _mean(s, "dup_rate"),
                  _mean(s, "follow"), _mean(s, "cmd_fail"), _mean(s, "mem_files")
        }
    }
    function _add(s, key, val,   cur) {
        if (val == "na" || val == "") return
        cur = sum[s SUBSEP key] + 0
        sum[s SUBSEP key] = cur + val
        cnt[s SUBSEP key]++
    }
    function _mean(s, key) {
        k = s SUBSEP key
        if (!(k in sum) || cnt[k] == 0) return "na"
        return sprintf("%.2f", sum[k] / cnt[k])
    }
    ' "$sessions" "$vitals"
done | sort -t, -k1,1 -k2,2 >> "$OUT"

echo "Wrote $OUT"
