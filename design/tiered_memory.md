# Tiered memory rollups — the whole life in every context window

Status: draft
Relates to: [monolith_thinker.md](monolith_thinker.md),
[recap.md](recap.md) (this generalizes recap from one tier to many).

## Problem

The monolith's short-term memory is a hard 20-step window. Context is built by
`_recent_stream` (`thinkers/_lib/common.sh`), which is just:

```sh
traj cat "$ROOT_TRAJ_ID" --raw | jq '<keep narrative types>' | tail -n 20
```

So on every wakeup the mind sees only the last ~20 steps. Everything older is
invisible unless it was deliberately saved to `mem` (semantic recall) or dug up
by the external `recap` tool. A mind that has lived thousands of steps
(nick-web-2 hit 2,176 on day one) is reasoning with a goldfish's window: it
forgets what it was doing an hour ago, repeats itself, and loses the thread of
long arcs.

Raising `THINK_CONTEXT_TAIL` doesn't fix it — it just moves the cliff. A linear
tail can never both (a) show recent detail and (b) cover a whole life, because
the whole life grows without bound and the window doesn't.

## Goal

Every context window should contain the agent's **entire life experience**,
at a level of detail that decays with age: the last few steps verbatim, the last
hour in fine summary, the last day coarser, the whole existence in a few broad
strokes — all at once, in bounded space. And it should **grow to fill whatever
context window the model has**: a bigger budget buys more detail everywhere, not
a longer forgetful tail.

The shape that gives you "complete coverage in bounded space" is a **logarithmic
pyramid of summaries** — recent = fine, distant = coarse, total size ∝ log(life
length).

## Core idea: tiered rollups (the memory pyramid)

Summaries at geometrically coarsening granularity. With a **fanout `F`** (default
10):

| tier | one entry summarizes | one entry covers | built from |
|------|----------------------|------------------|------------|
| 0 | — (raw trajectory steps) | 1 step | the mind log itself |
| 1 | `F` raw steps | 10 steps | tier 0 |
| 2 | `F` tier-1 rollups | 100 steps | tier 1 |
| 3 | `F` tier-2 rollups | 1,000 steps | tier 2 |
| k | `F` tier-(k-1) rollups | `F^k` steps | tier k-1 |

Tier k has one entry per `F^k` steps, so a life of `N` steps needs
`⌈log_F N⌉` tiers — 7 tiers covers a million steps at `F=10`. This is exactly
the "summary per 10 → per 100 → per 1,000" the mind log wants; the `F=10`
default reproduces those numbers, and `F` (or a per-tier fanout list like
`10,10,10`) is configurable.

Each rollup entry is the recap-shaped object we already produce: a short
summary, a few themes, and **cited step-ids** that literally appear under it
(see Drill-down). Higher tiers are **rolled up from the tier below**, not
re-summarized from raw steps — that's what makes the work exponentially cheap
(below) — but each entry carries forward a few of its children's notable
step-ids so concrete anchors survive the climb rather than dissolving into
summary-of-summary mush.

## Assembling one context window: the staircase

A context window is built as a **staircase** from coarse to fine, always
reaching back to birth:

```
[tier T ]  the whole life so far, in a handful of broad strokes
[tier k ]  … progressively finer for more recent spans …
[tier 2 ]  the last ~F·100 steps, one line per 100
[tier 1 ]  the last ~F·10 steps, one line per 10
[tier 0 ]  the last R steps, verbatim          ← the "now"
```

Read from the bottom up: show the last `R` raw steps; before them the `K₁`
tier-1 rollups covering the span just older; before those the `K₂` tier-2
rollups; and so on until the coarsest tier reaches step 0. Each tier contributes
a **bounded** number of entries (`Kₖ`, default = `F`), and each tier reaches
`F×` further back, so:

- **Coverage is total.** The coarsest tier's oldest entry starts at step 0.
  Nothing in the life is unrepresented.
- **Size is logarithmic.** Total ≈ `R + Σ Kₖ` ≈ `R + F·log_F N`. For a
  million-step life at `F=10`, `R=20`: ~20 raw + ~70 summary lines. Bounded,
  tiny, complete.
- **Detail decays smoothly with age**, because each step back up the staircase
  is one tier coarser.

"Grow to fill the context window" is just turning up `R` and the per-tier `Kₖ`:
a larger budget shows more raw steps and more summaries per tier (even whole
tiers verbatim), still complete, still bounded by the budget. The assembler
takes a **token budget** and fills it from the bottom (most valuable) up.

## Storage & incremental build (the exponential backoff of *work*)

Rollups live in a cache beside the log, e.g. `<traj-dir>/rollups/`, parallel to
recap's `<traj-dir>/recap/`. Entries are keyed by **absolute step-index range**,
which never shifts:

```
rollups/t1/000000-000010.json   summarizes steps [0,10)
rollups/t1/000010-000020.json   summarizes steps [10,20)
rollups/t2/000000-000100.json   summarizes tier-1 blocks [0,10)
…
```

A block is **sealed** the moment it's complete (its `F` children exist) and is
then **immutable and cached forever** — the past doesn't change, so it's
summarized exactly once. Only the **frontier** is ever recomputed: the current
partial tier-0 tail plus the youngest still-growing block at each tier.

This makes summarization cost back off exponentially, mirroring the memory it
builds:

- tier 1 fires once per `F` steps, tier 2 once per `F²`, tier k once per `F^k`.
- Lifetime LLM calls ≈ `N/F + N/F² + … ≈ N/(F−1)` — for `F=10`, about one small
  call per ten steps, amortized. Each call summarizes only `F` items, so it's
  cheap and fixed-size regardless of life length.
- Storage is `Σ N/F^k ≈ N/(F−1)` small files — and can be pruned/compacted at
  the low tiers since the higher tiers already cover them.

Build is **incremental and idempotent**: on demand (when context is assembled)
or on append, seal any newly-complete blocks bottom-up, reusing everything
already cached. Same log ⇒ same pyramid.

## Build on `recap`, don't reinvent

`recap` already implements the hard parts of a single tier: filter noise steps
(`idle`, seed thoughts, sub-run internals), render NUL-safely to `[id] type:
content…` lines, map a window → an episode via one `llm` call returning strict
JSON (title, summary, themes, notable step-ids), reduce, and cache incrementally
under `<traj-dir>/recap/`.

This design is **recursive recap**:

- **Tier 1** = recap over raw steps with `WINDOW=F` instead of 100.
- **Tier k>1** = the same map step, but its input "window" is `F` rollup
  entries from tier k-1 (rendered as lines) rather than raw steps.
- **New parts** are only: the recursion (feed a tier's output as the next
  tier's input), the sealed-block cache keyed by step-index, and the staircase
  assembler for context.

So the implementation is a generalization of `bin/recap` (or a sibling
`bin/rollup` that reuses its primitives), keeping recap's step-id discipline and
caching for free.

## Drill-down: memory that expands on demand

Every rollup entry carries the step-ids it summarizes (representative ones at
high tiers). That makes the pyramid **navigable**, not just lossy:

- The monolith's `recall` route can take a summary the model finds relevant and
  `traj cat` the underlying step-id range (or read the finer child blocks) to
  pull the actual steps back into context on the next wakeup — "zoom in" on a
  remembered span.
- This is how "grow to fill the context window" also works *selectively*: the
  default staircase is coarse far back, but the mind can spend budget expanding
  the one old span that matters right now, instead of uniformly.

## Relationship to `mem`

The pyramid does **not** replace `mem`. They're complementary:

- **`mem`** — *semantic, curated, explicit.* Facts/goals/skills the agent chose
  to remember, retrieved by meaning via `mem search`. Sparse and deliberate.
- **rollups** — *episodic, automatic, complete.* Everything that happened, at
  level-of-detail, retrieved by recency/position. Dense and exhaustive.

One answers "what do I know about X?"; the other answers "what has my life been,
and what was I just doing?" A mind wants both. (A natural interaction: a coarse
rollup noticing a recurring theme is exactly the signal for the `learn` route to
mint a durable `mem`.)

## Monolith integration

Replace the single `tail -n 20` with a budget-aware staircase assembler —
`_life_context` in `common.sh`, or a `recap --context --budget <tokens>`
subcommand the step calls:

```sh
# was: recent_context=$(_recent_stream "$THINK_CONTEXT_TAIL")
recent_context=$(_life_context --raw-tail "$THINK_CONTEXT_TAIL" \
                               --budget "${MONOLITH_CONTEXT_BUDGET:-6000}")
```

It emits the staircase (coarse→fine, then the raw tail) as labeled sections so
the prompt clearly distinguishes "your life so far (summarized)" from "right
now (verbatim)". The existing fast-reply and router prompts consume it exactly
where `recent_context` is used today; nothing else in the step changes.

## Edge cases & robustness

- **Noise.** Summarization tiers use recap's filter (drop `idle`, seeds,
  sub-run internals). The raw tail may keep `idle` for immediate continuity, but
  a block of pure idle summarizes to one line ("resting, N idle ticks").
- **Corrupt lines / blobs.** Same tolerant `fromjson?` parse and content
  truncation `_recent_stream`/recap already use; oversized step content is
  already blob-spilled by `traj`.
- **Build failure at a tier.** Degrade gracefully: if tier k can't be built,
  fall back to showing the finer tier's entries (more lines) or the raw range
  for that span — never drop coverage silently; log what was coarsened.
- **Determinism.** Sealed blocks are immutable and keyed by step range, so the
  pyramid is reproducible and caches never go stale for the past.
- **Fidelity of summary-of-summaries.** Carrying children's notable step-ids up
  each tier keeps concrete anchors; if a high tier drifts, drill-down recovers
  ground truth from the raw steps.

## Config knobs

| var | default | meaning |
|-----|---------|---------|
| `MONOLITH_CONTEXT_BUDGET` | `6000` | token budget the staircase fills |
| `ROLLUP_FANOUT` | `10` | `F` — steps per tier-1 entry, and children per higher tier (accepts a per-tier list, e.g. `10,10,10`) |
| `ROLLUP_RAW_TAIL` | `20` | `R` — most-recent steps shown verbatim |
| `ROLLUP_PER_TIER` | `= F` | `Kₖ` — entries shown per tier in the staircase |
| `ROLLUP_MODEL` | `SHELLM_FAST_MODEL` → … | model for rollup summaries (cheap; these are frequent, small calls) |

## Open questions

1. **Build trigger.** Lazily on context-assembly (simple, but a cold cache
   makes one wakeup slow) vs. a low-priority background sealer the dispatcher
   runs as steps land (smooth, but more moving parts). Lazy-with-cache first.
2. **Fanout vs. window.** `F=10` gives 10/100/1000. Is a larger tier-1 window
   (e.g. summarize per 20 raw steps, then ×10) better for the bottom tier, where
   individual steps are noisiest? Tune against a real mind log.
3. **Re-summarization on relevance.** Should drill-down expansions be cached per
   query, or always recomputed from raw? Start: raw, uncached — expansions are
   rare and cheap.
4. **Where the assembler lives.** Extend `recap` with a `--context` mode, or a
   new `bin/rollup`? Leaning toward extending recap to keep one summarizer.
