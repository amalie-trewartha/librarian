#!/usr/bin/env bash
# tests/test_traj_recursive_tree.sh — `traj tail -r` and `traj cat -r` return
# the whole tree, in timestamp order.
#
# Usage: tests/test_traj_recursive_tree.sh
#
# Why: the recursive views are the only readers in traj that sort steps, and
# the key comes from `to_epoch` in _sorted_tree_steps. Three ways it went
# wrong, all silent: the catch-all branch appended a second "Z" to stamps that
# already ended in one, so fromdateiso8601 errored on every step _iso_ts ever
# wrote and both commands printed nothing while exiting 0; the key floored to
# the second, so steps written in the same second tied and sort(1) fell back to
# comparing the JSON text; and an unparseable stamp took its step out of the
# tree. `search -r` and `check -r` walk the same files without to_epoch, so the
# halves of the same flag disagreed.
#
# Part A runs the real commands and leaves their stamps alone — the case a user
# hits. Part B builds a tree two levels deep with two branches and rewrites the
# stamps to defeat three wrong sort keys at once: every step but one lands
# inside a single second (a whole-second key ties them), their alphabetical
# order differs from their real one (a tie falls back to the JSON text), and
# one sits in 1970 so its key is shorter than the rest (a lexical key sorts it
# last instead of first).

set -uo pipefail
unset TRAJ_DIR TRAJ_ID ROOT_TRAJ_ID 2>/dev/null

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
export PATH="$REPO/bin:$PATH"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
is()  { # is LABEL EXPECTED ACTUAL
    if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "want [$2], got [$3]"; fi
}

command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL python3 not found"; exit 1; }

WORK=$(mktemp -d)
trap 'cd /; rm -rf "$WORK"' EXIT

contents() { jq -r '.content // empty' | tr '\n' ' ' | sed 's/ $//'; }
lines()    { grep -c . ; }

# =============================================================================
# Part A — real stamps, untouched
# =============================================================================
# Six appends at machine speed land in one or two seconds, so this is the case
# a whole-second sort key gets wrong. Stamps from _iso_ts are fixed-width UTC,
# so lexical order is chronological order and `sort` is a fair oracle.

export TRAJ_DIR="$WORK/live"
mkdir -p "$TRAJ_DIR"
TRAJ_ID=$(traj new --slug live | head -1)
export TRAJ_ID
LIVE_CHILD=""
for w in one two three; do
    traj append --field type=thought --field content="root-$w" >/dev/null
    if [[ -z "$LIVE_CHILD" ]]; then LIVE_CHILD=$(traj fork --slug livekid); fi
    TRAJ_ID="$LIVE_CHILD" traj append --field type=thought --field content="kid-$w" >/dev/null
done
live_on_disk=$(cat "$(traj path)" "$(TRAJ_ID="$LIVE_CHILD" traj path)" | lines)
live_out=$(traj cat -r --raw)

is "live tree: every step on disk comes back" "$live_on_disk" "$(printf '%s\n' "$live_out" | lines)"

live_ts=$(printf '%s\n' "$live_out" | jq -r '.ts')
is "live tree: stamps come back non-decreasing" \
   "$(printf '%s\n' "$live_ts" | LC_ALL=C sort)" "$live_ts"

# =============================================================================
# Part B — stamps rewritten, one second, adversarial ordering
# =============================================================================
# root ── kid ── grandkid        two levels, and two forks out of root so the
#     └── kid2                   per-file fork loop is exercised, not just the
#                                first fork it finds.

export TRAJ_DIR="$WORK/trajectories"
mkdir -p "$TRAJ_DIR"
TRAJ_ID=$(traj new --slug root | head -1)
export TRAJ_ID
traj append --field type=thought --field content=wolf >/dev/null
traj append --field type=thought --field content=zulu >/dev/null
CHILD=$(traj fork --slug kid)
TRAJ_ID="$CHILD" traj append --field type=thought --field content=alpha >/dev/null
traj append --field type=thought --field content=yankee >/dev/null
TRAJ_ID="$CHILD" traj append --field type=thought --field content=bravo >/dev/null
traj append --field type=thought --field content=xray >/dev/null
TRAJ_ID="$CHILD" traj append --field type=thought --field content=charlie >/dev/null
TRAJ_ID="$CHILD" traj append --field type=oddball --field content=no-ts >/dev/null
GRAND=$(TRAJ_ID="$CHILD" traj fork --slug grandkid)
TRAJ_ID="$GRAND" traj append --field type=thought --field content=delta >/dev/null
SIB=$(traj fork --slug kid2)
TRAJ_ID="$SIB" traj append --field type=thought --field content=echo >/dev/null

ROOT_FILE=$(traj path)
CHILD_FILE=$(TRAJ_ID="$CHILD" traj path)
GRAND_FILE=$(TRAJ_ID="$GRAND" traj path)
SIB_FILE=$(TRAJ_ID="$SIB" traj path)
[[ -f "$ROOT_FILE" && -f "$CHILD_FILE" && -f "$GRAND_FILE" && -f "$SIB_FILE" ]] \
    || { echo "FAIL could not build the tree"; exit 1; }

# --- rewrite the stamps -------------------------------------------------------
# Everything but wolf is inside the one second 12:00:10Z, and charlie sits 2ms
# after xray so the third millisecond digit has to survive. wolf is in 1970:
# an 8-digit key among 13-digit ones, first by value and last by text. bravo
# and charlie keep the legacy numeric-offset spelling of 12:00:10.400Z and
# 12:00:10.502Z — one ahead of UTC on a half-hour offset, one behind — so the
# sign and the minutes both stay covered. no-ts cannot be parsed at all.
cat > "$WORK/restamp.py" <<'PY'
import json, sys
stamps = dict(l.split("=", 1) for l in sys.stdin.read().splitlines() if l.strip())
out = []
for line in open(sys.argv[1]):
    if line.strip():
        rec = json.loads(line)
        key = rec.get("content") or rec.get("type")
        if key in stamps:
            rec["ts"] = stamps[key]
        out.append(json.dumps(rec))
open(sys.argv[1], "w").write("\n".join(out) + "\n")
PY

# restamp FILE — KEY=TS pairs on stdin; KEY is a step's .content, or .type for
# the header and fork steps that have none. Applied per file, so each file's
# header and forks are stamped independently. Both forks out of root share a
# stamp; they are filtered out of every ordering assertion below.
restamp() { python3 "$WORK/restamp.py" "$1"; }

restamp "$ROOT_FILE" <<'STAMPS'
trajectory=2026-09-02T12:00:00.000Z
wolf=1970-01-02T00:00:00.000Z
zulu=2026-09-02T12:00:10.100Z
fork=2026-09-02T12:00:10.150Z
yankee=2026-09-02T12:00:10.300Z
xray=2026-09-02T12:00:10.500Z
STAMPS
restamp "$CHILD_FILE" <<'STAMPS'
trajectory=2026-09-02T12:00:10.160Z
alpha=2026-09-02T12:00:10.200Z
bravo=2026-09-02T17:30:10.400+05:30
charlie=2026-09-02T08:00:10.502-04:00
no-ts=not-a-timestamp
fork=2026-09-02T12:00:10.550Z
STAMPS
restamp "$GRAND_FILE" <<'STAMPS'
trajectory=2026-09-02T12:00:10.560Z
delta=2026-09-02T12:00:10.600Z
STAMPS
restamp "$SIB_FILE" <<'STAMPS'
trajectory=2026-09-02T12:00:10.660Z
echo=2026-09-02T12:00:10.700Z
STAMPS

if ! grep -q '17:30:10.400+05:30' "$CHILD_FILE" \
   || ! grep -q '08:00:10.502-04:00' "$CHILD_FILE" \
   || ! grep -q 'not-a-timestamp' "$CHILD_FILE" \
   || ! grep -q '1970-01-02' "$ROOT_FILE"; then
    echo "FAIL fixture: the hand-written stamps did not land"; exit 1
fi

on_disk=$(cat "$ROOT_FILE" "$CHILD_FILE" "$GRAND_FILE" "$SIB_FILE" | lines)
thoughts() { traj cat -r --raw --filter type=thought | contents; }
# Chronological. Alphabetically this would be
# "alpha bravo charlie delta echo wolf xray yankee zulu", and lexically by key
# it would be "zulu alpha yankee bravo xray charlie delta echo wolf".
ORDER="wolf zulu alpha yankee bravo xray charlie delta echo"

# --- the tree comes back at all ----------------------------------------------
out=$(traj cat -r --raw); rc=$?
is "cat -r exits 0" "0" "$rc"
is "cat -r returns every step in the tree" "$on_disk" "$(printf '%s\n' "$out" | lines)"

# --- ordered by timestamp, across every branch and inside one second ---------
# Passing this needs a numeric, sub-second key and a recursion that reaches
# both branches and both levels: alpha is the child, delta the grandchild,
# echo the second branch out of root, wolf the short key.
is "cat -r interleaves the whole tree in timestamp order" "$ORDER" "$(thoughts)"

# --- the legacy numeric-offset stamps still parse, both signs and the minutes -
order=$(thoughts | tr ' ' '\n')
is "a +hh:mm stamp lands where its UTC instant belongs" "5" \
   "$(printf '%s\n' "$order" | grep -n '^bravo$' | cut -d: -f1)"
is "a -hh:mm stamp lands where its UTC instant belongs" "7" \
   "$(printf '%s\n' "$order" | grep -n '^charlie$' | cut -d: -f1)"

# --- a stamp that will not parse keeps its step ------------------------------
is "an unparseable stamp does not delete the step" "no-ts" \
   "$(traj cat -r --raw --filter type=oddball | contents)"

# --- --filter really filters, on .type not just on what has content ----------
is "cat -r honours --filter" "0" \
   "$(traj cat -r --raw --filter type=thought | jq -r 'select(.type != "thought") | .type' | lines)"

# --- each step is tagged with the file it actually came from ------------------
hex_of() { basename "$(dirname "$1")" | cut -d- -f1; }
root_hex=$(hex_of "$ROOT_FILE"); grand_hex=$(hex_of "$GRAND_FILE")
is "the four files have distinct hex ids" "4" \
   "$(for f in "$ROOT_FILE" "$CHILD_FILE" "$GRAND_FILE" "$SIB_FILE"; do hex_of "$f"; done | sort -u | lines)"
is "a root step carries the root file hex" "$root_hex" \
   "$(traj cat -r --raw --filter content=wolf | jq -r '._traj_hex')"
is "a grandchild step carries its own hex"  "$grand_hex" \
   "$(traj cat -r --raw --filter content=delta | jq -r '._traj_hex')"

# --- tail -r bounds the merged stream, not one file --------------------------
is "tail -r -n 2 takes the two newest in the whole tree" "delta echo" \
   "$(traj tail -r -n 2 --raw --filter type=thought | contents)"

# --- the formatted view is what a terminal gets ------------------------------
# The last field of a formatted line is the content, so this checks the same
# ordering through _format_line rather than only through --raw.
is "cat -r --format shows the tree in the same order" "$ORDER" \
   "$(traj cat -r --format --no-color --filter type=thought | awk '{print $NF}' | tr '\n' ' ' | sed 's/ $//')"

# --- the non-recursive view is unchanged --------------------------------------
is "cat without -r still shows only this file" "wolf zulu yankee xray" \
   "$(traj cat --raw --filter type=thought | contents)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
