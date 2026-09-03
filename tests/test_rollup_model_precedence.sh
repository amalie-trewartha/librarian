#!/usr/bin/env bash
# test_rollup_model_precedence.sh — which model the life summary rollups use
#
# Usage: tests/test_rollup_model_precedence.sh
#
# Why: the monolith's _life_context passes recap a --map-model of "the rollup
# knob, else the fast class". The flag overrides recap's own RECAP_MAP_MODEL,
# so setting SHELLM_FAST_MODEL for cheap utility calls silently moved the
# rollups, the mind's long-term memory, off the model the operator had pinned
# (2026-09-03). Order is now ROLLUP_MODEL, RECAP_MAP_MODEL, SHELLM_FAST_MODEL,
# and no flag at all when none is set.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

mkdir -p "$WORK/bin"
cat > "$WORK/bin/recap" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*"
STUB
chmod +x "$WORK/bin/recap"
export PATH="$WORK/bin:$PATH"

# Pull just _life_context out of the library; sourcing the whole file needs
# an identity environment.
eval "$(sed -n '/^_life_context()/,/^}/p' "$REPO/thinkers/_lib/common.sh")"

map_model() {  # prints the --map-model argument recap received, or "none"
    local out
    out=$(TRAJ_ID=t ROOT_TRAJ_ID=t _life_context 2>/dev/null)
    if [[ "$out" == *"--map-model "* ]]; then printf '%s' "$out" | sed 's/.*--map-model \([^ ]*\).*/\1/'; else echo none; fi
}

got=$(env -u ROLLUP_MODEL -u RECAP_MAP_MODEL -u SHELLM_FAST_MODEL bash -c "$(declare -f _life_context map_model); map_model")
[[ "$got" == "none" ]] && ok "nothing set: no --map-model flag (recap decides)" || bad "nothing set: no --map-model flag" "got $got"

got=$(env -u ROLLUP_MODEL -u RECAP_MAP_MODEL SHELLM_FAST_MODEL=cheap/flash bash -c "$(declare -f _life_context map_model); map_model")
[[ "$got" == "cheap/flash" ]] && ok "only the fast class set: rollups use it" || bad "only the fast class set: rollups use it" "got $got"

got=$(env -u ROLLUP_MODEL RECAP_MAP_MODEL=anthropic/claude-sonnet-5 SHELLM_FAST_MODEL=cheap/flash bash -c "$(declare -f _life_context map_model); map_model")
[[ "$got" == "anthropic/claude-sonnet-5" ]] && ok "recap's pinned map model beats the fast class" || bad "recap's pinned map model beats the fast class" "got $got"

got=$(ROLLUP_MODEL=explicit/rollup RECAP_MAP_MODEL=anthropic/claude-sonnet-5 SHELLM_FAST_MODEL=cheap/flash bash -c "$(declare -f _life_context map_model); map_model")
[[ "$got" == "explicit/rollup" ]] && ok "ROLLUP_MODEL beats both" || bad "ROLLUP_MODEL beats both" "got $got"

# The monolith asks recap for no verbatim raw tail unless ROLLUP_RAW_TAIL says
# otherwise: its own recent stream already shows the last durable steps.
raw=$(env -u ROLLUP_RAW_TAIL bash -c "$(declare -f _life_context); TRAJ_ID=t _life_context" | sed 's/.*--raw-tail \([^ ]*\).*/\1/')
[[ "$raw" == "0" ]] && ok "raw tail defaults to 0 for the monolith" || bad "raw tail defaults to 0 for the monolith" "got $raw"
raw=$(ROLLUP_RAW_TAIL=40 bash -c "$(declare -f _life_context); TRAJ_ID=t _life_context" | sed 's/.*--raw-tail \([^ ]*\).*/\1/')
[[ "$raw" == "40" ]] && ok "ROLLUP_RAW_TAIL still overrides" || bad "ROLLUP_RAW_TAIL still overrides" "got $raw"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
