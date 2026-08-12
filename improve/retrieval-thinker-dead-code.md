# Dead code: retrieval thinker reads env vars that are never set

## Summary
`thinkers/retrieval/step` reads the current step's content from environment
variables (`STEP_CONTENT` with a fallback to `CONTENT`), but the dispatcher
(`bin/thinkers:_dispatch_step`) never sets either variable — it pipes the step
JSON to the thinker's **stdin** instead. As a result, the retrieval thinker
never sees the current step's content, so its IDF-weighted keyword match and
`mem search` tier operate on empty input. The thinker is effectively dead code
— it runs but can never surface memories because it has nothing to match
against.

## Evidence
- `thinkers/retrieval/step` line 29:
  `step_content="${STEP_CONTENT:-${CONTENT:-}}"`
  (reads env vars, not stdin)
- `grep -rn "STEP_CONTENT=" thinkers/ bin/ lib/` → no matches (never set)
- `grep -n 'CONTENT=' bin/thinkers` → no matches (never set)
- `bin/thinkers:_dispatch_step` (line 402-403):
  `printf '%s' "$_djson" | SHELLM_LAUNCHED_BY="$_dname" "$_dscript"`
  (pipes step JSON to stdin, sets no CONTENT/STEP_CONTENT env var)
- `thinkers/monolith/step` (the working reference) reads from **stdin**.

## Proposed fix
Make `thinkers/retrieval/step` read the step content from stdin, the same way
`thinkers/monolith/step` does — then parse what it needs from the piped JSON.

Suggested change:
```bash
# Instead of: step_content="${STEP_CONTENT:-${CONTENT:-}}"
_step_json="$(cat)"
step_content="$(printf '%s' "$_step_json" | jq -r '.content // empty')"
```

## Verification after fix
Run a wakeup with a memory-worthy step and confirm the retrieval thinker
receives non-empty content and surfaces matching memories.
