# Review: nj/run_local_llm

## Branch stats
- 1 commit: `b69408b wip`
- ~30 files changed, large diff (adds RUN_LOCAL.md, heavily modifies bin/llm,
  deletes bin/identity and bin/recap, shrinks bin/shellm and bin/chat)

## What it does
Adds local-LLM support: new RUN_LOCAL.md docs, major refactor of bin/llm
(simplifies/rewrites LLM dispatch to support a local model path), and removes
bin/identity and bin/recap entirely. Also touches bin/focus, bin/mem,
bin/thinkers, bin/shellm-slack-bridge.

## Assessment
- **Substantial in-progress work.** This is not throwaway — it's a real
  feature branch (local LLM execution) with significant refactoring.
- **Marked "wip"** — not ready to merge as-is. The deletions of bin/identity
  and bin/recap need review: are they intentionally removed or just not yet
  ported?
- **Conflicts likely on merge.** Branch diverges from current main (main has
  moved forward with retrieval thinker, improve/ notes, lens.sh). bin/llm and
  bin/chat have likely changed on both sides — will need rebase/conflict
  resolution.
- **Recommendation: KEEP.** This is active feature work Nick will want to
  continue. Do not delete. Suggest Nick rebase onto current main before
  resuming to minimize conflict pain.

## Risk
- Deleting this branch would lose substantial work. Not a safe-delete
  candidate.
