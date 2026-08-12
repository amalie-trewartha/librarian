# Review Request: 46 commits (2026-08-06 → 2026-08-07)

**Status:** Tests green (177 assertions, 0 failures). Merged with origin/main (clean auto-merge). Ready to push.

## Summary

46 commits, 4015 insertions across 64 files. ~14.5 hours of work.
Grouped by theme below — review whichever themes interest you.

---

## 1. LLM & Model Capability (2 commits)

- `7afc7be` **llm: guard thinking params by model capability** — prevents sending thinking tokens to models that don't support them
- `0dbfbcf` **Fix nested shellm API key + model propagation** — nested shellm calls now inherit API key + model correctly

## 2. Thinkers System (5 commits)

- `1993285` **thinkers: add proprioception thinker** — monitors substrate for errors (dead code, exceptions)
- `0d24cbd` **thinkers: add post-stop stray tail vitals check** — cleans up orphaned tail processes after stop
- `4b96412` **fix(thinkers): block self-error feedback loops** — even with trigger_self enabled, thinker won't re-trigger on its own errors
- `f2e2dda` **test(thinkers): redirect stdin from /dev/null on start/stop_thinkers** — prevents thinkers from hanging on stdin during start/stop
- `5c2b763` **improve: add retrieval-thinker** — passive memory influence via keyword index (in-progress, not wired)

## 3. Memory & Retrieval (4 commits)

- `649594a` **mem: pipe search corpus via stdin** — avoids ARG_MAX overflow on large memory corpora
- `aaad444` **bin/mem: rebuild index.tsv on add/forget** — keeps index fresh without manual rebuild
- `3cd3e73` **common: integrate lens into _recent_stream** — lens hook in context assembly
- `70353ef` **lens: add lens.sh** — passive memory-influenced context selection

## 4. Slack & Outbound (1 commit)

- `3b906c8` **Slack outbound robustness + perf improvements** — retry logic, dedup, faster sends

## 5. Repetition Detection (3 commits)

- `5d664d7a` **improve: add within-response repetition detector** — catches repeated blocks within a single response
- `8620030` **improve: wire iteration repetition detector into bin/shellm** — catches repetition across iterations
- `60be21c` **chore(retrieval): remove accidentally-committed .bak debris**

## 6. Bug Fixes (3 commits)

- `38b5e7b` **fix(identity): drop broken _mem_count increment** — was incrementing wrong counter in import loop
- `dedc053` **fix(session): simplify id_args expansion** — `"${id_args[@]}"` instead of manual expansion

## 7. Terminal-Bench2 Eval (3 commits)

- `d9781e3` **docs(tbench2): add timeout/wrong-answer summaries + message to Braden**
- `c933bbc` **docs(tbench2): add v4 recommendation** — SECONDARY mechanism spec, TERTIARY triage
- `9f1ed13` **docs(next-steps): mark fuzzy thought-repetition proxy DONE**

## 8. Improve Notes & Reviews (19 commits)

Design docs, decision logs, review notes, and next-steps tracking.
Key files: `improve/decisions.md`, `improve/design/cards/wire-iteration-repetition-detector.md`, `improve/notes/*.md`, `improve/review-*.md`

## 9. Merge (1 commit)

- `a0d02f3` **Merge remote-tracking branch 'origin/main'** — integrated team's Slack/Telegram deploy commits (3 commits, clean auto-merge despite 4-file overlap)

---

## Verification

- `tests/test_context.sh` — 21 passed
- `tests/test_identity_export_import.sh` — 42 passed
- `tests/test_llm_retry.sh` — 48 passed
- `tests/test_recap.sh` — 30 passed
- `tests/test_thinkers_drain.sh` — 20 passed
- `tests/test_thinkers_pending.sh` — 16 passed
- `improve/tests/repetition_detector.sh` — OK
- `improve/tests/test_iteration_repetition.sh` — OK

**177 assertions, 0 failures.**
