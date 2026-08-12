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
