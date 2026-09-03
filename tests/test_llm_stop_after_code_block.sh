#!/usr/bin/env bash
# tests/test_llm_stop_after_code_block.sh — bin/llm stops reading the stream
# once the first fenced code block closes (LLM_STOP_AFTER_CODE_BLOCK).
#
# Usage: tests/test_llm_stop_after_code_block.sh
#
# bin/shellm runs the first fenced block of a response and discards the rest.
# On Audel (grok, 2026-09) 7% of responses kept going after the block with
# fake step metadata and another thought and block, and some looped that way
# until the 600s transfer cap killed the run. With the stop on, llm returns
# the moment the block closes. curl is stubbed with an SSE stream that keeps
# writing after the block; no network.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

# --- curl stub: streams the lines of $STREAM_FILE as one SSE delta each -----
# It keeps writing after the block, and exits 23 with "Failed writing body"
# when the reader has gone away (what real curl does). $STUB_LINES_SENT
# records how far it got.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
sent=0
while IFS= read -r line || [[ -n "$line" ]]; do
    chunk=$(printf '%s\n' "$line" | jq -Rsc '{choices:[{delta:{content:.}}]}')
    if ! printf 'data: %s\n\n' "$chunk"; then
        printf '%s\n' "$sent" > "$STUB_LINES_SENT"
        echo "curl: (23) Failed writing body" >&2
        exit 23
    fi
    sent=$((sent+1))
    printf '%s\n' "$sent" > "$STUB_LINES_SENT"
done < "$STREAM_FILE"
printf 'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":%s}}\n\n' "$sent"
printf 'data: [DONE]\n'
EOF
chmod +x "$WORK/bin/curl"
export PATH="$WORK/bin:$PATH"
export HEADLONG_HOME="$WORK/home"
mkdir -p "$HEADLONG_HOME"
export STUB_LINES_SENT="$WORK/sent"
export LLM_RETRIES=0
export LLM_USAGE_LEDGER="$WORK/ledger.jsonl"
unset ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY \
      OPENCODE_API_KEY LLM_API_KEY LLM_PROVIDER LLM_API_URL LLM_MODEL \
      LLM_MAX_TOKENS SHELLM_MODEL SHELLM_API_URL LLM_STOP_AFTER_CODE_BLOCK
cd "$WORK" || exit 1
LLM="$REPO/bin/llm"
URL="http://127.0.0.1:9/v1/chat/completions"
call() { LLM_PROVIDER=openai-compatible LLM_API_URL="$URL" "$LLM" -m stub "$@" "go" 2>"$WORK/stderr"; }
trap 'trap - SIGPIPE' SIGPIPE 2>/dev/null || true

# --- 1. a runaway continuation is cut at the closing fence -----------------
{
    printf 'Checking the log first.\n'
    printf '```bash\n'
    printf 'tail -n 3 log.txt\n'
    printf '```\n'
    printf '\n[in_tok]\n31864\n\n[run_id]\nfake\n\n'
    printf 'Now the next step.\n```bash\necho ping1\n```\n'
    i=0; while [[ $i -lt 400 ]]; do printf '```bash\necho ping%s\n```\n[out_tok]\n1\n' "$i"; i=$((i+1)); done
} > "$WORK/runaway.txt"
export STREAM_FILE="$WORK/runaway.txt"
: > "$STUB_LINES_SENT"
out=$(call --stop-after-code-block); rc=$?
expected=$'Checking the log first.\n```bash\ntail -n 3 log.txt\n```'
if [[ "$rc" -eq 0 && "$out" == "$expected" ]]; then
    ok "output ends at the first closing fence, exit 0"
else
    bad "output ends at the first closing fence, exit 0" "rc=$rc out=$(printf '%s' "$out" | head -c 200 | tr '\n' '|')"
fi
sent=$(cat "$STUB_LINES_SENT" 2>/dev/null || echo 0)
if [[ "$sent" -lt 100 ]]; then
    ok "the stream was abandoned early (stub sent $sent of 1600+ lines)"
else
    bad "the stream was abandoned early" "stub sent $sent lines"
fi
grep -q 'stopped reading after the first code block' "$WORK/stderr" && ok "stderr says the stream was cut" || bad "stderr says the stream was cut" "$(head -2 "$WORK/stderr")"
grep -q 'Failed writing body\|curl error' "$WORK/stderr" && bad "curl's broken-pipe exit is not reported as an error" || ok "curl's broken-pipe exit is not reported as an error"
if [[ -s "$LLM_USAGE_LEDGER" ]] && jq -e '.estimated == true and .out_tok > 0 and (has("in_tok") | not)' "$LLM_USAGE_LEDGER" >/dev/null 2>&1; then
    ok "the ledger gets an estimated out_tok, no in_tok"
else
    bad "the ledger gets an estimated out_tok, no in_tok" "$(cat "$LLM_USAGE_LEDGER" 2>/dev/null)"
fi

# --- 2. the env var does the same as the flag -------------------------------
: > "$STUB_LINES_SENT"
out=$(LLM_STOP_AFTER_CODE_BLOCK=1 call); rc=$?
[[ "$rc" -eq 0 && "$out" == "$expected" ]] && ok "LLM_STOP_AFTER_CODE_BLOCK=1 cuts the same way" || bad "LLM_STOP_AFTER_CODE_BLOCK=1 cuts the same way" "rc=$rc"

# --- 3. off by default: the whole stream is read ---------------------------
: > "$LLM_USAGE_LEDGER"
out=$(call); rc=$?
lines=$(printf '%s\n' "$out" | wc -l | tr -d ' ')
if [[ "$rc" -eq 0 && "$lines" -gt 1600 && "$out" == *'echo ping399'* ]]; then
    ok "without the option every line is read ($lines lines)"
else
    bad "without the option every line is read" "rc=$rc lines=$lines"
fi
jq -e '.in_tok == 100 and (has("estimated") | not)' "$LLM_USAGE_LEDGER" >/dev/null 2>&1 && ok "a full read keeps the provider's usage" || bad "a full read keeps the provider's usage" "$(cat "$LLM_USAGE_LEDGER")"

# --- 4. a fence inside a heredoc does not close the block ------------------
{
    printf 'Write the note.\n'
    printf '```bash\n'
    printf "cat > note.md <<'EOF'\n"
    printf '# Title\n```\nnot a real fence\n```\n'
    printf 'EOF\n'
    printf 'cat <<"DOC" > other.md\n```\nDOC\n'
    printf 'cat <<\\RAW\n```\nRAW\n'
    printf 'echo done\n'
    printf '```\n'
    printf 'trailing chatter\n'
} > "$WORK/heredoc.txt"
export STREAM_FILE="$WORK/heredoc.txt"
out=$(call --stop-after-code-block); rc=$?
if [[ "$rc" -eq 0 && "$out" == *'echo done'* && "$out" != *'trailing chatter'* ]]; then
    ok "quoted, double-quoted, and backslash heredocs shield inner fences; the real close still cuts"
else
    bad "quoted, double-quoted, and backslash heredocs shield inner fences; the real close still cuts" "rc=$rc out=$(printf '%s' "$out" | tr '\n' '|' | head -c 300)"
fi

# --- 5. a tagged fence hanging off a prose line opens the block -----------
{
    printf 'Do it now.```bash\n'
    printf 'echo tagged\n'
    printf '```\n'
    printf 'more\n'
} > "$WORK/tagged.txt"
export STREAM_FILE="$WORK/tagged.txt"
out=$(call --stop-after-code-block); rc=$?
[[ "$rc" -eq 0 && "$out" == *'echo tagged'* && "$out" != *more* ]] && ok "a tagged fence appended to prose opens the block" || bad "a tagged fence appended to prose opens the block" "rc=$rc out=$(printf '%s' "$out" | tr '\n' '|')"

# --- 6. no code block at all: the stream is read to the end ---------------
printf 'Just an answer.\nWith two lines.\n' > "$WORK/plain.txt"
export STREAM_FILE="$WORK/plain.txt"
out=$(call --stop-after-code-block); rc=$?
[[ "$rc" -eq 0 && "$out" == $'Just an answer.\nWith two lines.' ]] && ok "a response with no block is read whole" || bad "a response with no block is read whole" "rc=$rc out=$(printf '%s' "$out" | tr '\n' '|')"
grep -q 'stopped reading' "$WORK/stderr" && bad "no stop notice without a block" || ok "no stop notice without a block"

# --- 7. bin/shellm asks llm for the stop -----------------------------------
grep -q -- '--stop-after-code-block' "$REPO/bin/shellm" && grep -q 'SHELLM_STOP_AFTER_CODE_BLOCK' "$REPO/bin/shellm" \
    && ok "shellm passes --stop-after-code-block (SHELLM_STOP_AFTER_CODE_BLOCK)" || bad "shellm passes --stop-after-code-block"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
