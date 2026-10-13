# librarian

The Librarian: Librarian's memory store and context packer for project-mode
minds. Implements the design in the repository's `Librarian Memory & Context
System for a Long-Running Autonomous Agent.md`; the Librarian-specific
decisions are in `design/librarian.md`.

Standard library only at runtime (sqlite3 with FTS5, json, re, argparse):
the same code runs on the host from the monolith step and inside the shellm
sandbox from the mind's own bash, through the `tools/librarian` wrapper.

```
src/librarian/
  db.py         store, schema, clock (LIBRARIAN_NOW / PROJECT_NOW / PROJECT_TIME_SCALE), ULIDs
  model.py      node envelope, tags, tokens, insert/supersede/edges
  gate.py       the quality gate every write passes
  recall.py     tag match + BM25 (FTS5 or Python) + one graph hop
  rank.py       cut 1 (deterministic) and optional cut 2 (fast-model relevance)
  pack.py       budget packing and the fixed context-pack layout
  lifecycle.py  credit assignment, late outcomes, consolidation, decay
  identity.py   core/working identity, the human queue, probes
  triggers.py   progress feed, suggestion triggers, cooldowns
  outcome.py    the deterministic wake outcome rule and phase map
  runtime.py    `runtime pre` / `runtime post`, what the monolith step calls
  exchange.py   export mirrors, imports, stats, the offline eval
  llm.py        bridge to bin/llm with model tiers by role
  cli.py        the `librarian` command line (JSON by default, --text)
tests/          unittest-style tests (python3 -m unittest or pytest), fixtures/seed.json, eval/*.json
```

Run the tests:

```bash
python3 -m unittest discover -s librarian/tests -t librarian/tests   # no dependencies
uv run --project librarian pytest librarian/tests -q                  # what CI runs
tests/test_librarian_py.sh                                            # from the bash suite
```

Try it against a scratch identity:

```bash
export IDENTITY_DIR=/tmp/ident LIBRARIAN_LLM=0; mkdir -p "$IDENTITY_DIR/run"
tools/librarian --text init
tools/librarian --text propose --type skill --summary "when would I want this?" \
    --body 'the fix: `cmd --flag`; verified 2026-10-01' --tags pkg:x,area:tooling --source journal
tools/librarian --text pack --task "what am I doing" --tags pkg:x --phase debugging --budget 2000
```
