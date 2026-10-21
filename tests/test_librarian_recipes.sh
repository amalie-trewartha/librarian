#!/usr/bin/env bash
# tests/test_librarian_recipes.sh — every `librarian` command the project-mode
# prompt, charter and rituals show the mind, run the way the mind runs it:
# inside the sandbox, where only LIBRARIAN_STORE is set (no IDENTITY_DIR) and
# the wake's request file sits next to the store. The first live librarian
# runs lost memories to three mismatches between the recipes and the CLI
# (no store path in the sandbox, no provenance without --source, and
# space-separated --tags), each found one wake at a time. When a recipe in
# thinkers/monolith/prompt-project.md or identities/project/ changes, add it
# here. No LLM calls (LIBRARIAN_LLM=0), no docker.
#
# Usage: tests/test_librarian_recipes.sh
set -uo pipefail
unset IDENTITY_DIR IDENTITY_NAME MEM_DIR TRAJ_DIR TRAJ_ID ROOT_TRAJ_ID PROJECT_DIR LIBRARIAN_STORE LIBRARIAN_NOW \
    LIBRARIAN_SRC PROJECT_NOW PROJECT_TIME_SCALE 2>/dev/null
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
export PATH="$REPO/tools:$REPO/bin:$PATH"
export LIBRARIAN_LLM=0

pass=0; fail=0
command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL python3 not found"; exit 1; }

WORK=$(mktemp -d)
trap 'cd /; rm -rf "$WORK"' EXIT
export HOME="$WORK/home"; mkdir -p "$HOME"
ID="$WORK/ident"; mkdir -p "$ID/run"
printf 'name=cns\n' > "$ID/info.txt"
printf 'I am {{identity_name}}.\n' > "$ID/core_identity_prompt.md"
IDENTITY_DIR="$ID" IDENTITY_NAME=cns librarian -q init >/dev/null
printf '### a\nI flag uncertainty explicitly.\n' > "$WORK/core.md"
IDENTITY_DIR="$ID" librarian -q identity seed "$WORK/core.md" >/dev/null
P=p-test
# The wake's request file, as the runtime leaves it before the mind runs.
printf '{"request_id": "REQ-RECIPES", "project": "%s", "phase": "building"}\n' "$P" > "$ID/run/librarian_request.json"

# The sandbox's environment.
SB() { env -u IDENTITY_DIR LIBRARIAN_STORE="$ID/librarian/store.sqlite" librarian "$@"; }
out=""
run() {  # run <name> <accepted exit codes> <librarian args...>
    local name="$1" want="$2" rc; shift 2
    out=$(SB "$@" 2>&1); rc=$?
    if [[ " $want " == *" $rc "* ]]; then pass=$((pass+1)); printf 'ok   %s\n' "$name"
    else fail=$((fail+1)); printf 'FAIL %s — exit %s, want %s: %s\n' "$name" "$rc" "$want" "$(printf '%s' "$out" | tr '\n' ' ' | head -c 300)"; fi
}
id_of() { printf '%s' "$out" | jq -r '.id // empty' 2>/dev/null; }

printf 'Decision: Fort Collins CO (real city).\nAlternatives: synthetic city, Bellingham WA.\nWhy: LODES 8.1 (2021) and ACS 2022 5-year bulk files need no key: `curl https://lehd.ces.census.gov/data/lodes/LODES8/co/` works.\nRules out: ABM.\n' > "$WORK/dec.md"
printf 'Fix: apt-get install -y python3-numpy (pip is blocked by PEP 668 in ubuntu:24.04); verified 2026-10-13.\n' > "$WORK/skill.md"
printf 'Week 1: the data probe took 3 wakes; next time probe all candidate cities in one script (data/probe.sh).\n' > "$WORK/retro.md"

# ── proposals (prompt-project.md decide and CAPTURE, rituals) ────────────────
# Space-separated tags, exactly as the live mind wrote them.
run "decide recipe: propose decision with space-separated tags" 0 propose --type decision \
    --summary "Which city does the mobility model use? Fort Collins CO, for key-free LODES/ACS" \
    --tags area:scope project:$P ctx:building --body-file "$WORK/dec.md"
DEC=$(id_of)
run "CAPTURE recipe: propose skill --tags pkg:x area:y" 0 propose --type skill \
    --summary "python3 scripts fail with No module named numpy: apt-get install python3-numpy" \
    --tags pkg:numpy area:tooling --body-file "$WORK/skill.md"
SK=$(id_of)
run "propose with comma-separated tags" 0 propose --type skill \
    --summary "Overpass returns 406 without a User-Agent: pass curl -A" --tags pkg:curl,area:sources \
    --body "Fix: curl -A 'librarian' https://overpass-api.de/api/interpreter; 406 without it, verified 2026-10-13."
run "daily ritual: propose retrospective --tags area:process" 0 propose --type retrospective \
    --summary "When probing open data for a case city: script all candidates in one pass" \
    --tags area:process --body-file "$WORK/retro.md"
run "free time / weekly: propose skill --tags scope:generic" 0 propose --type skill \
    --summary "Long curl downloads trip the 30 s inactivity kill: run them detached with setsid and poll a log" \
    --tags scope:generic area:tooling --body "Fix: setsid -f bash fetch.sh > fetch.log 2>&1, then tail fetch.log each step; verified 2026-10-13."
run "daily ritual: propose --type skill --supersedes <id>" 0 propose --type skill --supersedes "$SK" \
    --summary "python3 scripts fail with No module named numpy: apt-get install python3-numpy python3-pandas" \
    --tags pkg:numpy area:tooling --body "Fix: apt-get install -y python3-numpy python3-pandas (pip blocked by PEP 668); verified 2026-10-14."
printf 'Value: US small-urban (50k-199k UZA) bus fare $0.74 per boarding (2024).\nSource: NTD 2024 https://data.transportation.gov/resource/ekg5-frzt.json, computed in model/calib/ntd_bus_fare.py.\nReview: reviews/2026-10-14-bus-supply.md (SURVIVES).\n' > "$WORK/fact.md"
run "verify recipe: propose fact with space-separated tags" 0 propose --type fact \
    --summary "What is the average bus fare paid per boarding in US small cities? \$0.74 (NTD 2024)" \
    --tags area:sources area:transit --body-file "$WORK/fact.md"
prov=$(python3 -c 'import sqlite3,sys,json; r=sqlite3.connect(sys.argv[1]).execute("select provenance from nodes where id=?",(sys.argv[2],)).fetchone(); print(json.loads(r[0]).get("run_id"))' "$ID/librarian/store.sqlite" "$DEC")
if [[ "$prov" == REQ-RECIPES ]]; then pass=$((pass+1)); echo "ok   a recipe proposal's provenance names the wake"
else fail=$((fail+1)); echo "FAIL a recipe proposal's provenance names the wake — got '$prov'"; fi

# ── reading (prompt-project.md, daily ritual) ────────────────────────────────
run "search --tags pkg:x,area:y --text --type --limit" 0 search --tags pkg:numpy,area:tooling --text "numpy" --type skill --limit 10
run "search with space-separated tags" 0 search --tags pkg:numpy area:tooling --text "numpy"
run "daily ritual: search --type skill --limit 30" 0 search --type skill --limit 30
run "fetch <id> <id>" 0 fetch "$DEC" "$SK"
run "show <id>" 0 show "$DEC"
run "fetching the pack's request id is a clean not-found" 4 fetch REQ-RECIPES

# ── review and identity (daily and weekly rituals) ───────────────────────────
run "daily ritual: dispute <id> --reason" 0 dispute "$DEC" --reason "LODES 2021 is the latest year; the body says 2022"
run "identity list --working" 0 identity list --working
# 5 = refused (a bound or a core conflict), a valid outcome; a usage error is not.
run "identity edit recipe" "0 5" identity edit --summary "I script data probes before deciding" \
    --body "I script data probes for every candidate before deciding." --occasion weekly \
    --reason "week 1 probe took 3 wakes" --episodes "$DEC"
run "identity propose" 0 identity propose --summary "I state uncertainty as ranges." --body "I state uncertainty as ranges."
run "suggestion list" 0 suggestion list
run "suggestion respond <id> accept parses (unknown id is not-found)" 4 suggestion respond NOPE accept
run "weekly ritual: stats --week 01" 0 stats --week 01

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
