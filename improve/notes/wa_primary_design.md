# WA-PRIMARY: Output Self-Verification — Design Notes

**Date:** 2026-08-07
**Author:** audel
**Related:** tbench2_wrong_answer_recommendation.md (WA-PRIMARY)

## Problem

~6 tbench2 tasks fail because the agent sets FINAL_FILE=path but the
file doesn't exist (or is empty) at the expected path. The agent
completes, thinks it's done, but the deliverable was never written.

## Current mechanism (bin/shellm)

1. Wrapped code after user code:
   ```
   [ -n "${FINAL+x}" ] && printf '%s' "$FINAL" > "$final_path"
   [ -n "${FINAL_FILE+x}" ] && cat "$FINAL_FILE" > "$final_path"
   ```
2. Main loop checks `[[ -f "$final_path" ]]` (line 2406)
3. If exists, reads as final_answer and terminates

## Bug

If FINAL_FILE points to a nonexistent file:
- `cat "$FINAL_FILE"` fails (file not found)
- But `> "$final_path"` still creates an empty final_path
- `[[ -f "$final_path" ]]` passes → empty final accepted → task "completes"

## Proposed fix

Two-layer check:

### Layer 1: wrapped code (immediate)

Change the FINAL_FILE line to verify existence before writing:
```bash
if [ -n "${FINAL_FILE+x}" ]; then
    if [ -f "$FINAL_FILE" ] && [ -s "$FINAL_FILE" ]; then
        cat "$FINAL_FILE" > "$final_path"
    else
        echo "ERROR: FINAL_FILE '$FINAL_FILE' does not exist or is empty" >&2
        # Don't write final_path — let the loop continue
    fi
fi
```

### Layer 2: main loop (defense in depth)

After reading final_answer, if it's empty, don't terminate —
re-prompt instead:
```bash
if [[ -f "$final_path" ]]; then
    final_answer=$(cat "$final_path")
    if [[ -z "$final_answer" ]]; then
        # Empty final — don't accept, feed back as feedback
        feedback="FINAL_FILE/FINAL was set but produced empty output. The deliverable file may not exist. Write the output file, then set FINAL_FILE again."
        # Continue loop instead of breaking
    fi
fi
```

## Risk

Low. A presence/emptiness check can't turn a pass into a fail.
Edge case: tasks where FINAL="" is legitimately empty — rare, and
the feedback loop handles it (agent can re-send with actual content).

## Effort

Half day (code + test with a mock task that sets FINAL_FILE to
nonexistent path).
