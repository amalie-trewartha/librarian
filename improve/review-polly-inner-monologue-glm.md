# Review notes: polly/inner-monologue-glm

_Pre-read 2026-08-05T23:40:00Z. Branch verified alive (1 commit ahead, 129 behind main)._

## Commit
- `bbd6512` — `inner_monologue: default THINK_MODEL to glm-5.2` (Andy Konwinski, 2026-07-10)
- 1 file changed, 1 insertion, 1 deletion

## Change
```diff
-THINK_MODEL="${THINK_MODEL:-${SHELLM_MODEL:-claude-opus-4-7}}"
+THINK_MODEL="${THINK_MODEL:-glm-5.2}"
```

## Observation
The change drops the `SHELLM_MODEL` fallback chain, so `inner_monologue` will
no longer follow the system-wide model setting — it hardcodes `glm-5.2` as
the default. This is likely intentional (GLM may be better suited for
inner monologue), but it's worth confirming:

1. **Intentional?** If the goal is "always use GLM for inner monologue
   regardless of system model," the hardcode is correct. If the goal was
   "prefer GLM but allow override," then `THINK_MODEL="${THINK_MODEL:-${SHELLM_MODEL:-glm-5.2}}"` would preserve the fallback chain.
2. **Consistency** — other thinkers use `${SHELLM_MODEL:-claude-opus-4-7}`. This branch diverges from that pattern.

## Verdict
Small, likely intentional. Worth a 1-line confirmation from Polly/Andy:
is the hardcode deliberate, or should `SHELLM_MODEL` stay in the chain?

## What I checked
- No other file changes
- No tests affected (inner_monologue has no test fixtures)
- Branch is 26 days old, no activity since
