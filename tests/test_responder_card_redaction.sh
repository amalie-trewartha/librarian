#!/usr/bin/env bash
# tests/test_responder_card_redaction.sh — card digits never enter the log
# through the responder's own writes (2026-09-21 card-in-log incident).
#
# Usage: tests/test_responder_card_redaction.sh
#
# The inbound message step keeps its raw content (it is the record). What
# this test pins: every string the responder itself appends or sends — the
# reply, the deferral `action` step, the observations, and person notes —
# has card-shaped and cvv/expiry-shaped digits replaced with
# [card redacted]/[redacted]. Dates, times, party sizes, confirmation
# numbers, phone numbers, and zips pass through untouched. Stubbed llm and
# chat; no LLM calls, no docker.

set -uo pipefail
unset IDENTITY_DIR IDENTITY_NAME MEM_DIR TRAJ_DIR TRAJ_ID ROOT_TRAJ_ID THINK_CONTEXT_TAIL 2>/dev/null

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
RESPONDER="$REPO/thinkers/responder/step"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found"; exit 1; }

WORK=$(mktemp -d)
trap 'cd /; rm -rf "$WORK"' EXIT

ME=testid
THEM=andy
ID="$WORK/ident"
TRAJ_ID="cafe0000-0000-0000-0000-0000000000cd"
mkdir -p "$ID/memories" "$ID/trajectories/$TRAJ_ID" "$ID/run"
printf 'name=%s\ncreated=test\nroot_trajectory=%s\n' "$ME" "$TRAJ_ID" > "$ID/info.txt"
TRAJ="$ID/trajectories/$TRAJ_ID/trajectory.jsonl"
printf 'test-token\n' > "$ID/run/dispatcher.token"

mkdir -p "$WORK/stub"
cat > "$WORK/stub/llm" <<'STUB'
#!/usr/bin/env bash
# Serves $STUB_REPLY_FILE for the reply call. For the person-notes call
# (recognizable by its -s system prompt containing 'notes'), serves
# $STUB_NOTES_FILE so notes can carry digits too.
for _a in "$@"; do :; done
_prev=""
for _a in "$@"; do [[ "$_prev" == "-s" ]] && _sys="$_a"; _prev="$_a"; done
if printf '%s' "${_sys:-}" | grep -q 'private notes about one person'; then cat "$STUB_NOTES_FILE"; else cat "$STUB_REPLY_FILE"; fi
STUB
cat > "$WORK/stub/chat" <<'STUB'
#!/usr/bin/env bash
# Records every invocation, and the reply body (stdin when piped).
printf 'CHATCALL: %s\n' "$*" >> "$STUB_CALLS_FILE"
if [[ "$1" == history ]]; then printf '[]\n'; else cat > "${STUB_SENT_FILE:-/dev/null}"; fi
exit 0
STUB
chmod +x "$WORK/stub/llm" "$WORK/stub/chat"
export STUB_REPLY_FILE="$WORK/reply" STUB_NOTES_FILE="$WORK/notes" STUB_SENT_FILE="$WORK/sent" STUB_CALLS_FILE="$WORK/calls"

ENV_COMMON=(PATH="$WORK/stub:$REPO/bin:$REPO/tools:$PATH" IDENTITY_DIR="$ID" IDENTITY_NAME="$ME"
    MEM_DIR="$ID/memories" TRAJ_DIR="$ID/trajectories" TRAJ_ID="$TRAJ_ID" HOME="$WORK/home"
    SHELLM_MODEL=stub-model THINK_CONTEXT_TAIL=30 RESPONDER_PERSON_NOTES=0 MONOLITH_TIERED_MEMORY=0)
run_responder() { : > "$STUB_SENT_FILE"; printf '%s' "$1" | env "${ENV_COMMON[@]}" "$RESPONDER" >> "$WORK/step.log" 2>&1; }
now() { date -u +%Y-%m-%dT%H:%M:%S.000Z; }

hdr() { printf '{"step_id":"hdr","type":"trajectory","ts":"%s"}\n' "$(now)" >> "$TRAJ"; }

# --- 1. reply: the sent text carries no card digits ------------------------
: > "$TRAJ"; hdr
printf '{"step_id":"trig-1","type":"message","from":"%s","to":"%s","content":"use 4242 4242 4242 4242 exp 12/28 cvv 411 for Bestia","ts":"%s","source":"chat"}\n' "$THEM" "$ME" "$(now)" >> "$TRAJ"
printf 'Got it, booking with 4242 4242 4242 4242 now.\n' > "$STUB_REPLY_FILE"
run_responder "$(grep -F '"step_id":"trig-1"' "$TRAJ")"
if grep -q '4242' "$STUB_SENT_FILE"; then bad "reply: card digits redacted in sent text" "$(cat "$STUB_SENT_FILE")"; else ok "reply: card digits redacted in sent text"; fi
_sent1=$(cat "$STUB_SENT_FILE")
if printf '%s' "$_sent1" | grep -q 'book' && printf '%s' "$_sent1" | grep -q 'redacted'; then ok "reply: text survives (not blanked)"; else bad "reply: text survives (not blanked)" "$_sent1"; fi

# --- 2. observations: no digit restatement from the trigger ----------------
: > "$TRAJ"; hdr
printf '{"step_id":"trig-2","type":"message","from":"%s","to":"%s","content":"card is 378282246310005, amex","ts":"%s","source":"chat"}\n' "$THEM" "$ME" "$(now)" >> "$TRAJ"
printf 'NO_REPLY\n' > "$STUB_REPLY_FILE"
run_responder "$(grep -F '"step_id":"trig-2"' "$TRAJ")"
if grep -q '378282246310005' "$TRAJ" && ! jq -r 'select(.type=="observation" or .type=="action" or .type=="reply_claim") | .content // empty' "$TRAJ" | grep -q '378282246310005'; then ok "observations: no amex restatement"; else bad "observations: no amex restatement" "$(jq -c 'select(.type=="observation")' "$TRAJ" | head -3)"; fi

# --- 3. deferral: action.request and the holding reply stay clean ----------
: > "$TRAJ"; hdr
printf '{"step_id":"trig-3","type":"message","from":"%s","to":"%s","content":"book Bestia with 4111-1111-1111-1111 cvv 777","ts":"%s","source":"chat"}\n' "$THEM" "$ME" "$(now)" >> "$TRAJ"
printf 'DEFER: book Bestia with card 4111-1111-1111-1111 exp 04/27 cvv 777 for Nov 7\nLet me get that booked.\n' > "$STUB_REPLY_FILE"
run_responder "$(grep -F '"step_id":"trig-3"' "$TRAJ")"
action_req=$(jq -r 'select(.type=="action") | .request // empty' "$TRAJ")
if printf '%s' "$action_req" | grep -q '4111'; then bad "deferral: action.request redacted" "$action_req"; else ok "deferral: action.request redacted"; fi
if printf '%s' "$action_req" | grep -q 'Bestia'; then ok "deferral: request text survives (work is readable)"; else bad "deferral: request text survives (work is readable)" "$action_req"; fi
if grep -q '777' "$TRAJ" && ! jq -r 'select(.type=="observation") | .content // empty' "$TRAJ" | grep -q '777'; then ok "deferral: cvv redacted in observations"; else bad "deferral: cvv redacted in observations" "$(jq -c 'select(.type=="observation")' "$TRAJ" | head -2)"; fi
# the message step itself keeps its raw content (the record)
if jq -r 'select(.type=="message" and .step_id=="trig-3") | .content' "$TRAJ" | grep -q '4111-1111-1111-1111'; then ok "record: inbound message step keeps raw content"; else bad "record: inbound message step keeps raw content"; fi

# --- 4. benign numbers pass through ---------------------------------------
: > "$TRAJ"; hdr
printf '{"step_id":"trig-4","type":"message","from":"%s","to":"%s","content":"Bestia Nov 7 2026 6pm party of 2 conf 2110728612 zip 94110","ts":"%s","source":"chat"}\n' "$THEM" "$ME" "$(now)" >> "$TRAJ"
printf 'Booked Bestia Nov 7 2026 6pm party of 2 conf 2110728612 zip 94110, reply 2110728612.\n' > "$STUB_REPLY_FILE"
run_responder "$(grep -F '"step_id":"trig-4"' "$TRAJ")"
sent=$(cat "$STUB_SENT_FILE")
if printf '%s' "$sent" | grep -q '2110728612' && printf '%s' "$sent" | grep -q '94110'; then ok "benign: confirmation number and zip survive"; else bad "benign: confirmation number and zip survive" "$sent"; fi

# --- 5. person notes inherit the redaction ---------------------------------
: > "$TRAJ"; hdr
printf '{"step_id":"trig-5","type":"message","from":"%s","to":"%s","content":"my card 5555 5555 5555 5555 for bookings","ts":"%s","source":"chat"}\n' "$THEM" "$ME" "$(now)" >> "$TRAJ"
printf 'notes: andy books tables, card 5555 5555 5555 5555\n' > "$STUB_NOTES_FILE"
printf 'ok\n' > "$STUB_REPLY_FILE"
printf '%s' "$(grep -F '"step_id":"trig-5"' "$TRAJ")" | env "${ENV_COMMON[@]}" RESPONDER_PERSON_NOTES=1 "$RESPONDER" >> "$WORK/step.log" 2>&1
notes_files=$(grep -rl '5555' "$ID/memories" 2>/dev/null | wc -l)
if (( notes_files == 0 )); then ok "person notes: no card digits stored"; else bad "person notes: no card digits stored" "$(grep -rl '5555' "$ID/memories" | head -1)"; fi

echo
# --- 6. portability: no GNU-only escape in the redaction expressions -----
# Stock macOS sed treats the GNU word boundary escape as no boundary at
# all, so rules anchored on it silently matched nothing there (the macOS
# bash 3.2 CI job caught it). This guard fails if it ever comes back.
_redact_body=$(sed -n '/^_redact_card()/,/^}/p' "$RESPONDER")
if printf '%s' "$_redact_body" | grep -q '\\b'; then
    bad "portability: _redact_card uses the GNU-only word boundary escape"
else
    ok "portability: _redact_card uses only POSIX boundaries"
fi

echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
