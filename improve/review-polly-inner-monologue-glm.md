# Review: polly/inner-monologue-glm

## Branch stats
- 1 commit: `bbd6512 inner_monologue: default THINK_MODEL to glm-5.2`
- Diverged from current main

## What it does
Defaults `THINK_MODEL` to `glm-5.2` for the inner_monologue thinker —
i.e., switches the default thinking model to a GLM variant (likely a
cheaper/different model than the current default).

## Assessment
- **Small, focused change.** The actual commit is a one-liner default
  change. The large merge-base diff (bin/identity deletion, bin/chat
  changes, etc.) is divergence noise from an old fork point — not real
  work on this branch.
- **Experiment with model selection.** Polly was exploring whether GLM
  works well as the inner monologue's thinking model. Worth keeping the
  result around as a data point.
- **Likely safe to rebase or cherry-pick.** The core change is small
  enough that if Polly wants it, a cherry-pick of the single commit
  onto current main would work. If not, the branch can be deleted
  without losing much.

## Recommendation
- **KEEP (for now).** Small experiment worth preserving until Polly
  decides whether glm-5.2 is a good default for inner_monologue.
- If Polly has moved on from this experiment, **safe to delete** —
  the change is trivial to recreate via cherry-pick if ever needed.
- Ask Polly: is glm-5.2 still relevant, or has the team settled on a
  different default?

## Risk
- Very low risk. The branch is one commit with a small diff. Even if
  deleted, the work is easily recreated.

## Precise diff analysis (2026-08-06)

Re-examined the one-line change. It does more than swap the default model:

```
-THINK_MODEL="${THINK_MODEL:-${SHELLM_MODEL:-claude-opus-4-7}}"
+THINK_MODEL="${THINK_MODEL:-glm-5.2}"
```

Two effects:
1. Bakes `glm-5.2` as the hardcoded default (replacing `claude-opus-4-7`).
2. **Removes the `SHELLM_MODEL` fallback entirely.** On main, if someone sets
   `SHELLM_MODEL` but not `THINK_MODEL`, inner_monologue follows
   `SHELLM_MODEL`. On Polly's branch, inner_monologue would *ignore*
   `SHELLM_MODEL` and always use `glm-5.2` unless `THINK_MODEL` is set
   explicitly.

Per design/model-resolution.md, `SHELLM_MODEL` is the persona-quality knob and
`THINK_MODEL` is a per-deployment override — the design intends thinkers to
fall back to `SHELLM_MODEL`, not bypass it. Dropping that fallback is a subtle
regression in the resolution chain.

If the goal is "use glm-5.2 for inner_monologue in this deployment," the
design-aligned approach is to set `THINK_MODEL=glm-5.2` in the deployment's
`.env` (or pass `--model glm-5.2` at the thinker level), not to change the
code default.
