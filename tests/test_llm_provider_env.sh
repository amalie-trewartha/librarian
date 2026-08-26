#!/usr/bin/env bash
# test_llm_provider_env.sh — LLM_PROVIDER is honored from the environment
#
# Usage: tests/test_llm_provider_env.sh
#
# curl is stubbed (it records the URL it was called with and answers with a
# minimal SSE stream), so this checks which provider branch bin/llm took
# without touching the network. The cases that matter:
#
#   - a model name no pattern matches (a local OpenAI-compatible alias) is
#     reachable by exporting LLM_PROVIDER, not only by passing --provider
#   - without a provider such a name still fails loudly
#   - --provider still beats the environment
#   - name-based detection is unchanged when LLM_PROVIDER is unset
#   - an env provider that disagrees with a classifiable name is honored and
#     warns on stderr, while a name no pattern matches stays quiet

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

# --- curl stub ---------------------------------------------------------------
# Records every argument in $CURL_ARGS (so the test can see which URL was
# picked) and answers with one SSE chunk plus [DONE], enough for the
# OpenAI-compatible extractors.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$CURL_ARGS"
out_file=""
prev=""
for a in "$@"; do
    [[ "$prev" == "-o" ]] && out_file="$a"
    prev="$a"
done
if [[ -n "$out_file" ]]; then
    printf '{"choices":[{"message":{"content":"ok"}}]}' > "$out_file"
    printf '200'
else
    printf 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
    printf 'data: [DONE]\n'
fi
EOF
chmod +x "$WORK/bin/curl"
export PATH="$WORK/bin:$PATH"

export ANTHROPIC_API_KEY="test-key"
export OPENAI_API_KEY="test-key"
export GEMINI_API_KEY="test-key"
export OPENROUTER_API_KEY="test-key"
export HEADLONG_HOME="$WORK/home"   # bin/llm writes run/llm_health.json here
mkdir -p "$HEADLONG_HOME"
export CURL_ARGS="$WORK/curl_args"
export LLM_RETRIES=0
# The shell running the suite may have sourced a .env that sets the very
# overrides under test; the unset cases assume they are absent.
unset LLM_PROVIDER LLM_API_URL LLM_MODEL

LLM="$REPO/bin/llm"

reset() { : > "$CURL_ARGS"; }
url_seen() { grep -c "$1" "$CURL_ARGS"; }

# ---------------------------------------------------------------------------
# A local alias no pattern matches is reachable via LLM_PROVIDER
# ---------------------------------------------------------------------------

reset
out=$(LLM_PROVIDER=openai LLM_API_URL="http://127.0.0.1:9/v1/chat/completions" \
      "$LLM" -m my-local-alias "say ok" 2>"$WORK/stderr")
rc=$?
if [[ "$rc" -eq 0 && "$out" == *ok* ]]; then
    ok "LLM_PROVIDER=openai reaches an unrecognized model name"
else
    bad "LLM_PROVIDER=openai reaches an unrecognized model name" "$(head -1 "$WORK/stderr")"
fi
if [[ "$(url_seen '127.0.0.1:9')" -ge 1 ]]; then
    ok "request went to the configured endpoint"
else
    bad "request went to the configured endpoint"
fi
# The mismatch warning must stay quiet here: detect_provider cannot classify
# this name, so there is nothing for the environment to disagree with.
if grep -q "overrides detected provider" "$WORK/stderr"; then
    bad "an unclassifiable name warns nothing" "$(grep -m1 'overrides detected' "$WORK/stderr")"
else
    ok "an unclassifiable name warns nothing"
fi

# ---------------------------------------------------------------------------
# Without a provider the same name still fails loudly (no silent default)
# ---------------------------------------------------------------------------

reset
"$LLM" -m my-local-alias "say ok" >/dev/null 2>"$WORK/stderr"
rc=$?
if [[ "$rc" -ne 0 ]] && grep -q "Cannot detect provider" "$WORK/stderr"; then
    ok "unset LLM_PROVIDER still dies on an unrecognized name"
else
    bad "unset LLM_PROVIDER still dies on an unrecognized name" "rc=$rc"
fi

# ---------------------------------------------------------------------------
# --provider beats the environment
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=openai "$LLM" -m my-local-alias --provider anthropic "say ok" \
    >/dev/null 2>"$WORK/stderr"
if [[ "$(url_seen 'api.anthropic.com')" -ge 1 ]]; then
    ok "--provider overrides LLM_PROVIDER"
else
    bad "--provider overrides LLM_PROVIDER" "$(head -1 "$WORK/stderr")"
fi

# ---------------------------------------------------------------------------
# Name-based detection is unchanged when LLM_PROVIDER is unset
# ---------------------------------------------------------------------------

reset
"$LLM" -m claude-sonnet-4-5 "say ok" >/dev/null 2>"$WORK/stderr"
if [[ "$(url_seen 'api.anthropic.com')" -ge 1 ]]; then
    ok "claude-* still detected as anthropic"
else
    bad "claude-* still detected as anthropic" "$(head -1 "$WORK/stderr")"
fi

reset
"$LLM" -m vendor/some-model "say ok" >/dev/null 2>"$WORK/stderr"
if [[ "$(url_seen 'openrouter.ai')" -ge 1 ]]; then
    ok "vendor/model still detected as openrouter"
else
    bad "vendor/model still detected as openrouter" "$(head -1 "$WORK/stderr")"
fi

# ---------------------------------------------------------------------------
# An env provider that contradicts a classifiable name is honored, but loudly
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=openai OPENAI_API_KEY=stub-key \
    "$LLM" -m claude-sonnet-4-5 "say ok" >/dev/null 2>"$WORK/stderr"
if [[ "$(url_seen 'api.openai.com')" -ge 1 ]]; then
    ok "env LLM_PROVIDER wins over a name it contradicts"
else
    bad "env LLM_PROVIDER wins over a name it contradicts" "$(head -1 "$WORK/stderr")"
fi
if grep -q "LLM_PROVIDER=openai overrides detected provider 'anthropic'" "$WORK/stderr"; then
    ok "the mismatch is reported on stderr"
else
    bad "the mismatch is reported on stderr" "$(head -1 "$WORK/stderr")"
fi

# A flag that overrides the environment is a deliberate choice, not a
# mismatch: nothing to warn about.
reset
LLM_PROVIDER=openai "$LLM" -m claude-sonnet-4-5 --provider anthropic "say ok" \
    >/dev/null 2>"$WORK/stderr"
if grep -q "overrides detected provider" "$WORK/stderr"; then
    bad "--provider silences the mismatch warning" "$(grep -m1 'overrides detected' "$WORK/stderr")"
else
    ok "--provider silences the mismatch warning"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
