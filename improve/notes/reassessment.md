# Reassessment: is the within-response detector the right fix?

## What I assumed
g001r4 emitted ~100 identical bash blocks in a SINGLE response.
A within-response repetition detector would catch that.

## What the real data shows (2026-08-06)
- trajectory.jsonl has only 28 steps total.
- The most repetitive single response has only ~4 bash fences.
- The actor.log shows ~48 copies of commands like `ls -la`, `pwd`,
  `for c in traj mem skills` — but these are spread ACROSS many
  iterations, not within one response.

## Honest conclusion
The g001r4 failure mode looks like ACROSS-ITERATION repetition
(the agent runs the same exploration commands every iteration and
never converges), NOT within-response repetition. The detector I
built and validated on synthetic 10x-block data does NOT match
the real failure pattern.

## Options
1. Keep the within-response detector anyway — it's cheap, catches
   a real (if rarer) failure mode, and does no harm.
2. Build an ACROSS-ITERATION detector: compare the code block
   about to be executed against the last N executed blocks; if it's
   a near-duplicate, inject "you are repeating" and break.
3. Both.

## Recommendation
Option 3 (both), but prioritize #2 — it matches the actual g001r4
failure. The across-iteration detector lives in the actor loop
right before execution, comparing against recent history, not in
extract_code.

## CORRECTION (this wakeup)
Need to verify: does trajectory.jsonl store prompts only (not model responses)?
The actor.log has 106 fences in 1 iteration. If those 106 fences are from a
# single model response (~50 blocks), the within-response detector IS correct.
# If they're from many small responses across sub-iterations, the across-iteration
# detector is needed. Checking actor.log structure now.
