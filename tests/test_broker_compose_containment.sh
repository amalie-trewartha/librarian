#!/usr/bin/env bash
# tests/test_broker_compose_containment.sh — the broker's compose validator
# must contain host paths at a directory boundary, not a string prefix.
#
# compose_validate_model is the ONLY gate on the host paths in a compose model
# the sandbox hands the broker; handle_compose runs the real `docker compose`
# as soon as it returns 0. Two things are under test here.
#
# Containment: a textual prefix test is not it. It lets /host/work-secret
# through while the workdir is /host/work, and `docker compose config` hands
# the validator paths it has NOT normalised (an absolute source keeps its `..`,
# verified against compose 2.40.3) and never resolves symlinks. So the check
# resolves each path and gates it with path_under(), and the cases below are
# the four ways out: the sibling prefix, the `..` climb, the symlink, and the
# DANGLING symlink that `test -e` calls missing.
#
# Coverage: bind sources are a fraction of the surface. A build context, an
# absolute Dockerfile, an additional context, an ssh key, a local build cache,
# a develop.watch path, a volume driver_opts.device, a secret or config file,
# an env_file and a label_file each name a host path, and none of them passes
# through .services[].volumes. The last two survive only the uninterpolated
# render, and the default render is what reads them, so they are checked first
# and the case below proves the default render never runs when one is outside.
#
# The real function is exercised against a stubbed `docker compose ... config`
# so the resolved model is the input under test. The accept cases and the
# unrelated rejections (privileged, docker.sock) are here to prove the
# validator is live: without them a validator that rejected everything, or one
# that never ran, would pass just as well.

set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

# Not a skip: the broker cannot run without jq, so a green result here without
# it would report a gate as verified that was never executed.
command -v jq >/dev/null 2>&1 || { echo "FAIL jq not found — the broker needs it, so this proves nothing"; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

export SHELLM_BROKER_WORKDIR="$WORK/work"
mkdir -p "$SHELLM_BROKER_WORKDIR/sub" "$WORK/work-secret"
ln -s "$WORK/work-secret" "$SHELLM_BROKER_WORKDIR/escape"   # symlink out, from inside
ln -s "$SHELLM_BROKER_WORKDIR" "$WORK/alias"                # another spelling of the workdir
ln -s "$WORK/never-created" "$SHELLM_BROKER_WORKDIR/dangle"  # points out, target absent

# The broker's entry point is guarded by a BASH_SOURCE test, so sourcing it
# yields its functions without running main.

# `docker compose ... config --format json` returns whatever the case wrote.
# The validator renders the model TWICE and the two renders do not carry the
# same fields: only the uninterpolated one still names env_file and label_file,
# and the default one is the one that reads those files. So the stub answers
# them separately, from $CFG_RAW and $CFG, and records which ran. A stub that
# served one fixture to both would pass every env_file case with the second
# render deleted, and could not show that the check happens before the read.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/docker" <<'STUB'
#!/usr/bin/env bash
raw=""
for arg in "$@"; do
    [[ "$arg" == "--no-interpolate" ]] && raw=1
done
if [[ -n "$raw" ]]; then
    printf 'raw\n' >> "$CALLS"
    if [[ "${RAW_RC:-0}" != 0 ]]; then
        printf '%s\n' "${RAW_ERR:-uninterpolated render failed}" >&2
        exit "$RAW_RC"
    fi
    cat "$CFG_RAW"
else
    printf 'default\n' >> "$CALLS"
    if [[ "${CFG_RC:-0}" != 0 ]]; then
        printf '%s\n' "${CFG_ERR:-default render failed}" >&2
        exit "$CFG_RC"
    fi
    cat "$CFG"
fi
STUB
chmod +x "$WORK/bin/docker"
export PATH="$WORK/bin:$PATH"
export CFG="$WORK/cfg.json"
export CFG_RAW="$WORK/cfg_raw.json"
export CALLS="$WORK/calls"

# shellcheck disable=SC1090  # the broker under test
source "$REPO/tools/shellm-docker-broker"
set +e   # the broker sets -e; validation returning 65 is an expected outcome

# check <name> accept|reject <compose-config-json> [request-json]
#
# A rejection has to be the validator's verdict, not any nonzero exit, so rc
# is pinned to 65 — rc 65 also covers the non-containment rejections
# (privileged, an unparseable model, a failed render), which is why the cases
# that are ABOUT the containment message assert on LAST_OUT as well.
#
# The uninterpolated render defaults to an empty model, because the fields it
# alone carries are absent from the default one. A case about those fields sets
# RAW below and leaves them out of the default fixture, the way compose does.
RAW='{}'
LAST_OUT=""
check() {
    local name="$1" want="$2" json="$3" request="${4:-}" out rc got
    [[ -n "$request" ]] || request='{}'
    printf '%s' "$json" > "$CFG"
    printf '%s' "$RAW" > "$CFG_RAW"
    RAW='{}'
    : > "$CALLS"
    out=$(compose_validate_model "$request" "$SHELLM_BROKER_WORKDIR" up 2>&1)
    rc=$?
    LAST_OUT="$out"
    [[ "$rc" -eq 0 ]] && got=accept || got=reject
    if [[ "$got" != "$want" ]]; then
        bad "$name" "expected $want, got $got${out:+ ($out)}"
    elif [[ "$want" == reject && "$rc" -ne 65 ]]; then
        bad "$name" "rejected with rc=$rc, expected 65"
    else
        ok "$name"
    fi
}

bind()    { printf '{"services":{"s":{"volumes":[{"type":"bind","source":"%s","target":"/x"}]}}}' "$1"; }
context() { printf '{"services":{"s":{"build":{"context":"%s"}}}}' "$1"; }

# --- the boundary itself -------------------------------------------------
check "bind inside the workdir is allowed"      accept "$(bind "$SHELLM_BROKER_WORKDIR/sub")"
check "bind on the workdir itself is allowed"   accept "$(bind "$SHELLM_BROKER_WORKDIR")"
check "bind on a sibling prefix path is denied" reject "$(bind "$WORK/work-secret")"
case "$LAST_OUT" in
    *"outside SHELLM_WORKDIR"*) ok "and the denial names the boundary" ;;
    *) bad "and the denial names the boundary" "got: $LAST_OUT" ;;
esac
check "build context on a sibling is denied"    reject "$(context "$WORK/work-secret")"

check "bind climbing out with .. is denied"      reject "$(bind "$SHELLM_BROKER_WORKDIR/../work-secret")"
check "bind through a symlink out is denied"    reject "$(bind "$SHELLM_BROKER_WORKDIR/escape")"
check "absolute Dockerfile outside is denied"   reject "$(printf '{"services":{"s":{"build":{"context":"%s","dockerfile":"/etc/Dockerfile"}}}}' "$SHELLM_BROKER_WORKDIR")"
check "a bind with no source is denied"         reject '{"services":{"s":{"volumes":[{"type":"bind","target":"/x"}]}}}'
check "a path compose would create is allowed"  accept "$(bind "$SHELLM_BROKER_WORKDIR/not-yet/deep")"

# --- the same rules through the workdir_alias spelling -------------------
# A request whose .workdir resolves to the broker workdir may spell paths that
# way; every case above must hold through that spelling too.
alias_req="$(printf '{"workdir":"%s"}' "$WORK/alias")"
check "alias: bind inside is allowed"           accept "$(bind "$WORK/alias/sub")"            "$alias_req"
check "alias: sibling prefix is denied"         reject "$(bind "$WORK/alias-secret")"         "$alias_req"
check "alias: .. climb is denied"               reject "$(bind "$WORK/alias/../work-secret")" "$alias_req"

# A model the path extraction cannot parse must not read as "no paths to
# object to". Against the pre-fix broker this is accepted.
check "an unparseable model is denied"          reject 'not json at all'

# --- the host paths that never pass through services[].volumes -----------
# Each of these named a file outside the workdir and mounted it into a
# brokered container while the bind check above was already in force.
check "volume driver_opts.device outside is denied" reject \
  "$(printf '{"services":{"s":{"volumes":[{"type":"volume","source":"esc","target":"/x"}]}},"volumes":{"esc":{"driver":"local","driver_opts":{"type":"none","device":"%s","o":"bind"}}}}' "$WORK/work-secret")"
check "volume device inside the workdir is allowed" accept \
  "$(printf '{"volumes":{"ok":{"driver":"local","driver_opts":{"type":"none","device":"%s","o":"bind"}}}}' "$SHELLM_BROKER_WORKDIR/sub")"
check "secret file outside is denied"           reject '{"secrets":{"sec":{"file":"/etc/hostname"}}}'
check "config file outside is denied"           reject '{"configs":{"c":{"file":"/etc/hostname"}}}'
check "additional build context outside is denied" reject \
  "$(printf '{"services":{"s":{"build":{"context":"%s","additional_contexts":{"extra":"/etc"}}}}}' "$SHELLM_BROKER_WORKDIR")"
check "a non-path additional context is allowed" accept \
  "$(printf '{"services":{"s":{"build":{"context":"%s","additional_contexts":{"img":"docker-image://alpine"}}}}}' "$SHELLM_BROKER_WORKDIR")"
# env_file and label_file exist only in the uninterpolated render, so these
# cases put them there and leave the default fixture bare, the way compose
# leaves it after it has read the files.
RAW='{"services":{"s":{"env_file":[{"path":"/etc/hostname","required":true}]}}}'
check "env_file outside is denied"              reject '{"services":{"s":{}}}'
RAW="$(printf '{"services":{"s":{"env_file":[{"path":"%s/app.env","required":true}]}}}' "$SHELLM_BROKER_WORKDIR")"
check "env_file inside the workdir is allowed"  accept '{"services":{"s":{}}}'
RAW='{"services":{"s":{"label_file":["/etc/hostname"]}}}'
check "label_file outside is denied"            reject '{"services":{"s":{}}}'
RAW="$(printf '{"services":{"s":{"label_file":["%s/app.labels"]}}}' "$SHELLM_BROKER_WORKDIR")"
check "label_file inside the workdir is allowed" accept '{"services":{"s":{}}}'
# An absolute env_file with an uninterpolated ${VAR} tail resolves as
# contained here, then the default render interpolates it to anywhere at all
# and reads the target — the path field is gone from that render, so this
# check is the only gate. It must lose before the default render runs.
RAW="$(printf '{"services":{"s":{"env_file":[{"path":"%s/${FILE}","required":true}]}}}' "$SHELLM_BROKER_WORKDIR")"
check "env_file with an uninterpolated variable is denied" reject '{"services":{"s":{}}}'
if grep -q default "$CALLS"; then
    bad "the variable path is never read: the default render is skipped" "calls: $(tr '\n' ' ' < "$CALLS")"
else
    ok "the variable path is never read: the default render is skipped"
fi

# --- the surfaces that survive the default render ------------------------
check "a relative additional context is denied" reject \
  "$(printf '{"services":{"s":{"build":{"context":"%s","additional_contexts":{"extra":"../work-secret"}}}}}' "$SHELLM_BROKER_WORKDIR")"
# oci-layout:// names a local OCI layout directory on the host, so it is a
# path with a scheme in front, not a non-path like docker-image://.
check "an oci-layout context outside is denied" reject \
  "$(printf '{"services":{"s":{"build":{"context":"%s","additional_contexts":{"l":"oci-layout://%s"}}}}}' "$SHELLM_BROKER_WORKDIR" "$WORK/work-secret")"
check "an oci-layout context inside the workdir is allowed" accept \
  "$(printf '{"services":{"s":{"build":{"context":"%s","additional_contexts":{"l":"oci-layout://%s/layout"}}}}}' "$SHELLM_BROKER_WORKDIR" "$SHELLM_BROKER_WORKDIR")"
check "a local build cache source outside is denied" reject \
  "$(printf '{"services":{"s":{"build":{"context":"%s","cache_from":["type=local,src=/etc"]}}}}' "$SHELLM_BROKER_WORKDIR")"
check "a local build cache dest outside is denied" reject \
  "$(printf '{"services":{"s":{"build":{"context":"%s","cache_to":["type=local,dest=%s"]}}}}' "$SHELLM_BROKER_WORKDIR" "$WORK/work-secret")"
check "a build cache inside the workdir is allowed" accept \
  "$(printf '{"services":{"s":{"build":{"context":"%s","cache_from":["type=local,src=%s/cache"]}}}}' "$SHELLM_BROKER_WORKDIR" "$SHELLM_BROKER_WORKDIR")"
# Compose leaves a cache_to dest relative where it resolves every other path
# field to absolute, so a relative candidate resolves against the project
# directory (itself confined to the workdir) and gets the same check; a
# relative climb out is refused by the `..` test after the join.
check "a relative cache dest inside is allowed" accept \
  "$(printf '{"services":{"s":{"build":{"context":"%s","cache_to":["type=local,dest=./cacheout"]}}}}' "$SHELLM_BROKER_WORKDIR")"
check "a relative cache dest climbing out is denied" reject \
  "$(printf '{"services":{"s":{"build":{"context":"%s","cache_to":["type=local,dest=../work-secret"]}}}}' "$SHELLM_BROKER_WORKDIR")"
check "a registry build cache is allowed"       accept \
  "$(printf '{"services":{"s":{"build":{"context":"%s","cache_from":["type=registry,ref=example.com/img:cache","alpine:latest"]}}}}' "$SHELLM_BROKER_WORKDIR")"
check "an ssh key outside is denied"            reject \
  "$(printf '{"services":{"s":{"build":{"context":"%s","ssh":["key=/root/.ssh/id_rsa"]}}}}' "$SHELLM_BROKER_WORKDIR")"
check "the default ssh agent is allowed"        accept \
  "$(printf '{"services":{"s":{"build":{"context":"%s","ssh":["default"]}}}}' "$SHELLM_BROKER_WORKDIR")"
# compose 2.40.3 normalizes build.ssh to id=source strings, but the map form
# is in the schema, and a bare absolute value in it names a host file; the
# extraction must not drop it for lacking an `=`.
check "a map-form ssh key outside is denied"    reject \
  "$(printf '{"services":{"s":{"build":{"context":"%s","ssh":{"mykey":"/root/.ssh/id_rsa"}}}}}' "$SHELLM_BROKER_WORKDIR")"
check "a develop.watch path outside is denied"  reject \
  "$(printf '{"services":{"s":{"develop":{"watch":[{"action":"sync","path":"%s","target":"/app"}]}}}}' "$WORK/work-secret")"
check "a develop.watch path inside is allowed"  accept \
  "$(printf '{"services":{"s":{"develop":{"watch":[{"action":"sync","path":"%s/src","target":"/app"}]}}}}' "$SHELLM_BROKER_WORKDIR")"

# A dangling symlink is not a path compose may create: the daemon follows it to
# a target outside the workdir. `test -e` is false for one, so it reads as a
# missing component unless the walk stops at the link itself.
check "a bind on a dangling symlink out is denied" reject "$(bind "$SHELLM_BROKER_WORKDIR/dangle")"
check "a bind through a dangling symlink is denied" reject "$(bind "$SHELLM_BROKER_WORKDIR/dangle/sub")"

# The workdir's own spelling can be a symlink too: macOS hands mktemp a path
# under /var, which is a symlink to /private/var, and CI caught this when every
# accept case turned into a rejection there. Same rule as the paths: resolve it.
symlink_root_case() {
    local out rc
    printf '%s' "$(bind "$WORK/alias/sub")" > "$CFG"
    out=$(SHELLM_BROKER_WORKDIR="$WORK/alias" compose_validate_model '{}' "$WORK/alias" up 2>&1)
    rc=$?
    if [[ "$rc" -eq 0 ]]; then
        ok "workdir spelled through a symlink still accepts what is inside it"
    else
        bad "workdir spelled through a symlink still accepts what is inside it" "rc=$rc${out:+ ($out)}"
    fi
}
symlink_root_case

# With no workdir at all the resolved root is empty, and path_under against an
# empty root contains every absolute path. This function is the single gate,
# so misconfiguration has to fail loudly, not accept everything.
degenerate_root_case() {
    local out rc
    printf '%s' "$(bind /etc)" > "$CFG"
    printf '{}' > "$CFG_RAW"
    out=$(SHELLM_BROKER_WORKDIR='' compose_validate_model '{}' "$WORK/work" up 2>&1)
    rc=$?
    if [[ "$rc" -eq 65 ]]; then
        ok "an empty workdir rejects instead of containing everything"
    else
        bad "an empty workdir rejects instead of containing everything" "rc=$rc${out:+ ($out)}"
    fi
}
degenerate_root_case

# --- what the two renders owe the caller ---------------------------------
# Either render failing is a rejection, not a shrug: a model the validator
# could not read is a model it cannot vouch for.
export RAW_RC=1 RAW_ERR="uninterpolated render exploded"
check "an uninterpolated render that fails is denied" reject '{"services":{"s":{}}}'
unset RAW_RC RAW_ERR

export CFG_RC=1 CFG_ERR="default render exploded"
check "a default render that fails is denied"         reject '{"services":{"s":{}}}'

# compose puts the contents of the file it choked on into that error text (an
# unterminated quote in an env_file comes back as the value itself), and the
# requester is not trusted with it.
CANARY="hunter2-canary"
export CFG_RC=1
export CFG_ERR="failed to read /etc/shadow: line 2: unterminated quoted value \"$CANARY\""
check "a render error is not relayed to the caller"   reject '{"services":{"s":{}}}'
unset CFG_RC CFG_ERR
case "$LAST_OUT" in
    *"$CANARY"*) bad "a render error is not relayed to the caller" "leaked: $LAST_OUT" ;;
    *)           ok  "compose's own words stay host-side" ;;
esac

# The order is the point, not just the check: the default render READS every
# env_file, so an env_file outside the workdir has to lose before it runs.
RAW='{"services":{"s":{"env_file":[{"path":"/etc/shadow","required":true}]}}}'
check "an env file outside is denied"           reject '{"services":{"s":{}}}'
if grep -q default "$CALLS"; then
    bad "the file is never read: the default render is skipped" "calls: $(tr '\n' ' ' < "$CALLS")"
else
    ok "the file is never read: the default render is skipped"
fi

# --- the validator is live -----------------------------------------------
check "bind on /etc is denied"                  reject "$(bind /etc)"
check "the Docker socket is denied"             reject "$(bind /var/run/docker.sock)"
check "privileged is denied"                    reject '{"services":{"s":{"privileged":true}}}'

# --- the denial as the requester actually sees it ------------------------
# Every case above reads compose_validate_model's own return. What the sandbox
# receives is handle_compose's JSON response, and a gate that rejects correctly
# while the response reads as empty or successful is still a hole, so drive the
# whole request path once and assert on what comes back.
export SHELLM_BROKER_LOG="$WORK/broker.log"
compose_request="$(printf '{"op":"compose","args":["up"],"cwd":"%s"}' "$SHELLM_BROKER_WORKDIR")"

printf '{"services":{"s":{}}}' > "$CFG"
printf '{"services":{"s":{"env_file":[{"path":"/etc/shadow","required":true}]}}}' > "$CFG_RAW"
: > "$CALLS"
response=$(handle_compose "$compose_request")
got_code=$(printf '%s' "$response" | jq -r '.exit_code')
got_err=$(printf '%s' "$response" | jq -r '.stderr')
got_out=$(printf '%s' "$response" | jq -r '.stdout')
if [[ "$got_code" == 65 && "$got_out" == "" && "$got_err" == *"outside SHELLM_WORKDIR"* ]]; then
    ok "the requester gets the rejection, not an empty success"
else
    bad "the requester gets the rejection, not an empty success" "response: $response"
fi

# compose's words can carry host file contents, and the broker log is a file
# on disk, so by default the log gets a withheld notice, not the text. The
# operator opts into the raw stderr with HEADLONG_BROKER_LOG_COMPOSE_STDERR.
: > "$SHELLM_BROKER_LOG"
: > "$CALLS"
printf '{}' > "$CFG_RAW"
export CFG_RC=1
export CFG_ERR="failed to read /etc/shadow: line 2: unterminated quoted value \"$CANARY\""
response=$(handle_compose "$compose_request")
got_err=$(printf '%s' "$response" | jq -r '.stderr')
case "$got_err" in
    *"$CANARY"*) bad "compose's words do not reach the requester" "leaked: $got_err" ;;
    *)           ok  "compose's words do not reach the requester" ;;
esac
if grep -q "$CANARY" "$SHELLM_BROKER_LOG"; then
    bad "the broker log withholds compose's words by default" "log: $(cat "$SHELLM_BROKER_LOG")"
else
    ok "the broker log withholds compose's words by default"
fi
if grep -q "withheld" "$SHELLM_BROKER_LOG"; then
    ok "and says so, instead of logging nothing"
else
    bad "and says so, instead of logging nothing" "log: $(cat "$SHELLM_BROKER_LOG")"
fi

: > "$SHELLM_BROKER_LOG"
: > "$CALLS"
export HEADLONG_BROKER_LOG_COMPOSE_STDERR=1
response=$(handle_compose "$compose_request")
unset HEADLONG_BROKER_LOG_COMPOSE_STDERR CFG_RC CFG_ERR
if grep -q "$CANARY" "$SHELLM_BROKER_LOG"; then
    ok "the opt-in puts the raw stderr in the broker log"
else
    bad "the opt-in puts the raw stderr in the broker log" "log: $(cat "$SHELLM_BROKER_LOG")"
fi

echo
echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
