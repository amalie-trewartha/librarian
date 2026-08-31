#!/usr/bin/env bash
# tests/test_install_secret_argv.sh — the container install keeps API keys off
# the docker command line.
#
# install.sh forwards a key and the interview answers into the container it
# starts. A value passed as `-e VAR=value` is an argument of the docker client,
# so it is readable from `ps` by any other local user for as long as that
# process lives; tests/test_var_secrets.sh already pins the same rule for the
# shellm path, and thinkers/_lib/common.sh already forwards keys by bare name
# for the same reason. Keys therefore go by NAME, which requires them to be exported.
# HEADLONG_LOCAL_URL is treated the same way: an endpoint URL can carry
# user:pass@ credentials or a query token, so its value must not reach argv.
# The remaining non-secret answers stay inline because two of them
# (HEADLONG_REPO, HEADLONG_BRANCH) are assigned by install.sh without export
# and a bare name would silently forward nothing.

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Source install.sh for its functions: drop the trailing `main "$@"`, which
# would otherwise run the installer.
sed '$ d' "$REPO/install.sh" > "$WORK/install.lib"

SECRET=sk-or-ARGVCANARY
OPENCODE_SECRET=sk-OPENCODECANARY
LOCAL_SECRET=local-ARGVCANARY
args=$(
    export OPENROUTER_API_KEY="$SECRET"
    export OPENCODE_API_KEY="$OPENCODE_SECRET"
    export HEADLONG_LOCAL_API_KEY="$LOCAL_SECRET"
    export HEADLONG_IDENTITY_NAME=ada
    export HEADLONG_LOCAL_URL=http://127.0.0.1:8090/v1
    # Set, deliberately NOT exported, which is how install.sh leaves them.
    # shellcheck disable=SC2034  # read by _docker_forward_args through ${!var}
    HEADLONG_REPO=https://example.invalid/fork.git
    # shellcheck disable=SC2034  # read by _docker_forward_args through ${!var}
    HEADLONG_BRANCH=experiment
    # shellcheck disable=SC1090  # generated copy of the installer under test
    source "$WORK/install.lib"
    # Flatten the NUL delimiters here: command substitution drops NUL bytes,
    # so the records must become space-separated before capture.
    _docker_forward_args | tr '\0' ' '
)
flat=" $args "   # padded so a match at either end still has a boundary

case "$flat" in
    *"$SECRET"*) bad "no API key value on the docker command line" "found $SECRET in: $flat" ;;
    *)           ok  "no API key value on the docker command line" ;;
esac
case "$flat" in
    *"-e OPENROUTER_API_KEY "*) ok "the key is forwarded by name" ;;
    *) bad "the key is forwarded by name" "got: $flat" ;;
esac
case "$flat" in
    *"$OPENCODE_SECRET"*) bad "every provider key goes by name, not just the first" "found $OPENCODE_SECRET in: $flat" ;;
    *"-e OPENCODE_API_KEY "*) ok "every provider key goes by name, not just the first" ;;
    *) bad "every provider key goes by name, not just the first" "got: $flat" ;;
esac
case "$flat" in
    *"$LOCAL_SECRET"*) bad "the local server key stays off the docker command line" "found $LOCAL_SECRET in: $flat" ;;
    *"-e HEADLONG_LOCAL_API_KEY "*) ok "the local server key is forwarded by name" ;;
    *) bad "the local server key is forwarded by name" "got: $flat" ;;
esac
# The endpoint URL can carry user:pass@ credentials or a query token, so it
# is forwarded by NAME (not inline), like the keys — its value must not reach
# the docker client's argv.
case "$flat" in
    *"http://host.docker.internal:8090/v1"*) bad "the local model URL stays off the docker command line" "found the URL value in: $flat" ;;
    *"-e HEADLONG_LOCAL_URL "*) ok "the local model URL is forwarded by name" ;;
    *) bad "the local model URL is forwarded by name" "got: $flat" ;;
esac
# Forwarding by name only works if the (possibly rewritten) URL is exported.
url_exported=$(
    export HEADLONG_LOCAL_URL=http://127.0.0.1:8090/v1
    # shellcheck disable=SC1090  # generated copy of the installer under test
    source "$WORK/install.lib"
    _docker_forward_args > "$WORK/fwd_url"
    # shellcheck disable=SC2034  # records drained, not inspected
    while IFS= read -r -d '' line; do :; done < "$WORK/fwd_url"
    export -p | grep -c '^declare -x HEADLONG_LOCAL_URL=.*host.docker.internal' || true
)
[[ "$url_exported" -ge 1 ]] && ok "the rewritten URL is exported for the bare name" \
    || bad "the rewritten URL is exported for the bare name" "not exported/rewritten after the call"
case "$flat" in
    *"-e HEADLONG_IDENTITY_NAME=ada "*) ok "interview answers are still forwarded inline" ;;
    *) bad "interview answers are still forwarded inline" "got: $flat" ;;
esac
# The two the script assigns itself: a bare name would forward nothing, because
# docker reads a name-only -e from its own environment.
case "$flat" in
    *"-e HEADLONG_REPO=https://example.invalid/fork.git "*) ok "an unexported repo override still reaches the container" ;;
    *) bad "an unexported repo override still reaches the container" "got: $flat" ;;
esac
case "$flat" in
    *"-e HEADLONG_BRANCH=experiment "*) ok "an unexported branch override still reaches the container" ;;
    *) bad "an unexported branch override still reaches the container" "got: $flat" ;;
esac

# Forwarding by name only works if the variable is actually exported, so prove
# the helper leaves it that way rather than trusting that the caller did.
exported=$(
    OPENROUTER_API_KEY="$SECRET"        # set, NOT exported
    # shellcheck disable=SC1090  # generated copy of the installer under test
    source "$WORK/install.lib"
    # The caller's exact collection pattern from _offer_docker_install: a
    # redirected call plus a NUL read loop. Process substitution here would
    # confine the export to a child and forward an empty value.
    _docker_forward_args > "$WORK/fwd"
    # shellcheck disable=SC2034  # the records are drained, not inspected
    while IFS= read -r -d '' line; do :; done < "$WORK/fwd"
    export -p | grep -c '^declare -x OPENROUTER_API_KEY=' || true
)
[[ "$exported" -ge 1 ]] && ok "the key is exported, so the bare name carries a value" \
    || bad "the key is exported, so the bare name carries a value" "not exported after the call"

# With no key and no answers set, only the repo/branch defaults install.sh
# fills in are forwarded, and no key name appears at all.
none=$(
    unset OPENROUTER_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY OPENCODE_API_KEY
    unset LLM_API_KEY HEADLONG_LOCAL_API_KEY HEADLONG_LOCAL_URL
    unset HEADLONG_IDENTITY_NAME HEADLONG_IDENTITY_VIBE HEADLONG_IDENTITY_FOCUS
    unset HEADLONG_IDENTITY_USER HEADLONG_OPERATOR_NAME
    # shellcheck disable=SC1090  # generated copy of the installer under test
    source "$WORK/install.lib"
    _docker_forward_args | tr '\0' ' '
)
case "$none" in
    *API_KEY*) bad "no key is forwarded when none is set" "got: $none" ;;
    *)         ok  "no key is forwarded when none is set" ;;
esac

echo
echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
