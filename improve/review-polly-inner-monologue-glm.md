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

## Assessment (2026-08-06)

**Branch status:** remote-only (origin/polly/inner-monologue-glm), 1 commit
ahead, 137 behind main. Last commit 2026-07-10 (~27 days old). NOT merged.

**Recommendation: fix the fallback chain, then merge (or close).**

The current branch hardcodes `glm-5.2` with no `SHELLM_MODEL` fallback:
```
THINK_MODEL="${THINK_MODEL:-glm-5.2}"
```
This means if a system-wide `SHELLM_MODEL` is set (e.g., to switch everyone
to a different model), `inner_monologue` silently ignores it — a regression
in the fallback contract that all other thinkers follow (actor,
mind_wanderer, values_manager, etc. all use the full chain).

**Better fix** — prefer GLM but respect `SHELLM_MODEL` overrides:
```
THINK_MODEL="${THINK_MODEL:-${SHELLM_MODEL:-glm-5.2}}"
```
This makes GLM the default inner-monologue model while keeping the fallback
chain intact. Consistent with every other thinker's pattern.

If the intent was truly "always GLM, never follow SHELLM_MODEL," then the
branch is correct as-is and just needs rebasing + merging. But that breaks
convention without explanation, so the fallback-preserving version is safer.
