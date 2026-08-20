#!/usr/bin/env bash
# test_mem_frontmatter.sh — tests for bin/mem frontmatter_field()
#
# frontmatter_field() extracts a YAML frontmatter value from a memory file.
# It should strip surrounding quotes so summary: "foo" returns foo, not "foo".
# This test documents that expected behavior and catches regressions if the
# quote-stripping sed is removed.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }

# Extract frontmatter_field() from bin/mem without running main.
# bin/mem calls main "$@" at the end, so sourcing it would exit.
eval "$(sed -n '/^frontmatter_field()/,/^}/p' "$REPO/bin/mem")"

# --- fixtures: quoted and unquoted frontmatter ---
mkdir -p "$WORK/mem"
cat > "$WORK/mem/quoted.md" <<'EOF'
---
summary: "A quoted summary"
importance: "high"
type: "lesson"
tags: ["t1", "t2"]
---

Body.
EOF

cat > "$WORK/mem/unquoted.md" <<'EOF'
---
summary: An unquoted summary
importance: medium
type: lesson
tags: [t1, t2]
---

Body.
EOF

# --- assertions: quoted values should be stripped ---
val=$(frontmatter_field "$WORK/mem/quoted.md" "summary")
[ "$val" = "A quoted summary" ] \
  && ok "quoted summary stripped" \
  || bad "quoted summary stripped" "got: [$val]"

val=$(frontmatter_field "$WORK/mem/quoted.md" "importance")
[ "$val" = "high" ] \
  && ok "quoted importance stripped" \
  || bad "quoted importance stripped" "got: [$val]"

val=$(frontmatter_field "$WORK/mem/quoted.md" "type")
[ "$val" = "lesson" ] \
  && ok "quoted type stripped" \
  || bad "quoted type stripped" "got: [$val]"

# --- assertions: unquoted values pass through unchanged ---
val=$(frontmatter_field "$WORK/mem/unquoted.md" "summary")
[ "$val" = "An unquoted summary" ] \
  && ok "unquoted summary unchanged" \
  || bad "unquoted summary unchanged" "got: [$val]"

val=$(frontmatter_field "$WORK/mem/unquoted.md" "importance")
[ "$val" = "medium" ] \
  && ok "unquoted importance unchanged" \
  || bad "unquoted importance unchanged" "got: [$val]"

# --- missing field returns empty ---
val=$(frontmatter_field "$WORK/mem/quoted.md" "nonexistent")
[ -z "$val" ] \
  && ok "missing field returns empty" \
  || bad "missing field returns empty" "got: [$val]"

echo ""
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
