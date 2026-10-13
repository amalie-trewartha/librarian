#!/usr/bin/env bash
# tests/test_librarian_cli.sh — the librarian CLI through its bash wrapper
# (tools/librarian → librarian/): init, the quality gate, summaries-only
# search, logged fetch, the fixed pack layout, episode close with credit,
# the export mirrors, and the human queue decided through librarian-project
# with git provenance. No LLM calls (LIBRARIAN_LLM=0), no docker.
#
# Usage: tests/test_librarian_cli.sh
set -uo pipefail
unset IDENTITY_DIR IDENTITY_NAME MEM_DIR TRAJ_DIR TRAJ_ID ROOT_TRAJ_ID PROJECT_DIR LIBRARIAN_STORE LIBRARIAN_NOW \
    LIBRARIAN_SRC PROJECT_NOW PROJECT_TIME_SCALE 2>/dev/null
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
export PATH="$REPO/tools:$REPO/bin:$PATH"
export LIBRARIAN_LLM=0

pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
has() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then ok "$1"; else bad "$1" "missing '$3' in: $(printf '%s' "$2" | head -c 500)"; fi; }
hasnt() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then bad "$1" "unexpected '$3'"; else ok "$1"; fi; }
eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "got '$2', want '$3'"; fi; }

command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL python3 not found"; exit 1; }

WORK=$(mktemp -d)
trap 'cd /; chmod -R u+w "$WORK" 2>/dev/null; rm -rf "$WORK"' EXIT
export HOME="$WORK/home"; mkdir -p "$HOME"
ID="$WORK/ident"; mkdir -p "$ID/run"
printf 'name=ada\ncreated=2026-10-01T00:00:00Z\n' > "$ID/info.txt"
printf 'I am {{identity_name}}.\n' > "$ID/core_identity_prompt.md"
export IDENTITY_DIR="$ID" IDENTITY_NAME=ada

# ── wrapper and init ─────────────────────────────────────────────────────────
out=$(librarian --version 2>&1); rc=$?
eq "wrapper finds the package next to itself" "$rc" 0
out=$(librarian search --tags pkg:x 2>&1); rc=$?
eq "no store is exit 2" "$rc" 2
out=$(librarian --text init 2>&1); rc=$?
eq "init succeeds" "$rc" 0
[[ -f "$ID/librarian/store.sqlite" ]] && ok "store created under the identity" || bad "store created under the identity"
out=$(librarian --text init 2>&1); eq "init is idempotent" "$?" 0

# ── the gate ─────────────────────────────────────────────────────────────────
out=$(librarian --text propose --type skill --summary "nothing specific" --body "just a lesson" --tags free 2>&1); rc=$?
eq "a bare lesson is rejected (exit 3)" "$rc" 3
has "rejection names the namespaced-tag rule" "$out" "namespaced tag"
has "rejection names the specifics rule" "$out" "specifics"
out=$(librarian propose --type skill --summary "colcon picks the system Eigen: set Eigen3_DIR explicitly" \
    --body 'Fix: `colcon build --cmake-args -DEigen3_DIR=/opt/eigen`; verified on Humble 2026-09-14.' \
    --tags pkg:colcon,pkg:eigen,area:build-system --source "journal 2026-09-14" --project p-1 2>&1); rc=$?
eq "a specific skill is stored" "$rc" 0
SK=$(printf '%s' "$out" | jq -r .id)
eq "new node enters probationary" "$(printf '%s' "$out" | jq -r .status)" probationary
out=$(librarian propose --type skill --summary "colcon picks the system Eigen: set Eigen3_DIR explicitly" \
    --body 'Fix: `colcon build --cmake-args -DEigen3_DIR=/opt/eigen`; verified on Humble 2026-09-14.' \
    --tags pkg:colcon,pkg:eigen,area:build-system --source "journal" --project p-1 2>&1)
eq "an identical proposal is merged, not written" "$(printf '%s' "$out" | jq -r .action)" merged
eq "merge names the target" "$(printf '%s' "$out" | jq -r .merge_target)" "$SK"

# ── search and fetch ─────────────────────────────────────────────────────────
out=$(librarian search --tags pkg:colcon --text "eigen link errors" 2>&1)
eq "search finds the skill" "$(printf '%s' "$out" | jq -r '.[0].id')" "$SK"
hasnt "search returns no bodies" "$out" '"body"'
out=$(librarian --text search --tags pkg:colcon 2>&1)
has "text search marks probation" "$out" "PROBATIONARY"
out=$(librarian fetch "$SK" 2>&1)
has "fetch returns the body" "$out" "Eigen3_DIR"
out=$(librarian --text fetch 01J00000000000000000000000 2>&1); eq "unknown id is exit 4" "$?" 4

# ── pack ─────────────────────────────────────────────────────────────────────
printf '### a\nI flag uncertainty explicitly.\n' > "$WORK/core.md"
librarian -q identity seed "$WORK/core.md"
out=$(librarian --text pack --task "colcon build fails with eigen link errors" --tags pkg:colcon --project p-1 --phase debugging --budget 2000 2>&1)
for m in "[IDENTITY: CORE]" "[IDENTITY: WORKING]" "[GROUP PREFERENCES]" "[TASK MEMORIES]" "[COVERAGE]" "[LIBRARIAN NOTES]" "[REQUEST]"; do
    has "pack has section $m" "$out" "$m"
done
first=$(printf '%s\n' "$out" | head -1); eq "pack starts with the core marker" "$first" "[IDENTITY: CORE]"
has "pack carries the skill with its id" "$out" "$SK · skill · PROBATIONARY"
has "coverage names the request tags" "$out" "[COVERAGE] pkg:colcon"
REQ=$(printf '%s\n' "$out" | sed -n 's/^\[REQUEST\] //p')
[[ -n "$REQ" ]] && ok "pack prints its request id" || bad "pack prints its request id"

# ── episode close and credit ─────────────────────────────────────────────────
out=$(librarian episode close --summary "fixed the build" --body "FINAL: fixed" --tags project:p-1 --outcome partial --criterion "journal only" --request "$REQ" --project p-1 2>&1)
eq "partial outcome moves no status" "$(printf '%s' "$out" | jq -r '.cited[0].status_after')" probationary
EP=$(printf '%s' "$out" | jq -r .episode_id)
out=$(librarian outcome amend "$EP" --outcome success --criterion "adversary review SURVIVES" 2>&1)
eq "a late success promotes the cited skill" "$(printf '%s' "$out" | jq -r '.cited[0].status_after')" active
eq "credit was reversed before re-applying" "$(printf '%s' "$out" | jq -r .reversed)" 1
out=$(librarian show "$SK" 2>&1)
eq "the skill is active" "$(printf '%s' "$out" | jq -r .status)" active
eq "use_count counts one episode" "$(printf '%s' "$out" | jq -r .use_count)" 1

# ── export mirrors ───────────────────────────────────────────────────────────
P="$WORK/proj"; mkdir -p "$P"; git -C "$P" init -q
out=$(librarian export --project-dir "$P" --project p-1 2>&1)
ls "$ID/librarian/export/lib-skill-$SK.md" >/dev/null 2>&1 && ok "identity mirror written with a mem-shaped name" || bad "identity mirror written"
has "mirror frontmatter is scalar" "$(cat "$ID/librarian/export/lib-skill-$SK.md")" "type: skill"
[[ -f "$P/addenda.md" && -f "$P/librarian.md" ]] && ok "project mirrors written" || bad "project mirrors written"
n=$(find "$P/skills/project" -name '*.md' | wc -l | tr -d ' '); eq "project skill mirrored" "$n" 1
has "skill mirror is marked generated" "$(cat "$P"/skills/project/*.md)" "generated by librarian export"

# ── human queue through librarian-project ────────────────────────────────────
printf '# Brief\nEstimate the levelized cost of green hydrogen.\n' > "$WORK/spec.md"
printf '# Review\n- Prefer small reviewable PRs over large feature branches.\n' > "$WORK/values.md"
out=$("$REPO/tools/librarian-project" init "$ID" --spec "$WORK/spec.md" --preferences "$WORK/values.md" 2>&1); rc=$?
eq "project init with the librarian succeeds" "$rc" 0
has "init reports the store" "$out" "memory:"
has "init kept the earlier store" "$out" "kept from earlier projects"
PD="$ID/workdir/project"
eq "init still makes one commit" "$(git -C "$PD" rev-list --count HEAD)" 1
[[ -f "$ID/project-pristine/project_id" ]] && ok "init writes a project id" || bad "init writes a project id"
has "env carries the package path" "$(cat "$ID/.env")" "LIBRARIAN_SRC="
out=$(librarian --text identity list --core 2>&1)
has "preferences import is human-authored and active" "$(librarian search --type preference --no-log)" '"status": "active"'
out=$(librarian identity propose --summary "I lead with the answer." --body "I lead with the answer." 2>&1)
QID=$(printf '%s' "$out" | jq -r .queue_id)
out=$("$REPO/tools/librarian-project" banner "$ID" 2>&1)
has "banner shows the queue" "$out" "Librarian check-in queue: 1 item"
out=$("$REPO/tools/librarian-project" queue "$ID" approve "$QID" "fine" 2>&1); rc=$?
eq "queue approve succeeds" "$rc" 0
eq "approval is committed as a human" "$(git -C "$PD" log -1 --format=%an)" human
has "the core node exists" "$(librarian --text identity list --core)" "I lead with the answer."
out=$("$REPO/tools/librarian-project" status "$ID" 2>&1)
has "status shows the librarian line" "$out" "librarian: "
out=$("$REPO/tools/librarian-project" librarian "$ID" stats 2>&1); rc=$?
eq "passthrough works" "$rc" 0

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
