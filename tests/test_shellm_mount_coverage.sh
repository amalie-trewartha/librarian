#!/usr/bin/env bash
# tests/test_shellm_mount_coverage.sh — which directories docker_setup believes
# an existing bind mount already covers.
#
# Usage: tests/test_shellm_mount_coverage.sh
#
# Why: the coverage test used to be a bare prefix match, so `/x/workdirs` read
# as covering the sibling `/x/workdirs-scratch`. The sibling then got no -v,
# docker created an empty directory at the -w path, and the run continued with
# the operator's files invisible and the agent's writes discarded — silently.
# It also decided container reuse, so a workdir it could never mount produced a
# fresh container on every run.
#
# These are container-side paths: a path inside the container is reachable only
# if it sits under a mount destination, and docker normalizes `..` in both -w
# and destinations (`-w /a/../b` lands on /a/b). So the predicate normalizes
# lexically and must NOT resolve symlinks — resolving would judge the host
# source instead, and a workdir symlinked into the runs dir but mounted at its
# link path would read as covered by a mount that does not contain it.
#
# The function is exercised directly; no docker daemon and no network.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
SHELLM="$REPO/bin/shellm"

pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

# Pull just the functions under test out of shellm, which otherwise runs main.
eval "$(awk '/^_norm_path\(\)/,/^}/' "$SHELLM")"
eval "$(awk '/^_path_covered\(\)/,/^}/' "$SHELLM")"

type _path_covered >/dev/null 2>&1 || { echo "FAIL _path_covered not extractable from bin/shellm"; exit 1; }

# covered PATH ROOT -> expect "yes" or "no"
covered() { if _path_covered "$1" "$2"; then echo yes; else echo no; fi; }

t() {
    local want="$1" path="$2" root="$3" label="$4" got
    got=$(covered "$path" "$root")
    if [[ "$got" == "$want" ]]; then ok "$label"
    else bad "$label" "covered('$path','$root') = $got, want $want"; fi
}

# --- existing semantics: these held before the fix and must keep holding ---
t yes /x/workdirs          /x/workdirs   "a path is covered by itself"
t yes /x/workdirs/run1     /x/workdirs   "a genuine child is covered"
t yes /x/workdirs/a/b/c    /x/workdirs   "a deep child is covered"
t no  /x/other             /x/workdirs   "an unrelated path is not covered"
t no  /x                   /x/workdirs   "a parent is not covered by its child"
t yes /anything/at/all     /             "the root covers everything"

# --- the defect: a sibling that merely shares the root's text ---
t no  /x/workdirs-scratch  /x/workdirs   "a sibling sharing the prefix is NOT covered"
t no  /x/workdirsX         /x/workdirs   "a sibling with one extra char is NOT covered"
t no  /x/workdirs.bak/f    /x/workdirs   "a file under a prefix-sharing sibling is NOT covered"

# --- the defect: unnormalized paths, which docker normalizes before acting ---
t no  /x/workdirs/../scratch    /x/workdirs  "a .. escape out of the root is NOT covered"
t yes /x/workdirs/run/../run2   /x/workdirs  "a .. that stays inside is still covered"
t yes /x/workdirs/./run1        /x/workdirs  "a . segment does not defeat coverage"
t yes /x//workdirs//run1        /x/workdirs  "duplicate slashes do not defeat coverage"
t yes /x/workdirs/run1/         /x/workdirs  "a trailing slash does not defeat coverage"
t yes /x/workdirs/run1          /x/workdirs/ "a trailing slash on the root still covers"
t no  /x/workdirs/../../etc     /x/workdirs  "a .. climb above the root is NOT covered"

# --- segments that must survive verbatim: no globbing, no word splitting ---
t yes '/x/workdirs/a*b'        /x/workdirs      "a glob char in a segment is data, not a pattern"
t no  '/x/workdirs*/evil'      /x/workdirs      "a glob char does not widen the root"
t yes '/x/work dirs/run1'      '/x/work dirs'   "a space in a segment is preserved"
t yes '/x/workdirs/[a]'        /x/workdirs      "bracket chars in a segment are data"

# --- degenerate inputs: must not crash, and must not widen coverage ---
n() { local got; got=$(_norm_path "$1"); if [[ "$got" == "$2" ]]; then ok "$3"; else bad "$3" "_norm_path('$1') = '$got', want '$2'"; fi; }
n ''          /  "an empty path normalizes to the root"
n /           /  "the root normalizes to itself"
n ///         /  "repeated slashes collapse to the root"
n /..         /  "a .. at the root cannot climb past it"
n /a/../..    /  "a .. climb past the root stops at the root"
n /a/b/../c   /a/c "a .. pops exactly one level"
t no  ''      /x   "an empty path is not covered by a real root"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ $((pass + fail)) -ge 27 ]] || { printf 'FAIL only %d assertions ran; expected at least 27\n' "$((pass + fail))"; exit 1; }
[[ "$fail" -eq 0 ]]
