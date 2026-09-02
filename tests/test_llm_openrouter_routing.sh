#!/usr/bin/env bash
# test_llm_openrouter_routing.sh — the OpenRouter provider routing block
#
# Usage: tests/test_llm_openrouter_routing.sh
#
# OpenRouter serves one model id from several hosts and picks one per request,
# so `provider` is the only thing in the payload that says where a prompt may
# go. curl is stubbed (it keeps the payload file bin/llm hands it and answers
# with a minimal SSE stream), so what is under test is the JSON that would have
# been sent, without touching the network.
#
# Three things are checked. The shape: the block appears only when a knob is
# set, `only` is emitted without touching allow_fallbacks (OpenRouter treats
# `only` as a hard allowlist, and allow_fallbacks is a separate retry setting),
# and slugs are normalised. The parsing: every knob is normalised once, so a
# settings file saying `LLM_OR_ZDR=true` cannot read as false, and a value that
# means neither is refused rather than guessed at.
#
# And that the filter compiles at all: the payload builders are the one part of
# bin/llm the rest of the suite never reaches, because every other test stubs
# `llm` itself. That gap is not hypothetical — `{provider: (if … end) + (if …
# end)}` parses under jq 1.8 and is a syntax error under jq 1.7, which is what
# ubuntu-latest ships and therefore what CI runs, so a filter only ever tried on
# a 1.8 dev box can be broken for every CI run and every container user. Any
# such error turns the pinned cases below red.
#
# Every run happens in a scratch cwd with HEADLONG_HOME pointed at an empty
# directory, so the checkout's own .env and the developer's ~/.headlong/.env
# cannot reach into the results.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found — bin/llm needs it, so this proves nothing"; exit 1; }

# --- curl stub ---------------------------------------------------------------
# bin/llm passes the payload as -d @FILE (never on argv), so the stub copies
# that file aside and answers with one SSE chunk plus [DONE].
mkdir -p "$WORK/bin" "$WORK/run" "$WORK/home/.headlong"
cat > "$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
    [[ "$a" == "-d@"* ]] && cp "${a#-d@}" "$PAYLOAD_OUT" 2>/dev/null
    [[ "$a" == @* ]] && cp "${a#@}" "$PAYLOAD_OUT" 2>/dev/null
done
printf 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
printf 'data: [DONE]\n'
EOF
chmod +x "$WORK/bin/curl"
export PATH="$WORK/bin:$PATH"
export PAYLOAD_OUT="$WORK/payload.json"

# run_llm [VAR=VAL ...] -- [llm args ...]
# Runs from a scratch cwd with an empty state home, so only what a case sets
# is in play. Leaves the payload in $PAYLOAD_OUT, stderr in $WORK/err.
run_llm() {
    local -a envs=()
    while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
    shift || true
    : > "$PAYLOAD_OUT"
    ( cd "$WORK/run" && printf 'hi' | env -u LLM_OR_ONLY -u LLM_OR_DATA_COLLECTION \
        -u LLM_OR_ZDR -u SHELLM_HOME -u LLM_PROVIDER \
        HOME="$WORK/home" HEADLONG_HOME="$WORK/home/.headlong" \
        OPENROUTER_API_KEY="test-key" OPENAI_API_KEY="test-key" \
        "${envs[@]+"${envs[@]}"}" \
        "$REPO/bin/llm" -m "openai/gpt-4o-mini" "$@" ) \
        > "$WORK/out" 2> "$WORK/err"
}

q() { jq -r "$1" "$PAYLOAD_OUT" 2>/dev/null; }

# --- 1. unpinned callers are unchanged ---------------------------------------
run_llm --
[[ "$(q 'has("provider")')" == "false" ]] \
    && ok "no knobs: payload carries no provider block" \
    || bad "no knobs: payload carries no provider block" "got $(q 'has("provider")')"

# --- 2. the pin, and only the pin ---------------------------------------------
run_llm -- --or-only openai
[[ "$(q '.provider.only | join(",")')" == "openai" ]] \
    && ok "--or-only pins provider.only" \
    || bad "--or-only pins provider.only" "got $(q '.provider.only')"
# OpenRouter documents `only` as the allowlist and allow_fallbacks as a
# separate retry setting; coupling them would refuse failover between two hosts
# the caller explicitly allowed, and buy nothing, since a host outside `only`
# is never used either way.
[[ "$(q '.provider | has("allow_fallbacks")')" == "false" ]] \
    && ok "--or-only leaves allow_fallbacks alone" \
    || bad "--or-only leaves allow_fallbacks alone" "got $(q '.provider.allow_fallbacks')"

# --- 3. the slug list is normalised ------------------------------------------
run_llm -- --or-only " OpenAI , Azure ,, "
[[ "$(q '.provider.only | join(",")')" == "openai,azure" ]] \
    && ok "slug list is downcased, trimmed and de-blanked" \
    || bad "slug list is downcased, trimmed and de-blanked" "got $(q '.provider.only | join(",")')"

# A pin that normalises to nothing is a typo. Treating it as "no pin" would
# route anywhere, which is the opposite of what was asked for.
run_llm -- --or-only " , ,"
[[ $? -ne 0 ]] && grep -q "no provider slugs left" "$WORK/err" \
    && ok "a pin that normalises away is refused" \
    || bad "a pin that normalises away is refused" "stderr: $(head -c160 "$WORK/err")"

# --- 4. data_collection is allow or deny -------------------------------------
run_llm -- --or-data-collection deny
[[ "$(q '.provider.data_collection')" == "deny" ]] \
    && ok "--or-data-collection deny is passed through" \
    || bad "--or-data-collection deny is passed through" "got $(q '.provider.data_collection')"

run_llm -- --or-data-collection nope
[[ $? -ne 0 ]] && grep -q "must be allow or deny" "$WORK/err" \
    && ok "an unknown data_collection value is refused" \
    || bad "an unknown data_collection value is refused" "stderr: $(head -c160 "$WORK/err")"

# --- 5. zdr is parsed once, not re-guessed at each use -----------------------
run_llm -- --or-zdr
[[ "$(q '.provider.zdr')" == "true" ]] \
    && ok "--or-zdr requests zero-data-retention endpoints" \
    || bad "--or-zdr requests zero-data-retention endpoints" "got $(q '.provider.zdr')"

bads=""
for v in true yes on 1 TRUE On; do
    run_llm "LLM_OR_ZDR=$v" --
    [[ "$(q '.provider.zdr')" == "true" ]] || bads="$bads $v"
done
[[ -z "$bads" ]] \
    && ok "LLM_OR_ZDR accepts true/yes/on/1 in any case" \
    || bad "LLM_OR_ZDR accepts true/yes/on/1 in any case" "not honoured:$bads"

bads=""
for v in false no 0 FALSE ""; do
    run_llm "LLM_OR_ZDR=$v" --
    [[ "$(q 'has("provider")')" == "false" ]] || bads="$bads '$v'"
done
[[ -z "$bads" ]] \
    && ok "LLM_OR_ZDR accepts false/no/0/empty as off" \
    || bad "LLM_OR_ZDR accepts false/no/0/empty as off" "still on for:$bads"

run_llm "LLM_OR_ZDR=maybe" --
[[ $? -ne 0 ]] && grep -q "must be 1/true/yes/on" "$WORK/err" \
    && ok "an unparseable LLM_OR_ZDR is refused, not read as false" \
    || bad "an unparseable LLM_OR_ZDR is refused, not read as false" "stderr: $(head -c160 "$WORK/err")"

# --- 6. all three compose ----------------------------------------------------
run_llm -- --or-only openai --or-data-collection deny --or-zdr
[[ "$(q '[.provider.only[0], .provider.data_collection, (.provider.zdr|tostring)] | join(" ")')" \
   == "openai deny true" ]] \
    && ok "all three knobs compose into one provider block" \
    || bad "all three knobs compose into one provider block" "got $(q '.provider')"

# --- 7. a constraint nobody typed here is announced --------------------------
# An LLM_OR_* out of a .env or a shell profile still decides where the prompt
# goes, so the effective routing is stated once on stderr.
run_llm "LLM_OR_ONLY=azure" --
[[ "$(q '.provider.only | join(",")')" == "azure" ]] \
    && ok "LLM_OR_ONLY is honoured like --or-only" \
    || bad "LLM_OR_ONLY is honoured like --or-only" "got $(q '.provider.only')"
grep -q "^llm: routing: openrouter only=azure$" "$WORK/err" \
    && ok "an environment-supplied constraint is announced on stderr" \
    || bad "an environment-supplied constraint is announced on stderr" "stderr: $(head -c160 "$WORK/err")"

run_llm -- --or-only azure
grep -q "llm: routing:" "$WORK/err" \
    && bad "a constraint typed on the command line is not announced" "stderr: $(head -c160 "$WORK/err")" \
    || ok "a constraint typed on the command line is not announced"

# --- 8. a .env layer reaches the knobs, and the test owns that file ----------
# Also the isolation check: every other case runs in this same cwd and sees no
# provider block, which only holds because nothing else put a .env here.
printf 'LLM_OR_ONLY=fromenvfile\n' > "$WORK/run/.env"
run_llm --
[[ "$(q '.provider.only | join(",")')" == "fromenvfile" ]] \
    && ok "a .env in the working directory supplies the knobs" \
    || bad "a .env in the working directory supplies the knobs" "got $(q '.provider.only')"
rm -f "$WORK/run/.env"

# --- 9. named and inferred providers behave the same -------------------------
run_llm -- --provider openrouter --or-only openai
[[ "$(q '.provider.only | join(",")')" == "openai" ]] \
    && ok "an explicitly named openrouter provider takes the knobs" \
    || bad "an explicitly named openrouter provider takes the knobs" "got $(q '.provider.only')"

# --- 10. other providers are told, not silently pinned -----------------------
# A stray LLM_OR_ZDR in a shell profile must neither read as a residency
# guarantee on a single-host provider nor kill the call. Kept on an
# OpenAI-compatible model so the stub's SSE is understood and what fails here
# can only be the guard, not the stream parser.
run_llm -- --provider openai -m gpt-4o-mini --or-zdr
rc=$?
[[ "$rc" -eq 0 ]] \
    && ok "an --or-* flag does not fail a non-OpenRouter call" \
    || bad "an --or-* flag does not fail a non-OpenRouter call" "exit $rc"
grep -q "OpenRouter-only" "$WORK/err" \
    && ok "an --or-* flag on another provider warns on stderr" \
    || bad "an --or-* flag on another provider warns on stderr" "stderr: $(head -c200 "$WORK/err")"
[[ "$(q 'has("provider")')" == "false" ]] \
    && ok "an --or-* flag adds no provider block for another provider" \
    || bad "an --or-* flag adds no provider block for another provider" "got $(q '.provider')"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
