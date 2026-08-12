#!/usr/bin/env bash
# Build a keyword index from audel's memories: keyword<TAB>mem_id<TAB>summary
# Reads each memory .md, extracts id + summary from frontmatter, tokens from body.
set -e
MEMDIR="${1:-/opt/shellm/app/.identities/audel/memories}"
OUT="${2:-/opt/shellm/app/.identities/audel/mem/index.tsv}"
mkdir -p "$(dirname "$OUT")"
> "$OUT"
# stopwords
declare -A STOP
for w in the a an and or but if then of to in is it this that for with on at by from as be was were are been being have has had do does did i you he she they we us our your my me him her them his hers its their; do STOP[$w]=1; done
for f in "$MEMDIR"/*.md; do
  [ -f "$f" ] || continue
  # extract id and summary from frontmatter
  mid=$(grep -a -m1 '^id:' "$f" | sed 's/^id: *//; s/ *$//')
  [ -z "$mid" ] && continue
  summary=$(grep -a -m1 '^summary:' "$f" | sed 's/^summary: *//; s/ *$//')
  summary=$(echo "$summary" | tr '[:upper:]' '[:lower:]' | tr -c '[:alnum:][:space:]' ' ')
  # collect text: summary + body (skip frontmatter)
  body=$(sed -n '/^---$/,/^---$/!p; /^---$/,/^---$/{ /^---$/d; /^summary:/p; /^tags:/p }' "$f" | tr -c '[:alnum:][:space:]' ' ')
  for tok in $summary $body; do
    t="${tok,,}"
    [ -z "$t" ] && continue
    [ -n "${STOP[$t]}" ] && continue
    # skip very short tokens
    [ ${#t} -lt 3 ] && continue
    echo -e "${t}\t${mid}\t${summary}" >> "$OUT"
  done
done
# sort and dedupe
tmp=$(mktemp)
sort -u "$OUT" > "$tmp" && mv "$tmp" "$OUT"
wc -l "$OUT"
