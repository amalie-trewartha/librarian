#!/usr/bin/env bash
# tests/test_redact_sensitive.sh — redact_sensitive masks every provider key.
#
# Usage: tests/test_redact_sensitive.sh
#
# The function is extracted from bin/shellm and exercised directly (sourcing
# the whole script would run it). Every provider key env var's value must
# come back masked, and the sk-ant- pattern is masked even with no env var
# carrying the value.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

eval "$(sed -n '/^redact_sensitive()/,/^}/p' "$REPO/bin/shellm")"
if ! declare -f redact_sensitive >/dev/null; then
    bad "redact_sensitive extracted from bin/shellm"
    printf '\n%d passed, %d failed\n' "$pass" "$fail"
    exit 1
fi

for var in ANTHROPIC_API_KEY LLM_API_KEY OPENAI_API_KEY OPENROUTER_API_KEY \
           GEMINI_API_KEY OPENCODE_API_KEY; do
    secret="key-$$-$RANDOM$RANDOM"
    export "$var=$secret"
    out=$(redact_sensitive "before $secret after")
    if [[ "$out" != *"$secret"* && "$out" == *redacted* ]]; then
        ok "$var value is masked"
    else
        bad "$var value is masked" "$out"
    fi
    unset "$var"
done

out=$(redact_sensitive "token sk-ant-abc123XYZ here")
if [[ "$out" == *'<redacted-anthropic-key>'* && "$out" != *sk-ant-abc123XYZ* ]]; then
    ok "sk-ant- pattern is masked without the env var"
else
    bad "sk-ant- pattern is masked without the env var" "$out"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
