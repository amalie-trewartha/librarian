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

## Cold start & tier growth (how many tiers, and when)

The pyramid is built lazily and incrementally, so it grows *with* the
trajectory — a fresh agent has none of it.

- **At 0 steps: zero rollup tiers.** Only tier 0 (the raw stream) exists, and
  it's empty; context is just the system prompt. Below `F` steps there are no
  rollups at all — the raw tail already shows everything.
- **A tier-k block seals — and that tier first appears — when the trajectory
  reaches `F^k` steps.** With `F=10`: the first tier-1 rollup is created at step
  10 (block `[0,10)` is complete), the first tier-2 at step 100, the first
  tier-3 at 1,000. A new tier is born each time `N` crosses a power of `F`.
- **So the number of live tiers at `N` steps is `⌊log_F N⌋`:** 0 for `N<10`,
  1 for `10 ≤ N < 100`, 2 for `100 ≤ N < 1,000`, and so on.
- **Sealed vs. shown are different moments.** A tier-1 block seals at step 10,
  but tier-1 rollups only start *appearing in the assembled context* once the
  raw tail no longer covers everything (`N > R`; with `R=20` that's step 21).
  Sealing early is harmless — it's just cache warming ahead of need.

**Is there a cap on tiers?** None is needed: tier count grows logarithmically,
so a billion steps is still only 9 tiers at `F=10`; the natural ceiling is
`⌈log_F N⌉`. An optional `ROLLUP_MAX_TIERS` can pin it — when the cap is hit,
the coarsest tier is allowed to accumulate *more than `F`* entries rather than
spawning a new tier, so its entry count then grows linearly (`≈ N/F^maxtier`,
still tiny). Default: uncapped.

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

## Sizing to the model (dynamic budget)

The budget shouldn't be a fixed number — it should track the **actual context
window of the model doing inference**, so we use as much of it as possible.

- **Resolve the window `W`** from the model in use (`THINK_MODEL` →
  `SHELLM_MODEL`), via a small model→window lookup with a `MODEL_CONTEXT_WINDOW`
  override for anything the table doesn't know. (Claude models are ~200K tokens
  by default, up to 1M with the long-context beta; the resolver reads the same
  model the run will use.)
- **Budget `B = round(W × MONOLITH_CONTEXT_FRACTION)`** (default fraction ~0.6),
  leaving headroom for the system prompt, tool defs, and the output. Setting
  `MONOLITH_CONTEXT_BUDGET=auto` (the default) derives `B` this way; a numeric
  value pins it instead.
- **Spend `B` bottom-up — most valuable first.** Grow the raw tail `R` first
  (recency is worth the most tokens), then raise the per-tier counts `Kₖ`, then
  promote the deepest tiers to verbatim, until `B` is exhausted. The parameters
  `R`, `Kₖ`, and how many tiers are shown in full become **derived from the
  model**, not hand-set.

Because the coarsest tier always reaches step 0, every budget stays *complete* —
a 1M-token window just shows thousands of raw steps and many summaries per tier;
a 200K window shows fewer of each; both still span the whole life. "Use as much
of the context as possible" is then simply a high `MONOLITH_CONTEXT_FRACTION`:
the staircase auto-expands to fill whatever the model offers.

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

**Decision (v1): build lazily on context-assembly, with the cache.** When the
staircase is assembled, seal any newly-complete blocks bottom-up and reuse
everything already cached — no background sealer running off the dispatcher.
It's the simplest thing that works, and because only the frontier is ever
computed, a warm cache makes assembly cheap; the one cold-cache wakeup that has
to seal a backlog is acceptable (and bounded — at most one new block per tier).
A background sealer stays available as a later optimization if that first
wakeup ever feels slow. Build is **idempotent**: same log ⇒ same pyramid.

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

**Decision (v1): extend `recap`, not a new binary.** The tiers, the recursion,
and the staircase assembler are added *inside* `bin/recap` (e.g. a `recap
--context` mode and internal recursive summarization), rather than spawning a
sibling `bin/rollup`. One summarizer, one cache format, one place for the
step-id discipline — no second tool to keep in sync.

**Decision (v1): the bottom tier is width `F`, like every other tier.** Even
though single steps are the noisiest input, we keep tier 1 = `F` raw steps for
simplicity and uniformity; a wider bottom window is a later tuning knob, not a
starting complication.

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

Replace the single `tail -n 20` with a budget-aware staircase assembler. Since
the assembler lives in `recap` (above), the step calls `recap --context --budget
<tokens>` (wrapped by a thin `_life_context` helper in `common.sh` for the
default flags):

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
| `MONOLITH_CONTEXT_BUDGET` | `auto` | token budget the staircase fills; `auto` derives it from the model's window (below), or set a fixed number |
| `MONOLITH_CONTEXT_FRACTION` | `0.6` | share of the model's context window to fill, leaving headroom for system prompt + tools + output |
| `MODEL_CONTEXT_WINDOW` | `auto` | the inference model's window in tokens; `auto` resolves it from the model name, override for unknown models |
| `ROLLUP_FANOUT` | `10` | `F` — steps per tier-1 entry, and children per higher tier (accepts a per-tier list, e.g. `10,10,10`) |
| `ROLLUP_MAX_TIERS` | `∞` | optional cap on tier count; when hit, the coarsest tier grows past `F` entries instead of spawning a new tier |
| `ROLLUP_RAW_TAIL` | `auto` (≥20) | `R` — most-recent steps shown verbatim; grows with the budget, floored at 20 |
| `ROLLUP_PER_TIER` | `auto` (≥F) | `Kₖ` — entries shown per tier in the staircase; grows with the budget |
| `ROLLUP_MODEL` | `SHELLM_FAST_MODEL` → … | model for rollup summaries (cheap; these are frequent, small calls) |

## Decided for v1

- **Build:** lazily on context-assembly, with the sealed-block cache (no
  background sealer). See Storage.
- **Bottom tier:** width `F`, uniform with every other tier (no special wider
  window). See Build on recap.
- **Home:** extend `bin/recap` (a `recap --context` mode + internal recursion);
  no new `bin/rollup`. See Build on recap.

## Open questions

1. **Re-summarization on relevance.** Should drill-down expansions be cached per
   query, or always recomputed from raw? Start: raw, uncached — expansions are
   rare and cheap.
2. **Bottom-tier width, revisited.** `F` is the v1 choice for simplicity; a
   wider tier-1 window (e.g. per-20 raw steps) may read better once we tune
   against a real mind log — a knob to revisit, not a blocker.
