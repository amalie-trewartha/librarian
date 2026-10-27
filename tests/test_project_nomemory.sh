#!/usr/bin/env bash
# tests/test_project_nomemory.sh — the no-memory control run
# (librarian-project init --no-memory, LIBRARIAN_MEMORY=0): no store is made
# or can be made, the wake prompt, charter and rituals carry no librarian
# instructions, and the core identity and the humans' preferences still reach
# every wake as plain files. Everything else must match a memory run, so the
# control differs from it in memory only.
#
# Usage: tests/test_project_nomemory.sh
#
# No LLM calls, no docker.

set -uo pipefail
unset IDENTITY_DIR IDENTITY_NAME MEM_DIR TRAJ_DIR TRAJ_ID ROOT_TRAJ_ID PROJECT_DIR PROJECT_DAILY_TOKENS \
    PROJECT_DAILY_AT PROJECT_FREETIME LIBRARIAN_PROJECT_MODE LIBRARIAN_MEMORY LIBRARIAN_PROJECT_TEMPLATE 2>/dev/null

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
export PATH="$REPO/bin:$REPO/tools:$PATH"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
has() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then ok "$1"; else bad "$1" "missing '$3' in: $(printf '%s' "$2" | head -c 400)"; fi; }
hasnt() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then bad "$1" "unexpected '$3'"; else ok "$1"; fi; }
eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "got '$2', want '$3'"; fi; }

command -v git >/dev/null 2>&1 || { echo "FAIL git not found"; exit 1; }

WORK=$(mktemp -d)
trap 'cd /; chmod -R u+w "$WORK" 2>/dev/null; rm -rf "$WORK"' EXIT
export HOME="$WORK/home"; mkdir -p "$HOME"

mkid() {  # mkid <dir>
    mkdir -p "$1/run" "$1/usage"
    printf 'name=ada\ncreated=2026-10-01T00:00:00Z\n' > "$1/info.txt"
    printf 'I am {{identity_name}}.\n' > "$1/core_identity_prompt.md"
}
printf '# Brief\nEstimate the levelized cost of green hydrogen in Texas in 2030.\n' > "$WORK/spec.md"
printf -- '- Prefer a short, honest answer with stated gaps.\n- Cite primary sources.\n' > "$WORK/preferences.md"

# The memory words a control run must never be told to use.
memory_words='librarian (propose|search|fetch|dismiss|dispute|identity|capture|suggestion|stats)|memory pack|TASK MEMORIES|FROM EARLIER BRIEFS|Memories (SURVIVES|BROKEN|UNVERIFIABLE)'

# ── the template and prompt variants ─────────────────────────────────────────
T="$REPO/identities/project" N="$REPO/identities/project-nomemory"
for f in $(cd "$T" && find . -type f | sort); do
    case "$f" in
        ./charter.md|./rituals/*|./addenda.md) continue ;;
    esac
    if cmp -s "$T/$f" "$N/$f"; then ok "nomemory template: $f same as the memory template"
    else bad "nomemory template: $f same as the memory template" "differs; only charter, rituals and addenda may"; fi
done
eq "nomemory template has the same files" "$(cd "$N" && find . -type f | sort | tr '\n' ' ')" "$(cd "$T" && find . -type f | sort | tr '\n' ' ')"
for f in charter.md addenda.md rituals/daily.md rituals/weekly.md rituals/final.md rituals/freetime.md; do
    if grep -E -- "$memory_words" "$N/$f" >/dev/null; then bad "nomemory $f has no librarian instructions" "$(grep -E -- "$memory_words" "$N/$f" | head -2)"
    else ok "nomemory $f has no librarian instructions"; fi
done
# The memory template does have them, so the check above can fail.
grep -E -- "$memory_words" "$T/charter.md" >/dev/null && ok "memory charter does name the librarian (check is live)" || bad "memory charter does name the librarian (check is live)"
# Only memory steps were removed: every other ritual instruction is kept.
for kw in 'Curate project/journal.md' 'Curate project/questions.md' 'Rate today 1 to 5' 'The single most valuable next step'; do
    has "nomemory daily ritual keeps: $kw" "$(cat "$N/rituals/daily.md")" "$kw"
done
for kw in 'Cold-eyes review' 'Bring project/deliverable.md up to date' 'Plan for next week'; do
    has "nomemory weekly ritual keeps: $kw" "$(cat "$N/rituals/weekly.md")" "$kw"
done
has "nomemory final ritual keeps the final report" "$(cat "$N/rituals/final.md")" "Write project/reports/final.md"
PM="$REPO/thinkers/monolith/prompt-project.md" PN="$REPO/thinkers/monolith/prompt-project-nomemory.md"
if grep -iF librarian "$PN" >/dev/null; then bad "nomemory wake prompt never mentions the librarian" "$(grep -iF librarian "$PN" | head -2)"
else ok "nomemory wake prompt never mentions the librarian"; fi
eq "nomemory wake prompt offers the same functions" \
    "$(grep -oE '^- \*\*[a-z]+\*\*' "$PN" | tr '\n' ' ')" "$(grep -oE '^- \*\*[a-z]+\*\*' "$PM" | tr '\n' ' ')"
eq "nomemory wake prompt keeps the rules" "$(sed -n '/^## Rules/,$p' "$PN")" "$(sed -n '/^## Rules/,$p' "$PM")"
has "step picks the nomemory prompt when LIBRARIAN_MEMORY=0" "$(cat "$REPO/thinkers/monolith/step")" 'LIBRARIAN_MEMORY:-1}" == 0 ]] && prompt_file="$SCRIPT_DIR/prompt-project-nomemory.md"'
has "step closes no episode when LIBRARIAN_MEMORY=0" "$(grep -n 'librarian runtime post' -B1 "$REPO/thinkers/monolith/step")" 'LIBRARIAN_MEMORY:-1}" != 0'

# ── init --no-memory ─────────────────────────────────────────────────────────
ID="$WORK/ident"; mkid "$ID"
out=$("$REPO/tools/librarian-project" init "$ID" --spec "$WORK/spec.md" --preferences "$WORK/preferences.md" --no-memory 2>&1); rc=$?
eq "init --no-memory succeeds" "$rc" 0
has "init reports memory off" "$out" "off (--no-memory)"
P="$ID/workdir/project" PP="$ID/project-pristine"
has ".env sets LIBRARIAN_MEMORY=0" "$(cat "$ID/.env")" "LIBRARIAN_MEMORY=0"
[[ -e "$ID/librarian" ]] && bad "no librarian store is made" "$(ls "$ID/librarian")" || ok "no librarian store is made"
cmp -s "$P/../../project-pristine/charter.md" "$P/charter.md" && ok "project charter is the pristine one" || bad "project charter is the pristine one"
if grep -E -- "$memory_words" "$P/charter.md" "$PP/rituals/"*.md >/dev/null; then bad "the run's charter and rituals have no librarian instructions"
else ok "the run's charter and rituals have no librarian instructions"; fi
[[ -f "$PP/identity-core.md" ]] && ok "core identity kept in pristine" || bad "core identity kept in pristine"
[[ -f "$PP/preferences/preferences.md" ]] && ok "preferences kept in pristine" || bad "preferences kept in pristine"
[[ -w "$PP/preferences/preferences.md" ]] && bad "pristine preferences are read-only" || ok "pristine preferences are read-only"
[[ -e "$P/skills" ]] && bad "no skills mirror dir" || ok "no skills mirror dir"
for d in daily reports reviews explorations model free-time; do [[ -d "$P/$d" ]] && ok "init makes $d/" || bad "init makes $d/"; done
eq "one initial commit" "$(git -C "$P" rev-list --count HEAD 2>/dev/null)" 1

mkid "$WORK/y"
out=$("$REPO/tools/librarian-project" init "$WORK/y" --spec "$WORK/spec.md" --no-memory --fresh-memory 2>&1); rc=$?
[[ "$rc" -ne 0 ]] && ok "--no-memory with --fresh-memory is refused" || bad "--no-memory with --fresh-memory is refused"
has "the refusal says why" "$out" "do not go together"

# ── the wake prompt's project section ────────────────────────────────────────
export IDENTITY_DIR="$ID" IDENTITY_NAME=ada
# shellcheck source=/dev/null
source "$REPO/thinkers/_lib/project.sh"
sec=$(LIBRARIAN_MEMORY=0 _project_section)
has "section shows the core identity" "$sec" "Your core identity (human-approved"
has "section shows a core identity line" "$sec" "- No unsourced number ever stands in for a sourced one"
hasnt "section drops the identity-core file's header prose" "$sec" "Seeded into the librarian store"
has "section shows the preferences" "$sec" "Prefer a short, honest answer with stated gaps."
before=$(printf '%s' "$sec" | sed '/<<<llm-cache-break>>>/q')
has "identity and preferences sit in the cached prefix" "$before" "Cite primary sources."
hasnt "no memory pack header" "$sec" "Your memory pack"
sec_on=$(LIBRARIAN_MEMORY=1 _project_section)
hasnt "with memory on, the section has no plain identity block" "$sec_on" "Your core identity (human-approved"
g=$(LIBRARIAN_MEMORY=0 _project_signals "charter.md" 2>/dev/null)
has "guard still restores and says so" "$g" "GUARD: these read-only files had changed"
hasnt "guard line names no librarian command" "$g" "librarian identity edit"

# ── the CLI refuses ──────────────────────────────────────────────────────────
out=$(LIBRARIAN_MEMORY=0 IDENTITY_DIR="$ID" "$REPO/tools/librarian" propose --type skill --summary x --body y 2>&1); rc=$?
eq "librarian refuses with memory off" "$rc" 3
has "the refusal says memory is off" "$out" "memory is off in this run"
[[ -e "$ID/librarian" ]] && bad "a refused call makes no store" || ok "a refused call makes no store"
out=$(LIBRARIAN_MEMORY=0 "$REPO/tools/librarian" --help 2>&1); rc=$?
eq "even --help refuses (any use shows in the logs)" "$rc" 3
out=$(LIBRARIAN_MEMORY=1 "$REPO/tools/librarian" --help 2>&1); rc=$?
eq "with memory on the CLI still runs" "$rc" 0
has "the sandbox is passed LIBRARIAN_MEMORY" "$(cat "$REPO/thinkers/_lib/common.sh")" "for _lv in LIBRARIAN_SRC LIBRARIAN_MEMORY"

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
