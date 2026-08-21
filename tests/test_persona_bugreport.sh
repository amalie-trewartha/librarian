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
mkdir -p "$HOME" "$HEADLONG_HOME/logs" "$HEADLONG_APP_DIR"
ln -s "$REPO/bin" "$HEADLONG_APP_DIR/bin"
ln -s "$REPO/tools" "$HEADLONG_APP_DIR/tools"
ln -s "$REPO/thinkers" "$HEADLONG_APP_DIR/thinkers"
ln -s "$REPO/identities" "$HEADLONG_APP_DIR/identities"
export PATH="$REPO/bin:$REPO/tools:$PATH"

KEY="sk-or-v1-0123456789abcdef0123456789abcdef0123456789abcdef"
PW="hunter2hunter2-very-secret"
cat > "$HEADLONG_HOME/.env" <<ENV
OPENROUTER_API_KEY=$KEY
SUPABASE_DB_PASSWORD=$PW
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
{"type":"thought","content":"the model is anthropic/claude-sonnet-4.5 and all is well","ts":"2026-08-21T15:00:01Z"}
ROWS
mkdir -p "$ID/run/logs" "$ID/memories" "$ID/workdir" "$TJ/blobs"
printf 'env: OPENROUTER_API_KEY=%s\n' "$KEY" > "$ID/run/logs/monolith.log"
printf -- '---\ntitle: db\n---\nthe db password is %s\n' "$PW" > "$ID/memories/db.md"
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
check_not "no sk-... shaped string survives"  grep -rqE 'sk-[A-Za-z0-9_-]{8,}' "$TOP"
check_not "other token value nowhere in bundle" grep -rqF 'ghp_OTHERTOKEN0123456789abcdefghijkl' "$TOP"
check_not "other password nowhere in bundle"  grep -rqF 'correcthorsebatterystaple' "$TOP"
check "legacy --var KEY=value row masked, 4+4 hint kept" grep -q -- '--var OPENROUTER_API_KEY=<redacted sk-o...cdef> think' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "token not in .env still masked by pattern (hint kept)" grep -q -- '--var GH_TOKEN=<redacted ghp_...ijkl> ' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "password on argv masked whole"         grep -q -- '--var PG_PASSWORD=<redacted> --var SHELLM_ENV=local' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check_not "no dangling hint tails"            grep -q -- '<redacted> [^ ]*>' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "bare --var KEY row untouched"          grep -q -- '--var OPENROUTER_API_KEY think' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "non-secret --var value kept"           grep -q -- '--var SHELLM_MODEL=anthropic/claude-sonnet-4.5' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "thinker log key scrubbed (hint kept)"  grep -q 'OPENROUTER_API_KEY=<redacted sk-o...cdef>$' "$TOP/identity/run/logs/monolith.log"
check "memory password scrubbed"              grep -q 'password is <redacted>' "$TOP/identity/memories/db.md"
check "plain thought text kept"               grep -q 'all is well' "$TOP/identity/trajectories/$(basename "$TJ")/trajectory.jsonl"
check "source trajectory untouched"           grep -qF "$KEY" "$TJ/trajectory.jsonl"

# 3. options
check "--include-workdir adds workdir" bash -c '
    persona alpha bugreport --out "$1" --include-workdir >/dev/null 2>&1 &&
    tar -tzf "$1" | grep -q "identity/workdir/scratch.txt"' _ "$WORK/b2.tgz"
check "default --out lands in HOME"    bash -c '
    out=$(persona alpha bugreport 2>/dev/null) && [[ "$out" == "$HOME/headlong-bugreport-alpha-"*.tgz && -s "$out" ]]'
check "--help exits 0 and mentions Usage" bash -c 'persona alpha bugreport --help | grep -q "^Usage:"'
check_not "unknown option is an error"    persona alpha bugreport --bogus
check "appears in persona --help"         bash -c 'persona alpha --help | grep -q bugreport'
check_not "no stray staging dirs left"    bash -c 'ls -d "${TMPDIR:-/tmp}"/headlong-bugreport.* 2>/dev/null | grep -q .'

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
