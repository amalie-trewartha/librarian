#!/usr/bin/env bash
# tests/test_chat_react.sh — producer for `chat react`.

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

new_out=$(traj new --traj_dir "$TRAJ_DIR" --slug react-test)
tid=$(printf '%s\n' "$new_out" | head -1)
export TRAJ_ID="$tid"
export ROOT_TRAJ_ID="$tid"
export IDENTITY_NAME="tester"
export CHATRC="$WORK/.chatrc"
printf 'default_send_from=tester\n' > "$CHATRC"
cd "$WORK" || exit 1

# --- happy path: stamps reaction + source:"chat" ---
if chat react --from tester --to slack-U1-C1-1.1 thumbsup >/dev/null 2>"$WORK/err"; then
    step=$(traj cat "$TRAJ_ID" --filter type=message --raw 2>/dev/null | tail -n 1)
    got_r=$(printf '%s' "$step" | jq -r '.reaction')
    got_c=$(printf '%s' "$step" | jq -r '.content')
    got_from=$(printf '%s' "$step" | jq -r '.from')
    got_to=$(printf '%s' "$step" | jq -r '.to')
    got_src=$(printf '%s' "$step" | jq -r '.source')
    if [[ "$got_r" == "thumbsup" && "$got_c" == ":thumbsup:" \
          && "$got_from" == "tester" && "$got_to" == "slack-U1-C1-1.1" \
          && "$got_src" == "chat" ]]; then
        ok "react stamps reaction field"
    else
        bad "react stamps reaction field" " $step"
    fi
else
    bad "react happy path" " $(cat "$WORK/err")"
fi

# --- :colons: are stripped ---
if chat react slack-U1-C1-1.1 :eyes: >/dev/null 2>"$WORK/err"; then
    step=$(traj cat "$TRAJ_ID" --filter type=message --raw 2>/dev/null | tail -n 1)
    got_r=$(printf '%s' "$step" | jq -r '.reaction')
    if [[ "$got_r" == "eyes" ]]; then
        ok "react strips surrounding colons"
    else
        bad "react strips surrounding colons" " $step"
    fi
else
    bad "react colon strip" " $(cat "$WORK/err")"
fi

# --- +1 is a valid Slack name ---
if chat react slack-U1-C1-1.1 +1 >/dev/null 2>"$WORK/err"; then
    step=$(traj cat "$TRAJ_ID" --filter type=message --raw 2>/dev/null | tail -n 1)
    got_r=$(printf '%s' "$step" | jq -r '.reaction')
    if [[ "$got_r" == "+1" ]]; then
        ok "react accepts +1"
    else
        bad "react accepts +1" " $step"
    fi
else
    bad "react +1" " $(cat "$WORK/err")"
fi

# --- --source-url is stamped ---
url="https://laudesters.slack.com/archives/C1/p1722400000123456"
if chat react --source-url "$url" slack-U1-C1-1.1 white_check_mark >/dev/null 2>"$WORK/err"; then
    step=$(traj cat "$TRAJ_ID" --filter type=message --raw 2>/dev/null | tail -n 1)
    got=$(printf '%s' "$step" | jq -r '.source_url')
    if [[ "$got" == "$url" ]]; then
        ok "react stamps source_url"
    else
        bad "react stamps source_url" " $step"
    fi
else
    bad "react source-url" " $(cat "$WORK/err")"
fi

# --- --reply-to copies source_url from the inbound step ---
chat send --from slack-U1-C1-1.1 --to tester --source-url "$url" "please look" >/dev/null 2>"$WORK/err" || true
inbound=$(traj cat "$TRAJ_ID" --filter type=message --raw 2>/dev/null | tail -n 1)
in_id=$(printf '%s' "$inbound" | jq -r '.step_id')
if chat react --reply-to "$in_id" slack-U1-C1-1.1 eyes >/dev/null 2>"$WORK/err"; then
    step=$(traj cat "$TRAJ_ID" --filter type=message --raw 2>/dev/null | tail -n 1)
    got=$(printf '%s' "$step" | jq -r '.source_url // empty')
    got_rt=$(printf '%s' "$step" | jq -r '.reply_to // empty')
    if [[ "$got" == "$url" && "$got_rt" == "$in_id" ]]; then
        ok "react --reply-to copies source_url"
    else
        bad "react --reply-to copies source_url" " $step"
    fi
else
    bad "react --reply-to" " $(cat "$WORK/err")"
fi

# --- unicode / spaces refused ---
if chat react slack-U1-C1-1.1 "thumbs up" >/dev/null 2>"$WORK/err"; then
    bad "space in name should be refused"
else
    ok "space in name is refused"
fi
if chat react slack-U1-C1-1.1 "👍" >/dev/null 2>"$WORK/err"; then
    bad "unicode emoji should be refused"
else
    ok "unicode emoji is refused"
fi

# --- missing emoji refused ---
if chat react slack-U1-C1-1.1 >/dev/null 2>"$WORK/err"; then
    bad "missing emoji should be refused"
else
    ok "missing emoji is refused"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
if (( fail > 0 )); then
    exit 1
fi
exit 0
