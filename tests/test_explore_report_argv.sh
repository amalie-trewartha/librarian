#!/usr/bin/env bash
# tests/test_explore_report_argv.sh — the report prompt stays off argv.
#
# Usage: tests/test_explore_report_argv.sh
#
# `shellm-explore --report` builds a prompt out of every run's context in the
# tree. Nothing that can hold it may travel through argv: Linux caps a single
# argument at 128 KiB and macOS caps total argv at 1 MiB, so a tree with a
# large recorded command used to die with "Argument list too long" (rc=126)
# before the model was ever called.
#
# The fixture is one run whose `command` holds a 200 KiB inline prompt — the
# same shape that put --prompt-file into bin/shellm. `llm` is stubbed and
# reports what it was handed, so the check is platform-independent: the
# prompt arrives on stdin and argv stays small.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

mkdir -p "$WORK/bin" "$WORK/traj/abc12345-run"

big=$(head -c 204800 /dev/zero | tr '\0' 'x')
{
    printf '{"type":"shellm-run","step_id":"s1","command":"shellm %s"}\n' "$big"
    printf '{"type":"run-summary","tldr":"a run with a large inline prompt"}\n'
} > "$WORK/traj/abc12345-run/trajectory.jsonl"

cat > "$WORK/bin/llm" <<'STUB'
#!/usr/bin/env bash
argv_bytes=0
for a in "$@"; do argv_bytes=$((argv_bytes + ${#a})); done
if [[ -t 0 ]]; then stdin_bytes=0; else s=$(cat); stdin_bytes=${#s}; fi
printf 'argv=%d stdin=%d\n' "$argv_bytes" "$stdin_bytes" >&2
printf 'a report\n'
STUB
chmod +x "$WORK/bin/llm"

PATH="$WORK/bin:$PATH" TRAJ_DIR="$WORK/traj" \
    bash "$REPO/tools/shellm-explore" abc12345 --report \
    > "$WORK/out" 2> "$WORK/err"
rc=$?

[[ "$rc" -eq 0 ]] \
    && ok "report survives a 200 KiB recorded command" \
    || bad "report survives a 200 KiB recorded command" "rc=$rc: $(tail -1 "$WORK/err")"

seen=$(grep -o 'argv=[0-9]* stdin=[0-9]*' "$WORK/err" | tail -1)
argv_bytes=${seen#argv=}; argv_bytes=${argv_bytes%% *}
stdin_bytes=${seen##*stdin=}

[[ -n "$seen" && "$argv_bytes" -lt 4096 ]] \
    && ok "llm argv stays small (${argv_bytes:-?} bytes)" \
    || bad "llm argv stays small" "${seen:-llm was never reached}"

[[ -n "$seen" && "$stdin_bytes" -gt 204800 ]] \
    && ok "the prompt reaches llm on stdin (${stdin_bytes:-?} bytes)" \
    || bad "the prompt reaches llm on stdin" "${seen:-llm was never reached}"

grep -q 'a report' "$WORK/out" \
    && ok "the report is printed" \
    || bad "the report is printed" "$(tail -1 "$WORK/out")"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
