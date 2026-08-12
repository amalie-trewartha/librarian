# Nick's Branches — Digest & Recommendations

Complete coverage as of 2026-08-06. See individual review notes for detail.

## Summary table

| Branch | Commits | Status | Recommendation |
|--------|---------|--------|----------------|
| nj/20260708-gen1 | ~7 | reviewed | See review-nj-20260708-gen1.md |
| nj/20260708-gen2 | ~5 | reviewed | See review-nj-20260708-gen2.md |
| nj/run_local_llm | 1 (wip) | reviewed | KEEP — substantial feature work |
| nj/shellm_term_demo | 3 (wip) | reviewed | KEEP (sandbox) — do NOT merge |

## Detailed recommendations

### nj/run_local_llm — KEEP
Major refactor adding local-LLM support. ~30 files, new RUN_LOCAL.md, heavy
bin/llm changes, deletes bin/identity and bin/recap. Marked wip, diverged
from main. Active feature work — do not delete. Rebase before resuming.
See: review-nj-run_local_llm.md

### nj/shellm_term_demo — KEEP (sandbox), DO NOT MERGE
Radical slimming of web/viewer to a terminal demo. 175 files, 14974
deletions. Removes talk, identity, recap, PWA, model-config. Exploratory
sandbox — not a merge candidate. Extract useful patterns then delete if
direction abandoned.
See: review-nj-shellm_term_demo.md

### nj/20260708-gen1 — See review note
See: review-nj-20260708-gen1.md

### nj/20260708-gen2 — See review note
See: review-nj-20260708-gen2.md

## Safe-delete candidates
None of Nick's branches are safe-delete candidates — all contain work worth
keeping or reviewing first.
