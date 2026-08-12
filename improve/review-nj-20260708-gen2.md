# Review notes: nj/20260708_gen2

_Pre-read 2026-08-05T22:45:25Z. Branch verified alive (not merged into main)._

**Diff method:** merge-base diff, NOT main..branch. Branch is 2 ahead / 126 behind main;
a main..branch diff would show main's commits as massive deletions.

## Nick's actual work
 improve/decisions.md               |   5 ++
 thinkers/actor/step                |  34 ++++++++++-
 thinkers/inner_monologue/prompt.md |  46 ++++++++++++--
 thinkers/inner_monologue/step      | 119 +++++++++++++++++++++++++++----------
 4 files changed, 167 insertions(+), 37 deletions(-)

## Commits
34d31b0 improve: apply gen-002 cards — action extraction, grounded monologue
3b9ed80 improve: apply gen-001 cards — grounded observations, no idle busy-wait

## Summary
Two commits on top of gen1. Changes to thinkers/inner_monologue (prompt + step)
and thinkers/actor/step. Builds on the gen-001 card work — gen2 appears to
iterate further on the actor observation counting and inner monologue loop.

## Review points
- gen2 builds on gen1 — check if gen1 is merged first (it isn't; both alive)
- The actor/step changes add observation counting to detect whether a run
  recorded any result — useful for preventing idle busy-wait loops
- inner_monologue/step changes remove the idle handling path — need to verify
  this doesn't break trigger_self (idle steps keep the loop alive)
- Empty/duplicate response handling was rewritten — check the new loop logic
  doesn't tight-loop on transient API failures (old code had sleep 1 backoff)

## Open questions for Nick
- Should gen1 be reviewed/merged before gen2, or are they meant to land together?
- The new loop structure in inner_monologue/step — is the done-loop replacement
  for the old empty-response placeholder? What prevents tight-looping now?
- Is the observation counter in actor/step meant to gate re-triggering?
