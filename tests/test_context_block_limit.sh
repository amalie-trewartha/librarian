#!/usr/bin/env bash
# tests/test_context_block_limit.sh — rows in the newest --tail-block block
# render whole up to --block-limit; older rows keep --prompt-limit.
#
# Why: a 2K cut on every output, including the one the model just produced,
# made the mind read files in slices and re-read them (273 of 313 outputs cut
# in one run, 2026-09-03). The band follows the block grid so a row shrinks
# exactly once, when the newest row crosses a block boundary, which is when
# the window start moves and the cache prefix resets anyway.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(dirname "$HERE")"
CONTEXT="$REPO/bin/context"
PATH="$REPO/bin:$PATH"; unset TRAJ_DIR TRAJ_ID 2>/dev/null || true
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
mkdir -p "$W/t"
# shellcheck disable=SC2054  # the commas are inside the type lists, not separators
PROD=(--assistant-types reasoning,final --user-types prompt,shell-output,feedback)

# N rows: even rows are reasoning, odd rows are shell-output with a 3000-byte
# stdout whose middle carries a marker "MID-<row>" (only visible when whole).
# Row 3 gets a 20000-byte stdout to check the band's own cap.
mk() {
    python3 - "$W/t/trajectory.jsonl" "$1" <<'PYEOF'
import json, sys
out, n = sys.argv[1], int(sys.argv[2])
with open(out, "w") as f:
    for i in range(n):
        if i % 2 == 0:
            f.write(json.dumps({"type": "reasoning", "cmd": "echo r%03d" % i, "step_id": "s-%03d" % i}) + "\n")
        else:
            size = 20000 if i == 3 else 3000
            body = ("a" * (size // 2 - 8)) + " MID-%03d " % i + ("b" * (size // 2 - 8))
            f.write(json.dumps({"type": "shell-output", "stdout": body, "step_id": "s-%03d" % i}) + "\n")
PYEOF
}
# render <extra flags...>: prints "<row>:whole|cut" per shell-output row
render() {
    "$CONTEXT" --traj_dir "$W" t "${PROD[@]}" --head 0 --tail 400 "$@" 2>/dev/null \
        | jq -r '.[] | select(.role=="user") | .content' \
        | python3 -c '
import sys,re
txt=sys.stdin.read()
for m in re.finditer(r"(MID-(\d{3}))|(\[\.\.\. truncated: (\d+) bytes total\. read with: traj show s-(\d{3}) --full\])", txt):
    if m.group(1): print("%s:whole" % m.group(2))
    else: print("%s:cut" % m.group(5))' | sort -u | tr '\n' ' '
}
has() { [[ " $1 " == *" $2 "* ]]; }

mk 100
out=$(render --tail-block 50 --block-limit 8192)
if has "$out" "051:whole" && has "$out" "099:whole" && has "$out" "049:cut" && has "$out" "001:cut"; then
    ok "N=100: rows 50-99 (current block) whole, rows 0-49 cut"
else bad "N=100 band" "$out"; fi
has "$out" "003:cut" && ok "a 20K output in an old block is cut" || bad "20K old block" "$out"

mk 101
out=$(render --tail-block 50 --block-limit 8192)
if has "$out" "099:cut" && has "$out" "051:cut" && ! has "$out" "099:whole"; then
    ok "N=101: crossing into block 2 shrinks block 1 once (rows 50-99 now cut)"
else bad "N=101 shrink" "$out"; fi
out=$(render --tail-block 50 --block-limit 8192 --whole-blocks 2)
if has "$out" "099:whole" && has "$out" "051:whole" && has "$out" "049:cut"; then
    ok "--whole-blocks 2 keeps the previous block whole"
else bad "whole-blocks 2" "$out"; fi

mk 100
out=$(render --tail-block 50)
if has "$out" "099:cut" && ! has "$out" "099:whole"; then
    ok "without --block-limit every row is cut at --prompt-limit (old behavior)"
else bad "no block-limit" "$out"; fi
out=$(render --block-limit 8192)
if has "$out" "099:whole" && has "$out" "097:cut"; then
    ok "--tail-block 1: only the newest row is whole"
else bad "tail-block 1 band" "$out"; fi
mk 4
out=$(render --tail-block 50 --block-limit 8192)
if has "$out" "003:cut" && has "$out" "001:whole"; then
    ok "inside the band a 20K output is still cut at --block-limit, a 3K one is whole"
else bad "band cap" "$out"; fi
# The band collapses under a byte budget instead of defeating it.
mk 100
big=$("$CONTEXT" --traj_dir "$W" t "${PROD[@]}" --head 0 --tail 400 --tail-block 50 --block-limit 8192 2>/dev/null | wc -c)
small=$("$CONTEXT" --traj_dir "$W" t "${PROD[@]}" --head 0 --tail 400 --tail-block 50 --block-limit 8192 --max-bytes 60000 2>/dev/null | wc -c)
if [[ "$big" -gt 60000 && "$small" -le 60000 ]]; then ok "--max-bytes still binds with a band ($big -> $small bytes)"; else bad "max-bytes with band" "$big -> $small"; fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
