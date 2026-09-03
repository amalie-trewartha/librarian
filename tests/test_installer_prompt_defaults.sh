#!/usr/bin/env bash
# test_installer_prompt_defaults.sh — first-run installer questions appear
# once, and pressing Enter at the local-model question selects cloud.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }

# Extract only the small decision helpers. Their dependencies are replaced
# below so the tests do not need a tty, Docker, a key, or a model server.
eval "$(sed -n '/^_location_offer_available()/,/^}/p' "$REPO/install.sh")"
eval "$(sed -n '/^ask_yn()/,/^}/p' "$REPO/tools/headlong-init")"
eval "$(sed -n '/^_ask_local_or_cloud()/,/^}/p' "$REPO/tools/headlong-init")"

# A bootstrap answer is temporary process state. The checkout installer sees
# the marker and skips its copy of the location question before checking the
# tty or Docker again.
export HEADLONG_INSTALL_LOCATION_CHOSEN=1
if _location_offer_available; then
    bad "location choice: checkout would ask again"
else
    ok "location choice: checkout skips the second prompt"
fi

# Keep the existing yes default for other confirmation questions, while the
# local-model offer passes an explicit no default.
ask() { printf '%s' "$2"; }
# shellcheck disable=SC2218  # ask_yn is extracted with eval above.
if ask_yn "ordinary question"; then
    ok "ask_yn: ordinary questions still default to yes"
else
    bad "ask_yn: ordinary questions still default to yes"
fi
# shellcheck disable=SC2218  # ask_yn is extracted with eval above.
if ask_yn "local question" "n"; then
    bad "ask_yn: explicit no default returns no"
else
    ok "ask_yn: explicit no default returns no"
fi

export HEADLONG_PROVIDER=""
export SHELLM_API_URL=""
export LLM_API_URL=""
export LLM_PROVIDER=""
export HAS_TTY=1
_have_key() { return 1; }
ASK_DEFAULT=""
ask_yn() { ASK_DEFAULT="${2:-y}"; [[ "$ASK_DEFAULT" != "n" ]]; }
if _ask_local_or_cloud; then
    bad "provider choice: Enter selected local"
else
    ok "provider choice: Enter selects cloud"
fi
if [[ "$ASK_DEFAULT" == "n" ]]; then
    ok "provider choice: local offer uses the no default"
else
    bad "provider choice: local offer uses the no default"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
