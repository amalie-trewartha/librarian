#!/usr/bin/env bash
# tests/test_skills_split.sh — the core `skills` reads (list, show, prompt,
# list-json) and forwards every manager subcommand to tools/headlong-skills,
# which sources the core for its helpers.
#
# Why: bin/skills was split on 2026-09-04 so the package manager stops counting
# against the core line budget. The mind is still told `skills install ...`
# works, so the forwarding path is part of the contract, and the manager must
# find the core script both as a sibling (installed) and via ../bin (checkout).
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check() { local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }

H=$(mktemp -d)
trap 'rm -rf "$H"' EXIT
export SKILLS_DIR="$H/skills" SKILLSRC="$H/none" SKILLS_KERNEL_DIR="$H/kernel" NO_COLOR=1
mkdir -p "$SKILLS_DIR/greet" "$SKILLS_KERNEL_DIR/core"
cat > "$SKILLS_DIR/greet/SKILL.md" <<'SK'
---
name: greet
description: Say hello politely
---
# Greet
Say hello.
SK
cat > "$SKILLS_KERNEL_DIR/core/SKILL.md" <<'SK'
---
name: core
description: Always loaded
---
Kernel body here.
SK

cd "$H" || exit 1
out=$("$REPO/bin/skills" list 2>&1)
check "core list names the skill"          grep -q 'greet' <<<"$out"
check "core show prints the body"          grep -q 'Say hello' <<<"$("$REPO/bin/skills" show greet 2>&1)"
check "core list-json is valid JSON with the skill" bash -c '"$0" list-json | jq -e ".[] | select(.name==\"greet\")"' "$REPO/bin/skills"
p=$("$REPO/bin/skills" prompt 2>&1)
check "core prompt carries the kernel body"        grep -q 'Kernel body here' <<<"$p"
check "core prompt lists the installed skill"      grep -q 'greet: Say hello' <<<"$p"
check "core show --requires on a plain skill"      grep -q 'No requirements' <<<"$("$REPO/bin/skills" show greet --requires 2>&1)"

# Forwarding from a checkout: bin/skills finds ../tools/headlong-skills.
PATH="/usr/bin:/bin" out=$("$REPO/bin/skills" check greet 2>&1); rc=$?
check "core forwards 'check' to the manager (exit 0)" test "$rc" -eq 0
check "forwarded check reports the skill"   grep -qi 'greet\|requirement' <<<"$out"
PATH="/usr/bin:/bin" out=$("$REPO/bin/skills" remote 2>&1); rc=$?
check "core forwards 'remote' (exit 0)"      test "$rc" -eq 0
check "core help does not advertise install" bash -c '! "$0" --help | grep -q "^  skills install"' "$REPO/bin/skills"

# The manager standing alone, and finding the core as a PREFIX sibling.
check "manager list works"                  grep -q 'greet' <<<"$("$REPO/tools/headlong-skills" list 2>&1)"
check "manager help advertises install"     bash -c '"$0" --help | grep -q "install"' "$REPO/tools/headlong-skills"
mkdir -p "$H/prefix"; cp "$REPO/bin/skills" "$REPO/tools/headlong-skills" "$H/prefix/"
check "manager finds a sibling core in PREFIX" grep -q 'greet' <<<"$("$H/prefix/headlong-skills" list 2>&1)"
check "core in PREFIX forwards to sibling manager" bash -c 'PATH="$1:/usr/bin:/bin" "$1/skills" check greet' _ "$H/prefix"
mv "$H/prefix/headlong-skills" "$H/prefix/hs.bak"
out=$(PATH="/usr/bin:/bin" "$H/prefix/skills" install foo 2>&1); rc=$?
check "core without a manager fails with a hint"  bash -c 'test "$1" -ne 0 && grep -q "headlong-skills" <<<"$2"' _ "$rc" "$out"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
