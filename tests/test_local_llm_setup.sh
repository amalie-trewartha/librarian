#!/usr/bin/env bash
# tests/test_local_llm_setup.sh — headlong-init's local (OpenAI-compatible)
# model-server setup path.
#
# Usage: tests/test_local_llm_setup.sh
#
# Why: the openai-compatible provider existed in bin/llm, but the installer
# only knew how to ask for a cloud API key — a local Ollama/LM Studio setup
# had to be configured by hand after install (issue #65). This pins the
# installer flow:
#
#   - HEADLONG_PROVIDER=local with HEADLONG_LOCAL_URL + HEADLONG_LOCAL_MODEL
#     completes with NO cloud key of any kind set, and persists
#     LLM_PROVIDER=openai-compatible, SHELLM_API_URL and SHELLM_MODEL
#   - the endpoint is verified with GET <base>/v1/models before anything is
#     written (a bad URL dies with a clear message, writes nothing)
#   - a base URL is normalized to the chat-completions URL bin/llm wants;
#     a full .../v1/chat/completions URL is accepted and kept as-is
#   - HEADLONG_LOCAL_MODEL wins over the server's list order (the operator's
#     explicit pick, not "first model in the list")
#   - the final proof is a real chat completion through bin/llm, so the
#     probe covers the exact chain a thinker will use
#   - HEADLONG_PROVIDER=cloud ignores local env vars entirely (the old path)
#   - a re-run keeps the local config without re-asking (idempotence)
#
# curl, docker, jq and llm are stubs; no network and no daemon are touched.
# Fixture keys below carry only a prefix shape and are deliberately not valid
# provider keys.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'cd /; rm -rf "$WORK"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check()     { local l="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$l"; else bad "$l"; fi; }
check_not() { local l="$1"; shift; if "$@" >/dev/null 2>&1; then bad "$l"; else ok "$l"; fi; }

# --- stubs -------------------------------------------------------------------
STUB="$WORK/stub"; mkdir -p "$STUB"

# curl: answer GET <base>/models from $CURL_MODELS_FILE (JSON body); append
# every /models hit to $CURL_MODELS_HITS (append, not last-write: init's
# dash-readiness poll curls too, and those must not erase the probe record).
# Every other request "fails" (empty reply), which is what a dead endpoint
# looks like to the caller. CURL_MODELS_UP=0 makes even /models unreachable
# (connection refused, rc 7) — a server that is simply down.
cat > "$STUB/curl" <<'STUBEOF'
#!/usr/bin/env bash
url=""
prev=""
for a in "$@"; do
    [[ "$prev" != -* && "$a" == http* ]] && url="$a"
    prev="$a"
done
case "$url" in
    */models)
        if [[ "${CURL_MODELS_UP:-1}" != "1" ]]; then
            printf 'curl: (7) Failed to connect\n' >&2
            exit 7
        fi
        printf '%s\n' "$url" >> "$CURL_MODELS_HITS"
        cat "$CURL_MODELS_FILE" 2>/dev/null || printf '{"data":[]}'
        exit 0
        ;;
esac
exit 7
STUBEOF

# docker: daemon up, nothing else (no image pull).
printf '#!/usr/bin/env bash\ncase "${1:-}" in info) exit 0 ;; *) exit 0 ;; esac\n' > "$STUB/docker"

# llm: an init that gets this far proves the chain — record the exit and let
# the caller decide the verdict via LLM_STUB_RC.
cat > "$STUB/llm" <<'STUBEOF'
#!/usr/bin/env bash
exit "${LLM_STUB_RC:-0}"
STUBEOF

chmod +x "$STUB/curl" "$STUB/docker" "$STUB/llm"

# A minimal fake checkout: headlong-init only checks that bin/shellm exists
# under HEADLONG_APP_DIR, but the no-tty path still creates an identity (the
# cloud tests drive it all the way there), so the tools it calls must exist.
APP="$WORK/app"; mkdir -p "$APP/bin" "$APP/tools"
: > "$APP/bin/shellm"

# identity: create the directory structure init writes into (memories, chat),
# without the real tool's behavior.
cat > "$APP/tools/identity" <<'STUBEOF'
#!/usr/bin/env bash
[[ "${1:-}" == "new" ]] || exit 0
name="${2:-ada}"; shift 2 || true
root="${IDENTITY_DIR:?IDENTITY_DIR not set}"
mkdir -p "$root/$name/memories" "$root/$name/chat"
# init sources activate and requires IDENTITY_NAME from it (thinkers start).
cat > "$root/$name/activate" <<'ACTEOF'
export IDENTITY_NAME=ada
ACTEOF
STUBEOF
chmod +x "$APP/tools/identity"

# thinkers / headlong-web: init starts the dash (no HEADLONG_NO_DASH in
# these runs), so the web stub must look alive: background itself quietly and
# print the serving line init greps for, then keep running so the pid check
# passes. thinkers is a no-op.
printf '#!/usr/bin/env bash\nexit 0\n' > "$APP/tools/thinkers"
cat > "$APP/tools/headlong-web" <<'STUBEOF'
#!/usr/bin/env bash
echo "headlong-web serving http://127.0.0.1:8099"
sleep 9999
STUBEOF
chmod +x "$APP/tools/thinkers" "$APP/tools/headlong-web"

# The persona phase reads the checkout's starter template (and the dash phase
# checks web/src/headlong_web/static/index.html).
mkdir -p "$APP/identities" "$APP/web/src/headlong_web/static"
printf 'name: {{identity_name}}\nvibe: {{vibe}}\nfocus: {{focus}}\n' \
    > "$APP/identities/starter-persona.md"
printf '<html></html>' > "$APP/web/src/headlong_web/static/index.html"

MODELS_FILE="$WORK/models.json"
CURL_MODELS_HITS="$WORK/models_hits"
: > "$CURL_MODELS_HITS"

# run_init <home> [VAR=VAL ...] — headlong-init with no tty, no inherited
# keys or local config, stubs first on PATH. Output to $WORK/out; the exit
# code lands in $RC (captured immediately — a following check() call would
# otherwise overwrite $?).
RC=0
run_init() {
    local home="$1"; shift
    mkdir -p "$home"
    env -i \
        HOME="$home" HEADLONG_HOME="$home/.headlong" HEADLONG_APP_DIR="$APP" \
        HEADLONG_NO_TTY=1 HEADLONG_UNSANDBOXED=1 PATH="$STUB:$PATH" \
        CURL_MODELS_FILE="$MODELS_FILE" CURL_MODELS_HITS="$CURL_MODELS_HITS" \
        CURL_MODELS_UP="${CURL_MODELS_UP:-1}" LLM_STUB_RC="${LLM_STUB_RC:-0}" "$@" \
        bash "$REPO/tools/headlong-init" </dev/null > "$WORK/out" 2>&1
    RC=$?
}

# ---------------------------------------------------------------------------
# local + URL + model: the full no-tty happy path
# ---------------------------------------------------------------------------
printf '{"data":[{"id":"qwen3:8b"},{"id":"gemma3:12b"},{"id":"llama3.2"}]}' > "$MODELS_FILE"
run_init "$WORK/h1" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:11434/v1 \
    HEADLONG_LOCAL_MODEL=qwen3:8b
check "local path: exits 0"                                  test "$RC" -eq 0
check "local path: persists LLM_PROVIDER=openai-compatible"  grep -qx 'LLM_PROVIDER=openai-compatible' "$WORK/h1/.headlong/.env"
check "local path: persists the chat-completions URL"        grep -qx 'SHELLM_API_URL=http://127.0.0.1:11434/v1/chat/completions' "$WORK/h1/.headlong/.env"
check "local path: persists the requested model"             grep -qx 'SHELLM_MODEL=qwen3:8b' "$WORK/h1/.headlong/.env"
check "local path: no key written"                           check_not grep -q '^LLM_API_KEY=' "$WORK/h1/.headlong/.env"
check "local path: models probe hit /v1/models"              grep -q '127.0.0.1:11434/v1/models' "$CURL_MODELS_HITS"

# A stray cloud key in the environment must not leak into the local .env.
run_init "$WORK/h1b" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:11434/v1 \
    HEADLONG_LOCAL_MODEL=qwen3:8b \
    ANTHROPIC_API_KEY=«redacted:sk-ant-…»
check "local path: a cloud key in the env stays out of the local .env" \
    check_not grep -q 'ANTHROPIC_API_KEY' "$WORK/h1b/.headlong/.env"

# ---------------------------------------------------------------------------
# a dead endpoint: verify first, write nothing
# ---------------------------------------------------------------------------
printf '{"data":[{"id":"qwen3:8b"}]}' > "$MODELS_FILE"
CURL_MODELS_UP=0 run_init "$WORK/h2" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:9999/v1 \
    HEADLONG_LOCAL_MODEL=qwen3:8b
check "dead endpoint: exits nonzero"                         test "$RC" -ne 0
check "dead endpoint: says it could not reach the server"    grep -qi 'could not reach\|could not list' "$WORK/out"
# The sandbox gate writes its own lines before the provider step; what matters
# is that no local-model config was persisted for a server that is not there.
check "dead endpoint: no local config persisted"             check_not grep -q 'LLM_PROVIDER=openai-compatible' "$WORK/h2/.headlong/.env"

# ---------------------------------------------------------------------------
# URL normalization: a full chat-completions URL is accepted as given
# ---------------------------------------------------------------------------
run_init "$WORK/h3" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:8080/v1/chat/completions \
    HEADLONG_LOCAL_MODEL=gemma3:12b
check "full URL accepted: exits 0"                           test "$RC" -eq 0
check "full URL accepted: kept as the chat URL"              grep -qx 'SHELLM_API_URL=http://127.0.0.1:8080/v1/chat/completions' "$WORK/h3/.headlong/.env"
check "full URL accepted: model probe still hit /v1/models"  grep -q '127.0.0.1:8080/v1/models' "$CURL_MODELS_HITS"

# A trailing slash on the base URL must not double up.
run_init "$WORK/h3b" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:11434/v1/ \
    HEADLONG_LOCAL_MODEL=llama3.2
check "trailing slash: exits 0"                              test "$RC" -eq 0
check "trailing slash: normalized chat URL"                  grep -qx 'SHELLM_API_URL=http://127.0.0.1:11434/v1/chat/completions' "$WORK/h3b/.headlong/.env"

# ---------------------------------------------------------------------------
# a key for a locked-down endpoint is persisted
# ---------------------------------------------------------------------------
printf '{"data":[{"id":"qwen3:8b"}]}' > "$MODELS_FILE"
run_init "$WORK/h4" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:1234/v1 \
    HEADLONG_LOCAL_MODEL=qwen3:8b \
    HEADLONG_LOCAL_API_KEY=«redacted:lm-studio-…»
check "local key: exits 0"                                   test "$RC" -eq 0
check "local key: persisted"                                 grep -qx 'LLM_API_KEY=«redacted:lm-studio-…»' "$WORK/h4/.headlong/.env"

# ---------------------------------------------------------------------------
# no model pinned, server exposes several: first in the list is used
# ---------------------------------------------------------------------------
run_init "$WORK/h5" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:11434/v1
check "no model pin: exits 0"                                test "$RC" -eq 0
check "no model pin: first listed model chosen"              grep -qx 'SHELLM_MODEL=qwen3:8b' "$WORK/h5/.headlong/.env"

# ---------------------------------------------------------------------------
# the final check is a real completion: a failing chain fails the setup
# ---------------------------------------------------------------------------
LLM_STUB_RC=1 run_init "$WORK/h6" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:11434/v1 \
    HEADLONG_LOCAL_MODEL=qwen3:8b
check "failing completion: exits nonzero"                    test "$RC" -ne 0
check "failing completion: says chat did not answer"         grep -qi 'did not answer\|chat completion' "$WORK/out"

# ---------------------------------------------------------------------------
# cloud wins explicitly: local env vars are ignored. The stub llm fails, so a
# nonzero exit proves the cloud key path was taken (and its failure mode is
# the key check, not the local flow).
# ---------------------------------------------------------------------------
LLM_STUB_RC=1 run_init "$WORK/h7" \
    HEADLONG_PROVIDER=cloud \
    HEADLONG_LOCAL_URL=http://127.0.0.1:11434/v1 \
    HEADLONG_LOCAL_MODEL=qwen3:8b \
    OPENAI_API_KEY=«redacted:sk-…»
check "cloud explicit: exits nonzero (stub llm fails, as in the key tests)" test "$RC" -ne 0
check "cloud explicit: no local config written"              check_not grep -q 'SHELLM_API_URL' "$WORK/h7/.headlong/.env"

# ---------------------------------------------------------------------------
# re-run idempotence: the same local config persists again (keyless), and
# an already-configured healthy local endpoint is kept without any
# HEADLONG_PROVIDER hint (the .env alone steers the re-run)
# ---------------------------------------------------------------------------
run_init "$WORK/h8" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:11434/v1 \
    HEADLONG_LOCAL_MODEL=qwen3:8b
run_init "$WORK/h8" \
    HEADLONG_PROVIDER=local \
    HEADLONG_LOCAL_URL=http://127.0.0.1:11434/v1 \
    HEADLONG_LOCAL_MODEL=qwen3:8b
check "re-run: still exits 0"                                test "$RC" -eq 0
check "re-run: config survives, exactly once per var" \
    test "$(grep -c '^SHELLM_API_URL=' "$WORK/h8/.headlong/.env")" -eq 1

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
