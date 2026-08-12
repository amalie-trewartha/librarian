# Nick branch digest — 2026-08-05

_Pre-read by audel. 4 alive branches reviewed via merge-base diff. 4 stale branches noted but not pre-read (already merged to main)._

## Alive branches (have unmerged work)

### nj/shellm_term_demo (3 commits ahead)
Terminal demo work. See improve/review-nj-shellm-term-demo.md for details.

### nj/run_local_llm (1 commit ahead)
Local LLM support: mlx_lm server + bin/llm wrapper + inner_monologue changes.
- New: RUN_LOCAL.md (setup guide for local mlx_lm server)
- New: bin/llm (25-line wrapper)
- Modified: thinkers/_lib/common.sh (+20), thinkers/inner_monologue/step (+38/-15)
- Key change: removes the "(repeat)" suffix from duplicate thoughts so _recent_stream's equality-based collapse works correctly.
- Questions: Is the repeat-suffix removal independent from local-LLM work? Is _count_actor_observations in actor/step related?
See improve/review-nj-run-local-llm.md.

### nj/20260708_gen1 (1 commit ahead)
"apply gen-001 cards — grounded observations, no idle busy-wait"
- Modified: thinkers/actor/step (+34), thinkers/inner_monologue/prompt.md (+30), thinkers/inner_monologue/step (+82/-31)
- Adds _count_actor_observations function to actor/step (detect whether a run recorded any result).
- Removes idle step_type handling from inner_monologue/step case statement.
See improve/review-nj-20260708-gen1.md.

### nj/20260708_gen2 (2 commits ahead)
"apply gen-002 cards — action extraction, grounded monologue"
- Includes gen1's commit + action extraction work.
- Modified: improve/decisions.md (+5), thinkers/actor/step (+34), thinkers/inner_monologue/prompt.md (+46), thinkers/inner_monologue/step (+119/-37)
- Adds extracted_actions array in inner_monologue/step — actions parsed from monologue and executed.
- Questions: How are extracted actions executed? What commands are supported? Is this the "action extraction" pattern from gen-002 cards?
See improve/review-nj-20260708-gen2.md.

## Stale branches (merged to main, no unmerged work)
- nj/admin_dash (0 ahead, 90 behind)
- nj/less_jq_calls_in_context (0 ahead, 145 behind)
- nj/model_resolution (0 ahead, 88 behind)
- nj/web_viewer (0 ahead, 108 behind)

These are fully merged — safe to delete remote branches if desired.

## Patterns across alive branches
1. **Inner monologue refactoring** is the common thread: gen1, gen2, and run_local_llm all modify thinkers/inner_monologue/step substantially.
2. **gen2 builds on gen1** — gen2's diff includes gen1's commit. If both are alive, gen2 supersedes gen1.
3. **run_local_llm's repeat-suffix removal** touches the same code as gen1/gen2's inner_monologue changes — potential merge conflict.

## Suggested priorities for Nick
1. **nj/20260708_gen2** — supersedes gen1, has the most substantive work (action extraction). Worth reviewing for merge.
2. **nj/run_local_llm** — independent feature (local LLM support), but the repeat-suffix change may conflict with gen2.
3. **nj/shellm_term_demo** — demo work, lower urgency.
4. **Stale branches** — consider deleting the 4 merged remote branches to reduce clutter.
