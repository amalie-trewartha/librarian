#!/usr/bin/env bash
# test_thinkers_silence_alert.sh — deploy/thinkers-silence-alert.sh
#
# Usage: tests/test_thinkers_silence_alert.sh
#
# Stubs curl on PATH to capture the Slack payload. A stale trajectory with a
# live dispatcher pid posts one "gone quiet" alert and writes the marker; a
# second tick posts nothing; a fresh trajectory posts the recovery and drops
# the marker; a dead dispatcher pid or a deliberate stop posts nothing.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
SCRIPT="$REPO/deploy/thinkers-silence-alert.sh"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

APP="$TMP/app"
ID="$APP/.identities/quiet"
mkdir -p "$ID/trajectories/abcd1234-root" "$ID/run/logs" "$TMP/stub"
printf 'name=quiet\ncreated=test\nroot_trajectory=abcd1234-ffff-0000-0000-000000000000\n' > "$ID/info.txt"
TRAJ="$ID/trajectories/abcd1234-root/trajectory.jsonl"
printf '{"type":"idle"}\n' > "$TRAJ"
printf 'SLACK_BOT_TOKEN=xoxb-test\nHEADLONG_ALERT_CHANNEL=C0TEST\n' > "$APP/.env"
printf 'tick\n' > "$ID/run/logs/dispatcher.log"

# curl stub: record the JSON payload, answer ok
cat > "$TMP/stub/curl" <<'STUB'
#!/usr/bin/env bash
prev=""
for a in "$@"; do [[ "$prev" == "--data" ]] && printf '%s\n' "$a" >> "$CURL_LOG"; prev="$a"; done
echo '{"ok":true}'
STUB
chmod +x "$TMP/stub/curl"
export CURL_LOG="$TMP/curl.log"

run() { PATH="$TMP/stub:$PATH" HEADLONG_SILENCE_SECS=600 HEADLONG_ALERT_FALLBACK_LOG="$TMP/fallback.log" bash "$SCRIPT" "$APP" quiet; }
posts() { if [[ -f "$CURL_LOG" ]]; then wc -l < "$CURL_LOG" | tr -d ' '; else echo 0; fi; }
age_traj() { touch -d "@$(( $(date +%s) - $1 ))" "$TRAJ" 2>/dev/null || touch -t "$(date -r $(( $(date +%s) - $1 )) +%Y%m%d%H%M.%S)" "$TRAJ"; }

# a live "dispatcher": this shell
printf '%s\n' "$$" > "$ID/run/dispatcher.pid"

# 1. stale trajectory → one alert + marker
age_traj 1200
run
if [[ "$(posts)" -eq 1 ]] && grep -q 'has gone quiet' "$CURL_LOG"; then ok "stale trajectory posts the alert"
else bad "stale trajectory posts the alert" "posts=$(posts) $(cat "$CURL_LOG" 2>/dev/null | head -c 200)"; fi
[[ -f "$ID/run/silent_since" ]] && ok "marker written" || bad "marker written"
grep -q 'C0TEST' "$CURL_LOG" && ok "posts to the alert channel" || bad "posts to the alert channel"

# 2. still stale → nothing more
run
[[ "$(posts)" -eq 1 ]] && ok "second tick is silent" || bad "second tick is silent" "posts=$(posts)"

# 3. fresh trajectory → recovery, marker gone
age_traj 10
run
if [[ "$(posts)" -eq 2 ]] && tail -n 1 "$CURL_LOG" | grep -q 'is back'; then ok "fresh trajectory posts the recovery"
else bad "fresh trajectory posts the recovery" "posts=$(posts) $(tail -n 1 "$CURL_LOG" 2>/dev/null | head -c 200)"; fi
[[ -f "$ID/run/silent_since" ]] && bad "marker removed" || ok "marker removed"

# 4. fresh and no marker → nothing
run
[[ "$(posts)" -eq 2 ]] && ok "healthy tick is silent" || bad "healthy tick is silent"

# 5. stale but dispatcher dead → nothing (death alert's job)
age_traj 1200
printf '999999\n' > "$ID/run/dispatcher.pid"
run
[[ "$(posts)" -eq 2 ]] && ok "dead dispatcher is not a silence" || bad "dead dispatcher is not a silence"

# 6. stale, live, but deliberate stop → nothing
printf '%s\n' "$$" > "$ID/run/dispatcher.pid"
touch "$ID/run/deliberate_stop"
run
[[ "$(posts)" -eq 2 ]] && ok "deliberate stop is not a silence" || bad "deliberate stop is not a silence"
rm -f "$ID/run/deliberate_stop"

# 7. no Slack config → fallback log line, no failure
rm -f "$APP/.env" "$ID/run/silent_since"
run; rc=$?
[[ "$rc" -eq 0 && -f "$TMP/fallback.log" ]] && ok "missing config degrades to the fallback log" || bad "missing config degrades to the fallback log" "rc=$rc"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
(( fail == 0 ))
