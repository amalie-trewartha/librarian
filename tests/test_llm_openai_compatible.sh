#!/usr/bin/env bash
# test_llm_openai_compatible.sh — the generic openai-compatible provider
#
# Usage: tests/test_llm_openai_compatible.sh
#
# curl is stubbed (it records its arguments and the payload it was handed,
# and answers with a minimal SSE stream or JSON body), so this checks the
# provider branch without touching the network. The cases that matter:
#
#   - the provider works with NO API key of any kind set (the point of it:
#     Ollama and friends need no key, and no dummy key masquerade either)
#   - no Authorization header is sent when LLM_API_KEY is unset
#   - LLM_API_KEY, when set, is sent as a Bearer token
#   - LLM_API_URL is required: without it the call dies loudly
#   - --provider openai-compatible works the same as the env var
#   - the non-streaming path answers too
#   - unknown model names default to the provider's 16384 output cap,
#     and -t still overrides it

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
# Records every argument in $CURL_ARGS and copies the -d @file payload to
# $CURL_PAYLOAD (the real payload tempfile is gone by the time the test can
# look), then answers with one SSE chunk plus [DONE], or a JSON body on the
# non-streaming (-o) path.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$CURL_ARGS"
out_file=""
prev=""
for a in "$@"; do
    [[ "$prev" == "-o" ]] && out_file="$a"
    [[ "$prev" == "-d" && "$a" == @* ]] && cat "${a#@}" > "$CURL_PAYLOAD"
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

export HEADLONG_HOME="$WORK/home"   # bin/llm writes run/llm_health.json here
mkdir -p "$HEADLONG_HOME"
export CURL_ARGS="$WORK/curl_args"
export CURL_PAYLOAD="$WORK/curl_payload"
export LLM_RETRIES=0
# Keyless operation is the point of this provider: every key must be absent,
# along with any .env-sourced overrides the suite's shell may carry. cd to
# the workdir so bin/llm finds no cwd .env either.
unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY \
      OPENCODE_API_KEY LLM_API_KEY LLM_PROVIDER LLM_API_URL LLM_MODEL \
      LLM_MAX_TOKENS SHELLM_MODEL
cd "$WORK" || exit 1

LLM="$REPO/bin/llm"
URL="http://127.0.0.1:9/v1/chat/completions"

reset() { : > "$CURL_ARGS"; : > "$CURL_PAYLOAD"; }

# ---------------------------------------------------------------------------
# Works with no API key of any kind
# ---------------------------------------------------------------------------

reset
out=$(LLM_PROVIDER=openai-compatible LLM_API_URL="$URL" \
      "$LLM" -m qwen3:8b "say ok" 2>"$WORK/stderr")
rc=$?
if [[ "$rc" -eq 0 && "$out" == *ok* ]]; then
    ok "keyless call succeeds via LLM_PROVIDER=openai-compatible"
else
    bad "keyless call succeeds via LLM_PROVIDER=openai-compatible" "$(head -1 "$WORK/stderr")"
fi
if grep -q '127.0.0.1:9' "$CURL_ARGS"; then
    ok "request went to LLM_API_URL"
else
    bad "request went to LLM_API_URL"
fi
if grep -qi 'authorization' "$CURL_ARGS"; then
    bad "no Authorization header without LLM_API_KEY" "$(grep -im1 authorization "$CURL_ARGS")"
else
    ok "no Authorization header without LLM_API_KEY"
fi
if grep -q '"max_tokens":[[:space:]]*16384' "$CURL_PAYLOAD"; then
    ok "unknown model gets the provider's 16384 default cap"
else
    bad "unknown model gets the provider's 16384 default cap" "$(grep -o '"max_tokens":[0-9]*' "$CURL_PAYLOAD" | head -1)"
fi

# ---------------------------------------------------------------------------
# LLM_API_KEY, when set, rides as a Bearer token
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=openai-compatible LLM_API_URL="$URL" LLM_API_KEY="sekrit" \
    "$LLM" -m qwen3:8b "say ok" >/dev/null 2>"$WORK/stderr"
if grep -q 'Authorization: Bearer sekrit' "$CURL_ARGS"; then
    ok "LLM_API_KEY is sent as Authorization: Bearer"
else
    bad "LLM_API_KEY is sent as Authorization: Bearer" "$(head -1 "$WORK/stderr")"
fi

# ---------------------------------------------------------------------------
# LLM_API_URL is required
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=openai-compatible "$LLM" -m qwen3:8b "say ok" \
    >/dev/null 2>"$WORK/stderr"
rc=$?
if [[ "$rc" -ne 0 ]] && grep -q 'LLM_API_URL is not set' "$WORK/stderr"; then
    ok "missing LLM_API_URL dies loudly"
else
    bad "missing LLM_API_URL dies loudly" "rc=$rc"
fi

# ---------------------------------------------------------------------------
# --provider flag path
# ---------------------------------------------------------------------------

reset
out=$(LLM_API_URL="$URL" \
      "$LLM" --provider openai-compatible -m qwen3:8b "say ok" 2>"$WORK/stderr")
if [[ "$out" == *ok* ]] && grep -q '127.0.0.1:9' "$CURL_ARGS"; then
    ok "--provider openai-compatible works"
else
    bad "--provider openai-compatible works" "$(head -1 "$WORK/stderr")"
fi

# ---------------------------------------------------------------------------
# Non-streaming path
# ---------------------------------------------------------------------------

reset
out=$(LLM_PROVIDER=openai-compatible LLM_API_URL="$URL" \
      "$LLM" --no-stream -m qwen3:8b "say ok" 2>"$WORK/stderr")
if [[ "$out" == *ok* ]]; then
    ok "non-streaming path answers"
else
    bad "non-streaming path answers" "$(head -1 "$WORK/stderr")"
fi

# ---------------------------------------------------------------------------
# -t overrides the provider default cap
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=openai-compatible LLM_API_URL="$URL" \
    "$LLM" -t 512 -m qwen3:8b "say ok" >/dev/null 2>"$WORK/stderr"
if grep -q '"max_tokens":[[:space:]]*512' "$CURL_PAYLOAD"; then
    ok "-t overrides the default cap"
else
    bad "-t overrides the default cap" "$(grep -o '"max_tokens":[0-9]*' "$CURL_PAYLOAD" | head -1)"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
