#!/usr/bin/env bash
# tests/test_persona_bugreport.sh — `persona <name> bugreport` bundles the
# identity and scrubs secrets.
#
# Usage: tests/test_persona_bugreport.sh
#
# Covers:
#   1. The bundle is a .tgz with report.txt, the identity (trajectory,
#      thinker logs, memories) and the state-home logs; workdir/ and the
#      .env file are left out.
#   2. Secrets are scrubbed everywhere in the bundle: the literal value of
#      every credential-looking variable in the env files (API key, DB
#      password), legacy `--var SOME_KEY=value` rows, and sk-... shaped
#      strings — while non-secret values (the model name) stay readable.
#      Keys/tokens keep a first-4/last-4 hint (`<redacted sk-o...cdef>`);
#      passwords are masked whole.
#   3. --out picks the path; --help works; an unknown option is an error.
#
# Everything runs under a throwaway HOME / app dir, so the real
# ~/.headlong and the repo's own .identities are never touched.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'cd /; rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
check() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$label"; else bad "$label"; fi; }
check_not() { local label="$1"; shift; if "$@" >/dev/null 2>&1; then bad "$label"; else ok "$label"; fi; }

# --- a fake install ----------------------------------------------------------
# app dir = the repo's bin/ + tools/ with its own .identities; state home with
# an .env holding two secrets and one plain setting.
export HOME="$WORK/home"
export HEADLONG_HOME="$WORK/home/.headlong"
export HEADLONG_APP_DIR="$WORK/app"
export TMPDIR="$WORK/tmp"
mkdir -p "$HOME" "$HEADLONG_HOME/logs" "$HEADLONG_APP_DIR" "$TMPDIR"
ln -s "$REPO/bin" "$HEADLONG_APP_DIR/bin"
ln -s "$REPO/tools" "$HEADLONG_APP_DIR/tools"
ln -s "$REPO/thinkers" "$HEADLONG_APP_DIR/thinkers"
ln -s "$REPO/identities" "$HEADLONG_APP_DIR/identities"
export PATH="$REPO/bin:$REPO/tools:$PATH"

KEY="sk-or-v1-0123456789abcdef0123456789abcdef0123456789abcdef"
PW="hunter2hunter2-very-secret"
DSN="postgresql://bugreport-user:bugreport-pass@example.invalid/private-db"
# This produces a malformed one-line sed program. Its isolated literal pass
# may fail, but it must not prevent the other literals or fixed patterns from
# being scrubbed.
export BROKEN_SECRET=$'first-line\nsecond-line'
cat > "$HEADLONG_HOME/.env" <<ENV
OPENROUTER_API_KEY=$KEY
SUPABASE_DB_PASSWORD=$PW
DATABASE_DSN=$DSN
SHELLM_MODEL=anthropic/claude-sonnet-4.5
ENV
printf 'headlong-web serving on http://127.0.0.1:8080\n' > "$HEADLONG_HOME/logs/web.log"
printf 'init ok\n' > "$HEADLONG_HOME/logs/init.log"

(cd "$HEADLONG_APP_DIR" && identity new alpha >/dev/null 2>&1) || { bad "identity new alpha"; exit 1; }
ID="$HEADLONG_APP_DIR/.identities/alpha"
ln -s alpha "$HEADLONG_APP_DIR/.identities/default"

# Seed content: a trajectory with a legacy key-on-argv row and a plain row,
# a thinker log that echoed the key, a memory that quotes the DB password,
# a workdir file, and a binary blob (must not be mangled or crash sed).
TJ=$(ls -d "$ID"/trajectories/*-root 2>/dev/null | head -1)
[[ -n "$TJ" ]] || { TJ="$ID/trajectories/deadbeef-root"; mkdir -p "$TJ"; }
cat >> "$TJ/trajectory.jsonl" <<ROWS
{"type":"shellm-run","cmd":"shellm --var SHELLM_MODEL=anthropic/claude-sonnet-4.5 --var OPENROUTER_API_KEY=$KEY think","ts":"2026-08-21T14:00:00Z"}
{"type":"shellm-run","cmd":"shellm --var OPENROUTER_API_KEY think","ts":"2026-08-21T15:00:00Z"}
{"type":"shellm-run","cmd":"shellm --var GH_TOKEN=ghp_OTHERTOKEN0123456789abcdefghijkl --var PG_PASSWORD=correcthorsebatterystaple --var SHELLM_ENV=local run","ts":"2026-08-21T15:30:00Z"}
{"type":"shellm-run","cmd":"shellm --var DATABASE_DSN=$DSN --var CURL_OPTS=--retry=2 run","ts":"2026-08-21T15:31:00Z"}
{"type":"thought","content":"the model is anthropic/claude-sonnet-4.5 and all is well","ts":"2026-08-21T15:00:01Z"}
ROWS
mkdir -p "$ID/run/logs" "$ID/memories" "$ID/workdir" "$TJ/blobs"
printf 'env: OPENROUTER_API_KEY=%s\n' "$KEY" > "$ID/run/logs/monolith.log"
printf -- '---\ntitle: db\n---\nthe db password is %s\nthe dsn is %s\n' "$PW" "$DSN" > "$ID/memories/db.md"
printf 'scratch file\n' > "$ID/workdir/scratch.txt"
head -c 2048 /dev/urandom > "$TJ/blobs/bin.dat"

# --- run it ------------------------------------------------------------------
OUT="$WORK/bundle.tgz"
if ! out=$(persona alpha bugreport --out "$OUT" 2>"$WORK/stderr"); then
    bad "bugreport exits 0" "$(cat "$WORK/stderr")"; exit 1
fi
ok "bugreport exits 0"
check "prints the bundle path on stdout" test "$out" = "$OUT"
check "bundle exists"                    test -s "$OUT"
check "stderr names the file"            grep -qF "  $OUT" "$WORK/stderr"

X="$WORK/x"; mkdir -p "$X"
tar -xzf "$OUT" -C "$X" || { bad "bundle is a valid tgz"; exit 1; }
ok "bundle is a valid tgz"
TOP=$(ls -d "$X"/headlong-bugreport-alpha-* 2>/dev/null | head -1)
check "top dir named headlong-bugreport-alpha-<stamp>" test -d "$TOP"

# 1. contents
check "report.txt present"                test -s "$TOP/report.txt"
check "report: identity name"             grep -q '^identity: alpha$' "$TOP/report.txt"
check "report: headlong commit line"      grep -q '^headlong commit: ' "$TOP/report.txt"
check "report: model visible (not a secret)" grep -q '^SHELLM_MODEL=anthropic/claude-sonnet-4.5' "$TOP/report.txt"
check "report: env names listed, values hidden" grep -q '^OPENROUTER_API_KEY=<hidden>$' "$TOP/report.txt"
check "report: status section"            grep -q '^mind: ' "$TOP/report.txt"
check "report: trajectory row count"      grep -qE 'trajectory.jsonl: [0-9]+ rows' "$TOP/report.txt"
check "report: says workdir left out"     grep -q 'left out: workdir/' "$TOP/report.txt"
check "identity/trajectory.jsonl present" test -s "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "identity/run/logs present"         test -s "$TOP/identity/run/logs/monolith.log"
check "identity/memories present"         test -s "$TOP/identity/memories/db.md"
check "identity/info.txt present"         test -s "$TOP/identity/info.txt"
check "home/logs present"                 test -s "$TOP/home/logs/web.log"
check_not "workdir left out"              test -e "$TOP/identity/workdir/scratch.txt"
check_not ".env not in bundle"            find "$TOP" -name '.env' -print -quit | grep -q .
check "binary blob carried intact"        cmp -s "$TJ/blobs/bin.dat" "$TOP/identity/trajectories/$(basename "$TJ")/blobs/bin.dat"

# 2. scrubbing
check_not "API key value nowhere in bundle"   grep -rqF "$KEY" "$TOP"
check_not "DB password nowhere in bundle"     grep -rqF "$PW" "$TOP"
check_not "DSN literal nowhere in bundle"     grep -rqF "$DSN" "$TOP"
check_not "no sk-... shaped string survives"  grep -rqE 'sk-[A-Za-z0-9_-]{8,}' "$TOP"
check_not "other token value nowhere in bundle" grep -rqF 'ghp_OTHERTOKEN0123456789abcdefghijkl' "$TOP"
check_not "other password nowhere in bundle"  grep -rqF 'correcthorsebatterystaple' "$TOP"
check "legacy --var KEY=value row masked, 4+4 hint kept" grep -q -- '--var OPENROUTER_API_KEY=<redacted sk-o...cdef> think' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "token not in .env still masked by pattern (hint kept)" grep -q -- '--var GH_TOKEN=<redacted ghp_...ijkl> ' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "password on argv masked whole"         grep -q -- '--var PG_PASSWORD=<redacted> --var SHELLM_ENV=local' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "DSN on argv masked whole"              grep -q -- '--var DATABASE_DSN=<redacted> --var CURL_OPTS=--retry=2' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "CURL_OPTS is not a URL false positive" grep -q -- '--var CURL_OPTS=--retry=2 run' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check_not "no dangling hint tails"            grep -q -- '<redacted> [^ ]*>' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "bare --var KEY row untouched"          grep -q -- '--var OPENROUTER_API_KEY think' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "non-secret --var value kept"           grep -q -- '--var SHELLM_MODEL=anthropic/claude-sonnet-4.5' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "thinker log key scrubbed (hint kept)"  grep -q 'OPENROUTER_API_KEY=<redacted sk-o...cdef>$' "$TOP/identity/run/logs/monolith.log"
check "memory password scrubbed"              grep -q 'password is <redacted>' "$TOP/identity/memories/db.md"
check "memory DSN literal scrubbed"           grep -q 'dsn is <redacted>' "$TOP/identity/memories/db.md"
check "plain thought text kept"               grep -q 'all is well' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "source trajectory untouched"           grep -qF "$KEY" "$TJ/trajectory.jsonl"

# 3. anonymous sed programs and output-temp cleanup
REAL_SED=$(command -v sed)
mkdir -p "$WORK/failbin" "$WORK/redact-state"
cat > "$WORK/failbin/sed" <<EOF
#!/usr/bin/env bash
real_sed='$REAL_SED'
uses_program=0
program_arg=""
prev=""
for arg in "\$@"; do
    if [[ "\$prev" == -f ]]; then uses_program=1; program_arg="\$arg"; break; fi
    prev="\$arg"
done
if [[ "\$uses_program" -eq 1 ]]; then
    printf '%s\n' "\$program_arg" >> "\$REDACT_STATE/program-args"
    if [[ -f "\$REDACT_STATE/previous-temp" ]]; then
        old=\$(cat "\$REDACT_STATE/previous-temp")
        [[ ! -e "\$old" ]] || touch "\$REDACT_STATE/leaked-temp"
    fi
    current=\$(find "\$TMPDIR" -name '.redact-output.*' -print -quit 2>/dev/null)
    [[ -z "\$current" ]] || printf '%s\n' "\$current" > "\$REDACT_STATE/previous-temp"
    if [[ "\${REDACT_SED_MODE:-}" == error && ! -f "\$REDACT_STATE/failed-once" ]]; then
        touch "\$REDACT_STATE/failed-once"
        exit 42
    fi
    if [[ "\${REDACT_SED_MODE:-}" == signal && ! -f "\$REDACT_STATE/signalled" ]]; then
        touch "\$REDACT_STATE/signalled"
        kill -TERM "\$PPID"
        sleep 1
        exit 143
    fi
fi
exec "\$real_sed" "\$@"
EOF
chmod +x "$WORK/failbin/sed"

rm -rf "$WORK/redact-state"; mkdir "$WORK/redact-state"
if PATH="$WORK/failbin:$PATH" REDACT_STATE="$WORK/redact-state" REDACT_SED_MODE=error \
        persona alpha bugreport --out "$WORK/error-pass.tgz" >/dev/null 2>&1; then
    ok "one sed error does not abort later redaction passes"
else
    bad "one sed error does not abort later redaction passes"
fi
check_not "failed sed output temp is removed before the next pass" test -e "$WORK/redact-state/leaked-temp"
if [[ -s "$WORK/redact-state/program-args" ]] \
   && ! grep -qF "$KEY" "$WORK/redact-state/program-args" \
   && ! grep -qF "$PW" "$WORK/redact-state/program-args" \
   && ! grep -qF "$DSN" "$WORK/redact-state/program-args"; then
    ok "sed program argv contains no private literals"
else
    bad "sed program argv contains no private literals"
fi
check_not "implementation has no secret sed script path" grep -q 'headlong-redact' "$REPO/tools/persona"
rm -f "$WORK/error-pass.tgz"

rm -rf "$WORK/redact-state"; mkdir "$WORK/redact-state"
if PATH="$WORK/failbin:$PATH" REDACT_STATE="$WORK/redact-state" REDACT_SED_MODE=signal \
        persona alpha bugreport --out "$WORK/signal-pass.tgz" >/dev/null 2>&1; then
    bad "TERM interrupts redaction"
else
    ok "TERM interrupts redaction"
fi
check_not "signal leaves no output redaction temp" bash -c \
    'find "$1" -name ".redact-output.*" -print -quit | grep -q .' _ "$WORK"
check_not "signal leaves no secret-bearing sed script" bash -c \
    'find "$1" -name "headlong-redact.*" -print -quit | grep -q .' _ "$WORK"

# 4. options
check "--include-workdir adds workdir" bash -c '
    persona alpha bugreport --out "$1" --include-workdir >/dev/null 2>&1 &&
    tar -tzf "$1" | grep -q "identity/workdir/scratch.txt"' _ "$WORK/b2.tgz"
check "default --out lands in HOME"    bash -c '
    out=$(persona alpha bugreport 2>/dev/null) && [[ "$out" == "$HOME/headlong-bugreport-alpha-"*.tgz && -s "$out" ]]'
check "--help exits 0 and mentions Usage" bash -c 'persona alpha bugreport --help | grep -q "^Usage:"'
check_not "unknown option is an error"    persona alpha bugreport --bogus
check "appears in persona --help"         bash -c 'persona alpha --help | grep -q bugreport'
check_not "no stray staging dirs left"    bash -c 'ls -d "${TMPDIR:-/tmp}"/headlong-bugreport.* 2>/dev/null | grep -q .'
check_not "no secret-bearing sed scripts exist" bash -c \
    'find "$1" -name "headlong-redact.*" -print -quit | grep -q .' _ "$WORK"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
