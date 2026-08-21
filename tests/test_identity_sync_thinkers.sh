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
unset IDENTITY_DIR IDENTITY_NAME IDENTITY_MEM_DIR IDENTITY_SKILLS_DIR IDENTITY_SKILLS_KERNEL_DIR

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
PATH="$REPO/bin:$REPO/tools:$PATH"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$label"; else bad "$label"; fi; }
check_not() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then bad "$label"; else ok "$label"; fi; }

WORK=$(mktemp -d)
trap 'cd /; rm -rf "$WORK"' EXIT
cd "$WORK" || exit 1

# Isolate HOME. tools/identity turns on symlink mode from
# $HOME/.headlong-thinkers/.use-symlinks, and its bundled source is the repo's
# own thinkers/ when run from a checkout — so on a --symlinks install this
# test's identity got thinkers/monolith as a symlink INTO the repo, and the
# "hand-edited prompt" write below landed in the real thinkers/monolith/
# prompt.md (observed 2026-08-19). Copy mode is also what these assertions
# actually mean: "a local edit survives" only makes sense for a real copy.
export HOME="$WORK"

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

check "fresh identity ledger seeded"    grep -qx actor "$T/.retired_done"

# Simulate a pre-consolidation identity: no ledger yet (it did not exist
# then), stale copies of two retired thinkers, one user-authored thinker,
# one hand-edited bundled prompt.
rm -f "$T/.retired_done"
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

# On a POST-consolidation identity the seeded ledger means a user-authored
# thinker that happens to reuse a retired name is never disabled.
identity new bravo >/dev/null 2>&1
TB="$WORK/.identities/bravo/thinkers"
fake_thinker "$TB/learning"
identity sync-thinkers bravo >/dev/null 2>&1
check_not "user thinker under retired name survives on fresh identity" \
    test -e "$TB/learning/disabled"

# Post-consolidation identity that PREDATES the ledger (monolith/responder
# present, no .retired_done, none of the six dirs): the first reconcile
# must close the question for ALL six names — not just ones with dirs — so
# a thinker the operator authors afterwards under a retired name survives.
identity new carol >/dev/null 2>&1
TC="$WORK/.identities/carol/thinkers"
rm -f "$TC/.retired_done"
identity sync-thinkers carol >/dev/null 2>&1
check "first sync ledgers dirless names"  grep -qx learning "$TC/.retired_done"
fake_thinker "$TC/learning"
identity sync-thinkers carol >/dev/null 2>&1
check_not "later user thinker survives on pre-ledger identity" \
    test -e "$TC/learning/disabled"

# sync-thinkers must not require a default identity when given a name:
# the systemd start path runs it on boxes where no default was ever set.
rm -f "$WORK/.identities/default"
identity sync-thinkers alpha >/dev/null 2>&1
check "works without a default identity" test $? -eq 0

printf '\n%d passed, %d failed\n' "$pass" "$fail"
exit $((fail > 0))
