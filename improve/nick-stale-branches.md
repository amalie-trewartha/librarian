# Remote branch audit — 2026-08-06

_audel audit. Updated from the 2026-08-05 nj/*-only pass to cover all remote branches._

## Fully merged (ahead=0, safe to delete)

| Branch | Behind main | Last commit | Last message |
|--------|------------|-------------|-------------|
| `origin/fix-chat-env-openrouter-mount-guard` | 139 | 2026-07-10 | Show source inside type tag as [type, source] in traj tail/cat output |
| `origin/fix/bash32-broker-executive-loop` | 153 | 2026-07-07 | Fix bash 3.2 crash in docker broker, fix executive infinite-loop stall |
| `origin/fix/thinker-shellm-env-workdir` | 153 | 2026-07-07 | Add --env and --workdir to _build_shellm_flags for thinkers |
| `origin/main` | 22 | 2026-08-05 | web: talk typing backstop 45s->3min, fast-poll window 30s->60s |
| `origin/nj/admin_dash` | 105 | 2026-07-15 | deploy cleanup |
| `origin/nj/less_jq_calls_in_context` | 160 | 2026-07-07 | context: render trajectory in a single jq pass instead of forking per line |
| `origin/nj/model_resolution` | 103 | 2026-07-15 | fix some default-to-claude settings to enable full openrouter |
| `origin/nj/web_viewer` | 123 | 2026-07-11 | minor fallback fix in step labeling |
| `origin/thinkers-dispatch-reliability` | 149 | 2026-07-07 | Overhaul thinker dispatch reliability + reorganize thinker roster |

## Unmerged but stale (ahead>0, >100 behind, >20 days old)

| Branch | Ahead | Behind | Last commit | Last message |
|--------|-------|-------|-------------|-------------|
| `origin/nj/20260708_gen1` | 1 | 141 | 2026-07-08 | improve: apply gen-001 cards — grounded observations, no idle busy-wait |
| `origin/nj/20260708_gen2` | 2 | 141 | 2026-07-08 | improve: apply gen-002 cards — action extraction, grounded monologue |
| `origin/nj/run_local_llm` | 1 | 116 | 2026-07-13 | wip |
| `origin/nj/shellm_term_demo` | 3 | 104 | 2026-07-15 | wi |
| `origin/polly/inner-monologue-glm` | 1 | 139 | 2026-07-10 | inner_monologue: default THINK_MODEL to glm-5.2 |

## Notes

- **Merged branches:** fully in main, no unique commits. Safe to
  `git push origin --delete <branch>`. The 2026-08-05 note covered
  only the 4 nj/* branches; this pass adds 3 more (fix/* and
  thinkers-dispatch-reliability).
- **Unmerged stale branches:** these have a few unique commits but are
  100+ behind main and 3+ weeks old. Each needs review/rebase/merge
  or close. See individual review-* notes where they exist.
- polly/inner-monologue-glm assessed in review-polly-inner-monologue-glm.md.
- I have not deleted anything — this is an audit only. Deletion is
  the branch owner's call.
