# The Librarian: memory and context for project mode

Status: implemented (all four phases of the spec), exercised offline only.
Spec: `Librarian Memory & Context System for a Long-Running Autonomous
Agent.md` in the repository root (Amalie Trewartha, 2026-10-09). Code:
`librarian/` (Python, standard library only), `tools/librarian` (wrapper),
hooks in `thinkers/monolith/step` and `thinkers/_lib/project.sh`, commands
in `tools/headlong-project`, templates in `identities/project/`. Tests:
`librarian/tests/`, `tests/test_librarian_py.sh`, `tests/test_librarian_cli.sh`,
`tests/test_librarian_wake.sh`.

This note records what the spec left open, what Headlong decided, and where
the implementation deviates from the spec and why. The spec itself is the
reference for the memory model, the ranking signals and the lifecycle.

## What it is in Headlong terms

A project-mode mind runs for weeks. Every wake, the monolith step asks the
librarian for a **context pack** before the model runs, and tells it what
happened after. The pack replaces the "life so far" rollups and the
related-memories section in project wakes; `project-memory.md` stays, as
task state. The store is per identity (`<identity>/librarian/store.sqlite`),
so what one project teaches is available to the next.

```
pre-run   librarian runtime pre   → maintenance (daily/weekly), context request, pack, signal lines
          (the pack goes into the project section: charter → spec → references → pack → project memory → journal tail → clock → STATE)
post-run  librarian runtime post  → outcome from artifacts → episode → credit → progress/triggers → captures → export mirrors
model     librarian search/fetch/propose/identity edit/suggestion respond, from its own bash
humans    headlong-project queue|probe|preferences|librarian, committed to project/ as author human
```

## Decisions

| Question (spec) | Decision |
|---|---|
| Graph DB vs SQLite | SQLite with adjacency tables and FTS5 (Python fallback when FTS5 is missing). Standard library only, because the CLI also runs inside the shellm sandbox where only python3 is installed. |
| Vector index | Not yet. Recall is tag match (specificity-weighted) + BM25 over summary and tags + one graph hop. The `embeddings` table and a null `EmbedProvider` are the seam. |
| Who is the librarian | A deterministic program with optional single-call model stages, not a second agent loop. Model tiers by role: `rank` and `judge` on the fast model, `draft` and `probe-answer` on the main model, `core-check` escalates heuristic → fast → main → human queue. `LIBRARIAN_MODEL_<ROLE>` overrides; `LLM_RUN_ID=librarian:<role>` attributes spend. |
| Default budget | `LIBRARIAN_PACK_TOKENS` = 8000 estimated tokens (chars/4). |
| Agent writes or proposes | Proposes. `librarian propose` runs the quality gate at write time; nothing bypasses it. |
| Seeding the group model | `headlong-project init --preferences FILE` imports stated values as active, human-authored preference nodes. Observed standards come from consolidation; recurring needs from retrospectives. |
| Multi-agent scoping | Not addressed. Blind and delegate runs are cut off from the store on purpose (see below). |

## Deviations from the spec, and why

- **One wake is one episode, and the progress feed is per wake.** The spec
  streams progress every N tool calls. Headlong's model runs one bash block
  per step inside a sandbox the host cannot interrupt, so the librarian sees
  the run's steps after the fact. Suggestions therefore land as routing
  signals on the next wake, and the cooldown counts project time or tool
  calls across wakes.
- **Outcomes need exogenous evidence.** The spec's "verification passed"
  signal has no test suite in research work. The runtime decides from
  artifacts, in this order: a ritual's output file written → `success`; an
  adversary review that cites a packed memory → `success` or `failure` for
  that memory (per-id override on the citation); step cap hit or a failed run
  → `failure`; an error signature that recurred after a skill for it was
  packed → `failure` for that skill; a journal entry plus FINAL → `partial`;
  FINAL alone → `partial`; nothing → `unknown`. The agent's own activity is
  never evidence of success. Late upgrades run on the weekly ritual: a
  failure signature that never recurred → `success`; a human edit to the
  deliverable inside the review window → `failure`.
- **`partial` is a real outcome.** The charter makes the journal entry the
  definition of a finished work wake; a FINAL without one is the "appearance
  of progress" case. Neither moves confidence.
- **Resolved failures are detected by the runtime.** When a command family
  fails twice and then succeeds, a `pending_capture` row opens and every
  following wake carries a CAPTURE signal until a skill with matching tags
  is proposed. After `LIBRARIAN_CAPTURE_TTL_DAYS` (3) the librarian drafts
  the skill itself from the trajectory span (main model, probationary,
  provenance `auto-draft`), or archives the row as `undrafted` without a
  model. Same fail-safe shape as rituals keyed to output files.
- **Episodes enter `active`, not `probationary`.** They are records of
  outcomes, not claims awaiting confirmation; probation is for the distilled
  types. They are never deduplicated.
- **Working-identity rate limit is per project week.** The spec says one
  edit per project close. Headlong projects run for weeks, so the weekly
  ritual counts as a close (`--occasion weekly`, keyed on the project
  week), the final ritual as `project-close`, plus one edit per accepted
  repeated-failure suggestion.
- **Blind and delegate never see the store.** A pack would hand the
  adversary the favored approach and the explorer the prior decisions.
  `bin/blind` runs with `HEADLONG_LIBRARIAN=0`; verdicts flow back through
  the outcome rule.
- **Skills are nodes; files are mirrors.** `project/skills/**`, `addenda.md`
  and `project/librarian.md` are regenerated by `librarian export` every
  wake and committed with `project/`. The identity-wide mirror under
  `<identity>/librarian/export/lib-*.md` is what the dashboard's Memories
  page reads.

## Where things live

| Path | What |
|---|---|
| `<identity>/librarian/store.sqlite` | the store (WAL; one writer at a time, 5 s busy timeout) |
| `<identity>/librarian/export/lib-<type>-<ulid>.md` | identity-wide markdown mirror, `bin/mem`-shaped frontmatter |
| `<identity>/run/librarian_request.json` | this wake's request: id, packed ids, ritual, phase (written by `pre`, consumed by `post` and by `fetch`) |
| `<identity>/run/librarian_signals` | CAPTURE, LIBRARIAN SUGGESTION and queue notices for this wake |
| `<identity>/run/librarian.log` | stderr of `runtime post` |
| `<identity>/project-pristine/project_id` | `p-<YYYYMMDD>-<slug>`, the `project:` tag for this run |
| `<identity>/project-pristine/probes.md` | the consistency probes |
| `project/addenda.md`, `project/skills/**`, `project/librarian.md` | generated mirrors |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `HEADLONG_LIBRARIAN` | 1 | 0 turns the hooks off; the wake gets today's plain excerpt |
| `HEADLONG_LIBRARIAN_SRC` | `<app>/librarian/src` (init writes it to `.env`) | the package path, passed into the sandbox read-only |
| `LIBRARIAN_PACK_TOKENS` | 8000 | pack budget in estimated tokens |
| `LIBRARIAN_MODEL`, `LIBRARIAN_MODEL_RANK|JUDGE|DRAFT|CORE_CHECK|PROBE_ANSWER` | tier defaults | model per role |
| `LIBRARIAN_LLM` | 1 | 0 skips every model stage (tests, offline runs) |
| `LIBRARIAN_LLM_MAX_CALLS` | 4 | model calls per CLI invocation |
| `LIBRARIAN_EXCLUDE_WAKES` | 1 | how many previous packs' task memories are excluded from the next |
| `LIBRARIAN_CAPTURE_TTL_DAYS` | 3 | days before an uncaptured resolved failure is auto-drafted or archived |
| `LIBRARIAN_REVIEW_WINDOW_DAYS` | 7 | window for late outcome upgrades on the weekly ritual |
| `LIBRARIAN_RECUR_WINDOW_DAYS` | 7 | days without recurrence that upgrade a partial episode |
| `LIBRARIAN_NOW`, `PROJECT_NOW`, `PROJECT_TIME_SCALE` | | the clock (tests and accelerated runs); durations are project seconds |
| `LIBRARIAN_STORE` | `$IDENTITY_DIR/librarian/store.sqlite` | store path override |
| `LIBRARIAN_FTS` | | `python` forces the BM25 fallback |

## Operator runbook

```bash
headlong-project init ada --spec brief.md --preferences values.md   # store, core identity, stated values
headlong-project status ada            # ... librarian: N nodes (...); queue K; captures open C
headlong-project queue ada             # core proposals, refused working edits, disputes, new area: tags
headlong-project queue ada approve Q7  # applied as author human, committed to project/
headlong-project probe ada             # consistency probes against the identity nodes
headlong-project preferences ada add "Prefer boring, well-understood tools."
headlong-project librarian ada stats   # any librarian command against the identity's store
headlong-project librarian ada eval --set librarian/tests/eval   # the offline ranking regression
```

## Phase gates (from the spec), to check on live runs

| Phase | Gate | Where to read it |
|---|---|---|
| Store & capture | gate-passing nodes appear; every wake has an episode with an outcome | `librarian stats`, `project/librarian.md` |
| Librarian v1 | pack precision ≥ 50%; uncovered-pull rate falling | `stats.pack_precision`, `stats.uncovered_pull_rate`; `librarian eval` offline |
| Lifecycle | suggestion acceptance ≥ 40%; duplicate pairs trending to zero | `stats.suggestions`, `stats.duplicate_pairs_last_run` |
| Identity & group | probe drift under threshold; every identity change traceable | `probe compare`, `identity list --history`, the queue |

## Known limits

- The outcome rule is only as good as the artifacts: a project that never
  runs adversary reviews confirms nothing until the weekly non-recurrence
  upgrade.
- The core-contradiction heuristic (stemmed overlap plus negation parity or
  an antonym pair) is weak without a model; conflicts it misses are caught
  later by probes, conflicts it invents go to the queue, never lost.
- Token estimates are chars/4; the pack keeps 5% headroom.
- No embeddings, so recall misses paraphrases that share no tag or term.
- The librarian's model stages run on the host inside the wake and count
  against the project budget; the daily ritual wake carries consolidation.
