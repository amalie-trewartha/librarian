#!/usr/bin/env bash
# tests/test_chat_send_file.sh — producer + renderer for `chat send-file`.
#
# Covers Nick's leftover notes: empty/oversize rejection, content_b64 on the
# mind-log step, and model-facing `context` eliding that field.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK="${SHELLM_TEST_WORK:-}"
if [[ -z "$WORK" ]]; then
    WORK=$(mktemp -d)
    trap 'rm -rf "$WORK"' EXIT
else
    rm -rf "$WORK"; mkdir -p "$WORK"
fi

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

export PATH="$REPO/bin:$PATH"
export TRAJ_DIR="$WORK/traj"
mkdir -p "$TRAJ_DIR"

new_out=$(traj new --traj_dir "$TRAJ_DIR" --slug send-file-test)
tid=$(printf '%s\n' "$new_out" | head -1)
export TRAJ_ID="$tid"
export ROOT_TRAJ_ID="$tid"
export IDENTITY_NAME="tester"
export CHATRC="$WORK/.chatrc"
printf 'default_send_from=tester\n' > "$CHATRC"
cd "$WORK" || exit 1

# --- happy path: text file keeps body in content (Slack/web still read it) ---
printf 'hello file\n' > "$WORK/note.txt"
if chat send-file --from tester --to slack-U1-C1 "$WORK/note.txt" >/dev/null 2>"$WORK/err"; then
    step=$(traj cat "$TRAJ_ID" --filter type=message --raw 2>/dev/null | tail -n 1)
    got_name=$(printf '%s' "$step" | jq -r '.filename')
    got_content=$(printf '%s' "$step" | jq -r '.content')
    got_from=$(printf '%s' "$step" | jq -r '.from')
    got_to=$(printf '%s' "$step" | jq -r '.to')
    got_src=$(printf '%s' "$step" | jq -r '.source')
    b64=$(printf '%s' "$step" | jq -r '.content_b64')
    printf '%s' "$b64" | base64 -d > "$WORK/decoded.txt" 2>/dev/null || true
    if [[ "$got_name" == "note.txt" && "$got_content" == "hello file" \
          && "$got_from" == "tester" && "$got_to" == "slack-U1-C1" \
          && "$got_src" == "chat" ]] && cmp -s "$WORK/note.txt" "$WORK/decoded.txt"; then
        ok "send-file text keeps body in content for non-Telegram routes"
    else
        bad "send-file stamps fields" " step=$step"
    fi
else
    bad "send-file happy path" " $(cat "$WORK/err")"
fi

# --- binary file stays off argv / round-trips ---
printf 'a\0b\xffc' > "$WORK/blob.bin"
if chat send-file --from tester --to telegram-1-1 "$WORK/blob.bin" >/dev/null 2>"$WORK/err"; then
    step=$(traj cat "$TRAJ_ID" --filter type=message --raw 2>/dev/null | tail -n 1)
    b64=$(printf '%s' "$step" | jq -r '.content_b64')
    printf '%s' "$b64" | base64 -d > "$WORK/blob.out" 2>/dev/null
    got_content=$(printf '%s' "$step" | jq -r '.content')
    if cmp -s "$WORK/blob.bin" "$WORK/blob.out" \
          && [[ "$got_content" == "[file: blob.bin]" ]]; then
        ok "send-file round-trips binary bytes"
    else
        bad "send-file binary round-trip"
    fi
else
    bad "send-file binary" " $(cat "$WORK/err")"
fi

# --- empty file is refused ---
: > "$WORK/empty.txt"
if chat send-file --from tester --to telegram-1-1 "$WORK/empty.txt" >/dev/null 2>"$WORK/err"; then
    bad "empty file should be refused"
else
    if grep -q "empty file" "$WORK/err"; then
        ok "empty file refused"
    else
        bad "empty file error message" " $(cat "$WORK/err")"
    fi
fi

# --- oversize file is refused ---
printf '0123456789' > "$WORK/big.txt"
if CHAT_SEND_FILE_MAX_BYTES=4 chat send-file --from tester --to telegram-1-1 "$WORK/big.txt" >/dev/null 2>"$WORK/err"; then
    bad "oversize file should be refused"
else
    if grep -q "too large" "$WORK/err"; then
        ok "oversize file refused"
    else
        bad "oversize file error message" " $(cat "$WORK/err")"
    fi
fi

# --- context renderer elides content_b64 ---
rendered=$(context --traj_dir "$TRAJ_DIR" "$TRAJ_ID" 2>/dev/null || true)
if printf '%s' "$rendered" | grep -q 'content_b64'; then
    bad "context leaked content_b64"
else
    if printf '%s' "$rendered" | grep -q 'note.txt'; then
        ok "context shows filename, hides content_b64"
    else
        # filename may still appear via the marker in content
        if printf '%s' "$rendered" | grep -q '\[file: note.txt\]'; then
            ok "context shows file marker, hides content_b64"
        else
            bad "context missing file marker" " rendered=${rendered:0:400}"
        fi
    fi
fi

# --- recent-stream jq elides content_b64 (same transform as common.sh) ---
line=$(jq -nc --arg b64 "$(base64 -w 0 < "$WORK/note.txt" | tr -d '\n')" \
    '{type:"message", filename:"note.txt", content:"", content_b64:$b64}')
stream=$(printf '%s\n' "$line" | jq -c 'del(.content_b64)
    | .content = (
        (if ((.content // "") == "") and ((.filename // "") != "")
         then "[file: \(.filename)]"
         else (.content // "") end)
        | tostring
      )')
if printf '%s' "$stream" | grep -q 'content_b64'; then
    bad "recent-stream still has content_b64"
else
    marker=$(printf '%s' "$stream" | jq -r '.content')
    if [[ "$marker" == "[file: note.txt]" ]]; then
        ok "recent-stream substitutes file marker and drops content_b64"
    else
        bad "recent-stream marker" " $stream"
    fi
fi

echo
echo "passed: $pass"
echo "failed: $fail"
[[ "$fail" -eq 0 ]]
