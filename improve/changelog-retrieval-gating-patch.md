# Retrieval-thinker gating patch (2026-08-08)

## Status
Applied to live filesystem. `.identities/` is gitignored, so not committed to git.

## Bug
`step` script surfaced only ONE memory via `sort | head -1` of grep hits —
alphabetically-first mid always won, silently dropping all other matches.
Repro: token "retrieval" matched 71 distinct mids; only 1 surfaced.

## Fix
- Score memories by query-token match frequency (not alphabetical).
- Surface top-N (default 3, `RETRIEVAL_TOP_N` env override).
- Min-score filter (default 1, `RETRIEVAL_MIN_SCORE` env override).
- `grep -F -w` retained for whole-word matching.

## Files
- Patched: `.identities/audel/thinkers/retrieval/step` (90 lines)
- Backup:  `.identities/audel/thinkers/retrieval/step.bak.20260808`

## Verification
- Live wakeup surfaced 3 memories with scores [225, 213, 168].
- `bash -n` syntax check passed.
- Sample input test passed.

## Revert
```bash
cp .identities/audel/thinkers/retrieval/step.bak.20260808 \
   .identities/audel/thinkers/retrieval/step
```
