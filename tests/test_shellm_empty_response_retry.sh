#!/usr/bin/env bash
# tests/test_shellm_empty_response_retry.sh — call_llm only fails the call
# when llm actually failed.
#
# Usage: tests/test_shellm_empty_response_retry.sh
#
# `llm --thinking` streams the model's reasoning to stderr and, when the
# token budget runs out during that reasoning, returns 200 with no visible
# text and exits 0. run_loop's empty-response retry exists for exactly that
# case (feed the captured thinking back as assistant context and continue),
# so call_llm must hand it back an empty response instead of dying on the
# thinking text. A real failure — llm exiting non-zero — must still die.
#
# Live-provider check (2026-08-29, OpenRouter, claude-sonnet-5 and
# gpt-oss-120b): with the budget exhausted during reasoning, non-streaming
# calls return exit 0 with empty stdout, so the retry is reachable. On
# call_llm's actual streaming path it depends on whether any reasoning
# delta streamed before truncation: if yes, mark_emitted lets llm exit 0
# with the thinking on stderr (the case this retry feeds back); if nothing
# streamed, llm's own empty-stream guard retries 3x and exits non-zero,
# and call_llm correctly dies before the retry.
#
# call_llm is extracted from bin/shellm and exercised directly (sourcing the
# whole script would run it) against a stub `llm` on PATH.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/bin"
cat > "$tmp/bin/llm" <<'STUB'
#!/usr/bin/env bash
# Stub llm: LLM_STUB_MODE picks which provider outcome to imitate.
case "$LLM_STUB_MODE" in
    thinking_only)   printf 'Thinking: the budget ran out here\n' >&2; exit 0 ;;
    thinking_blank)  printf 'Thinking: the budget ran out here\n' >&2; printf '\n'; exit 0 ;;
    thinking_text)   printf 'Thinking: done\n' >&2; printf 'visible answer\n'; exit 0 ;;
    silent)          exit 0 ;;
    failed)          printf 'llm: error: API error (HTTP 500)\n' >&2; exit 1 ;;
esac
STUB
chmod +x "$tmp/bin/llm"

# Run call_llm the way run_loop does: inside a command substitution, in a
# shell with bin/shellm's own `set -euo pipefail`. The nesting is not
# cosmetic: bash does not carry errexit into the QUIET=0 branch's pipeline
# subshell from there, which is what lets that branch record llm's exit code
# at all. Writes the captured thinking to $tmp/think and stderr to $tmp/err.
run_call_llm() {
    local mode="$1" quiet="$2"
    : > "$tmp/think"
    LLM_STUB_MODE="$mode" QUIET="$quiet" PATH="$tmp/bin:$PATH" \
    SHELLM_MODEL=stub-model SHELLM_EFFORT=medium SHELLM_MAX_TOKENS='' \
    THINK_FILE="$tmp/think" REPO="$REPO" \
        bash -c '
            set -euo pipefail
            die() { echo "shellm: error: $*" >&2; exit 1; }
            _fn=$(sed -n "/^call_llm()/,/^}/p" "$REPO/bin/shellm")
            _last=$(printf "%s" "$_fn" | tail -n 1)
            if [ "$_last" != "}" ]; then
                echo "test bug: could not extract call_llm from bin/shellm" >&2; exit 2
            fi
            eval "$_fn"
            declare -f call_llm >/dev/null || { echo "test bug: call_llm not defined" >&2; exit 2; }
            _response=$(call_llm "system prompt" "[]" "$THINK_FILE")
            printf "%s" "$_response"
        ' 2>"$tmp/err"
}

check() {
    local label="$1" mode="$2" quiet="$3" want_rc="$4" want_out="$5"
    local out rc
    out=$(run_call_llm "$mode" "$quiet"); rc=$?
    if [[ "$rc" -eq "$want_rc" && "$out" == "$want_out" ]]; then
        ok "$label (QUIET=$quiet)"
    else
        bad "$label (QUIET=$quiet)" "rc=$rc want=$want_rc out=$(printf '%q' "$out") stderr=$(printf '%q' "$(cat "$tmp/err")")"
    fi
}

for quiet in 0 1; do
    # The reported bug: thinking on stderr with no visible text is not an
    # error, and dying on it makes run_loop's retry unreachable.
    check "thinking on stderr, no visible text returns empty" thinking_only "$quiet" 0 ""

    # The thinking has to survive the call, or the retry has nothing to feed
    # back and falls through to the sleep-and-repeat branch.
    run_call_llm thinking_only "$quiet" >/dev/null
    if [[ -s "$tmp/think" ]] && grep -q 'budget ran out' "$tmp/think"; then
        ok "thinking is captured for the retry (QUIET=$quiet)"
    else
        bad "thinking is captured for the retry (QUIET=$quiet)" "$(cat "$tmp/think")"
    fi

    # Whitespace-only output is the same empty response after $( ) strips it.
    check "blank line with thinking returns empty" thinking_blank "$quiet" 0 ""

    # A normal answer is unaffected by any of this.
    check "visible text is returned" thinking_text "$quiet" 0 "visible answer"

    # No output and nothing on stderr: still an empty response, still no die.
    check "silent success returns empty" silent "$quiet" 0 ""

    # Must-not: a failed llm call still dies rather than reaching the retry.
    check "a non-zero llm exit still fails the call" failed "$quiet" 1 ""
    if grep -q 'llm failed (exit 1)' "$tmp/err"; then
        ok "the failure message names llm's exit code (QUIET=$quiet)"
    else
        bad "the failure message names llm's exit code (QUIET=$quiet)" "$(cat "$tmp/err")"
    fi
done

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
