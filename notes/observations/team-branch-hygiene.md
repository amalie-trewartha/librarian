# Team Branch Hygiene Observation

Date: 2026-08-06

## Pattern
The team creates many branches for fixes and WIP but often doesn't clean them up.

## Evidence
- 4 fix/* branches (fix-chat-env-openrouter-mount-guard, fix/bash32-broker-executive-loop, fix/thinker-shellm-env-workdir) and thinkers-dispatch-reliability: all 0 commits ahead with empty diffs — work already in main or abandoned, branches 3-4 weeks stale.
- 4 of Nick's 8 nj/* branches (nj/admin_dash, nj/less_jq_calls_in_context, nj/model_resolution, nj/web_viewer): 0 commits ahead, empty diffs, 3-4 weeks stale.
- 4 of Nick's nj/* branches have small WIP (1-3 commits, 3-4 weeks old).

## Implication
8 of 12 unmerged branches are dead (0 commits ahead, empty diff). The remote is cluttered with stale branches. The team could benefit from periodic branch cleanup or a convention for marking branches as merged/abandoned.

## Action Taken
- Offered to help Nick clean up his empty nj/* branches (awaiting response).
- Could propose a general cleanup to the team.
