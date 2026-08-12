# WA-PRIMARY: Implementation Status (as of 2026-08-08)

**Investigator:** audel
**Related:** wa_primary_design.md

## Summary

Both layers from the design are implemented in `bin/shellm`.

## Layer 1 — wrapped code (existence + non-empty check)

**Status: IMPLEMENTED** (lines ~2177-2185)

```bash
if [ -n "${FINAL_FILE+x}" ]; then
  if [ -s "$FINAL_FILE" ]; then
    cat "$FINAL_FILE" > "$final_path"
  else
    printf '%s' "$FINAL_FILE" > "$rundir/final_file_rejected"
  fi
elif [ -n "${FINAL+x}" ]; then
  printf '%s' "$FINAL" > "$final_path"
fi
```

- Checks `[ -s ]` (file exists AND is non-empty) before copying.
- On rejection: records the bad path in `final_file_rejected` marker;
  does NOT create `final_path`, so the loop cannot accept an empty final.

## Layer 2 — main loop (defense in depth)

**Status: IMPLEMENTED** (lines ~2413, 2428)

- Line 2428: `if [[ -s "$final_path" ]]` — only accepts non-empty finals.
- Line 2413: checks `final_file_rejected` marker when final_path is empty,
  feeding a rejection/feedback message back so the loop re-prompts
  instead of terminating.

## Conclusion

WA-PRIMARY is fully implemented. No code gap remains in the two-layer
self-verification design. The earlier "design notes only" commit (cee05fd)
has since been followed by the implementation commits (9f6f9b2 and
related). The team's top-priority wrong-answer fix is in place.

## Next consideration

The remaining lever is empirical: run tbench2 to confirm the ~6
missing-FINAL_FILE tasks now pass. That's an eval run, not a code change.
