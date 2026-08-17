#!/usr/bin/env bash
# test_identity_sync_thinkers.sh — roster reconcile for existing identities
#
# Usage: tests/test_identity_sync_thinkers.sh
#
# Copy-mode bootstrap never revisits an existing thinker dir, so identities
# created before the roster consolidation kept the six deleted thinkers —
# active, subscribed, and (for actor) answering messages beside the new
# responder. `identity sync-thinkers` reconciles: retired bundled names get
# a `disabled` marker (the service wrapper and `thinkers start` both honor
# it), newly bundled thinkers are bootstrapped in, and everything else —
# user-authored thinkers, local edits, live bundled thinkers — is left
# alone. No LLM calls, no docker.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
PATH="$REPO/bin:$PATH"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$label"; else bad "$label"; fi; }
check_not() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then bad "$label"; else ok "$label"; fi; }

WORK=$(mktemp -d)
trap 'cd /; rm -rf "$WORK"' EXIT
cd "$WORK"

fake_thinker() { # fake_thinker <dir>
    mkdir -p "$1"
    printf '#!/usr/bin/env bash\ntrue\n' > "$1/step"; chmod +x "$1/step"
    printf '{"types":["message"]}\n' > "$1/subscriptions.jsonl"
}

identity new alpha >/dev/null 2>&1 || { bad "identity new alpha"; exit 1; }
T="$WORK/.identities/alpha/thinkers"

check "fresh identity has monolith"     test -d "$T/monolith"
check "fresh identity has responder"    test -d "$T/responder"
check_not "fresh identity lacks actor"  test -d "$T/actor"

# Simulate a pre-consolidation identity: stale copies of two retired
# thinkers, one user-authored thinker, one hand-edited bundled prompt.
fake_thinker "$T/actor"
fake_thinker "$T/mind_wanderer"
fake_thinker "$T/mycustom"
echo "nick's curated prompt" > "$T/monolith/prompt.md"

# The new responder dir must also appear if missing (upgrade adds it).
rm -rf "$T/responder"

identity sync-thinkers alpha >/dev/null 2>&1
rc=$?
check "sync-thinkers exits 0"           test "$rc" -eq 0
check "actor got disabled marker"       test -f "$T/actor/disabled"
check "mind_wanderer got marker"        test -f "$T/mind_wanderer/disabled"
check "actor dir kept (not deleted)"    test -f "$T/actor/step"
check_not "user thinker untouched"      test -e "$T/mycustom/disabled"
check_not "live monolith not disabled"  test -e "$T/monolith/disabled"
check "responder bootstrapped back"     test -f "$T/responder/step"
check "local prompt edit survives" \
    grep -q "nick's curated prompt" "$T/monolith/prompt.md"

# Idempotent: a second run changes nothing and does not stack markers.
marker_before=$(cat "$T/actor/disabled")
identity sync-thinkers alpha >/dev/null 2>&1
check "second run exits 0"              test $? -eq 0
check "marker unchanged on rerun" \
    test "$(cat "$T/actor/disabled")" = "$marker_before"

# An operator's deliberate re-enable must STICK: each name is retired once
# (recorded in .retired_done), so deleting the marker keeps the thinker
# enabled across every future sync/restart.
rm "$T/actor/disabled"
identity sync-thinkers alpha >/dev/null 2>&1
check_not "operator re-enable sticks"   test -e "$T/actor/disabled"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
exit $((fail > 0))
