#!/usr/bin/env bash
# test_llm_adapter.sh — the adapter seam (LLM_PROVIDER=adapter + LLM_ADAPTER)
#
# Usage: tests/test_llm_adapter.sh
#
# A stub adapter records its argv, its stdin, and the system-prompt file it
# is handed, then answers on stdout — so this checks the invoker side of the
# contract in design/providers.md without any real provider. The cases:
#
#   - the adapter runs and its stdout is llm's stdout
#   - --model and --max-tokens are always passed; unknown names get the
#     16384 fallback cap and -t overrides it
#   - the messages JSON arrives on stdin
#   - -s reaches the adapter via --system-prompt-file
#   - --no-stream, --effort, and --thinking LEVEL are forwarded
#   - LLM_USAGE_FILE reaches the adapter and its usage lands in the ledger
#   - missing LLM_ADAPTER dies loudly; a non-executable path dies loudly
#   - a nonzero adapter exit fails the call with the adapter's exit code
#     reported, and the health marker records the error

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

# --- stub adapter ------------------------------------------------------------
# Records argv to $ADAPTER_ARGS (one per line) and stdin to $ADAPTER_STDIN.
# Copies the --system-prompt-file target to $ADAPTER_SYS (the real file is a
# tempfile llm removes). Writes usage JSON when ADAPTER_USAGE is set. Answers
# "adapter says ok", or exits $ADAPTER_RC.
cat > "$WORK/adapter" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$ADAPTER_ARGS"
cat > "$ADAPTER_STDIN"
prev=""
for a in "$@"; do
    [[ "$prev" == "--system-prompt-file" ]] && cat "$a" > "$ADAPTER_SYS"
    prev="$a"
done
if [[ -n "${ADAPTER_USAGE:-}" && -n "${LLM_USAGE_FILE:-}" ]]; then
    printf '%s' "$ADAPTER_USAGE" > "$LLM_USAGE_FILE"
fi
if [[ "${ADAPTER_RC:-0}" -ne 0 ]]; then
    echo "stub adapter failing on purpose" >&2
    exit "$ADAPTER_RC"
fi
printf 'adapter says ok'
EOF
chmod +x "$WORK/adapter"

export HEADLONG_HOME="$WORK/home"   # bin/llm writes run/llm_health.json here
mkdir -p "$HEADLONG_HOME"
export ADAPTER_ARGS="$WORK/adapter_args"
export ADAPTER_STDIN="$WORK/adapter_stdin"
export ADAPTER_SYS="$WORK/adapter_sys"
export LLM_RETRIES=0
unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY \
      OPENCODE_API_KEY LLM_API_KEY LLM_PROVIDER LLM_API_URL LLM_MODEL \
      LLM_MAX_TOKENS SHELLM_MODEL SHELLM_API_URL LLM_ADAPTER \
      ADAPTER_USAGE ADAPTER_RC LLM_USAGE_FILE LLM_USAGE_LEDGER
cd "$WORK" || exit 1

LLM="$REPO/bin/llm"

reset() { : > "$ADAPTER_ARGS"; : > "$ADAPTER_STDIN"; : > "$ADAPTER_SYS"; }

has_arg_pair() {  # has_arg_pair FLAG VALUE — argv is recorded one per line
    grep -A1 -x -- "$1" "$ADAPTER_ARGS" | tail -1 | grep -qx -- "$2"
}

# ---------------------------------------------------------------------------
# The adapter runs, stdout passes through, flags carry model and cap
# ---------------------------------------------------------------------------

reset
out=$(LLM_PROVIDER=adapter LLM_ADAPTER="$WORK/adapter" \
      "$LLM" -m qwen3:8b "say ok" 2>"$WORK/stderr")
rc=$?
if [[ "$rc" -eq 0 && "$out" == "adapter says ok" ]]; then
    ok "adapter runs and its stdout is llm's stdout"
else
    bad "adapter runs and its stdout is llm's stdout" "rc=$rc: $(head -1 "$WORK/stderr")"
fi
if has_arg_pair "--model" "qwen3:8b"; then
    ok "--model is passed"
else
    bad "--model is passed" "$(tr '\n' ' ' < "$ADAPTER_ARGS")"
fi
if has_arg_pair "--max-tokens" "16384"; then
    ok "unknown model gets the 16384 fallback cap"
else
    bad "unknown model gets the 16384 fallback cap" "$(tr '\n' ' ' < "$ADAPTER_ARGS")"
fi
if jq -e '.[0].role == "user" and (.[0].content | contains("say ok"))' "$ADAPTER_STDIN" >/dev/null 2>&1; then
    ok "messages JSON arrives on stdin"
else
    bad "messages JSON arrives on stdin" "$(head -c 120 "$ADAPTER_STDIN")"
fi

# ---------------------------------------------------------------------------
# -t override, system prompt, --no-stream, --effort, --thinking LEVEL
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=adapter LLM_ADAPTER="$WORK/adapter" \
    "$LLM" -t 512 -m qwen3:8b -s "be brief" --no-stream \
    --effort low --thinking high "say ok" >/dev/null 2>"$WORK/stderr"
if has_arg_pair "--max-tokens" "512"; then
    ok "-t overrides the cap"
else
    bad "-t overrides the cap" "$(tr '\n' ' ' < "$ADAPTER_ARGS")"
fi
if [[ "$(cat "$ADAPTER_SYS")" == "be brief" ]]; then
    ok "-s reaches the adapter via --system-prompt-file"
else
    bad "-s reaches the adapter via --system-prompt-file" "$(cat "$ADAPTER_SYS")"
fi
if grep -qx -- "--no-stream" "$ADAPTER_ARGS"; then
    ok "--no-stream is forwarded"
else
    bad "--no-stream is forwarded"
fi
if has_arg_pair "--effort" "low"; then
    ok "--effort is forwarded"
else
    bad "--effort is forwarded" "$(tr '\n' ' ' < "$ADAPTER_ARGS")"
fi
if has_arg_pair "--thinking" "high"; then
    ok "--thinking LEVEL is forwarded"
else
    bad "--thinking LEVEL is forwarded" "$(tr '\n' ' ' < "$ADAPTER_ARGS")"
fi

# ---------------------------------------------------------------------------
# Usage lands in the ledger
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=adapter LLM_ADAPTER="$WORK/adapter" \
    ADAPTER_USAGE='{"in_tok":11,"out_tok":22}' \
    LLM_USAGE_LEDGER="$WORK/ledger.jsonl" \
    "$LLM" -m qwen3:8b "say ok" >/dev/null 2>"$WORK/stderr"
if grep -q '"in_tok":11' "$WORK/ledger.jsonl" 2>/dev/null \
   && grep -q '"provider":"adapter"' "$WORK/ledger.jsonl"; then
    ok "adapter usage lands in the ledger"
else
    bad "adapter usage lands in the ledger" "$(head -1 "$WORK/ledger.jsonl" 2>/dev/null)"
fi

# ---------------------------------------------------------------------------
# Missing and non-executable adapters die loudly
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=adapter "$LLM" -m qwen3:8b "say ok" >/dev/null 2>"$WORK/stderr"
rc=$?
if [[ "$rc" -ne 0 ]] && grep -q 'LLM_ADAPTER is not set' "$WORK/stderr"; then
    ok "missing LLM_ADAPTER dies loudly"
else
    bad "missing LLM_ADAPTER dies loudly" "rc=$rc"
fi

reset
: > "$WORK/not-exec"
LLM_PROVIDER=adapter LLM_ADAPTER="$WORK/not-exec" \
    "$LLM" -m qwen3:8b "say ok" >/dev/null 2>"$WORK/stderr"
rc=$?
if [[ "$rc" -ne 0 ]] && grep -q 'not executable' "$WORK/stderr"; then
    ok "non-executable LLM_ADAPTER dies loudly"
else
    bad "non-executable LLM_ADAPTER dies loudly" "rc=$rc"
fi

# ---------------------------------------------------------------------------
# A failing adapter fails the call and marks health
# ---------------------------------------------------------------------------

reset
LLM_PROVIDER=adapter LLM_ADAPTER="$WORK/adapter" ADAPTER_RC=3 \
    "$LLM" -m qwen3:8b "say ok" >/dev/null 2>"$WORK/stderr"
rc=$?
if [[ "$rc" -ne 0 ]] && grep -q 'adapter exited 3' "$WORK/stderr"; then
    ok "nonzero adapter exit fails the call with the code reported"
else
    bad "nonzero adapter exit fails the call with the code reported" "rc=$rc: $(head -1 "$WORK/stderr")"
fi
if jq -e '.ok == false' "$HEADLONG_HOME/run/llm_health.json" >/dev/null 2>&1; then
    ok "adapter failure is recorded in the health marker"
else
    bad "adapter failure is recorded in the health marker" "$(cat "$HEADLONG_HOME/run/llm_health.json" 2>/dev/null)"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
