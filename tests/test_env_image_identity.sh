#!/usr/bin/env bash
# test_env_image_identity.sh — a running env is only reusable for the image it
# was built from.
#
# Usage: tests/test_env_image_identity.sh
#
# By default shellm reuses any running env that env_metadata_matches accepts,
# so that predicate is the whole of what --docker-image means on a second run.
# It already compares access mode, tool mounts, --var mounts and the workdirs
# mount; the image was written to the env directory but never read back, so a
# run asking for a different image silently got the first container. The flag
# reads as accepted, and the run record then names the image that was requested
# rather than the one that served the run.
#
# env_metadata_matches and its message are lifted out of bin/shellm with sed
# (as tests/test_mem_frontmatter.sh does for bin/mem) so the predicate can be
# put through its cases directly, with the env directory on disk as the only
# input and no Docker daemon involved.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

eval "$(sed -n '/^docker_metadata_value()/,/^}/p'         "$REPO/bin/shellm")"
eval "$(sed -n '/^_compute_var_mounts()/,/^}/p'           "$REPO/bin/shellm")"
eval "$(sed -n '/^env_metadata_matches()/,/^}/p'          "$REPO/bin/shellm")"
eval "$(sed -n '/^env_metadata_mismatch_message()/,/^}/p' "$REPO/bin/shellm")"
eval "$(sed -n '/^_resume_docker_image()/,/^}/p'          "$REPO/bin/shellm")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

SHELLM_ENVS_DIR="$WORK/envs"
SHELLM_WORKDIRS_DIR="$WORK/workdirs"
# shellcheck disable=SC2034  # read by env_metadata_matches, eval'd in above
SHELLM_DOCKER_ACCESS="none"
_SHELLM_TOOL_MOUNTS_VERSION="v1"

# make_env NAME TYPE [IMAGE] — an env directory as env_register writes one.
# Omitting IMAGE is an env from before the image was recorded.
make_env() {
    local name="$1" type="$2" image="${3-}"
    local d="$SHELLM_ENVS_DIR/$name"
    mkdir -p "$d"
    printf '%s\n' "$type"                 > "$d/type"
    printf 'none\n'                       > "$d/docker_access"
    printf 'v1\n'                         > "$d/tool_mounts_version"
    printf '%s\n' "$SHELLM_WORKDIRS_DIR"  > "$d/workdirs_dir"
    : > "$d/var_mounts"
    [[ -n "$image" ]] && printf '%s\n' "$image" > "$d/image"
    return 0
}

matches() {  # matches ENV REQUESTED_IMAGE
    SHELLM_DOCKER_IMAGE="$2" env_metadata_matches "$1"
}

# --- 1. same image: reuse is what it was always for ---------------------------
make_env same docker "ubuntu:24.04"
matches same "ubuntu:24.04" \
    && ok "same image is reusable" \
    || bad "same image is reusable"

# --- 2. different image: the flag must not be silently voided -----------------
make_env other docker "ubuntu:24.04"
matches other "alpine:3.20" \
    && bad "a different image is not reusable" "reused an env built from another image" \
    || ok "a different image is not reusable"

# A tag move is a different image to anyone who typed the tag.
make_env tag docker "ubuntu:24.04"
matches tag "ubuntu:latest" \
    && bad "a different tag of the same repo is not reusable" \
    || ok "a different tag of the same repo is not reusable"

# --- 3. envs predating the recorded image still reattach ----------------------
# There is nothing to compare, so this stays a match: the alternative is
# forcing every already-running env to be rebuilt on upgrade.
make_env legacy docker
matches legacy "ubuntu:24.04" \
    && ok "an env with no recorded image is still reusable" \
    || bad "an env with no recorded image is still reusable"

# --- 4. the image gate applies to docker envs only ----------------------------
# The stored image disagrees here on purpose: without one, a local env would
# pass this whatever the gate did, and the case would prove nothing.
make_env plain local "ubuntu:24.04"
matches plain "alpine:3.20" \
    && ok "a local env is unaffected by the requested image" \
    || bad "a local env is unaffected by the requested image"

# --- 5. an explicit --env says which axis disagreed ---------------------------
# env_resolve turns a mismatch into this message when the env was named
# explicitly, so it has to name the image rather than fall through to the
# access-mode sentence, which would send the reader somewhere unrelated.
msg=$(SHELLM_DOCKER_IMAGE="alpine:3.20" env_metadata_mismatch_message other)
[[ "$msg" == *"ubuntu:24.04"* && "$msg" == *"alpine:3.20"* ]] \
    && ok "the mismatch message names both images" \
    || bad "the mismatch message names both images" "got: $msg"
[[ "$msg" != *"docker_access"* ]] \
    && ok "the mismatch message does not blame access mode" \
    || bad "the mismatch message does not blame access mode" "got: $msg"

# --- 6. resuming a run that used a custom image -------------------------------
# The image check above is what makes this necessary: a resume that quietly
# asked for the default would now fail to match the very env it is resuming,
# and build a second container beside it. _resume_docker_image is the decision,
# and the assertions below run its answer back through the predicate.
make_env custom docker "alpine:3.20"

img=$(_resume_docker_image 0 "ubuntu:latest" "alpine:3.20")
[[ "$img" == "alpine:3.20" ]] \
    && ok "a resume with no image given inherits the trajectory's" \
    || bad "a resume with no image given inherits the trajectory's" "got $img"
matches custom "$img" \
    && ok "the inherited image reattaches the env instead of rebuilding" \
    || bad "the inherited image reattaches the env instead of rebuilding"

# An image the caller did choose is never overridden, so a resume that names a
# conflicting one still fails rather than being quietly corrected into working.
img=$(_resume_docker_image 1 "ubuntu:24.04" "alpine:3.20")
[[ "$img" == "ubuntu:24.04" ]] \
    && ok "an explicit image survives a resume" \
    || bad "an explicit image survives a resume" "got $img"
matches custom "$img" \
    && bad "an explicit conflicting image still fails on resume" "reused anyway" \
    || ok "an explicit conflicting image still fails on resume"

# A trajectory with no recorded image (a local run, or one from before the
# field existed) leaves the caller's default alone.
img=$(_resume_docker_image 0 "ubuntu:latest" "")
[[ "$img" == "ubuntu:latest" ]] \
    && ok "a trajectory with no recorded image changes nothing" \
    || bad "a trajectory with no recorded image changes nothing" "got $img"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
