# Decision ledger

Append-only record of what each generation proposed and what became of it. This is the loop's anti-whiplash memory: `decide.sh` appends a line per reviewed card, the implementation handoff updates verdicts, and `critique.sh`/`synthesize.sh` feed recent entries back to the LLM so it doesn't re-propose applied fixes, revert recent ones on thin evidence, or resurrect declined cards. Unlike `generations/` (gitignored, disposable), this file is committed.

Line format:

```
- <date> <gen> ACCEPTED <card-slug> → <target> — pending implementation
- <date> <gen> ACCEPTED <card-slug> → <target> — IMPLEMENTED|REVISED|REJECTED: <one-line reason>   (updated by the verifier)
- <date> <gen> SKIPPED  <card-slug> → <target> — <optional human note>
```

*(Pre-ledger history: two validation generations ran on 2026-07-08 and were reset; their findings are summarized in [design/overview.md](design/overview.md). The `thinkers stop` process leak was diagnosed and fixed outside the loop — see [log.md](log.md).)*

## Entries
- 2026-08-08 gen-002 ACCEPTED fix-action-extraction-multiline → thinkers/monolith/step — IMPLEMENTED: commit 34d31b0 "apply gen-002 cards — action extraction, grounded monologue"
- 2026-08-08 gen-002 ACCEPTED fix-idle-on-bus-regression → thinkers/inner_monologue/step — IMPLEMENTED: commit 34d31b0 (grounded monologue, no idle busy-wait). Backoff via monolith/step dispatch hints, not inner loop.
- 2026-08-08 gen-002 ACCEPTED add-curl-timeout-web-research → bin/llm — IMPLEMENTED: commit 9382148 "curl connect/idle timeouts to prevent stalled-API hangs" (--connect-timeout, --max-time in bin/llm:769-771). Applied to LLM wrapper, not web-research skill directly.
- 2026-08-08 gen-003 ACCEPTED chat-thinker-split → thinkers/responder — IMPLEMENTED: sole-ownership message reply moved to responder thinker; monolith/step no longer emits chat replies (comment: "replies are the responder thinker's job, not ours").
- 2026-08-08 gen-003 ACCEPTED fix-memory-index-rebuild → bin/mem + thinkers/retrieval/build_index.sh — PARTIALLY IMPLEMENTED: commit 0d0ff96 improved rebuild_index error reporting, but build_index.sh does NOT exist in production (only in gen-001 test identities). rebuild_index call absent from bin/mem. New memories may be invisible to keyword retrieval — needs follow-up.
