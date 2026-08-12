# Guard false-positive fix (2026-08-06)

## Bug
The within-response repetition guard in `thinkers/actor/step`
used `grep -q REPETITIVE` to decide whether the detector flagged
the response. But `improve/tests/repetition_detector.sh` runs
internal self-test cases by default, emitting lines like:

    [case3 repetitive 10x] REPETITIVE: 10 blocks, 45 duplicate pairs (threshold=3)

These self-test lines contain the string "REPETITIVE" regardless
of the verdict on the *real* input. So the guard's `grep -q
REPETITIVE` matched the self-test output even when the real-input
verdict was `[real-input] OK` — causing the guard to false-fire
on **every** clean response and abort every normal actor
iteration.

## Repro
- Clean single-block input → guard reported "ABORT fires" (BUG)
- 20x-duplicate input → guard reported "ABORT fires" (correct)

## Fix
Tighten the guard's grep to match only the real-input verdict
line:

    grep -q "[real-input] REPETITIVE"

The detector script is untouched (it's validated work; the
self-tests are useful when run standalone).

## Verification
- Clean single-block input → passes (no abort) — correct
- 20x-duplicate input → aborts — correct

## Status
Applied to `thinkers/actor/step`, not committed. Belongs to the
patch_plan.md integration; commit alongside it.
