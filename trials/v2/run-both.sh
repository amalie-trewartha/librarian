#!/usr/bin/env bash
# Set up and start both arms, their schedulers, their day-7 stops and the
# guard, in one go. TIME_SCALE and SCRATCH_GB pass through to launch.sh
# (smoke trial: TIME_SCALE=84 SCRATCH_GB=8). Refuses when a kit exists.
#   trials/v2/run-both.sh            # the real run (TIME_SCALE 2.3333)
#   TIME_SCALE=84 SCRATCH_GB=8 trials/v2/run-both.sh
set -euo pipefail
RB=$(cd "$(dirname "$(realpath "$0")")" && pwd)
ROOT="${TRIAL_ROOT:-$HOME}"
for k in kit-a kit-b; do [[ ! -d "$ROOT/$k" ]] || { echo "run-both.sh: $ROOT/$k exists" >&2; exit 1; }; done
for k in kit-a kit-b; do
    "$RB/launch.sh" "$k" check
    "$RB/launch.sh" "$k" setup
done
for k in kit-a kit-b; do
    "$RB/launch.sh" "$k" start
    nohup setsid "$RB/scheduler.sh" --kit "$ROOT/$k" >> "$ROOT/$k/trial/scheduler.out" 2>&1 < /dev/null &
    nohup setsid "$RB/end-at.sh" --kit "$ROOT/$k" >> "$ROOT/$k/trial/end-at.out" 2>&1 < /dev/null &
done
nohup setsid "$RB/guard.sh" >> "$ROOT/trial-guard.out" 2>&1 < /dev/null &
sleep 3
for k in kit-a kit-b; do
    echo "== $k"; cat "$ROOT/$k/trial/ARM" "$ROOT/$k/trial/scale"
    "$RB/scheduler.sh" --kit "$ROOT/$k" --dry-run | tail -6
done
echo "started $(date -u +%FT%TZ)"
