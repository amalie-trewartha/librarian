#!/usr/bin/env bash
# tests/test_librarian_py.sh — the librarian package's own tests (librarian/tests),
# run through the standard library so the bash suite covers them without uv or
# pytest installed. CI also runs them under pytest (uv run --project librarian).
#
# Usage: tests/test_librarian_py.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
command -v python3 >/dev/null 2>&1 || { echo "FAIL python3 not found"; exit 1; }
unset IDENTITY_DIR IDENTITY_NAME LIBRARIAN_STORE LIBRARIAN_NOW LIBRARIAN_LLM PROJECT_NOW PROJECT_TIME_SCALE 2>/dev/null
cd "$REPO/librarian" || exit 1
if python3 -m unittest discover -s tests -t tests -q 2>&1 | tail -n 5; then
    echo "ok   librarian python tests"
    exit 0
fi
echo "FAIL librarian python tests"
exit 1
