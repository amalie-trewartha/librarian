# The Librarian: memory and context for project mode (v2)

Status: v2, implemented on branch `librarian-v2` (2026-10-31) from what
the A to D trials showed (design/librarian_trials_retrospective.md). Code:
`librarian/` (Python, standard library only), `tools/librarian` (wrapper),
hooks in `thinkers/monolith/step`, commands in `tools/librarian-project`,
templates in `identities/project/`. Tests: `librarian/tests/`,
`tests/test_librarian_py.sh`, `tests/test_librarian_cli.sh`,
`tests/test_librarian_recipes.sh`, `tests/test_librarian_wake.sh`. The
original spec is `Librarian Memory & Context System for a Long-Running
Autonomous Agent.md` in the repository root; v1's decisions and their
measured results are in the retrospective.

## Design rule

Every mechanism either changes what the mind sees in its prompt or is
gone. Bookkeeping that only moved a confidence number is out: in v1,
confidence never entered the ranking score, 96% of credit rows were zero,
and the two times the sign was decisive it was wrong.

## Goals

1. Carry across briefs what files do not: sourced facts about shared
   inputs, tooling skills, decisions, and lessons about how to work.
2. **Internal consistency of the work across briefs.** A quantity two
   briefs share carries one value, unit, year and source everywhere, or
   a recorded reason for the difference. The charter states it, the
   store tags it (`shared:<quantity>`), the pack shows it, the runtime
   checks it, and the reviewers are told to check it.
3. Low overhead: no model call in `runtime pre` or `post`, a pack of about
   2,000 tokens, and the main model spending its tokens on the work, not
   on memory chores.

## What happens on a wake

```
pre    librarian runtime pre  → task text (brief title, plan head, last journal entry, signals)
                              → pack: identity, preferences, [LESSONS], [SHARED VALUES], [TASK MEMORIES]
                              → signals: LESSON DUE (brief close), PREMORTEM DUE (brief start),
                                CONSISTENCY (shared values disagree), CAPTURE (resolved repeated failure)
                              → on a brief's first wake: judge the closed brief's lessons, refresh the files
model  librarian search / fetch / propose / shared / capture clear, from its own bash
post   librarian runtime post → outcome from artifacts → episode + citations → review_claim rows
                              → facts from SURVIVES claims → captures → ledger and digest when they changed
```

### Pack

Fixed order so the stable prefix caches. Identity core and preferences
verbatim (seeded at init). [LESSONS]: up to 3 retrospectives (or
`area:process` skills and decisions) from any brief, ranked by situation
(`ctx:` tag against the phase and ritual, `ctx:planning` and other
briefs' retrospectives at a brief's start, a `fail:` tag the current
brief's reviews keep finding), then by net judgment, then the one shown
longest ago. [SHARED VALUES]: facts tagged `shared:` whose quantity words
occur in the task text, all of them on a brief's first wakes, conflicting
ones first. [TASK MEMORIES]: up to 8 facts, skills and decisions by a
transparent score: IDF-weighted tag overlap, BM25 over summary, tags and
body keywords, recency with half-lives of 5 to 7 days, cited-when-shown
rate, and a type-by-phase prior. A candidate with no tag, text or graph
evidence is not packed. Rows the last pack showed and the mind neither
cited nor fetched are excluded once. Every row shows `shown N cited M`
and, when a review judged it, `reviews +k/-b`. No episodes: the journal
tail is the record of recent wakes. The model ranking cut is off
(`LIBRARIAN_RANK_LLM=1` turns it on; an omission then only demotes).

### Writing

- The mind proposes skills (after a resolved failure), decisions, and
  lessons (one retrospective per brief at its close, at most one more at
  a daily ritual), through the quality gate.
- The runtime writes a `fact` for every claim the adversary marks
  SURVIVES, from the claims file's text, with the review as provenance,
  the wake's tags, `area:review` and any `shared:` tag the claim carried.
  Status active. The mind need not propose what the reviewer confirmed.
- Facts tagged `shared:<quantity>` are the shared values. The runtime
  renders `project/shared-values.md` from them when one changes and at
  rituals.

### Lessons

One lesson moment per brief: on a new brief's first wake, if the closed
brief left no retrospective, LESSON DUE shows for up to 3 wakes. Lessons
are judged at the next brief's close by class recurrence: for each
`fail:<class>` tag on a lesson written before the closed brief, the
closed brief's rate of not-standing claims of that class per review is
compared with the brief before; fell → `confirmed` (and the lesson
leaves probation), rose → `recurred`. At least 3 reviews on both sides.
No judgment from single reviews: in run D the reviewer always found
something, and claim-level judging went 36 failures to 1 success.

### Consistency

`consistency.py`: facts tagged `shared:` grouped by quantity; the number
in a summary (skipping bare years) is its value; two briefs whose values
differ by more than 1% and that carry no `scope:reconciled` tag are a
conflict. Conflicts raise a CONSISTENCY signal every wake until one fact
is superseded or one is re-proposed with `scope:reconciled` and the
reason. `librarian shared` lists the ledger; `librarian-project banner`
counts conflicts; the cold-eyes reviewer receives the ledger file; the
adversary role checks shared quantities and classes a silent difference
`stale` or `basis`.

### Outcomes and credit

`outcome.decide_outcome` is unchanged: a ritual file written → success;
a review names ids → per-id overrides, wake partial; step cap or rc≠0 →
failure; journal + FINAL → partial. `lifecycle.close_episode` records
the episode and citations and keeps the per-node counters (use, success,
failure), which the pack shows. Confidence is still stored for
compatibility but nothing reads it for ranking. Recurred error
signatures are not scored.

## Removed from v1, and why

| Mechanism | Measured | Removed |
|---|---|---|
| Episodes in the pack | 50% of tokens, 6% cited | yes |
| Transfer section (BM25 on brief text) | 5% cited | yes |
| Practices | never formed | yes (lessons carry `reviews +k/-b`) |
| LESSON DUE per broken review | 19 lessons in a day | yes (one per brief) |
| Reviewer-judged lessons via `Lessons applied` | 36 failures / 1 success | replaced by class recurrence |
| Haiku rank cut | 93-99% of packs; omission vetoed tag hits | off by default |
| Confidence as ranking input, decay, late upgrades | never in the score | gone |
| Consolidation (merge, generalize, promote), disputes, probes, identity edits, check-in queue | 0-1 uses in 14 days | gone |
| Decision-point and other suggestions | 13% accepted | gone |
| Per-wake export of every node | O(store) per wake | at rituals and on change |
| Capture auto-draft (model call) | 0 useful | gone (captures expire) |

## Where things live

| Path | What |
|---|---|
| `<identity>/librarian/store.sqlite` | the store (WAL) |
| `<identity>/librarian/export/lib-*.md` | identity-wide markdown mirror, refreshed at rituals |
| `<identity>/run/librarian_request.json` | this wake's request: id, packed ids, task ids, ritual, phase, project |
| `<identity>/run/librarian_signals` | the wake's signal lines |
| `<identity>/run/librarian.log` | stderr of `runtime post` |
| `project/shared-values.md`, `project/librarian.md` | generated: the ledger and the digest |
| `project/risks.md` | the mind's pre-mortems, one section per brief |

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LIBRARIAN_MEMORY` | 1 | 0 turns the hooks off (the control arm) |
| `LIBRARIAN_PACK_TOKENS` | 2000 | pack budget in estimated tokens |
| `LIBRARIAN_LESSONS` | 1 | 0 drops [LESSONS], LESSON DUE and PREMORTEM DUE |
| `LIBRARIAN_SHARED` | 1 | 0 drops [SHARED VALUES] and CONSISTENCY |
| `LIBRARIAN_RANK_LLM` | 0 | 1 adds the model relevance cut to the task ranking |
| `LIBRARIAN_EXCLUDE_WAKES` | 1 | how many previous packs' uncited task rows are excluded |
| `LIBRARIAN_BRIEF_START_WAKES` | 3 | wakes that count as a brief's start |
| `LIBRARIAN_BRIEF_LESSON_WAKES` | 3 | wakes a closed brief's LESSON DUE is shown |
| `LIBRARIAN_CAPTURE_TTL_DAYS` | 3 | days before an uncaptured resolved failure expires |
| `LIBRARIAN_NOW`, `PROJECT_NOW`, `PROJECT_TIME_SCALE` | | the clock; the scale may be fractional |
| `SHELLM_SCRATCH_DIR` | | a host directory mounted as the container's /tmp (capped per kit) |

## Known limits

- The value of a shared fact is the first non-year number in its
  summary; a quantity whose summary leads with another number needs a
  summary that leads with the value.
- Lesson judgment needs three reviews per brief on both sides; briefs
  with fewer reviews judge nothing.
- No embeddings: recall misses paraphrases that share no tag or term.
- Facts from SURVIVES claims are only as good as the claims file: a
  claim without a number is skipped, and a claims file the runtime cannot
  find next to the review (`<name>-claims.md` or `claims.md` in the
  review's directory) yields none.
