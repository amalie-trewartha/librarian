# Review notes: nj/20260708_gen1

_Pre-read 2026-08-05T22:44:42Z. Filled 2026-08-05T22:47:30Z. Branch verified alive._

**Diff method:** merge-base diff, NOT `main..branch`. Branch is 126 behind main — a `main..branch` diff would show main's commits as massive deletions, not Nick's actual work.

## Nick's actual work
 thinkers/actor/step                | 34 +++++++++++++++-
 thinkers/inner_monologue/prompt.md | 30 ++++++++++++--
 thinkers/inner_monologue/step      | 82 ++++++++++++++++++++++++++------------
 3 files changed, 115 insertions(+), 31 deletions(-)

## Commits
3b9ed80 improve: apply gen-001 cards — grounded observations, no idle busy-wait

## Summary
Single commit applying "gen-001 cards" — a set of improvements focused on two themes: (1) grounding actor observations in what actually happened, and (2) eliminating idle busy-waiting in the inner monologue loop.

**actor/step (+34):** Adds `_count_actor_observations()` helper and an `obs_before` counter before the main shellm loop runs. Intent: detect whether the actor actually recorded any result during its run, so downstream logic can tell "nothing was emitted" from "something was emitted." Also introduces an `act_rc` variable (captured but the full usage is cut off in the diff — likely for exit-code handling).

**inner_monologue/prompt.md (+30):** Strengthens the prompt with two new directives. First, an anti-hedging rule: vague futuring ("I might", "perhaps later", "worth considering") is called out as a smell — if it's worth thinking twice, it's worth one line of action now. Includes a guard against re-saving what the last observation already saved. Second, a "commit before idle" rule: before going idle or letting a quiet stretch pass, ask whether anything durable (mem, focus, file) was committed recently; if not, do it now. Also adds a rule to never wrap output in JSON — the runner adds the envelope.

**inner_monologue/step (+82/-31):** Two structural changes. (1) Removes the idle-handling block — the old code emitted a placeholder thought and slept 1s on empty LLM responses; this is the "no idle busy-wait" part. (2) Removes the repeat-suffix logic (the `last_content` comparison that appended " (repeat)" to duplicate steps), replacing it with a comment explaining that `_recent_stream` collapses repeats with a count, and a mutated suffix would defeat that equality check. The idle case in the `case "$response"` block is also removed.

## Review points
1. **Removing idle handling changes the loop contract.** The old empty-response + sleep-1s backoff protected against transient API failures tight-looping. Removing it means an empty response now falls through to the normal step path. If the LLM returns empty repeatedly, this could tight-loop. Worth confirming Nick's intent — is the backoff handled elsewhere now, or is the assumption that empty responses are rare enough?
2. **Repeat-suffix removal matches run_local_llm.** Both branches remove the `last_content` / " (repeat)" suffix logic and for the same reason. This is the conflict point flagged in the digest — gen2 also does this. If both merge, the second one will have nothing to apply here, but there's no logical conflict.
3. **`_count_actor_observations` is added but its consumer is cut off.** The diff shows the function body starts but the `act_rc` usage that likely pairs with it is truncated. Need to see the full actor/step diff to judge whether the count is actually used or dead code.
4. **Anti-hedging prompt rule is strong and good.** "If it's worth thinking twice, it's worth one line of action now" is exactly the kind of directive that turns rumination into progress. This aligns with my own verify-before-asserting lesson.
5. **Commit-before-idle rule is valuable.** This would have caught my "claimed wrote notes but didn't" slip. The rule is sound; the question is whether it's enforceable from the step script or just prompt guidance.
6. **JSON-output prohibition rule is additive and safe.** No risk; good hygiene.

## Open questions for Nick
- The `_count_actor_observations` helper is added in actor/step but the diff is truncated where `act_rc` is used — is the count actually consumed, or is it scaffolding for a later card?
- Removing the empty-response backoff (sleep 1s) means a flaky LLM endpoint could tight-loop the inner monologue. Is the backoff moved elsewhere, or is the assumption that empty responses are rare?
- The idle case (`"idle"|"action: idle"`) is removed from the case block in inner_monologue/step. Does idle handling move entirely into the prompt ("Before going idle...") or is there a new path for it?
- gen1 and gen2 both touch inner_monologue/step's repeat-suffix logic — is gen2 strictly a superset of gen1, or do they diverge enough that both could land? (The digest flagged this; a direct answer would unblock merge planning.)
