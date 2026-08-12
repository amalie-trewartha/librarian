# Findings: pipes-note scenario — g001r4 (z-ai/glm-5.2, 60s)

## Result
- 28 trajectory steps. Zero artifacts: workdir/ empty, memories/ empty.
- No notes.md written. No memories saved. Cross-session recall half has nothing to carry forward.

## Root cause
z-ai/glm-5.2 **repetition loop**: the actor emitted real bash (env
exploration: cd, ls, which, env grep) but repeated the SAME code block
across the single iteration with "I need to break this loop" self-talk
until the 60s timeout fired. It never advanced to the actual task
(writing notes.md, saving memories).

This is NOT the "natural-language intentions" failure I first
diagnosed — the actor DID emit shell commands. Earlier diagnosis was
wrong and has been corrected here.

## Key evidence: g001r1 succeeded with the SAME model
g001r1 (z-ai/glm-5.2) succeeded: 9 iterations, 55 steps, workdir=1,
memories=6. It also started with env-exploration bash but explored
ONCE then proceeded to write notes and save 6 memories. g001r4 got
stuck repeating the exploration block.

**Conclusion: the repetition loop is scenario/run-specific, not
model-specific.** z-ai/glm-5.2 CAN complete tasks under shellm.

## What's different (open)
- Configs for both runs were empty — need to determine the actual
  scenario each ran from trajectory/manifest.
- g001r1 had 9 iterations; g001r4 had 1. Both term=0 (not killed).
- The trigger for the loop is in the scenario prompt or run setup,
  not the model.

## Candidate fixes (to test)
1. Add a "do not repeat exploration" instruction to the actor prompt.
2. Detect repeated identical code blocks and break/inject guidance.
3. Give the actor the env info up-front so it doesn't need to explore.
4. Test g001r4's scenario with a model known to not loop (e.g. the
   haiku fix) to isolate scenario vs model interaction.
