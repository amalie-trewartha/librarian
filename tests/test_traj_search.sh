#!/usr/bin/env bash
# tests/test_traj_search.sh — `traj search` prefilters rows with one grep and
# takes --tail N, so a self-check on a long log finishes; blob-backed output is
# still searched. No LLM calls, no docker.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(dirname "$HERE")"
export PATH="$REPO/bin:$PATH"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
TRAJ_ID="cafe0000-0000-0000-0000-0000000000d0"
mkdir -p "$WORK/trajectories/$TRAJ_ID/blobs"
T="$WORK/trajectories/$TRAJ_ID/trajectory.jsonl"
export TRAJ_DIR="$WORK/trajectories" TRAJ_ID
printf '{"step_id":"%s","type":"trajectory","ts":"2026-01-01T00:00:00Z"}\n' "$TRAJ_ID" > "$T"
printf '{"step_id":"s1","type":"reasoning","cmd":"chat send --to slack-C1 \\"Dr. Claw paper\\"","ts":"2026-01-01T00:00:01Z"}\n' >> "$T"
printf '{"step_id":"s2","type":"shell-output","stdout":"nothing here","ts":"2026-01-01T00:00:02Z"}\n' >> "$T"
printf 'RISE paper in a blob\n' > "$WORK/trajectories/$TRAJ_ID/blobs/b1.txt"
printf '{"step_id":"s3","type":"shell-output","stdout":"[blob]","stdout_ref":"blobs/b1.txt","ts":"2026-01-01T00:00:03Z"}\n' >> "$T"
printf '{"step_id":"s4","type":"reasoning","cmd":"echo later","ts":"2026-01-01T00:00:04Z"}\n' >> "$T"
printf 'TRUNCATED tail only\n' > "$WORK/trajectories/$TRAJ_ID/blobs/b2.txt"
printf '{"step_id":"s5","type":"shell-output","stderr":"[blob]","stderr_ref":"blobs/b2.txt","ts":"2026-01-01T00:00:05Z"}\n' >> "$T"
printf '{"step_id":"s6","type":"shell-output","stdout":"phantom fallback text","stdout_ref":"blobs/gone.txt","ts":"2026-01-01T00:00:06Z"}\n' >> "$T"
printf 'needle at line one\nneedle also at line two\n' > "$WORK/trajectories/$TRAJ_ID/blobs/b4.txt"
printf '{"step_id":"s7","type":"shell-output","stdout":"needle at line one","stdout_ref":"blobs/b4.txt","ts":"2026-01-01T00:00:07Z"}\n' >> "$T"
printf '{"step_id":"s8","type":"shell-output","stdout":"plain first\\nneedle second line","stdout_ref":"blobs/gone3.txt","ts":"2026-01-01T00:00:08Z"}\n' >> "$T"
printf '{"step_id":"s9","type":"shell-output","stdout":"tail says \\"needle\\" in quotes","stdout_ref":"blobs/gone4.txt","ts":"2026-01-01T00:00:09Z"}\n' >> "$T"
printf '{"step_id":"s10","type":"merge","content":"needle result","from_traj":"kid","from_step":"k1","from_traj_ref":"../kid/trajectory.jsonl","ts":"2026-01-01T00:00:10Z"}\n' >> "$T"

out=$(traj search "Dr. Claw")
[[ "$out" == "s1:cmd:"* ]] && [[ $(printf '%s\n' "$out" | grep -c .) -eq 1 ]] && ok "a literal match is found in the row's field" || bad "literal match" "$out"
out=$(traj search -i "dr. claw")
[[ "$out" == "s1:cmd:"* ]] && ok "-i is honoured by the prefilter" || bad "-i" "$out"
out=$(traj search "RISE paper")
[[ "$out" == "s3:stdout:"* ]] && ok "text that lives in a blob is still searched" || bad "blob search" "$out"
out=$(traj search "Dr. Claw" --tail 5)
[[ -z "$out" ]] && ok "--tail 5 does not reach an older row" || bad "--tail bounds" "$out"
out=$(traj search "phantom fallback" --tail 5)
[[ "$out" == "s6:stdout:"* ]] && ok "--tail 5 still finds a recent row" || bad "--tail recent" "$out"
out=$(traj search -E 'Dr\. (Claw|Paw)')
[[ "$out" == "s1:cmd:"* ]] && ok "-E regex works through the prefilter" || bad "-E" "$out"
traj search "x" --tail abc >/dev/null 2>&1 && bad "--tail rejects non-numbers" || ok "--tail rejects non-numbers"

out=$(traj search "TRUNCATED")
[[ "$out" == "s5:stderr:1:"* ]] && ok "stderr blob text is searched" || bad "stderr blob" "$out"
out=$(traj search "phantom fallback")
[[ "$out" == "s6:stdout:1:"* ]] && ok "a missing blob file falls back to the inline text" || bad "missing blob fallback" "$out"
out=$(traj search "needle")
[[ $(printf '%s\n' "$out" | grep -c '^s7:stdout:') -eq 2 ]] && ok "a match in blob and truncated inline prints once, from the blob" || bad "no double print" "$out"
out=$(traj search "RISE paper" --field cmd)
[[ -z "$out" ]] && ok "--field cmd skips blob stdout" || bad "field filter with blobs" "$out"

out=$(traj search -E '^needle' --field stdout)
[[ "$out" == *"s7:stdout:1:needle at line one"* && "$out" == *"s7:stdout:2:needle also at line two"* && "$out" == *"s8:stdout:2:needle second line"* ]] && ok "an anchored pattern reaches a decoded field behind a missing blob" || bad "anchored decode" "$out"
out=$(traj search '"needle"' --field stdout)
[[ "$out" == 's9:stdout:1:tail says "needle" in quotes' ]] && ok "a quoted literal matches decoded text the row escapes" || bad "quoted literal" "$out"
out=$(traj search -E '^needle' --field content)
[[ "$out" == "s10:content:1:needle result" ]] && ok "a structural reference row's inline content is searched" || bad "merge content" "$out"
out=$(traj search -E '^needle' --field stdout --tail 4)
[[ "$out" == *"s8:stdout:2:needle second line"* ]] && ok "--tail 4 reaches the decoded fallback row" || bad "--tail decode" "$out"
out=$(traj search -E '^needle' --field stdout --tail 2)
[[ -z "$out" ]] && ok "--tail 2 bounds the decoded fallback" || bad "--tail decode bounds" "$out"
out=$(traj search -E '^needle' --field cmd)
[[ -z "$out" ]] && ok "--field cmd leaves decoded stdout alone" || bad "decoded field filter" "$out"

# Empty inline previews: traj append with SHELLM_STDOUT_INLINE_LIMIT=0 spills
# every field, so the row carries an empty preview plus a ref, and the jq
# chunk stream still emits one blank content line for it. The reader must
# count that line or it desyncs and silently drops every later field and row.
printf 'needle lives in the blob only\n' > "$WORK/trajectories/$TRAJ_ID/blobs/b5.txt"
printf '{"step_id":"s11","type":"shell-output","stdout":"","stdout_ref":"blobs/b5.txt","ts":"2026-01-01T00:00:11Z"}\n' >> "$T"
printf '{"step_id":"s12","type":"shell-output","stdout":"","stdout_ref":"blobs/gone5.txt","stderr":"needle with an empty stdout inline","ts":"2026-01-01T00:00:12Z"}\n' >> "$T"
printf '{"step_id":"s13","type":"shell-output","stdout":"needle decoded after empty previews","stdout_ref":"blobs/gone6.txt","ts":"2026-01-01T00:00:13Z"}\n' >> "$T"
out=$(traj search "needle lives in the blob")
[[ "$out" == "s11:stdout:1:needle lives in the blob only" ]] && ok "an empty inline preview with an existing blob still searches the blob" || bad "empty inline, existing blob" "$out"
out=$(traj search "needle with an empty stdout")
[[ "$out" == "s12:stderr:1:needle with an empty stdout inline" ]] && ok "a row with an empty inline preview keeps its later fields searchable" || bad "field after an empty preview" "$out"
out=$(traj search -E '^needle' --field stdout)
[[ "$out" == *"s13:stdout:1:needle decoded after empty previews"* ]] && ok "a decoded fallback after empty inline previews is still found" || bad "decoded fallback after empties" "$out"

# The reported case itself: every field spilled, only empty previews inline.
SHELLM_STDOUT_INLINE_LIMIT=0 traj append --field type=shell-output --field stdout='needle row a out' --field stderr='needle row a err' >/dev/null
SHELLM_STDOUT_INLINE_LIMIT=0 traj append --field type=shell-output --field stdout='needle row b out' --field stderr='needle row b err' >/dev/null
out=$(traj search "needle row")
[[ $(printf '%s\n' "$out" | grep -c 'needle row') -eq 4 ]] && ok "SHELLM_STDOUT_INLINE_LIMIT=0 rows yield all four matches" || bad "all-spilled rows" "$out"
out=$(traj search "needle row" --tail 2)
[[ $(printf '%s\n' "$out" | grep -c 'needle row') -eq 4 ]] && ok "--tail 2 bounds to the two all-spilled rows and still returns four matches" || bad "all-spilled rows, tail bound" "$out"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ $fail -eq 0 ]]
