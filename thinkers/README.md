# thinkers/

The thought processes that make up a mind. Each subdirectory is one
thinker: a `step` executable that produces the next thought, and a
`subscriptions.jsonl` that says which trajectory entries wake it. The
`thinkers` dispatcher in [bin/](../bin/) runs them.

- `monolith/` is the main mind loop, with its prompt in `prompt.md`.
- `responder/` handles fast chat replies.
- `_lib/` holds shell helpers shared by the thinkers.

Code here counts against the under-10K-lines core (`cloc bin/ thinkers/`).
