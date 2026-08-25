#!/usr/bin/env bash
# tests/test_broker_compose_containment.sh — the broker's compose validator
# must contain host paths at a directory boundary, not a string prefix.
#
# compose_validate_model is the ONLY gate on the bind sources, build contexts
# and absolute Dockerfiles in a compose model the sandbox hands the broker;
# handle_compose runs the real `docker compose` as soon as it returns 0. A
# textual prefix test is not containment: it lets /host/work-secret through
# while the workdir is /host/work, and `docker compose config` hands the
# validator paths it has NOT normalised (an absolute source keeps its `..`,
# verified against compose 2.40.3) and never resolves symlinks. So the check
# resolves each path and gates it with path_under(), and the cases below are
# the three ways out: the sibling prefix, the `..` climb, and the symlink.
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

# Source the broker for its functions: drop the trailing `main "$@"`, which
# would otherwise print usage and exit.
sed '$ d' "$REPO/tools/shellm-docker-broker" > "$WORK/broker.lib"

# `docker compose ... config --format json` returns whatever the case wrote.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/docker" <<'STUB'
#!/usr/bin/env bash
cat "$CFG"
STUB
chmod +x "$WORK/bin/docker"
export PATH="$WORK/bin:$PATH"
export CFG="$WORK/cfg.json"

# shellcheck disable=SC1090  # generated copy of the broker under test
source "$WORK/broker.lib"
set +e   # the broker sets -e; validation returning 65 is an expected outcome

# check <name> accept|reject <compose-config-json> [request-json]
#
# A rejection has to be the containment verdict, not any nonzero exit: rc 65
# with the "outside SHELLM_WORKDIR" message. Asserting only "nonzero" would let
# a case pass because jq errored or the model failed to parse.
check() {
    local name="$1" want="$2" json="$3" request="${4:-}" out rc got
    [[ -n "$request" ]] || request='{}'
    printf '%s' "$json" > "$CFG"
    out=$(compose_validate_model "$request" "$SHELLM_BROKER_WORKDIR" up 2>&1)
    rc=$?
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
check "env_file outside is denied"              reject \
  '{"services":{"s":{"env_file":[{"path":"/etc/hostname","required":true}]}}}'
check "env_file inside the workdir is allowed"  accept \
  "$(printf '{"services":{"s":{"env_file":[{"path":"%s/app.env","required":true}]}}}' "$SHELLM_BROKER_WORKDIR")"

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

# --- the validator is live -----------------------------------------------
check "bind on /etc is denied"                  reject "$(bind /etc)"
check "the Docker socket is denied"             reject "$(bind /var/run/docker.sock)"
check "privileged is denied"                    reject '{"services":{"s":{"privileged":true}}}'

echo
echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
