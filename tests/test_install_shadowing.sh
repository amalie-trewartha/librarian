#!/usr/bin/env bash
# tests/test_install_shadowing.sh — install.sh deals with commands that would
# shadow or collide with the ones it installs.
#
# Usage: tests/test_install_shadowing.sh
#
# Ahead of the install directory on PATH: another llm (the Python llm CLI's
# shape) and an older Librarian copy are moved aside to *.pre-headlong-*, and
# an unrelated program with one of our generic names is left alone with a
# warning. A non-Librarian file at the install path itself is kept, renamed,
# before it is replaced. --keep-conflicts only warns. Runs install.sh against
# a throwaway HOME; no network, no docker.

set -uo pipefail
unset IDENTITY_DIR IDENTITY_NAME LIBRARIAN_HOME SHELLM_HOME PREFIX SYMLINKS 2>/dev/null
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
has() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then ok "$1"; else bad "$1" "missing '$3' in: $(printf '%s' "$2" | tail -c 500)"; fi; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

setup() {
    rm -rf "$WORK/home"; mkdir -p "$WORK/home/early" "$WORK/home/.local/bin"
    E="$WORK/home/early" P="$WORK/home/.local/bin"
    printf '#!/usr/bin/python3\nfrom llm.cli import cli\ncli()\n' > "$E/llm"
    printf '#!/usr/bin/env bash\n# mem - memory store for shellm identities\n' > "$E/mem"
    printf '#!/bin/sh\necho my own chat tool\n' > "$E/chat"
    printf '#!/bin/sh\necho my own context tool\n' > "$P/context"
    chmod +x "$E/llm" "$E/mem" "$E/chat" "$P/context"
}
run_install() {
    (cd "$REPO" && env -i HOME="$WORK/home" PATH="$E:$P:/usr/local/bin:/usr/bin:/bin" TERM=dumb \
        bash ./install.sh --symlinks "$@" </dev/null 2>&1)
}

setup
out=$(run_install); rc=$?
[[ $rc -eq 0 ]] && ok "install succeeds" || bad "install succeeds" "rc=$rc: $(printf '%s' "$out" | tail -5)"
[[ ! -e "$E/llm" ]] && ls "$E"/llm.pre-headlong-* >/dev/null 2>&1 && ok "a shadowing llm is moved aside" || bad "a shadowing llm is moved aside"
[[ ! -e "$E/mem" ]] && ls "$E"/mem.pre-headlong-* >/dev/null 2>&1 && ok "an older Librarian copy ahead on PATH is moved aside" || bad "an older Librarian copy ahead on PATH is moved aside"
[[ -e "$E/chat" ]] && ok "an unrelated same-named program is left alone" || bad "an unrelated same-named program is left alone"
has "and it is warned about" "$out" "$E/chat (not Librarian) shadows"
has "the moves are reported" "$out" "Moved aside $E/llm"
has "hash -r is suggested" "$out" "hash -r"
ls "$P"/context.pre-headlong-* >/dev/null 2>&1 && ok "a non-Librarian file at the install path is kept, renamed" || bad "a non-Librarian file at the install path is kept, renamed"
[[ "$(readlink "$P/context")" == "$REPO/bin/context" ]] && ok "and replaced by Librarian's" || bad "and replaced by Librarian's" "$(readlink "$P/context")"
[[ "$(cd "$WORK/home" && env -i PATH="$E:$P:/usr/bin:/bin" bash -c 'command -v llm')" == "$P/llm" ]] && ok "llm now resolves to Librarian's" || bad "llm now resolves to Librarian's"

out=$(run_install); rc=$?
[[ $rc -eq 0 ]] && ok "re-running is safe" || bad "re-running is safe"
[[ "$(ls "$P"/context.pre-headlong-* 2>/dev/null | wc -l)" -eq 1 ]] && ok "re-running does not back up Librarian's own links" || bad "re-running does not back up Librarian's own links"

setup
out=$(run_install --keep-conflicts)
[[ -e "$E/llm" && -e "$E/mem" ]] && ok "--keep-conflicts moves nothing" || bad "--keep-conflicts moves nothing"
has "--keep-conflicts still warns" "$out" "$E/llm shadows"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
