# Patch Plan: Integrate repetition detector into actor/step

## Status
- Detector: tests/repetition_detector.sh — VALIDATED against real g001r4
  iteration-1 response (53 blocks, 1276 dup pairs, flagged REPETITIVE).
- Two checks: (1) exact-duplicate pairs (REP_THRESHOLD=3),
  (2) block-count threshold (BLOCK_THRESHOLD=15) for near-duplicate
  proliferation.

## Goal
Before executing the extracted code block, run the detector on the
full model response. If REPETITIVE, abort the iteration early
(emit an observation, do NOT execute), so the loop doesn't burn
the timeout executing near-identical exploration blocks.

## Integration point
In thinkers/actor/step, locate the section where the model response
is received and extract_code pulls the first bash block. Insert
BEFORE execution:

```
# Detect within-response repetition before executing.
RESP_FILE=$(mktemp)
printf '%s' "$MODEL_RESPONSE" > "$RESP_FILE"
if bash "$SCRIPT_DIR/../../tests/repetition_detector.sh" "$RESP_FILE" 2>/dev/null | grep -q REPETITIVE; then
  echo "REPETITIVE response detected — aborting iteration"
  # append observation, skip execution, continue loop
  rm -f "$RESP_FILE"
  # goto next iteration / continue
fi
rm -f "$RESP_FILE"
```

## Next wakeup
1. Confirm canonical actor step path.
2. Read the exact lines around extract_code.
3. Insert the detector call, test on a synthetic repetitive response.
