#!/usr/bin/env bash
# tests/test_librarian_wake.sh — the librarian inside a project-mode wake
# (design/librarian.md). Drives the real thinkers/monolith/step against a
# throwaway identity set up by librarian-project init, with a stubbed shellm
# that captures the --prompt-file and writes trajectory steps. Pins:
#   - the memory pack sits in the project section (after the references,
#     before project memory) and replaces the life and related sections;
#   - a journal-only wake closes a `partial` episode, an adversary SURVIVES
#     review citing a packed id closes `success` and activates that node,
#     a failed run closes `failure`, a ritual file closes `success`;
#   - two failures then a success of one command family open a CAPTURE
#     signal that clears once a matching skill is proposed;
#   - the same error in three wakes raises a LIBRARIAN SUGGESTION;
#   - the daily ritual runs maintenance once;
#   - degrade paths: LIBRARIAN_MEMORY=0, no store, a failing librarian.
# No LLM calls, no docker.
set -uo pipefail
unset IDENTITY_DIR IDENTITY_NAME MEM_DIR TRAJ_DIR TRAJ_ID ROOT_TRAJ_ID PROJECT_DIR LIBRARIAN_STORE LIBRARIAN_NOW \
    LIBRARIAN_SRC LIBRARIAN_MEMORY PROJECT_NOW PROJECT_TIME_SCALE PROJECT_DAILY_TOKENS 2>/dev/null
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(dirname "$HERE")"; STEP="$REPO/thinkers/monolith/step"
export PATH="$REPO/tools:$REPO/bin:$PATH"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
has() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then ok "$1"; else bad "$1" "missing '$3' in: $(printf '%s' "$2" | head -c 400)"; fi; }
hasnt() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then bad "$1" "unexpected '$3'"; else ok "$1"; fi; }
eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "got '$2', want '$3'"; fi; }
command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "FAIL git not found"; exit 1; }

WORK=$(mktemp -d); trap 'cd /; chmod -R u+w "$WORK" 2>/dev/null; rm -rf "$WORK"' EXIT
export HOME="$WORK/home"; mkdir -p "$HOME" "$WORK/stub"
ID="$WORK/ident"; TRAJ_ID="cafe0000-0000-0000-0000-0000000000bb"
mkdir -p "$ID/memories" "$ID/trajectories/$TRAJ_ID" "$ID/run"
printf 'name=ada\ncreated=2026-10-01T00:00:00Z\nroot_trajectory=%s\n' "$TRAJ_ID" > "$ID/info.txt"
printf 'I am {{identity_name}}, a curious companion.\n' > "$ID/core_identity_prompt.md"
TRAJ="$ID/trajectories/$TRAJ_ID/trajectory.jsonl"; : > "$TRAJ"
printf 'test-token\n' > "$ID/run/dispatcher.token"
printf '# Green hydrogen in Texas\nEstimate the levelized cost in 2030.\n' > "$WORK/spec.md"
LIBRARIAN_LLM=0 "$REPO/tools/librarian-project" init "$ID" --spec "$WORK/spec.md" >/dev/null 2>&1 || { echo "FAIL init"; exit 1; }
P="$ID/workdir/project"
export IDENTITY_DIR="$ID"
PROJECT_ID=$(cat "$ID/project-pristine/project_id")
L() { LIBRARIAN_LLM=0 librarian "$@"; }
# A skill the pack can carry.
SK=$(L propose --type skill --summary "pint is missing in the sandbox: pip install --user pint and export PYTHONPATH" \
    --body 'Fix: `pip install --user pint` then `export PYTHONPATH=$HOME/.local/lib/python3.12/site-packages`; verified 2026-10-02.' \
    --tags pkg:pint,pkg:python,area:tooling --source journal --project "$PROJECT_ID" | jq -r .id)
[[ -n "$SK" && "$SK" != null ]] || { echo "FAIL seeding a skill"; exit 1; }

# The stub shellm: captures the prompt, writes a run's steps, optionally a
# journal entry or a review file, and prints FINAL.
cat > "$WORK/stub/shellm" <<'STUB'
#!/usr/bin/env bash
prev=""; for a in "$@"; do [[ "$prev" == "--prompt-file" ]] && cp "$a" "$STUB_CAPTURE"; prev="$a"; done
rid="run-$RANDOM$RANDOM"; ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
[[ -n "${SHELLM_RUN_ID_OUT:-}" ]] && printf '%s' "$rid" > "$SHELLM_RUN_ID_OUT"
step() { printf '%s\n' "$1" | jq -c --arg rid "$rid" --arg ts "$ts" '. + {run_id:$rid, ts:$ts, step_id:("s-" + (now|tostring) + "-" + (input_line_number|tostring) + "-" + (.type))}' >> "$STUB_TRAJ"; }
step '{"type":"shellm-run"}'
[[ -n "${STUB_PROMPT_TEXT:-}" ]] && step "$(jq -nc --arg c "$STUB_PROMPT_TEXT" '{type:"prompt", content:$c}')"
case "${STUB_MODE:-plain}" in
  errors)   # the same error, every wake
    step '{"type":"reasoning","thought":"run it","cmd":"python3 model.py"}'
    step '{"type":"shell-output","stdout":"","stderr":"Traceback\nModuleNotFoundError: No module named '"'"'pint'"'"'","exit":1}' ;;
  acted)    # one clean tool call (then e.g. the model API dies)
    step '{"type":"reasoning","thought":"look","cmd":"ls"}'
    step '{"type":"shell-output","stdout":"model.py","stderr":"","exit":0}' ;;
  resolve)  # two failures then the same family succeeds
    step '{"type":"reasoning","thought":"run it","cmd":"python3 model.py"}'
    step '{"type":"shell-output","stdout":"","stderr":"ModuleNotFoundError: No module named '"'"'pint'"'"'","exit":1}'
    step '{"type":"reasoning","thought":"again","cmd":"python3 model.py --fast"}'
    step '{"type":"shell-output","stdout":"","stderr":"ModuleNotFoundError: No module named '"'"'pint'"'"'","exit":1}'
    step '{"type":"reasoning","thought":"install","cmd":"pip install --user pint"}'
    step '{"type":"shell-output","stdout":"ok","stderr":"","exit":0}'
    step '{"type":"reasoning","thought":"run it","cmd":"python3 model.py"}'
    step '{"type":"shell-output","stdout":"42","stderr":"","exit":0}' ;;
esac
step "$(jq -nc --arg c "did a thing${STUB_CITE:+ using $STUB_CITE}" '{type:"observation", content:$c, source:"monolith"}')"
if [[ -n "${STUB_JOURNAL:-}" ]]; then printf '\n### 2026-10-01 12:00Z — %s\nType: work\nWhat: %s\n' "$STUB_JOURNAL" "$STUB_JOURNAL" >> "$STUB_PROJECT/journal.md"; fi
if [[ -n "${STUB_REVIEW:-}" ]]; then mkdir -p "$STUB_PROJECT/reviews"; printf 'Claim rests on %s.\nVerdict: %s\n' "$STUB_CITE" "$STUB_REVIEW" > "$STUB_PROJECT/reviews/claim-$RANDOM.md"; fi
if [[ -n "${STUB_RITUAL_FILE:-}" ]]; then mkdir -p "$(dirname "$STUB_PROJECT/$STUB_RITUAL_FILE")"; printf 'ritual done\n' > "$STUB_PROJECT/$STUB_RITUAL_FILE"; fi
step '{"type":"final","content":"Did the thing"}'
[[ -n "${STUB_STDERR:-}" ]] && printf '%s\n' "$STUB_STDERR" >&2
[[ -n "${STUB_FINAL+x}" ]] && printf '%s\n' "$STUB_FINAL" || printf 'Did the thing. Next: more.\n'
exit "${STUB_RC:-0}"
STUB
chmod +x "$WORK/stub/shellm"
export STUB_CAPTURE="$WORK/prompt" STUB_TRAJ="$TRAJ" STUB_PROJECT="$P" SHELLM_MODEL=test-model
WAKE='{"type":"monolith-wake","content":"wake","source":"monolith-timer"}'
run_step() {  # run_step [ENV=VAL ...]
    printf '%s' "$WAKE" | env PATH="$WORK/stub:$PATH" IDENTITY_DIR="$ID" IDENTITY_NAME=ada MEM_DIR="$ID/memories" \
        TRAJ_DIR="$ID/trajectories" TRAJ_ID="$TRAJ_ID" HOME="$WORK/home" LIBRARIAN_LLM=0 \
        LIBRARIAN_SRC="$REPO/librarian/src" MONOLITH_TIERED_MEMORY=1 PROJECT_IDLE_SKIP_STREAK=0 "$@" "$STEP" >> "$WORK/step.log" 2>&1
}
last_episode() { L search --type episode --limit 1 --no-log | jq -r '.[0].id'; }
episode_outcome() { L show "$1" | jq -r '.outcome.value + " | " + .outcome.criterion'; }

# ── 1. pack placement and the replaced sections ──────────────────────────────
run_step STUB_JOURNAL="first entry"; eq "wake 1 runs" "$?" 0
prompt=$(cat "$WORK/prompt")
has "pack is in the prompt" "$prompt" "Your memory pack (from the librarian store"
has "pack carries core identity" "$prompt" "I flag safety-relevant uncertainty"
has "pack carries the seeded skill" "$prompt" "$SK · skill · PROBATIONARY"
pos_pack=$(printf '%s\n' "$prompt" | grep -n '^\[IDENTITY: CORE\]' | head -1 | cut -d: -f1)
pos_spec=$(printf '%s\n' "$prompt" | grep -n '^Project specification' | head -1 | cut -d: -f1)
pos_mem=$(printf '%s\n' "$prompt" | grep -n '^Project memory (project/project-memory.md' | head -1 | cut -d: -f1)
pos_stream=$(printf '%s\n' "$prompt" | grep -n '^Recent stream' | head -1 | cut -d: -f1)
(( pos_spec < pos_mem && pos_mem < pos_pack && pos_pack < pos_stream )) && ok "pack sits after project memory, which sits after the spec" || bad "pack placement" "spec=$pos_spec pack=$pos_pack mem=$pos_mem stream=$pos_stream"
# Cache-break markers: one after the spec block, one after project memory,
# both above the pack (bin/llm turns them into cache breakpoints).
mk_lines=$(printf '%s\n' "$prompt" | grep -n '^<<<llm-cache-break>>>$' | cut -d: -f1 | tr '\n' ' ')
read -r mk1 mk2 mk3 <<<"$mk_lines"
(( pos_spec < mk1 && mk1 < pos_mem && pos_mem < mk2 && mk2 < pos_pack )) && [[ -z "${mk3:-}" ]] \
    && ok "two cache markers: after the spec, after project memory" || bad "cache marker placement" "markers=$mk_lines spec=$pos_spec mem=$pos_mem pack=$pos_pack"
pos_ws=$(printf '%s\n' "$prompt" | grep -n '^Workspace: ' | head -1 | cut -d: -f1)
(( mk2 < pos_ws && pos_ws < pos_pack )) && ok "the workspace map sits below the markers in project mode" || bad "workspace placement" "ws=$pos_ws markers=$mk_lines"
eq "the workspace map appears once" "$(printf '%s\n' "$prompt" | grep -c '^Workspace: ')" 1
has "project memory stays in the wake" "$prompt" "Project memory (project/project-memory.md"
has "journal tail shrinks to two entries" "$prompt" "Last 2 journal entries"
hasnt "life section is replaced" "$prompt" "Your life so far"
hasnt "related memories are replaced" "$prompt" "Related memories ("
[[ -f "$ID/run/librarian_request.json" ]] && bad "request file is removed after the wake" || ok "request file is removed after the wake"
EP1=$(last_episode)
eq "journal-only wake closes partial" "$(episode_outcome "$EP1")" "partial | journal entry + FINAL (unverified)"
eq "the packed skill stays probationary after a partial" "$(L show "$SK" | jq -r .status)" probationary
eq "the pack entry was cited by the episode" "$(L show "$SK" | jq -r .use_count)" 1
has "the wake's commit carries FINAL" "$(git -C "$P" log -1 --format=%s)" "Did the thing"
[[ -f "$P/librarian.md" ]] && ok "project digest mirror is written" || bad "project digest mirror is written"

# ── 2. outcomes from exogenous evidence ──────────────────────────────────────
run_step STUB_CITE="$SK" STUB_REVIEW=SURVIVES STUB_JOURNAL="verified claim"
EP2=$(last_episode)
has "adversary SURVIVES closes partial for the wake" "$(episode_outcome "$EP2")" "partial | adversary review SURVIVES"
eq "the cited skill is now active" "$(L show "$SK" | jq -r .status)" active
run_step STUB_CITE="$SK" STUB_REVIEW=BROKEN STUB_JOURNAL="broken claim"
EP3=$(last_episode)
has "adversary BROKEN closes partial for the wake" "$(episode_outcome "$EP3")" "partial | adversary review BROKEN"
eq "a failure lowers confidence" "$(L show "$SK" | jq -r '.confidence < 0.6')" true
# The verdict is about the memory the review names, not the rest of the wake's pack.
moved=$(python3 -I -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(*c.execute("select sum(node_id!=?), sum(node_id!=? and delta_conf!=0) from credit_log where episode_id=?", (sys.argv[2],)*2+(sys.argv[3],)).fetchone())' "$ID/librarian/store.sqlite" "$SK" "$EP3")
[[ "${moved% *}" -ge 1 && "${moved#* }" == 0 ]] && ok "a review credits only the memories it names" || bad "a review credits only the memories it names" "other pack credits / moved: $moved"
n_ep=$(L stats | jq -r '.nodes.by_type.episode'); c_sk=$(L show "$SK" | jq -r .confidence)
run_step STUB_RC=1 STUB_FINAL=""
eq "a run that never acted (API down) records no episode" "$(L stats | jq -r '.nodes.by_type.episode')" "$n_ep"
eq "a run that never acted credits nothing" "$(L show "$SK" | jq -r .confidence)" "$c_sk"
run_step STUB_MODE=errors STUB_RC=1 STUB_FINAL=""
EP4=$(last_episode)
eq "a failed run closes failure" "$(episode_outcome "$EP4")" "failure | run failed (rc=1)"
c_sk=$(L show "$SK" | jq -r .confidence)
run_step STUB_MODE=acted STUB_RC=1 STUB_FINAL="" STUB_CITE="$SK" \
    STUB_STDERR="shellm: error: llm failed (exit 1): llm: error: API error (HTTP 503): Bedrock is unable to process your request."
eq "a run the model API cut off mid-run closes partial" "$(episode_outcome "$(last_episode)")" "partial | run cut off by model API failure (rc=1)"
eq "a run the model API cut off credits nothing" "$(L show "$SK" | jq -r .confidence)" "$c_sk"
run_step STUB_FINAL=""
EP5=$(last_episode)
eq "no artifact closes unknown" "$(episode_outcome "$EP5")" "unknown | no measurable artifact"

# ── 2a. a mixed review credits each memory by its own verdict ──────────────
SK2=$(L propose --type skill --summary "ogr2ogr is missing in the sandbox: apt-get install gdal-bin" \
    --body 'Fix: `apt-get install -y gdal-bin`; verified 2026-10-02.' --tags pkg:gdal,area:tooling --source journal --project "$PROJECT_ID" | jq -r .id)
c_sk=$(L show "$SK" | jq -r .confidence); c_sk2=$(L show "$SK2" | jq -r .confidence)
run_step STUB_CITE="$SK" STUB_REVIEW="SURVIVES for claim 1, BROKEN for claim 2
Memories SURVIVES: $SK
Memories BROKEN: $SK2" STUB_JOURNAL="mixed review"
has "a mixed review closes partial" "$(episode_outcome "$(last_episode)")" "partial | adversary review mixed"
eq "the surviving memory gains" "$(L show "$SK" | jq -r --argjson c "$c_sk" '.confidence > $c')" true
eq "the broken memory loses" "$(L show "$SK2" | jq -r --argjson c "$c_sk2" '.confidence < $c')" true

# ── 2b. only what the mind wrote this wake counts as cited ───────────────────
cited_line() { L show "$1" | jq -r .body | grep '^Cited:' || true; }
run_step STUB_PROMPT_TEXT="[TASK MEMORIES]
- $SK · skill · ACTIVE" STUB_JOURNAL="no ids here"
hasnt "an id only in the prompt is not cited" "$(cited_line "$(last_episode)")" "$SK"
run_step STUB_JOURNAL="used $SK for the fix"
has "an id in this wake's journal entry is cited" "$(cited_line "$(last_episode)")" "$SK"
run_step STUB_JOURNAL="a later entry"
hasnt "an id in an older journal entry is not cited again" "$(cited_line "$(last_episode)")" "$SK"

# ── 3. resolved failure → CAPTURE signal → cleared by a skill ───────────────
run_step STUB_MODE=resolve STUB_JOURNAL="fixed pint"
eq "a resolved failure opens a pending capture" "$(L stats | jq -r .pending_capture)" 1
run_step STUB_JOURNAL="next"
has "CAPTURE signal reaches the next wake" "$(cat "$WORK/prompt")" "- CAPTURE: you resolved"
has "CAPTURE names the propose command" "$(cat "$WORK/prompt")" "librarian propose --type skill"
L -q propose --type skill --summary "python3 scripts fail with No module named pint: install it to the user site first" \
    --body 'Symptom: ModuleNotFoundError: No module named '"'"'pint'"'"'. Fix: `pip install --user pint`; verified 2026-10-01.' \
    --tags pkg:python3,area:tooling --source journal --project "$PROJECT_ID"
run_step STUB_JOURNAL="after capture"
eq "a matching skill clears the capture" "$(L stats | jq -r .pending_capture)" 0
hasnt "CAPTURE signal is gone" "$(cat "$WORK/prompt")" "- CAPTURE:"

# ── 4. repeated failure → suggestion → response ──────────────────────────────
# The resolve wake above already logged the signature once, so the third
# sighting can come on the second or third errors wake; the signal reaches
# the prompt of the wake after the one that raised it.
SID=""; found=""
for i in 1 2 3 4; do
    run_step STUB_MODE=errors STUB_JOURNAL="failing $i"
    prompt=$(cat "$WORK/prompt")
    if printf '%s' "$prompt" | grep -F -- "- LIBRARIAN SUGGESTION [repeated-failure]" >/dev/null; then found="$prompt"; break; fi
done
[[ -n "$found" ]] && ok "repeated failure raises a suggestion" || bad "repeated failure raises a suggestion" "no signal in 4 wakes"
has "the suggestion points at the skill" "$found" "$SK"
SID=$(printf '%s\n' "$found" | sed -n 's/.*LIBRARIAN SUGGESTION \[repeated-failure\] (\(S[0-9A-Z]*\)).*/\1/p' | head -1)
L -q suggestion respond "$SID" accept 2>/dev/null; eq "the suggestion can be answered" "$?" 0
run_step STUB_JOURNAL="quiet"
hasnt "an answered suggestion is not repeated" "$(cat "$WORK/prompt")" "- LIBRARIAN SUGGESTION ["

# ── 5. daily ritual: maintenance once, ritual file closes success ───────────
now=$(date +%s)
printf '%s\n' "$(( now - 2 * 86400 ))" > "$ID/project-pristine/started_at"   # two project days in: the daily ritual is due
# The day the ritual closes is the date of the latest PROJECT_DAILY_AT
# boundary at or before now, so with the 21:00 default it is yesterday until
# 21:00 UTC and today after it — the run's wall clock decided whether this
# section passed. Pin the boundary to 00:00: it is then always today's date.
day=$(date -u -d "@$now" +%F 2>/dev/null || date -u -r "$now" +%F)
run_step PROJECT_DAILY_AT=00:00 STUB_RITUAL_FILE="daily/$day.md" STUB_JOURNAL="daily"
EP6=$(last_episode)
has "a written ritual file closes success" "$(episode_outcome "$EP6")" "success | ritual daily output written"
rows=$(IDENTITY_DIR="$ID" python3 -c "import sqlite3,sys; c=sqlite3.connect('$ID/librarian/store.sqlite'); print(c.execute(\"select count(*) from maintenance where kind='daily'\").fetchone()[0])")
eq "daily maintenance ran once" "$rows" 1
run_step PROJECT_DAILY_AT=00:00 STUB_JOURNAL="another"
rows=$(python3 -c "import sqlite3; c=sqlite3.connect('$ID/librarian/store.sqlite'); print(c.execute(\"select count(*) from maintenance where kind='daily'\").fetchone()[0])")
eq "a second wake adds no maintenance row" "$rows" 1

# ── 6. degrade paths ─────────────────────────────────────────────────────────
run_step LIBRARIAN_MEMORY=0 STUB_JOURNAL="off"
prompt=$(cat "$WORK/prompt")
hasnt "LIBRARIAN_MEMORY=0 removes the pack" "$prompt" "Your memory pack (from the librarian store"
has "the old journal tail returns" "$prompt" "Last 5 journal entries"
has "related/life logic is untouched when off" "$prompt" "Project memory (project/project-memory.md"
mv "$ID/librarian" "$ID/librarian.aside"
run_step STUB_JOURNAL="nostore"
prompt=$(cat "$WORK/prompt")
hasnt "no store: no pack" "$prompt" "Your memory pack (from the librarian store"
n_err=$(grep -c '"reason":"prompt-section-failed"' "$TRAJ" || true)
eq "no store is not an error step" "$n_err" 0
mv "$ID/librarian.aside" "$ID/librarian"
mkdir -p "$WORK/broken"; printf '#!/usr/bin/env bash\necho boom >&2; exit 1\n' > "$WORK/broken/librarian"; chmod +x "$WORK/broken/librarian"
printf '%s' "$WAKE" | env PATH="$WORK/broken:$WORK/stub:$PATH" IDENTITY_DIR="$ID" IDENTITY_NAME=ada MEM_DIR="$ID/memories" \
    TRAJ_DIR="$ID/trajectories" TRAJ_ID="$TRAJ_ID" HOME="$WORK/home" LIBRARIAN_LLM=0 STUB_JOURNAL="broken" "$STEP" >> "$WORK/step.log" 2>&1
prompt=$(cat "$WORK/prompt")
hasnt "a failing librarian leaves the pack out" "$prompt" "Your memory pack (from the librarian store"
has "the old excerpt is back" "$prompt" "Project memory (project/project-memory.md"
n_err=$(grep -c '"section":"librarian"' "$TRAJ" || true)
eq "a failing librarian is an error step" "$n_err" 1

# ── 7. blind never sees the store ────────────────────────────────────────────
has "blind runs with the librarian off" "$(cat "$REPO/bin/blind")" "LIBRARIAN_MEMORY=0"
has "the --bin list forwards librarian" "$(sed -n '/for cmd in mem traj/p' "$REPO/thinkers/_lib/common.sh")" "librarian"

# ── 8. idle rest without a model call ───────────────────────────────────────
# Three timer wakes that change no project file, then the fourth skips the
# model; a file a background job left under project/ brings the model back.
# Nothing due by the real clock: close today's daily ritual if it is owed.
due=$(export IDENTITY_DIR="$ID" IDENTITY_NAME=ada; source "$REPO/thinkers/_lib/project.sh"; _project_due_ritual)
[[ "$due" == daily* ]] && STUB_RITUAL_FILE="daily/${due#daily }.md"
run_step STUB_JOURNAL="work before the idle stretch" PROJECT_FREETIME=0 ${STUB_RITUAL_FILE:+STUB_RITUAL_FILE=$STUB_RITUAL_FILE}
for i in 1 2 3; do run_step PROJECT_IDLE_SKIP_STREAK=3 PROJECT_FREETIME=0; done
eq "idle: three idle wakes counted" "$(cat "$ID/run/project_idle_streak")" 3
rm -f "$WORK/prompt"
run_step PROJECT_IDLE_SKIP_STREAK=3 PROJECT_FREETIME=0
[[ -f "$WORK/prompt" ]] && bad "idle: the fourth idle wake makes no model call" || ok "idle: the fourth idle wake makes no model call"
has "idle: the step log says why" "$(tail -3 "$WORK/step.log")" "project idle (streak 3): no model call"
grep -q '_project_commit "rest: idle, nothing due"' "$STEP" && ok "idle: a skip commits like a rest" || bad "idle: a skip commits like a rest"
mkdir -p "$P/model"; printf '42\n' > "$P/model/background-result.txt"
run_step PROJECT_IDLE_SKIP_STREAK=3 PROJECT_FREETIME=0
[[ -f "$WORK/prompt" ]] && ok "idle: a background job's output under project/ wakes the model" || bad "idle: a background job's output under project/ wakes the model"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
