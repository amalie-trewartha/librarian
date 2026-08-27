#!/usr/bin/env bash
# tests/test_bridge_env.sh — the bridge launchers read Headlong's .env files.
#
# Usage: tests/test_bridge_env.sh
#
# Covers, for tools/headlong-slack-bridge and tools/headlong-telegram-bridge:
#   1. A variable set only in the checkout's .env reaches the bridge.
#   2. A variable set only in the state home's .env reaches the bridge.
#   3. A variable already in the environment wins over both, so systemd's
#      EnvironmentFile and `slack run` keep precedence.
#   4. With no .env anywhere the launcher still runs.
#
# `uv` is stubbed to print the variables it was handed, so nothing is
# installed and no bridge actually starts.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

mkdir -p "$WORK/bin" "$WORK/app/tools" "$WORK/app/slack" "$WORK/app/telegram" \
         "$WORK/home/.headlong"
cp "$REPO/tools/headlong-slack-bridge" "$REPO/tools/headlong-telegram-bridge" \
   "$WORK/app/tools/"

cat > "$WORK/bin/uv" <<'STUB'
#!/usr/bin/env bash
printf 'BOT=%s\n' "${SLACK_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-unset}}"
printf 'IDENTITY=%s\n' "${HEADLONG_SLACK_IDENTITY:-${HEADLONG_TELEGRAM_IDENTITY:-unset}}"
STUB
chmod +x "$WORK/bin/uv"

export PATH="$WORK/bin:$PATH"
export HOME="$WORK/home"
export HEADLONG_HOME="$WORK/home/.headlong"

# Run one launcher with a clean environment except what the caller names.
run() {
    local script="$1"; shift
    env -u SLACK_BOT_TOKEN -u TELEGRAM_BOT_TOKEN \
        -u HEADLONG_SLACK_IDENTITY -u HEADLONG_TELEGRAM_IDENTITY \
        "$@" "$WORK/app/tools/$script" 2>/dev/null
}

for bridge in slack telegram; do
    script="headlong-${bridge}-bridge"
    if [[ "$bridge" == slack ]]; then
        token_var=SLACK_BOT_TOKEN; id_var=HEADLONG_SLACK_IDENTITY
    else
        token_var=TELEGRAM_BOT_TOKEN; id_var=HEADLONG_TELEGRAM_IDENTITY
    fi

    printf '%s=from-app-env\n' "$token_var" > "$WORK/app/.env"
    printf 'export %s=from-home-env\n' "$id_var" > "$HEADLONG_HOME/.env"

    out=$(run "$script")
    [[ "$out" == *"BOT=from-app-env"* ]] \
        && ok "$script: checkout .env" \
        || bad "$script: checkout .env" "$out"
    [[ "$out" == *"IDENTITY=from-home-env"* ]] \
        && ok "$script: state home .env" \
        || bad "$script: state home .env" "$out"

    out=$(run "$script" "$token_var=from-environ")
    [[ "$out" == *"BOT=from-environ"* ]] \
        && ok "$script: environment wins over .env" \
        || bad "$script: environment wins over .env" "$out"

    # The same key in both files: the checkout wins, the order every other
    # _load_env copy uses (bin/llm, tools/persona, bin/shellm, common.sh).
    printf '%s=from-app-env\n' "$token_var" > "$WORK/app/.env"
    printf '%s=from-home-env\n' "$token_var" > "$HEADLONG_HOME/.env"
    out=$(run "$script")
    [[ "$out" == *"BOT=from-app-env"* ]] \
        && ok "$script: checkout .env wins over state home" \
        || bad "$script: checkout .env wins over state home" "$out"

    # Sourcing the .env must not let a command's stdout ride into a value...
    printf 'echo loading\n%s=xoxb-clean\n' "$token_var" > "$WORK/app/.env"
    rm -f "$HEADLONG_HOME/.env"
    out=$(run "$script")
    [[ "$out" == *"BOT=xoxb-clean"* ]] \
        && ok "$script: a command's stdout stays out of the value" \
        || bad "$script: a command's stdout stays out of the value" "$out"

    # ...and a file the shell cannot parse must say so on stderr, instead of
    # silently loading nothing while the operator hunts a "missing" token.
    printf '%s="unterminated\n' "$token_var" > "$WORK/app/.env"
    err=$(env -u SLACK_BOT_TOKEN -u TELEGRAM_BOT_TOKEN \
        -u HEADLONG_SLACK_IDENTITY -u HEADLONG_TELEGRAM_IDENTITY \
        "$WORK/app/tools/$script" 2>&1 >/dev/null)
    [[ "$err" == *"could not read"* ]] \
        && ok "$script: a malformed .env warns instead of staying silent" \
        || bad "$script: a malformed .env warns instead of staying silent" "$err"

    rm -f "$WORK/app/.env" "$HEADLONG_HOME/.env"
    out=$(run "$script")
    [[ "$out" == *"BOT=unset"* ]] \
        && ok "$script: no .env is not an error" \
        || bad "$script: no .env is not an error" "$out"
done

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
