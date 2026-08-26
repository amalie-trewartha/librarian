#!/usr/bin/env bash
# tests/test_sandbox_symlink_mounts.sh — which host paths the broker will mount
# into the sandbox.
#
# Usage: tests/test_sandbox_symlink_mounts.sh
#
# Why: symlink_mounts() mounts the *parent directory* of every symlink target
# it finds in the workdir, and the agent has write access to that workdir. So
# `ln -s ~/.ssh/id_ed25519 x` used to be enough to get ~/.ssh mounted into the
# next container, and `ln -s ~/.headlong/.env x` the state home holding the API
# key — the sandbox handing over host files rather than being broken out of.
# Targets are now confined to the app checkout plus whatever the operator opts
# into via HEADLONG_SANDBOX_RO_DIRS.
#
# The functions are exercised directly; no docker daemon and no network.

set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
BROKER="$REPO/tools/shellm-docker-broker"

WORK=$(mktemp -d)
trap 'cd /; rm -rf "$WORK"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

# Pull just the functions under test out of the broker, which otherwise starts
# serving when run.
{ awk '/^path_under\(\)/,/^}/'         "$BROKER"
  awk '/^sandbox_ro_dirs\(\)/,/^}/'    "$BROKER"
  awk '/^symlink_allow_root\(\)/,/^}/' "$BROKER"
  awk '/^symlink_mounts\(\)/,/^}/'     "$BROKER"
} > "$WORK/funcs.sh"
log_msg() { :; }
# shellcheck disable=SC1090
. "$WORK/funcs.sh"

# A checkout shaped like the real one: the app dir is the one holding
# .identities, and thinkers/skills are symlinked into the identity from it.
APP="$WORK/app"
WD="$APP/.identities/ada/workdir"
mkdir -p "$APP/.identities/ada" "$APP/thinkers/monolith" "$WD"
echo step > "$APP/thinkers/monolith/step"
ln -sf "$APP/thinkers/monolith/step" "$WD/step"

# Somewhere the operator never opted into, standing in for ~/.ssh.
SECRETS="$WORK/secrets"; mkdir -p "$SECRETS"; echo key > "$SECRETS/id_ed25519"
# Somewhere they did.
PROJ="$WORK/project"; mkdir -p "$PROJ"; echo code > "$PROJ/main.c"

export HEADLONG_HOME="$WORK/state-empty"
unset HEADLONG_SANDBOX_RO_DIRS

# --- no allowlist: the checkout is reachable, nothing else ------------------
ln -sf "$SECRETS/id_ed25519" "$WD/stolen"
out=$(symlink_mounts "$WD")
case "$out" in *"$APP/thinkers/monolith"*) ok "app-checkout symlink still mounted" ;;
                *) bad "app-checkout symlink still mounted" "$out" ;; esac
case "$out" in *"$SECRETS"*) bad "symlink to an unlisted dir refused" "$out" ;;
                *) ok "symlink to an unlisted dir refused" ;; esac

# --- the checkout root itself must not escape to its parent -----------------
# The mount is the target's parent dir, so a symlink AT the checkout root
# would mount dirname(checkout) — the checkout's parent — unless the parent,
# not the target, is what gets checked.
rm -f "$WD/stolen"
ln -sf "$APP" "$WD/whole_checkout"
out=$(symlink_mounts "$WD")
# A mount line is "<dir>:<dir>:ro"; the parent is followed by ':' only when
# the mount dir is exactly the parent (a legit "$APP/..." mount is followed
# by '/'), so this substring is precise.
PARENT=$(dirname "$APP")
case "$out" in
    *"$PARENT:"*) bad "symlink to the checkout root does not mount its parent" "$out" ;;
    *)            ok "symlink to the checkout root does not mount its parent" ;;
esac
rm -f "$WD/whole_checkout"

# --- opting a directory in makes it reachable, and only it ------------------
export HEADLONG_SANDBOX_RO_DIRS="$PROJ"
ln -sf "$PROJ/main.c" "$WD/proj"
out=$(symlink_mounts "$WD")
case "$out" in *"$PROJ"*) ok "symlink into an allowlisted dir permitted" ;;
                *) bad "symlink into an allowlisted dir permitted" "$out" ;; esac
case "$out" in *"$SECRETS"*) bad "unlisted dir still refused with an allowlist set" "$out" ;;
                *) ok "unlisted dir still refused with an allowlist set" ;; esac

# --- sandbox_ro_dirs ---------------------------------------------------------
[ "$(sandbox_ro_dirs | grep -c "$PROJ")" -eq 1 ] \
    && ok "sandbox_ro_dirs reads the environment" || bad "sandbox_ro_dirs reads the environment"

export HEADLONG_SANDBOX_RO_DIRS="$PROJ:$WORK/does-not-exist"
[ -z "$(sandbox_ro_dirs | grep does-not-exist)" ] \
    && ok "sandbox_ro_dirs drops missing dirs" || bad "sandbox_ro_dirs drops missing dirs"

# A single entry has no trailing newline once split; the last one must survive.
export HEADLONG_SANDBOX_RO_DIRS="$PROJ"
[ "$(sandbox_ro_dirs | wc -l | tr -d ' ')" -eq 1 ] \
    && ok "sandbox_ro_dirs yields a sole entry (no trailing newline)" \
    || bad "sandbox_ro_dirs yields a sole entry (no trailing newline)"

unset HEADLONG_SANDBOX_RO_DIRS
mkdir -p "$WORK/state"; export HEADLONG_HOME="$WORK/state"
printf 'HEADLONG_SANDBOX_RO_DIRS=%s\n' "$PROJ" > "$WORK/state/.env"
[ "$(sandbox_ro_dirs | grep -c "$PROJ")" -eq 1 ] \
    && ok "sandbox_ro_dirs falls back to the state .env" || bad "sandbox_ro_dirs falls back to the state .env"

# --- a workdir with no checkout above it allows nothing outside itself -------
unset HEADLONG_SANDBOX_RO_DIRS; export HEADLONG_HOME="$WORK/state-empty"
LONE="$WORK/lone"; mkdir -p "$LONE"; ln -sf "$SECRETS/id_ed25519" "$LONE/x"
out=$(symlink_mounts "$LONE")
case "$out" in *"$SECRETS"*) bad "no-checkout workdir denies outside targets" "$out" ;;
                *) ok "no-checkout workdir denies outside targets" ;; esac

# --- the docker argv must guard the mount arrays against set -u -------------
# The broker runs `set -u`; on bash 3.2 an unguarded "${empty[@]}" aborts with
# "unbound variable", and in the default config (no allowlist, no followed
# symlinks) both mount arrays are empty. The argv must expand them with the
# ${arr[@]+"${arr[@]}"} guard. Assert the source uses it and not the bare form.
for arr in symlink_vols ro_vols; do
    if grep -q "\${$arr\[@\]+\"\${$arr\[@\]}\"}" "$BROKER"; then
        ok "$arr expanded with the empty-array guard"
    else
        bad "$arr expanded with the empty-array guard" "bare expansion aborts under set -u on bash 3.2"
    fi
done
# And the guarded idiom actually survives set -u on this platform's bash.
if /bin/bash -c 'set -euo pipefail; a=(); c=(x ${a[@]+"${a[@]}"} y); printf "%s\n" "${c[@]}"' >/dev/null 2>&1; then
    ok "empty-array guard survives set -u on /bin/bash"
else
    bad "empty-array guard survives set -u on /bin/bash"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
