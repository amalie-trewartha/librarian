#!/usr/bin/env bash
# tests/test_project_mode.sh — project mode for long unattended runs
# (design/long_autonomy.md): librarian-project init, the read-only guard, the
# wake-prompt section, ritual scheduling, dated question defaults, the token
# budget and rest floors, the stall signal, the git commit of project/, and
# blind's isolation from the parent trajectory.
#
# Usage: tests/test_project_mode.sh
#
# The clock is pinned with PROJECT_NOW; shellm is faked for blind. No LLM
# calls, no docker.

set -uo pipefail
unset IDENTITY_DIR IDENTITY_NAME MEM_DIR TRAJ_DIR TRAJ_ID ROOT_TRAJ_ID PROJECT_DIR PROJECT_DAILY_TOKENS \
    PROJECT_DAILY_AT PROJECT_FREETIME LIBRARIAN_PROJECT_MODE _SHELLM_PARENT_TRAJ_ID 2>/dev/null

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
export PATH="$REPO/bin:$PATH"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
# grep without -q reads all its input: under pipefail, -q exiting early would
# SIGPIPE printf on a large input and fail the pipeline even on a match.
has() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then ok "$1"; else bad "$1" "missing '$3' in: $(printf '%s' "$2" | head -c 600)"; fi; }
hasnt() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then bad "$1" "unexpected '$3'"; else ok "$1"; fi; }
eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "got '$2', want '$3'"; fi; }

command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "FAIL git not found"; exit 1; }

WORK=$(mktemp -d)
trap 'cd /; chmod -R u+w "$WORK" 2>/dev/null; rm -rf "$WORK"' EXIT
export HOME="$WORK/home"; mkdir -p "$HOME"

ID="$WORK/ident"
mkdir -p "$ID/run" "$ID/usage"
printf 'name=ada\ncreated=2026-10-01T00:00:00Z\n' > "$ID/info.txt"
printf 'I am {{identity_name}}, a curious companion.\n' > "$ID/core_identity_prompt.md"
printf '# Brief\nEstimate the levelized cost of green hydrogen in Texas in 2030.\n' > "$WORK/spec.md"

# ── init ─────────────────────────────────────────────────────────────────────
printf '# An exemplar LCA\nGoal and scope...\n' > "$WORK/exemplar.md"
out=$("$REPO/tools/librarian-project" init "$ID" --spec "$WORK/spec.md" --reference "$WORK/exemplar.md" 2>&1); rc=$?
eq "init succeeds" "$rc" 0
P="$ID/workdir/project"
for f in charter.md spec.md deliverable.md project-memory.md journal.md questions.md addenda.md STATE roles/adversary.md roles/coldeyes.md roles/explorer.md; do
    [[ -f "$P/$f" ]] && ok "init wrote $f" || bad "init wrote $f"
done
[[ -f "$ID/project-pristine/rituals/daily.md" ]] && ok "rituals live in pristine" || bad "rituals live in pristine"
e=$(cat "$ID/project-pristine/end_at"); n=$(date +%s)
(( e - n > 13 * 86400 && e - n <= 14 * 86400 )) && ok "init sets a 14-day end by default" || bad "init sets a 14-day end by default" "end-now=$((e - n))"
[[ -w "$P/charter.md" ]] && bad "charter is read-only" || ok "charter is read-only"
[[ -w "$P/roles" ]] && ok "roles dir stays writable (guard can restore a deleted role)" || bad "roles dir stays writable"
eq "one initial commit" "$(git -C "$P" rev-list --count HEAD 2>/dev/null)" 1
[[ -d "$P/model" ]] && ok "init creates model/" || bad "init creates model/"
has "persona replaced with project persona" "$(cat "$ID/core_identity_prompt.md")" "research agent assigned to one long project"
has "old persona kept" "$(cat "$ID/core_identity_prompt.md.pre-project")" "curious companion"
out=$("$REPO/tools/librarian-project" init "$ID" --spec "$WORK/spec.md" 2>&1); rc=$?
[[ $rc -ne 0 ]] && ok "second init refused without --force" || bad "second init refused without --force"
has "init sets the default 2M daily budget" "$(cat "$ID/.env")" "PROJECT_DAILY_TOKENS=2000000"

export IDENTITY_DIR="$ID" IDENTITY_NAME=ada LIBRARIAN_TZ=UTC
# shellcheck disable=SC1091
source "$REPO/thinkers/_lib/project.sh"
_project_on && ok "project mode detected" || bad "project mode detected"
LIBRARIAN_PROJECT_MODE=0 _project_on && bad "LIBRARIAN_PROJECT_MODE=0 disables" || ok "LIBRARIAN_PROJECT_MODE=0 disables"

# ── guard ────────────────────────────────────────────────────────────────────
chmod u+w "$P/charter.md"; printf 'I may edit my rules.\n' > "$P/charter.md"
restored=$(_project_guard)
eq "guard reports the edited charter" "$restored" "charter.md"
has "guard restored the charter" "$(cat "$P/charter.md")" "Standards for claims"
eq "guard is quiet when intact" "$(_project_guard)" ""
[[ -f "$P/reference/exemplar.md" && ! -w "$P/reference/exemplar.md" ]] && ok "reference copied read-only" || bad "reference copied read-only"
chmod u+w "$P/reference/exemplar.md"; echo changed > "$P/reference/exemplar.md"
eq "guard restores edited reference" "$(_project_guard)" "reference/exemplar.md"
rm -f "$P/roles/adversary.md"
eq "guard restores a deleted role" "$(_project_guard)" "roles/adversary.md"
has "guard signal names the file" "$(_project_signals "$restored")" "GUARD: these read-only files"

# ── prompt section ───────────────────────────────────────────────────────────
printf '### 2026-10-05 10:00Z — first source\nType: task\nStatus: done\n' >> "$P/journal.md"
sec=$(_project_section)
has "section has the charter, name filled in" "$sec" "You are ada, a long-running research agent"
has "section has the spec" "$sec" "green hydrogen in Texas"
has "section has the journal tail" "$sec" "first source"
has "section has the project clock" "$sec" "Project clock: day"
has "section has STATE" "$sec" "STATE: active"
has "section lists reference material by name" "$sec" "reference/exemplar.md"
hasnt "section does not inline reference material" "$sec" "Goal and scope..."

# ── rituals ──────────────────────────────────────────────────────────────────
ep() { date -u -d "$1" +%s; }
export PROJECT_NOW; PROJECT_NOW=$(ep '2026-10-05 22:00')
setstart() { chmod u+w "$ID/project-pristine"; printf '%s' "$(ep "$1")" > "$ID/project-pristine/started_at"; }
setstart '2026-10-05 10:00'
eq "daily due after the 21:00 boundary" "$(_project_due_ritual)" "daily 2026-10-05"
has "ritual signal carries the instructions" "$(_project_signals)" "project/daily/2026-10-05.md"
PROJECT_NOW=$(ep '2026-10-06 08:00')
eq "before the next boundary, the same day is still owed" "$(_project_due_ritual)" "daily 2026-10-05"
printf 'eval\n' > "$P/daily/2026-10-05.md"
eq "daily file clears it" "$(_project_due_ritual)" ""
setstart '2026-10-05 21:30'; PROJECT_NOW=$(ep '2026-10-05 23:00')
eq "a project started after the boundary owes nothing" "$(_project_due_ritual)" ""
setstart '2026-09-27 12:00'; PROJECT_NOW=$(ep '2026-10-05 22:00')
eq "week 2: weekly report for week 01 due" "$(_project_due_ritual)" "weekly 01"
has "weekly instructions name the review file" "$(_project_signals)" "project/reviews/week-01.md"
printf 'report\n' > "$P/reports/week-01.md"
eq "then the daily is due" "$(_project_due_ritual)" ""   # 10-05 daily already written
setstart '2026-09-30 00:00'; PROJECT_NOW=$(ep '2026-10-05 20:00')
printf 'eval\n' > "$P/daily/2026-10-04.md"
r=$(_project_due_ritual)
has "day 6: free time opens" "$r" "freetime 01"
[[ -f "$ID/run/project_freetime_01" ]] && ok "free time start recorded in run/" || bad "free time start recorded in run/"
PROJECT_NOW=$(ep '2026-10-06 09:00')
printf 'eval\n' > "$P/daily/2026-10-05.md"
has "after 12h the free-time signal says it ended" "$(_project_signals)" "FREE TIME has ended"
mkdir -p "$P/free-time/week-01"; printf 'did things\n' > "$P/free-time/week-01/report.md"
eq "free-time report closes it" "$(_project_due_ritual)" ""
PROJECT_FREETIME=0; rm -f "$P/free-time/week-01/report.md"
eq "PROJECT_FREETIME=0 disables it" "$(_project_due_ritual)" ""
unset PROJECT_FREETIME
printf 'did things\n' > "$P/free-time/week-01/report.md"

# ── questions and defaults ───────────────────────────────────────────────────
PROJECT_NOW=$(ep '2026-10-06 09:00')
git -C "$P" add -A >/dev/null; git -C "$P" -c user.name=ada -c user.email=a@x commit -qm "agent work" >/dev/null
cat >> "$P/questions.md" <<'EOF'
### 2026-10-01 — Discount rate — STATUS: open
Blocking: yes
Default: 8% real
Default-by: 2026-10-05
Answer: (a human writes here, or runs: librarian-project answer <name> <Qn> "...". Never you.)

### 2026-10-02 — Electrolyzer type — STATUS: open
Blocking: no
Default: PEM
Default-by: 2026-10-20

### 2026-10-02 — Functional unit — STATUS: open
Blocking: yes
Default-by: never

### 2026-10-03 — Water source — STATUS: open
Blocking: no

### 2026-09-30 — Region — STATUS: answered
Default-by: 2026-10-01
Answer: ERCOT (the agent wrote this)
EOF
# The agent's own wake writes these: commit them as the agent, not as a human.
git -C "$P" add -A >/dev/null; git -C "$P" -c user.name=ada -c user.email=a@x commit -qm "agent asks" >/dev/null
_project_number_questions
has "Q ids stamped in order" "$(grep '^### Q' "$P/questions.md" | head -1)" "### Q1 — 2026-10-01 — Discount rate"
eq "five questions numbered" "$(grep -c '^### Q[0-9]' "$P/questions.md")" 5
hasnt "the format example is not numbered" "$(grep 'short title' "$P/questions.md")" "### Q"
cp "$P/questions.md" "$WORK/q.before"; _project_number_questions
cmp -s "$WORK/q.before" "$P/questions.md" && ok "numbering is idempotent" || bad "numbering is idempotent"
git -C "$P" add -A >/dev/null; git -C "$P" -c user.name=ada -c user.email=a@x commit -qm "ids" >/dev/null
q=$(_project_questions | tr '\037' '\t')
hasnt "the template's format example is not a question" "$q" "short title"
cp "$P/questions.md" "$WORK/q.saved"
printf '\n### 2026-10-04 — Unnumbered, written mid-wake — STATUS: open\nBlocking: no\nDefault-by: 2026-10-30\nAnswer:\n' >> "$P/questions.md"
has "an unnumbered question with no answer is open, not human-answered" "$(_project_question_rows | tr '\037' '\t')" "Q?	open	Unnumbered"
hasnt "no bogus HUMAN ANSWER signal for it" "$(_project_signals)" "HUMAN ANSWER"
printf '\n### Q9 — 2026-10-04 — Revised default — STATUS: open\nBlocking: no\nDefault: old guess\nDefault (revised 2026-10-05): H = 0.47\nDefault-by: 2026-10-30\nAnswer:\n' >> "$P/questions.md"
has "a revised Default line is the default humans see" "$(_project_question_rows | tr '\037' '\t' | grep '^Q9')" "default: H = 0.47"
cp "$WORK/q.saved" "$P/questions.md"
has "questions parsed with id, title, status, blocking, default-by" "$q" "Q1	Discount rate	open	yes	2026-10-05"
eq "placeholder Answer counts as no answer" "$(printf '%s\n' "$q" | grep '^Q1' | cut -f7)" ""
sig=$(_project_signals)
has "matured default flagged" "$sig" 'DEFAULT DUE: no human answered Q1 "Discount rate"'
hasnt "future default not flagged" "$(printf '%s' "$sig" | grep 'DEFAULT DUE')" "Electrolyzer"
hasnt "never-default not flagged" "$(printf '%s' "$sig" | grep 'DEFAULT DUE')" "Functional unit"
has "missing Default-by flagged" "$sig" 'Q4 "Water source"'
has "open and blocking counts" "$sig" "Questions: 4 open, 2 blocking"
has "agent-written answer is flagged" "$sig" "QUESTION RECORD WRONG: Q5"
rows=$(_project_question_rows | tr '\037' '\t')
has "agent-written answer is unverified" "$rows" "Q5	unverified"

# ── humans: banner, answer, provenance, summary ──────────────────────────────
ban=$(_project_question_banner)
has "banner shouts the open count" "$ban" "!!! 4 OPEN QUESTION(S) FOR A HUMAN"
has "banner says how to answer" "$ban" "librarian-project answer ada <Qn>"
has "banner marks blocking" "$ban" "Q1 [BLOCKING]  Discount rate"
has "banner: default due now" "$ban" "default due now (2026-10-05)"
has "banner: future default date" "$ban" "default applies on 2026-10-20"
has "banner: never defaults" "$ban" "will NOT default"
has "banner: unverified answer" "$ban" "no human wrote the answer: Q5"
out=$("$REPO/tools/librarian-project" answer "$ID" Q2 "Use alkaline, it is cheaper at this scale" 2>&1); rc=$?
eq "answer command succeeds" "$rc" 0
has "answer line written" "$(grep -A4 '^### Q2' "$P/questions.md")" "Answer: Use alkaline, it is cheaper at this scale (human, "
eq "answer committed as human" "$(git -C "$P" log -1 --format=%an)" "human"
hasnt "answer leaves no uncommitted summary behind" "$(git -C "$P" status --porcelain)" "questions-summary.md"
has "question stays open until applied" "$(grep '^### Q2' "$P/questions.md")" "STATUS: open"
has "human answer recognized from git" "$(_project_human_answers)" "Q2"
has "agent signal: apply the human answer" "$(_project_signals)" 'HUMAN ANSWER: a human answered Q2'
has "banner: human answer waiting" "$(_project_question_banner)" "answered by a human; the agent applies it"
out=$("$REPO/tools/librarian-project" answer "$ID" Q9 "x" 2>&1); rc=$?
[[ $rc -ne 0 ]] && ok "answer to an unknown id refused" || bad "answer to an unknown id refused"
# A human edits by hand between wakes; the pre-wake commit attributes it.
sed -i 's/^Default-by: never$/Default-by: never\nAnswer: per kg of H2 at the plant gate/' "$P/questions.md"
_project_commit_outside
eq "between-wake edits committed as human" "$(git -C "$P" log -1 --format=%an)" "human"
has "hand-written answer recognized" "$(_project_human_answers)" "Q3"
# The agent applies answers and defaults.
sed -i -e 's/^\(### Q1 .*STATUS: \)open/\1defaulted/' -e 's/^\(### Q2 .*STATUS: \)open/\1answered/' "$P/questions.md"
sed -i 's/^Default-by: 2026-10-05$/Default-by: 2026-10-05\nResolution: 2026-10-06 default applied: 8% real discount rate/' "$P/questions.md"
rows=$(_project_question_rows | tr '\037' '\t')
has "closed by default" "$rows" "Q1	default	Discount rate	2026-10-06 default applied: 8% real discount rate"
has "closed by human" "$rows" "Q2	human	Electrolyzer type	Use alkaline"
_project_write_summary
sum=$(cat "$P/questions-summary.md")
has "summary lists open questions first" "$sum" "## Open: waiting on a human"
has "summary: open human answer waiting" "$sum" "**Q3** Functional unit"
has "summary: closed by default" "$sum" "| Q1 | Discount rate | 2026-10-01 | Default (no human answer) |"
has "summary: closed by human" "$sum" "| Q2 | Electrolyzer type | 2026-10-02 | Human answer | Use alkaline"
has "summary: unverified flagged" "$sum" "UNVERIFIED"
out=$("$REPO/tools/librarian-project" questions "$ID" --closed 2>&1)
has "questions --closed: human" "$out" "HUMAN ANSWER: Use alkaline"
has "questions --closed: default" "$out" "DEFAULT USED (no human answer)"
hasnt "questions --closed hides the open banner" "$out" "OPEN QUESTION"
out=$(PROJECT_NOW="$PROJECT_NOW" "$REPO/tools/librarian-project" status "$ID" 2>&1)
has "status leads with open questions" "$(printf '%s' "$out" | head -1)" "OPEN QUESTION(S) FOR A HUMAN"
has "status shows the budget from .env" "$out" "(cap 2000000 tokens); whole run:"
sed -i 's/^\(### Q5 .*STATUS: \)answered/\1moot/' "$P/questions.md"   # tidy for what follows

# ── STATE, budget and the delay floor ────────────────────────────────────────
eq "active state: no floor" "$(_project_delay_floor)" 0
printf 'blocked\nwaiting on the functional unit\n' > "$P/STATE"
eq "blocked with a human answer waiting: no floor" "$(_project_delay_floor)" 0
sed -i 's/^\(### Q3 .*STATUS: \)open/\1answered/' "$P/questions.md"
sed -i 's/^\(### Q1 .*STATUS: \)defaulted/\1open/' "$P/questions.md"
eq "blocked with a matured default: no floor" "$(_project_delay_floor)" 0
sed -i 's/^\(### Q1 .*STATUS: \)open/\1defaulted/' "$P/questions.md"
eq "blocked, nothing due: rest floor" "$(_project_delay_floor)" 3600
rm -f "$ID/run/project_rest_checked"
_project_should_skip_rest spontaneous && bad "blocked: first rest wake runs the model (daily check)" || ok "blocked: first rest wake runs the model (daily check)"
_project_should_skip_rest spontaneous && ok "blocked: later rest wakes the same day skip it" || bad "blocked: later rest wakes the same day skip it"
PROJECT_NOW=$((PROJECT_NOW + 90000)) _project_should_skip_rest spontaneous && bad "blocked: a day later it checks again" || ok "blocked: a day later it checks again"
has "blocked signal" "$(_project_signals)" "STATE is blocked"
# Fully blocked: the earliest default is pulled forward, non-blocking first.
# (A live run idled 5 h behind defaults 4-6 days out.)
cat >> "$P/questions.md" <<'EOF'

### 2026-10-06 — Plant size — STATUS: open
Blocking: yes
Default: 100 MW
Default-by: 2026-10-08

### 2026-10-06 — Capacity factor — STATUS: open
Blocking: no
Default: 45%
Default-by: 2026-10-12

### 2026-10-06 — Stack life — STATUS: open
Blocking: no
Default: 80,000 h
Default-by: 2026-10-10

### 2026-10-06 — Grid mix — STATUS: open
Blocking: no
Default-by: never
EOF
git -C "$P" add -A >/dev/null; git -C "$P" -c user.name=ada -c user.email=a@x commit -qm "agent asks more" >/dev/null
_project_number_questions
eq "blocked: earliest non-blocking default is picked over an earlier blocking one" "$(_project_blocked_default | cut -d$'\037' -f1)" "Q8"
sig=$(_project_signals)
has "blocked: early default signalled" "$sig" 'DEFAULT DUE (early): STATE is blocked, so instead of idling until 2026-10-10 you apply the earliest open default now: Q8 "Stack life"'
eq "blocked with an early default: no rest floor" "$(_project_delay_floor)" 0
_project_should_skip_rest spontaneous && bad "blocked with an early default: the wake runs the model" || ok "blocked with an early default: the wake runs the model"
ban=$(_project_question_banner)
has "banner tells humans the default is coming early" "$ban" "the agent is blocked, so it applies this default at its next wake (date was 2026-10-10)"
has "banner keeps the date for the others" "$ban" "default applies on 2026-10-12"
sed -i 's/^\(### Q8 .*STATUS: \)open/\1defaulted/' "$P/questions.md"
eq "next wake: the next non-blocking default" "$(_project_blocked_default | cut -d$'\037' -f1)" "Q7"
sed -i 's/^\(### Q7 .*STATUS: \)open/\1defaulted/' "$P/questions.md"
eq "then a blocking one; never-defaults are skipped" "$(_project_blocked_default | cut -d$'\037' -f1)" "Q6"
eq "PROJECT_BLOCKED_DEFAULT=0 turns it off" "$(PROJECT_BLOCKED_DEFAULT=0 _project_blocked_default)" ""
sig=$(PROJECT_NOW=$(ep '2026-10-09 09:00') _project_signals)
hasnt "a matured default already due: nothing pulled early" "$sig" "DEFAULT DUE (early)"
has "a matured default already due: the normal signal" "$sig" 'DEFAULT DUE: no human answered Q6 "Plant size"'
"$REPO/tools/librarian-project" answer "$ID" Q9 "Texas 2030 ERCOT mix" >/dev/null 2>&1
eq "a human answer waiting: nothing pulled early" "$(_project_blocked_default)" ""
printf 'active\n' > "$P/STATE"
sed -i 's/^\(### Q9 .*STATUS: \)open/\1answered/' "$P/questions.md"
sed -i 's/^\(### Q6 .*STATUS: \)open/\1moot/' "$P/questions.md"
printf 'blocked\nx\n' > "$P/STATE"
eq "every open question closed or undated: nothing pulled early" "$(_project_blocked_default)" ""
printf 'active\n' > "$P/STATE"
ts_recent=$(TZ=UTC date -u -d "@$((PROJECT_NOW - 3600))" +%Y-%m-%dT%H:%M:%SZ)
ts_old=$(TZ=UTC date -u -d "@$((PROJECT_NOW - 90000))" +%Y-%m-%dT%H:%M:%SZ)
printf '{"ts":"%s","in_tok":900,"out_tok":100}\n{"ts":"%s","in_tok":500000,"out_tok":0}\n{"ts":"%s","in_tok":7000,"out_tok":1000}\n' \
    "$ts_recent" "$ts_old" "$ts_recent" > "$ID/usage/llm.jsonl"
eq "tokens counted over 24h only" "$(_project_tokens_24h)" 9000
PROJECT_DAILY_TOKENS=11000
has "budget warning near the cap" "$(_project_signals)" "BUDGET: 9000 tokens of 11000 tokens"
has "budget warning names the free hold line" "$(_project_signals)" "At 9900 tokens the runtime pauses ordinary wakes for free"
_project_should_hold spontaneous && bad "under the hold line: wakes run" || ok "under the hold line: wakes run"
# Budget hold (live trial 2026-10-16: 127 paid rest wakes overnight at about 90% of the cap).
PROJECT_DAILY_TOKENS=10000
eq "hold line is 90% of the daily cap" "$(_project_hold_line)" 9000
has "at the hold line: BUDGET HOLD signal" "$(_project_signals)" "BUDGET HOLD: 9000 tokens of 10000 tokens"
_project_should_hold spontaneous && ok "at the hold line: a timer wake skips the model" || bad "at the hold line: a timer wake skips the model"
_project_should_hold reactive && bad "at the hold line: a reactive wake still runs" || ok "at the hold line: a reactive wake still runs"
( _project_due_ritual() { printf 'daily 2026-10-01'; }; _project_should_hold spontaneous ) && bad "at the hold line: a due ritual still runs" || ok "at the hold line: a due ritual still runs"
( _project_signals() { printf -- '- HUMAN ANSWER: Q1\n'; }; _project_should_hold spontaneous ) && bad "at the hold line: a human answer still runs" || ok "at the hold line: a human answer still runs"
( _project_signals() { printf -- '- DEFAULT DUE: Q2\n'; }; _project_should_hold spontaneous ) && bad "at the hold line: a matured default still runs" || ok "at the hold line: a matured default still runs"
PROJECT_BUDGET_HOLD=0 _project_should_hold spontaneous && bad "PROJECT_BUDGET_HOLD=0 turns the hold off" || ok "PROJECT_BUDGET_HOLD=0 turns the hold off"
PROJECT_BUDGET_HOLD=1 _project_should_hold spontaneous && bad "PROJECT_BUDGET_HOLD=1 turns the hold off" || ok "PROJECT_BUDGET_HOLD=1 turns the hold off"
PROJECT_BUDGET_HOLD=0.95 _project_should_hold spontaneous && bad "a higher hold line is not reached yet" || ok "a higher hold line is not reached yet"
PROJECT_DAILY_TOKENS=8000
has "budget spent signal" "$(_project_signals)" "BUDGET SPENT"
eq "budget floor" "$(_project_delay_floor)" 1800
PROJECT_DAILY_TOKENS=1000000
eq "pacing: a 50K-token wake waits 50K/1M of a day" "$(_project_delay_floor 50000)" 4320
PROJECT_PACE=0 eq "PROJECT_PACE=0 turns pacing off" "$(PROJECT_PACE=0 _project_delay_floor 50000)" 0
lines=$(_project_ledger_lines)
printf '{"ts":"%s","provider":"anthropic","in_tok":100,"out_tok":50,"cache_tok":2000}\n{"ts":"%s","provider":"openai","in_tok":3000,"out_tok":50,"cache_tok":2000}\n' \
    "$ts_recent" "$ts_recent" >> "$ID/usage/llm.jsonl"
eq "wake spend: cache reads at a tenth (Anthropic 100+50+200, OpenAI 3000+50-1800)" "$(_project_tokens_after "$lines")" 1600
unset PROJECT_DAILY_TOKENS

# ── stall ────────────────────────────────────────────────────────────────────
touch -d "@$((PROJECT_NOW - 20 * 3600))" "$P/journal.md"
has "stall flagged after 12h without journal change" "$(_project_signals)" "STALL"
touch -d "@$((PROJECT_NOW - 3600))" "$P/journal.md"
hasnt "no stall when the journal moved" "$(_project_signals)" "STALL"

# ── idle wakes (live trial 2026-10-16: ~50 paid "nothing due" wakes an hour) ─
G="$WORK/idle-repo"; mkdir -p "$G/model"
git -C "$G" init -q && printf 'active\n' > "$G/STATE" && printf 'j\n' > "$G/journal.md" && printf 'l\n' > "$G/librarian.md"
git -C "$G" add -A && git -C "$G" -c user.name=t -c user.email=t@t commit -qm init
(
    _project_dir() { printf '%s' "$G"; }
    h=$(_project_head)
    [[ -n "$h" ]] && ok "idle: HEAD recorded before the wake" || bad "idle: HEAD recorded before the wake"
    _project_wake_changed "$h" && bad "idle: a clean tree is no work" || ok "idle: a clean tree is no work"
    printf 'resting\n' >> "$G/STATE"; printf 'x\n' >> "$G/librarian.md"; printf 'q\n' > "$G/questions-summary.md"
    _project_wake_changed "$h" && bad "idle: STATE, librarian.md and questions-summary.md alone are no work" || ok "idle: STATE, librarian.md and questions-summary.md alone are no work"
    printf 'new entry\n' >> "$G/journal.md"
    _project_wake_changed "$h" && ok "idle: a journal edit is work" || bad "idle: a journal edit is work"
    git -C "$G" add -A && git -C "$G" -c user.name=t -c user.email=t@t commit -qm wake
    _project_wake_changed "$h" && ok "idle: work the mind committed itself still counts" || bad "idle: work the mind committed itself still counts"
    h=$(_project_head); printf 'r\n' > "$G/model/result.json"
    _project_wake_changed "$h" && ok "idle: a new untracked file is work" || bad "idle: a new untracked file is work"
)
rm -f "$ID/run/project_idle_streak"
eq "idle: no streak yet" "$(_project_idle_streak)" 0
eq "idle: no streak, no floor" "$(_project_idle_floor)" 0
_project_note_wake idle
eq "idle: one idle wake waits PROJECT_IDLE_FLOOR" "$(_project_idle_floor)" 600
hasnt "idle: one idle wake gets no IDLE signal" "$(_project_signals)" "- IDLE:"
_project_note_wake idle
eq "idle: streak counts idle wakes" "$(_project_idle_streak)" 2
eq "idle: the floor doubles per idle wake" "$(_project_idle_floor)" 1200
has "idle: two idle wakes add the IDLE signal" "$(_project_signals)" "- IDLE: your last 2 wakes changed no project file"
has "idle: the signal points at the free blocked rest" "$(_project_signals)" "set STATE to blocked: a blocked mind rests for free"
eq "idle: an active mind's delay floor follows the streak" "$(PROJECT_PACE=0 _project_delay_floor 0)" 1200
( _project_due_ritual() { printf 'daily 2026-10-01'; }; eq "idle: a due ritual is not delayed" "$(PROJECT_PACE=0 _project_delay_floor 0)" 0 )
( _project_signals() { printf -- '- HUMAN ANSWER: Q1\n'; }; eq "idle: a human answer is not delayed" "$(PROJECT_PACE=0 _project_delay_floor 0)" 0 )
_project_note_wake idle; _project_note_wake idle; _project_note_wake idle
eq "idle: the floor stops at PROJECT_IDLE_CAP" "$(_project_idle_floor)" 1800
eq "idle: PROJECT_IDLE_FLOOR=0 turns it off" "$(PROJECT_IDLE_FLOOR=0 _project_idle_floor)" 0
hasnt "idle: PROJECT_IDLE_NUDGE=0 turns the signal off" "$(PROJECT_IDLE_NUDGE=0 _project_signals)" "- IDLE:"
cp "$P/STATE" "$WORK/STATE.keep"; printf 'blocked\n' > "$P/STATE"
hasnt "idle: no IDLE signal once STATE is blocked" "$(_project_signals)" "- IDLE:"
cp "$WORK/STATE.keep" "$P/STATE"
_project_note_wake work
eq "idle: a working wake resets the streak" "$(_project_idle_streak)" 0
eq "idle: and the floor" "$(_project_idle_floor)" 0

# ── idle rest without a model call ───────────────────────────────────────────
# An active mind on an idle streak skips the model (run A: 495 paid "Rest"
# wakes, $142) until something changes, something is due, or an hour passes.
# Nothing due: stub the ritual and signal checks (restored after).
eval "_orig_due_ritual() $(declare -f _project_due_ritual | tail -n +2)"
eval "_orig_signals() $(declare -f _project_signals | tail -n +2)"
_project_due_ritual() { :; }; _project_signals() { :; }
{
    git -C "$P" add -A >/dev/null; git -C "$P" -c user.name=ada -c user.email=a@x commit -qm "before idle" >/dev/null
    printf 'active\n' > "$P/STATE"
    rm -f "$ID/run/project_last_real_wake"
    _project_note_wake idle; _project_note_wake idle; _project_note_wake idle
    _project_should_skip_idle spontaneous && bad "idle skip: no record of a real wake, the wake runs" || ok "idle skip: no record of a real wake, the wake runs"
    _project_note_real_wake
    _project_should_skip_idle spontaneous && ok "idle skip: three idle wakes and nothing changed, no model call" || bad "idle skip: three idle wakes and nothing changed, no model call"
    _project_should_skip_idle reactive && bad "idle skip: a reactive wake always runs" || ok "idle skip: a reactive wake always runs"
    PROJECT_IDLE_SKIP_STREAK=4 _project_should_skip_idle spontaneous && bad "idle skip: below PROJECT_IDLE_SKIP_STREAK the wake runs" || ok "idle skip: below PROJECT_IDLE_SKIP_STREAK the wake runs"
    PROJECT_IDLE_SKIP_STREAK=0 _project_should_skip_idle spontaneous && bad "idle skip: PROJECT_IDLE_SKIP_STREAK=0 turns it off" || ok "idle skip: PROJECT_IDLE_SKIP_STREAK=0 turns it off"
    PROJECT_NOW=$((PROJECT_NOW + 3600)) _project_should_skip_idle spontaneous && bad "idle skip: an hour after the last real wake the wake runs" || ok "idle skip: an hour after the last real wake the wake runs"
    PROJECT_NOW=$((PROJECT_NOW + 1800)) PROJECT_IDLE_SKIP_MAX=1200 _project_should_skip_idle spontaneous && bad "idle skip: PROJECT_IDLE_SKIP_MAX sets that hour" || ok "idle skip: PROJECT_IDLE_SKIP_MAX sets that hour"
    printf 'resting\n' >> "$P/STATE"; _project_write_summary
    _project_should_skip_idle spontaneous && ok "idle skip: STATE and questions-summary.md alone change nothing" || bad "idle skip: STATE and questions-summary.md alone change nothing" "$(_project_newer_than_real_wake)"
    printf 'blocked\n' > "$P/STATE"
    _project_should_skip_idle spontaneous && bad "idle skip: only for STATE active (blocked has its own rest)" || ok "idle skip: only for STATE active (blocked has its own rest)"
    printf 'active\n' > "$P/STATE"
    ( _project_due_ritual() { printf 'daily 2026-10-01'; }; _project_should_skip_idle spontaneous ) && bad "idle skip: a due ritual runs the wake" || ok "idle skip: a due ritual runs the wake"
    ( _project_signals() { printf -- '- DEFAULT DUE: Q1\n'; }; _project_should_skip_idle spontaneous ) && bad "idle skip: a matured default runs the wake" || ok "idle skip: a matured default runs the wake"
    ( _project_signals() { printf -- '- HUMAN ANSWER: Q1\n'; }; _project_should_skip_idle spontaneous ) && bad "idle skip: a human answer runs the wake" || ok "idle skip: a human answer runs the wake"
    mkdir -p "$P/.blind/run1"; printf 'done\n' > "$P/.blind/run1/report.md"
    _project_should_skip_idle spontaneous && bad "idle skip: a background job's output under project/ runs the wake" || ok "idle skip: a background job's output under project/ runs the wake"
    eq "idle skip: the new file is named" "$(_project_newer_than_real_wake)" ".blind/run1/report.md"
    rm -rf "$P/.blind/run1"
    _project_should_skip_idle spontaneous && ok "idle skip: back to skipping once it is gone" || bad "idle skip: back to skipping once it is gone"
    printf 'between wakes\n' >> "$P/journal.md"; touch -d '-2 minutes' "$P/journal.md"; _project_commit_outside
    _project_should_skip_idle spontaneous && bad "idle skip: a commit since the last real wake runs the wake" || ok "idle skip: a commit since the last real wake runs the wake"
    _project_note_real_wake
    _project_should_skip_idle spontaneous && ok "idle skip: a new real wake is the new baseline" || bad "idle skip: a new real wake is the new baseline"
    chmod u+w "$P/spec.md"; printf '\nA second brief.\n' >> "$P/spec.md"; touch -d '-2 minutes' "$P/spec.md"
    _project_should_skip_idle spontaneous && bad "idle skip: a new brief in spec.md runs the wake" || ok "idle skip: a new brief in spec.md runs the wake"
    cp "$ID/project-pristine/spec.md" "$P/spec.md"; touch -d '-2 minutes' "$P/spec.md"; chmod a-w "$P/spec.md"
    _project_should_skip_idle spontaneous && ok "idle skip: the same brief again skips" || bad "idle skip: the same brief again skips"
    _project_note_wake work
    _project_should_skip_idle spontaneous && bad "idle skip: a working wake ends the streak" || ok "idle skip: a working wake ends the streak"
    git -C "$P" add -A >/dev/null; git -C "$P" -c user.name=ada -c user.email=a@x commit -qm "after idle" >/dev/null
}
eval "_project_due_ritual() $(declare -f _orig_due_ritual | tail -n +2)"
eval "_project_signals() $(declare -f _orig_signals | tail -n +2)"
rm -f "$ID/run/project_last_real_wake"; _project_note_wake work

# ── deadline, phases and the deliverable ─────────────────────────────────────
setstart '2026-10-01 00:00'
setend() { chmod u+w "$ID/project-pristine/end_at" 2>/dev/null; printf '%s' "$(ep "$1")" > "$ID/project-pristine/end_at"; }
setend '2026-10-15 00:00'                       # a 14-day run
PROJECT_NOW=$(ep '2026-10-03 12:00'); eq "phase: build in the first half" "$(_project_phase)" build
PROJECT_NOW=$(ep '2026-10-09 12:00'); eq "phase: harden in the second half" "$(_project_phase)" harden
PROJECT_NOW=$(ep '2026-10-13 06:00'); eq "phase: final in the last 2 days" "$(_project_phase)" final
has "final stretch signal" "$(_project_signals)" "FINAL STRETCH: 1d 18h left. No new scope."
PROJECT_NOW=$(ep '2026-10-03 12:00')
has "build signal names the time left" "$(_project_signals)" "DEADLINE: 11d 12h left in the run (phase: build)"
has "clock line shows day of N and the end" "$(_project_section)" "Project clock: day 3 of 14, week 01, phase build."
_project_deliverable_started && bad "template deliverable is not started" || ok "template deliverable is not started"
has "day 3, no draft: deliverable missing" "$(_project_signals)" "DELIVERABLE MISSING: day 3"
PROJECT_NOW=$(ep '2026-10-01 18:00')
hasnt "day 1: not yet missing" "$(_project_signals)" "DELIVERABLE MISSING"
PROJECT_NOW=$(ep '2026-10-02 06:00')
has "day 2: missing, and it asks for the crude model first" "$(_project_signals)" "Build the crude end-to-end model now"
PROJECT_NOW=$(ep '2026-10-03 12:00')
printf '# Deliverable\n## Answer\nAbout 4 USD/kg, wide band.\n' > "$P/deliverable.md"
touch -d "@$((PROJECT_NOW - 3600))" "$P/deliverable.md"
_project_deliverable_started && ok "draft counts as started" || bad "draft counts as started"
hasnt "fresh draft: no deliverable signal" "$(_project_signals)" "DELIVERABLE"
touch -d "@$((PROJECT_NOW - 72 * 3600))" "$P/deliverable.md"
has "deliverable stale after 48h" "$(_project_signals)" "DELIVERABLE STALE: project/deliverable.md has not changed in 72h"
touch -d "@$((PROJECT_NOW - 3600))" "$P/deliverable.md"
PROJECT_NOW=$(ep '2026-10-15 09:00')
eq "phase: ended" "$(_project_phase)" ended
eq "final ritual due at the end, ahead of weekly and daily" "$(_project_due_ritual)" "final final"
has "final ritual instructions" "$(_project_signals)" "project/reviews/final.md"
has "run ended signal" "$(_project_signals)" "THE RUN HAS ENDED"
printf 'draft\n' > "$P/reports/final.md"
touch -d "@$(( $(_project_end_at) - 3600 ))" "$P/reports/final.md"
eq "a final.md drafted before the end leaves the final ritual due" "$(_project_due_ritual)" "final final"
printf 'final\n' > "$P/reports/final.md"
touch -d "@$PROJECT_NOW" "$P/reports/final.md"
printf 'active\n' > "$P/STATE"
eq "after the end and the final report, the mind rests" "$(_project_delay_floor)" 3600
_project_should_skip_rest spontaneous && ok "finished run: timer wakes skip the model" || bad "finished run: timer wakes skip the model"
_project_should_skip_rest reactive && bad "a reactive wake still runs" || ok "a reactive wake still runs"
hasnt "no stale nag after the end" "$(_project_signals)" "DELIVERABLE STALE"
# A human extends the run.
git -C "$P" add -A >/dev/null; git -C "$P" -c user.name=ada -c user.email=a@x commit -qm "final" >/dev/null
out=$(PROJECT_NOW="$PROJECT_NOW" "$REPO/tools/librarian-project" deadline "$ID" --end 2099-01-01 2>&1); rc=$?
eq "deadline --end succeeds" "$rc" 0
has "extension reopens a finished run" "$out" "reopened"
[[ ! -f "$P/reports/final.md" ]] && ls "$P"/reports/final-superseded-*.md >/dev/null 2>&1 && ok "old final report kept under a dated name" || bad "old final report kept under a dated name"
has "STATE back to active" "$(head -1 "$P/STATE")" "active"
eq "extension committed as human" "$(git -C "$P" log -1 --format=%an)" "human"
out=$("$REPO/tools/librarian-project" deadline "$ID" --end 2020-01-01 2>&1); rc=$?
[[ $rc -ne 0 ]] && ok "an end in the past is refused" || bad "an end in the past is refused"
setend '2026-10-15 00:00'; rm -f "$P"/reports/final-superseded-*.md
PROJECT_NOW=$(ep '2026-10-06 09:00')
rm -f "$ID/project-pristine/end_at"
eq "no end date: open phase" "$(_project_phase)" open
hasnt "open-ended run: no deadline signal" "$(_project_signals)" "DEADLINE"

# ── accelerated clock and the whole-run budget ───────────────────────────────
S0=$(ep '2026-10-01 00:00'); setstart '2026-10-01 00:00'; setend '2026-10-09 00:00'   # an 8-day run
unset PROJECT_NOW
export PROJECT_TIME_SCALE=24 PROJECT_REAL_NOW=$((S0 + 3600))        # one real hour in
eq "scaled clock: 1 real hour is 1 project day" "$(_pj_now)" $((S0 + 86400))
has "scaled clock: day 2 in the section" "$(_project_section)" "Project clock: day 2 of 8"
has "scaled clock: the wake is told" "$(_project_signals)" "PROJECT TIME runs 24x faster"
touch -d "@$((S0 + 1800))" "$P/journal.md"
eq "file times convert to project time" "$(_pj_mtime "$P/journal.md")" $((S0 + 43200))
PROJECT_DAILY_TOKENS=1000000
eq "pacing in real seconds under scale" "$(_project_delay_floor 50000)" 180
printf '{"ts":"%s","in_tok":100,"out_tok":0}\n{"ts":"%s","in_tok":7,"out_tok":0}\n{"ts":"%s","in_tok":5000,"out_tok":0}\n' \
    "$(TZ=UTC date -u -d "@$((S0 - 600))" +%Y-%m-%dT%H:%M:%SZ)" "$(TZ=UTC date -u -d "@$((S0 + 300))" +%Y-%m-%dT%H:%M:%SZ)" \
    "$(TZ=UTC date -u -d "@$((S0 + 3000))" +%Y-%m-%dT%H:%M:%SZ)" > "$ID/usage/llm.jsonl"
PROJECT_REAL_NOW=$((S0 + 5400))   # 1.5 real hours in: the budget day began at S0+1800
eq "budget day is one project day (a real hour)" "$(_project_tokens_24h)" 5000
eq "run total counts from the project start" "$(_project_tokens_total)" 5007
eq "wake ceiling: half the daily cap by default" "$(_project_wake_ceiling)" 500000
PROJECT_TOTAL_TOKENS=6000 eq "wake ceiling: never more than the run budget left" "$(PROJECT_TOTAL_TOKENS=6000 _project_wake_ceiling)" 993
eq "wake ceiling: explicit setting wins" "$(PROJECT_WAKE_TOKENS=1234 _project_wake_ceiling)" 1234
has "wake budget signal" "$(_project_signals)" "WAKE BUDGET: about 500000 tokens"
PROJECT_TOTAL_TOKENS=6000
_project_over_budget && bad "under the run cap" || ok "under the run cap"
has "run budget warning past 70%" "$(_project_signals)" "RUN BUDGET: 5007 tokens of the 6000 tokens"
PROJECT_TOTAL_TOKENS=5000
_project_over_budget && ok "over the run cap" || bad "over the run cap"
eq "budget rest scaled" "$(_project_delay_floor 0)" 75
printf 'blocked\nx\n' > "$P/STATE"; unset PROJECT_TOTAL_TOKENS
printf 'eval\n' > "$P/daily/2026-10-01.md"   # the project day that closed is done
eq "rest floor scaled" "$(_project_delay_floor 0)" 150
printf 'active\n' > "$P/STATE"
# Dollar budgets: the unit switches, and cost_usd is what counts.
printf '{"ts":"%s","provider":"bedrock-invoke","in_tok":100,"out_tok":0,"cost_usd":0.30}\n{"ts":"%s","provider":"bedrock-invoke","in_tok":100,"out_tok":0,"cost_usd":0.25}\n' \
    "$(TZ=UTC date -u -d "@$((S0 + 3000))" +%Y-%m-%dT%H:%M:%SZ)" "$(TZ=UTC date -u -d "@$((S0 + 5000))" +%Y-%m-%dT%H:%M:%SZ)" > "$ID/usage/llm.jsonl"
unset PROJECT_DAILY_TOKENS
PROJECT_DAILY_USD=1
eq "a dollar cap switches the unit" "$(_project_unit)" usd
eq "spend in micro-dollars" "$(_project_tokens_total)" 550000
eq "spend formats as dollars" "$(_project_fmt "$(_project_tokens_total)")" '$0.55'
eq "daily dollar cap in micro-dollars" "$(_project_cap_daily)" 1000000
eq "wake ceiling: half the daily dollar cap" "$(_project_wake_ceiling)" 500000
eq "dollar hold line: 90% of the daily cap" "$(_project_fmt "$(_project_hold_line)")" '$0.90'
_project_budget_hold && bad "\$0.55 of \$1: no hold" || ok "\$0.55 of \$1: no hold"
PROJECT_BUDGET_HOLD=0.5 _project_budget_hold && ok "\$0.55 past a \$0.50 hold line: hold" || bad "\$0.55 past a \$0.50 hold line: hold"
has "wake budget signal in dollars" "$(_project_signals)" 'WAKE BUDGET: about $0.50'
PROJECT_TOTAL_USD=0.5
_project_over_budget && ok "over a dollar run cap" || bad "over a dollar run cap"
unset PROJECT_DAILY_USD PROJECT_TOTAL_USD
eq "no dollar caps: back to tokens" "$(_project_unit)" tokens
unset PROJECT_DAILY_TOKENS PROJECT_TIME_SCALE PROJECT_REAL_NOW
PROJECT_NOW=$(ep '2026-10-06 09:00')
rm -f "$ID/project-pristine/end_at"

# ── commit ───────────────────────────────────────────────────────────────────
before=$(git -C "$P" rev-list --count HEAD)
_project_commit "Added discount-rate default. Next: capex."
eq "commit made when files changed" "$(git -C "$P" rev-list --count HEAD)" $((before + 1))
eq "commit message is the FINAL" "$(git -C "$P" log -1 --format=%s)" "Added discount-rate default. Next: capex."
_project_commit "nothing"
eq "no empty commit" "$(git -C "$P" rev-list --count HEAD)" $((before + 1))

# ── blind ────────────────────────────────────────────────────────────────────
FAKE="$WORK/fakebin"; mkdir -p "$FAKE"
cat > "$FAKE/shellm" <<'EOF'
#!/usr/bin/env bash
pf=""; while [[ $# -gt 0 ]]; do [[ "$1" == --prompt-file ]] && pf="$2"; shift; done
echo "parent=${_SHELLM_PARENT_TRAJ_ID:-none} traj=${TRAJ_ID:-none}"
echo "files: $(find . -type f | sort | tr '\n' ' ')"
grep -c 'adversarial reviewer' "$pf" || true
EOF
chmod +x "$FAKE/shellm"
cd "$ID/workdir"
out=$(PATH="$FAKE:$PATH" _SHELLM_PARENT_TRAJ_ID=abc TRAJ_ID=root blind --role adversary -f project/project-memory.md \
    --out project/reviews/claim.md "The LCOH is 3 USD/kg" 2>/dev/null); rc=$?
eq "blind runs" "$rc" 0
has "blind hides the parent trajectory" "$out" "parent=none traj=none"
has "blind passes only the given file" "$out" "files: ./project/project-memory.md "
has "blind uses the role prompt" "$out" "1"
has "blind --out writes the answer" "$(cat project/reviews/claim.md 2>/dev/null)" "parent=none"
# Run D: the lessons a piece of work applied are hidden from the reviewer and
# recorded, before the verdict, in .blind/lessons.jsonl.
mkdir -p "$FAKE/l"
cat > "$FAKE/l/shellm" <<'EOF'
#!/usr/bin/env bash
echo "BROKEN: the fleet total double counts PHEVs in the 2030 cohort"
echo "seen: $(find . -type f | sort | tr '\n' ' ') lessons-lines=$(find . -type f -exec cat {} + | grep -ci 'lessons applied')"
EOF
chmod +x "$FAKE/l/shellm"
L1=01JA0000000000000000000001; L2=01JA0000000000000000000002
printf 'C1. The fleet is 42.\nLessons applied: %s\n' "$L1" > project/reviews/f-claims.md
printf 'Lessons applied: %s\n' "$L2" > project/reviews/f-lessons.md
rm -f project/.blind/lessons.jsonl
out=$(PATH="$FAKE/l:$PATH" blind --role adversary -f project/reviews/f-claims.md -f project/reviews/f-lessons.md \
    --out project/reviews/f-adversary.md "The fleet is 42" 2>/dev/null); rc=$?
eq "blind with lessons runs" "$rc" 0
has "the reviewer gets the claims file" "$out" "./project/reviews/f-claims.md"
has "the reviewer never sees a Lessons applied line" "$out" "lessons-lines=0"
case "$out" in *f-lessons.md*) bad "the -lessons.md sidecar is not handed over" "$out" ;; *) ok "the -lessons.md sidecar is not handed over" ;; esac
led=$(cat project/.blind/lessons.jsonl 2>/dev/null)
has "ledger names the claims file's lesson" "$led" "$L1"
has "ledger names the sidecar's lesson" "$led" "$L2"
has "ledger keeps the verdict line" "$led" "BROKEN: the fleet total double counts PHEVs"
has "ledger keeps the --out path" "$led" "project/reviews/f-adversary.md"
rm -f project/reviews/f-claims.md project/reviews/f-lessons.md project/reviews/f-adversary.md project/.blind/lessons.jsonl
out=$(PATH="$FAKE/l:$PATH" blind --role adversary -f project/project-memory.md "x" 2>/dev/null)
[[ ! -e project/.blind/lessons.jsonl ]] && ok "no ledger line when no lessons were named" || bad "no ledger line when no lessons were named"
saved=$(ls project/reviews/*-adversary.md 2>/dev/null | head -1)
[[ -n "$saved" ]] && grep -q "BROKEN: the fleet total" "$saved" && ok "an adversary review without --out is saved under reviews/" || bad "an adversary review without --out is saved under reviews/" "$(ls project/reviews)"
err=$(PATH="$FAKE/l:$PATH" blind --role adversary -f project/project-memory.md "x" 2>&1 >/dev/null)
has "a review without Claim verdicts lines is flagged" "$err" "has no Claim verdicts lines"
rm -f project/reviews/*-adversary.md
out=$(PATH="$FAKE:$PATH" blind --role coldeyes 2>/dev/null)
has "coldeyes gets its default files" "$out" "./project/deliverable.md ./project/journal.md ./project/project-memory.md ./project/questions.md ./project/spec.md"
out=$(PATH="$FAKE:$PATH" LLM_USAGE_LEDGER="$WORK/wl.jsonl" PROJECT_LEDGER_MARK=1 PROJECT_WAKE_TOKENS=1000 \
    bash -c 'printf "{\"in_tok\":99999}\n{\"in_tok\":600,\"out_tok\":500}\n" > "$LLM_USAGE_LEDGER"; blind --role explorer "x"' 2>&1); rc=$?
[[ $rc -ne 0 ]] && ok "blind refuses once the wake spent its ceiling" || bad "blind refuses once the wake spent its ceiling" "$out"
has "refusal says what to do" "$out" "this wake has spent its budget (110% of its share"
out=$(PATH="$FAKE:$PATH" LLM_USAGE_LEDGER="$WORK/wl.jsonl" PROJECT_LEDGER_MARK=1 PROJECT_WAKE_TOKENS=5000 blind --role explorer "x" 2>/dev/null); rc=$?
[[ $rc -eq 0 ]] && ok "blind runs while the wake is under its ceiling" || bad "blind runs while the wake is under its ceiling"
out=$(cd "$P" && PATH="$FAKE:$PATH" PROJECT_DIR="$P" blind --role coldeyes 2>/dev/null); rc=$?
eq "coldeyes works from inside project/" "$rc" 0
has "role files resolved against the workspace" "$out" "./project/spec.md"
mkdir -p "$P/project/reviews"   # a stray project/project/ must not be taken for the project
out=$(cd "$P" && PATH="$FAKE:$PATH" blind --role adversary "x" 2>&1); rc=$?
eq "from inside project/, the project is found despite a stray project/project/" "$rc" 0
rm -rf "$P/project"
(cd "$P" && PATH="$FAKE:$PATH" PROJECT_DIR="$P" blind --role coldeyes --out project/reviews/inside.md >/dev/null 2>&1)
[[ -f "$P/reviews/inside.md" && ! -e "$P/project" ]] && ok "--out project/... from inside project/ lands in project/reviews" || bad "--out project/... from inside project/ lands in project/reviews"
rm -f "$P/reviews/inside.md"
# delegate: blind with the helper role on a cheaper model.
cat > "$FAKE/shellm" <<'EOF'
#!/usr/bin/env bash
echo "args: $*"
pf=""; while [[ $# -gt 0 ]]; do [[ "$1" == --prompt-file ]] && pf="$2"; shift; done
grep -c 'smaller, cheaper model' "$pf" || true
EOF
chmod +x "$FAKE/shellm"
out=$(cd "$ID/workdir" && PATH="$FAKE:$PATH" SHELLM_MODEL=us.anthropic.claude-opus-5-5 delegate -f project/project-memory.md "List the values" 2>/dev/null)
has "delegate picks the matching cheap model" "$out" "--model us.anthropic.claude-haiku-4-5-20251001-v1:0"
has "delegate caps its steps" "$out" "--max-iterations 15"
has "delegate uses the helper role" "$out" "1"
out=$(cd "$ID/workdir" && PATH="$FAKE:$PATH" SHELLM_MODEL=claude-opus-5-5 SHELLM_FAST_MODEL=claude-sonnet-5-5 delegate "x" 2>/dev/null)
has "delegate prefers the deployment's fast model" "$out" "--model claude-sonnet-5-5"
out=$(cd "$ID/workdir" && PATH="$FAKE:$PATH" BLIND_MODEL=main-x BLIND_MODEL_COLDEYES=bedrock-converse/us.meta.llama4 blind --role coldeyes 2>/dev/null)
has "per-role model for cold-eyes" "$out" "--model bedrock-converse/us.meta.llama4"
out=$(cd "$ID/workdir" && PATH="$FAKE:$PATH" BLIND_MODEL=main-x BLIND_MODEL_COLDEYES=bedrock-converse/us.meta.llama4 blind --role adversary "x" 2>/dev/null)
has "other roles keep BLIND_MODEL" "$out" "--model main-x"
out=$(cd "$ID/workdir" && PATH="$FAKE:$PATH" BLIND_MODEL_HELPER=should-not-win delegate -m cheap-y "x" 2>/dev/null)
has "an explicit -m beats the per-role model" "$out" "--model cheap-y"
out=$(cd "$ID/workdir" && PATH="$FAKE:$PATH" DELEGATE_MODEL=bedrock-converse/amazon.nova-lite-v1:0 delegate "x" 2>/dev/null)
has "DELEGATE_MODEL wins" "$out" "--model bedrock-converse/amazon.nova-lite-v1:0"
out=$(cd "$ID/workdir" && PATH="$FAKE:$PATH" LLM_USAGE_LEDGER="$WORK/wl.jsonl" PROJECT_LEDGER_MARK=1 PROJECT_WAKE_TOKENS=1000 delegate "x" 2>&1); rc=$?
[[ $rc -ne 0 ]] && ok "delegate respects the wake budget" || bad "delegate respects the wake budget" "$out"
has "blind runs are gitignored" "$(git -C "$P" status --porcelain)" "reviews/claim.md"
hasnt "blind scratch is not committed" "$(git -C "$P" status --porcelain)" ".blind"
cd /

# ── monolith step wiring (static) ────────────────────────────────────────────
step=$(cat "$REPO/thinkers/monolith/step")
has "step sources project.sh" "$step" '_lib/project.sh'
has "step picks the project prompt" "$step" 'prompt-project.md'
has "step commits project/" "$step" '_project_commit'
has "step skips the model under the budget hold" "$step" '_project_should_hold "$wake_mode"'
has "step records project HEAD before the run" "$step" 'project_head_before=$(_project_head)'
has "step counts a no-change wake as a rest for the backoff" "$step" '_project_wake_changed "${project_head_before:-}"'
has "step keeps reactive wakes out of the idle streak" "$step" '"$project_mode" -eq 1 && "$wake_mode" != reactive'
has "step caps each wake's steps" "$step" 'project_iter_flags=(--max-iterations'
has "blind caps its steps" "$(cat "$REPO/bin/blind")" '--max-iterations "$iters"'
has "blind reaches the sandbox" "$(cat "$REPO/thinkers/_lib/common.sh")" 'chat recap blind'

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
