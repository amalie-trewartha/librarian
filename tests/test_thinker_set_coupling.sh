#!/usr/bin/env bash
# tests/test_thinker_set_coupling.sh — headlong-init and persona must start the
# same thinkers.
#
# Usage: tests/test_thinker_set_coupling.sh
#
# Why: this is a coupling that fails SILENTLY. headlong-init brings a mind up
# with `thinkers start monolith responder`; `<name> start` in tools/persona
# brings it back after `<name> stop`. When the two lists drift, nothing errors
# — the dispatcher starts, status.json says "ok", the dash says "ok", and the
# agent visibly thinks. Only the dropped thinker's job stops happening. With
# the responder missing, messages from the human are no longer answered by the
# thinker built to answer them promptly; they wait on the monolith's reasoning
# loop instead, turning a few seconds of latency into minutes, and the pause/
# resume that caused it is long forgotten by then.
#
# Derived from the shipped scripts, so adding a thinker to one starter and not
# the other fails here rather than in someone's session.

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

# The thinker names on a `thinkers start ...` line, sorted, one per line.
# Comments are stripped first so prose mentioning the command cannot match.
# No \b: it is a GNU extension BSD grep is not guaranteed to honor.
start_set() {
    sed 's/#.*//' "$1" \
        | grep -oE '(^|[^[:alnum:]_-])thinkers[[:space:]]+start[[:space:]]+[a-z0-9_ -]+' \
        | sed -E 's/.*thinkers[[:space:]]+start[[:space:]]+//' \
        | tr ' ' '\n' | sed '/^$/d' | sort -u
}

init_set=$(start_set "$REPO/tools/headlong-init")
persona_set=$(start_set "$REPO/tools/persona")
bootstrap_set=$(start_set "$REPO/deploy/bootstrap-slack-identity.sh")

if [[ -z "$init_set" ]]; then
    bad "found a 'thinkers start' line in tools/headlong-init"
elif [[ -z "$persona_set" ]]; then
    bad "found a 'thinkers start' line in tools/persona"
else
    ok "both starters invoke 'thinkers start'"
    if [[ "$init_set" == "$persona_set" ]]; then
        ok "they start the same thinkers: $(echo "$init_set" | tr '\n' ' ')"
    else
        bad "they start the same thinkers" \
            "headlong-init=[$(echo "$init_set" | tr '\n' ' ')] persona=[$(echo "$persona_set" | tr '\n' ' ')]"
    fi
    # The responder is the human-facing one; name it explicitly so that
    # dropping it from BOTH starters still fails here.
    if echo "$persona_set" | grep -qx responder; then
        ok "persona starts the responder (the human-facing thinker)"
    else
        bad "persona starts the responder (the human-facing thinker)" \
            "resume would leave messages waiting on the monolith"
    fi
fi

# The deploy bootstrap's legacy fallback hardcodes the same list; it must
# not drift either (an empty set is fine — it would mean the fallback now
# enumerates the roster dynamically like deploy/thinkers-service.sh).
if [[ -n "$bootstrap_set" && "$bootstrap_set" != "$init_set" ]]; then
    bad "bootstrap-slack-identity fallback starts the same thinkers" \
        "bootstrap=[$(echo "$bootstrap_set" | tr '\n' ' ')] headlong-init=[$(echo "$init_set" | tr '\n' ' ')]"
else
    ok "bootstrap-slack-identity fallback matches headlong-init (or starts none)"
fi

# Every named thinker must actually ship, or the starter silently no-ops.
while IFS= read -r t; do
    [[ -n "$t" ]] || continue
    if [[ -e "$REPO/thinkers/$t/step" ]]; then
        ok "thinker '$t' ships a step script"
    else
        bad "thinker '$t' ships a step script" "thinkers/$t/step is missing"
    fi
done <<< "$init_set"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
