#!/usr/bin/env bash
# tests/test_responder_deferral.sh — deferrals that bind the mind
# (design/conversation_memory.md, part 5).
#
# Usage: tests/test_responder_deferral.sh
#
# The responder has no tools. When the model answers "DEFER: <work>" on the
# first line, the step must send the holding message below it, append an
# `action` step (source responder, trigger_step, person, request) that the
# monolith routes on, and mark its observation deferred. The monolith step
# must then show a PENDING REQUEST routing hint naming the exact follow-up
# command until an observation carries resolves=<trigger>. `chat reply
# --follow-up` must deliver a second reply to an already answered message,
# which the duplicate guard otherwise refuses. Stubbed llm and shellm; no LLM
# calls, no docker.

set -uo pipefail
unset IDENTITY_DIR IDENTITY_NAME MEM_DIR TRAJ_DIR TRAJ_ID ROOT_TRAJ_ID THINK_CONTEXT_TAIL 2>/dev/null

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
RESPONDER="$REPO/thinkers/responder/step"
MONOLITH="$REPO/thinkers/monolith/step"

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
TRAJ_ID="cafe0000-0000-0000-0000-0000000000de"
mkdir -p "$ID/memories" "$ID/trajectories/$TRAJ_ID" "$ID/run"
printf 'name=%s\ncreated=test\nroot_trajectory=%s\n' "$ME" "$TRAJ_ID" > "$ID/info.txt"
TRAJ="$ID/trajectories/$TRAJ_ID/trajectory.jsonl"
printf 'test-token\n' > "$ID/run/dispatcher.token"

mkdir -p "$WORK/stub"
cat > "$WORK/stub/llm" <<'STUB'
#!/usr/bin/env bash
cat "$STUB_REPLY_FILE"
STUB
cat > "$WORK/stub/shellm" <<'STUB'
#!/usr/bin/env bash
prev=""
for a in "$@"; do [[ "$prev" == "--prompt-file" ]] && cp "$a" "$STUB_CAPTURE"; prev="$a"; done
exit 0
STUB
chmod +x "$WORK/stub/llm" "$WORK/stub/shellm"
export STUB_REPLY_FILE="$WORK/reply" STUB_CAPTURE="$WORK/prompt"

ENV_COMMON=(PATH="$WORK/stub:$REPO/bin:$REPO/tools:$PATH" IDENTITY_DIR="$ID" IDENTITY_NAME="$ME"
    MEM_DIR="$ID/memories" TRAJ_DIR="$ID/trajectories" TRAJ_ID="$TRAJ_ID" HOME="$WORK/home"
    SHELLM_MODEL=stub-model THINK_CONTEXT_TAIL=30 RESPONDER_PERSON_NOTES=0 MONOLITH_TIERED_MEMORY=0)
run_responder() { printf '%s' "$1" | env "${ENV_COMMON[@]}" "$RESPONDER" >> "$WORK/step.log" 2>&1; }
run_monolith()  { printf '%s' "$1" | env "${ENV_COMMON[@]}" MONOLITH_SHARE_HINT_EVERY=0 "$MONOLITH" >> "$WORK/step.log" 2>&1; }
now() { date -u +%Y-%m-%dT%H:%M:%S.000Z; }

# --- 1. a DEFER reply: holding message + action + deferred observation -------
: > "$TRAJ"
printf '{"step_id":"hdr","type":"trajectory","ts":"%s"}\n' "$(now)" >> "$TRAJ"
printf '{"step_id":"trig-1","type":"message","from":"%s","to":"%s","content":"how is the bridge work going?","ts":"%s","source":"chat"}\n' "$THEM" "$ME" "$(now)" >> "$TRAJ"
printf 'DEFER: check the telegram bridge work status and report it\nLet me look into that and get back to you.\n' > "$STUB_REPLY_FILE"
run_responder "$(grep -F '"step_id":"trig-1"' "$TRAJ")"

sent=$(jq -c 'select(.type=="message" and .from=="testid" and .reply_to=="trig-1")' "$TRAJ" | tail -1)
if [[ "$(printf '%s' "$sent" | jq -r .content)" == "Let me look into that and get back to you." ]]; then
    ok "the holding message below DEFER is what gets sent"
else
    bad "the holding message below DEFER is what gets sent" "got $sent"
fi
act=$(jq -c 'select(.type=="action" and .source=="responder")' "$TRAJ" | tail -1)
if [[ -n "$act" && "$(printf '%s' "$act" | jq -r .trigger_step)" == trig-1 \
      && "$(printf '%s' "$act" | jq -r .person)" == "$THEM" \
      && "$(printf '%s' "$act" | jq -r .request)" == "check the telegram bridge work status and report it" ]]; then
    ok "an action step carries trigger_step, person, and the request"
else
    bad "an action step carries trigger_step, person, and the request" "got $act"
fi
if printf '%s' "$act" | jq -e '.content | contains("chat reply --follow-up --reply-to trig-1 andy") and contains("resolves=trig-1")' >/dev/null 2>&1; then
    ok "the action names the exact delivery command"
else
    bad "the action names the exact delivery command" "got $(printf '%s' "$act" | jq -r .content)"
fi
act_line=$(grep -n '"type":"action"' "$TRAJ" | cut -d: -f1 | tail -1)
msg_line=$(grep -n '"reply_to":"trig-1"' "$TRAJ" | cut -d: -f1 | tail -1)
[[ "$act_line" -lt "$msg_line" ]] && ok "the action is appended before the holding message" || bad "the action is appended before the holding message" "action line $act_line, message line $msg_line"
obs=$(jq -c 'select(.type=="observation" and .source=="responder" and .trigger_step=="trig-1")' "$TRAJ" | tail -1)
if [[ "$(printf '%s' "$obs" | jq -r .decision)" == replied && "$(printf '%s' "$obs" | jq -r .deferred)" == true \
      && "$(printf '%s' "$obs" | jq -r .context_msgs)" =~ ^[0-9]+$ ]]; then
    ok "the observation is replied + deferred, with the metrics"
else
    bad "the observation is replied + deferred, with the metrics" "got $obs"
fi

# --- 2. the monolith sees a PENDING REQUEST hint until it is resolved --------
rm -f "$STUB_CAPTURE"
run_monolith "$act"
if grep -q 'PENDING REQUEST from andy: check the telegram bridge work status' "$STUB_CAPTURE" 2>/dev/null \
   && grep -q 'chat reply --follow-up --reply-to trig-1 andy' "$STUB_CAPTURE" \
   && grep -q -- '--field resolves=trig-1' "$STUB_CAPTURE"; then
    ok "the monolith prompt shows the pending request with the delivery command"
else
    bad "the monolith prompt shows the pending request with the delivery command" "$(grep -o 'PENDING[^\n]*' "$STUB_CAPTURE" 2>/dev/null | head -1)"
fi
if grep -q 'pending request' "$REPO/thinkers/monolith/prompt.md" && grep -q -- '--follow-up' "$REPO/thinkers/monolith/prompt.md"; then
    ok "the monolith prompt allows the one reply exception"
else
    bad "the monolith prompt allows the one reply exception"
fi

# the mind delivers: follow-up reply to an already answered trigger
if printf 'The bridge work is half done: file sends work, photos next.' \
     | env "${ENV_COMMON[@]}" chat reply --follow-up --reply-to trig-1 "$THEM" 2>>"$WORK/step.log"; then
    ok "chat reply --follow-up sends a second reply to an answered message"
else
    bad "chat reply --follow-up sends a second reply to an answered message" "$(tail -2 "$WORK/step.log")"
fi
n=$(jq -c 'select(.type=="message" and .from=="testid" and .reply_to=="trig-1")' "$TRAJ" | wc -l | tr -d ' ')
fu=$(jq -c 'select(.type=="message" and .from=="testid" and .reply_to=="trig-1" and .follow_up==true)' "$TRAJ" | wc -l | tr -d ' ')
[[ "$n" == 2 && "$fu" == 1 ]] && ok "the follow-up is stamped reply_to and follow_up:true" || bad "the follow-up is stamped reply_to and follow_up:true" "replies=$n follow_up=$fu"
if ! printf 'dup' | env "${ENV_COMMON[@]}" chat reply --reply-to trig-1 "$THEM" 2>/dev/null; then
    bad "a plain second reply is still refused by the guard" "chat exited nonzero"
else
    n2=$(jq -c 'select(.type=="message" and .from=="testid" and .reply_to=="trig-1")' "$TRAJ" | wc -l | tr -d ' ')
    [[ "$n2" == 2 ]] && ok "a plain second reply is still refused by the guard" || bad "a plain second reply is still refused by the guard" "now $n2 replies"
fi

# resolving observation clears the hint
env "${ENV_COMMON[@]}" traj append --field type=observation --field content="Delivered the bridge status to andy." --field source=monolith --field resolves=trig-1 >/dev/null
rm -f "$STUB_CAPTURE"
run_monolith '{"type":"monolith-wake","content":"wake","source":"monolith-timer"}'
if ! grep -q 'PENDING REQUEST' "$STUB_CAPTURE" 2>/dev/null; then
    ok "an observation with resolves=<trigger> clears the hint"
else
    bad "an observation with resolves=<trigger> clears the hint"
fi

# --- 3. a normal reply appends no action ------------------------------------
printf '{"step_id":"trig-2","type":"message","from":"%s","to":"%s","content":"thanks!","ts":"%s","source":"chat"}\n' "$THEM" "$ME" "$(now)" >> "$TRAJ"
printf 'Any time.\n' > "$STUB_REPLY_FILE"
run_responder "$(grep -F '"step_id":"trig-2"' "$TRAJ")"
acts=$(jq -c 'select(.type=="action" and .source=="responder")' "$TRAJ" | wc -l | tr -d ' ')
[[ "$acts" == 1 ]] && ok "a normal reply appends no action" || bad "a normal reply appends no action" "actions=$acts"
obs=$(jq -c 'select(.type=="observation" and .source=="responder" and .trigger_step=="trig-2")' "$TRAJ" | tail -1)
[[ "$(printf '%s' "$obs" | jq 'has("deferred")')" == false ]] && ok "a normal reply is not marked deferred" || bad "a normal reply is not marked deferred"

# --- 4. DEFER with nothing under it gets the default holding line -----------
printf '{"step_id":"trig-3","type":"message","from":"%s","to":"%s","content":"what is in the latest commit?","ts":"%s","source":"chat"}\n' "$THEM" "$ME" "$(now)" >> "$TRAJ"
printf 'DEFER: read the latest commit and summarize it\n' > "$STUB_REPLY_FILE"
run_responder "$(grep -F '"step_id":"trig-3"' "$TRAJ")"
sent=$(jq -r 'select(.type=="message" and .from=="testid" and .reply_to=="trig-3") | .content' "$TRAJ" | tail -1)
[[ "$sent" == "Let me look into that and get back to you." ]] && ok "a bare DEFER sends the default holding line" || bad "a bare DEFER sends the default holding line" "got '$sent'"

echo
echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
