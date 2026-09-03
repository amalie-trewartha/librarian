#!/usr/bin/env bash
# tests/test_persona_chat_exit.sh — the simple `persona <name>` chat loop
# (used when the Rust TUI is not installed) exits cleanly and takes its
# background message watcher with it.
#
# Usage: tests/test_persona_chat_exit.sh
#
# Why: the loop's EXIT trap kills a watcher whose pid lives in a function
# local. The trap runs after the function has returned, so it must carry the
# pid itself rather than read the variable (fatal under set -u).
#
# Everything runs under a throwaway HOME / app dir, so the real
# ~/.headlong and the repo's own .identities are never touched.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
# A unique identity name so the pgrep below cannot match anything else on
# the machine, and so cleanup can kill a leaked watcher.
NAME="chatexit$$"
cleanup() { pkill -f "bin/$NAME\$" 2>/dev/null; cd /; rm -rf "$WORK"; }
trap cleanup EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$label"; else bad "$label"; fi; }
check_not() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then bad "$label"; else ok "$label"; fi; }

# wait_until <seconds> <command...>
wait_until() {
    local deadline=$(( $(date +%s) + $1 )); shift
    while ! "$@" >/dev/null 2>&1; do
        [[ $(date +%s) -ge $deadline ]] && return 1
        sleep 0.2
    done
}
# The watcher is a subshell of the chat process, so it shows up under the
# same command line.
watcher_gone() { ! pgrep -f "bin/$NAME\$" >/dev/null 2>&1; }

# --- a fake install ----------------------------------------------------------
export HOME="$WORK/home"
export HEADLONG_HOME="$WORK/home/.headlong"
export HEADLONG_APP_DIR="$WORK/app"
mkdir -p "$HOME" "$HEADLONG_HOME" "$HEADLONG_APP_DIR" "$WORK/bin"
ln -s "$REPO/bin" "$HEADLONG_APP_DIR/bin"
ln -s "$REPO/tools" "$HEADLONG_APP_DIR/tools"
ln -s "$REPO/thinkers" "$HEADLONG_APP_DIR/thinkers"
ln -s "$REPO/identities" "$HEADLONG_APP_DIR/identities"

# The name is linked to persona the way headlong-init does it, so the chat
# runs as a bare `<name>`, the same as a real install. No headlong-tui on
# this PATH, so persona takes the simple chat loop.
ln -s "$REPO/tools/persona" "$WORK/bin/$NAME"
export PATH="$WORK/bin:$REPO/bin:$REPO/tools:/usr/bin:/bin"

(cd "$HEADLONG_APP_DIR" && identity new "$NAME" >/dev/null 2>&1) || { bad "identity new $NAME"; exit 1; }
ID="$HEADLONG_APP_DIR/.identities/$NAME"

# --- one line, then EOF ------------------------------------------------------
printf 'hello there\n' | "$NAME" >"$WORK/stdout" 2>"$WORK/stderr"
rc=$?

check     "chat exits 0 on EOF"                    test "$rc" -eq 0
check_not "no unbound-variable error on exit"      grep -q 'unbound variable' "$WORK/stderr"
check     "background watcher killed on exit"      wait_until 5 watcher_gone
# Proves the loop ran the send path before leaving, not that it bailed early.
check     "typed message landed in the trajectory" grep -rq '"hello there"' "$ID"/trajectories/*/trajectory.jsonl

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
