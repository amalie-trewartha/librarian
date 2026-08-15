# Context assembly — one owner for a thinker's whole window

Status: draft
Relates to: [tiered_memory.md](tiered_memory.md) (the rollups this assembles),
[recap.md](recap.md) (builds them), [monolith_thinker.md](monolith_thinker.md).

## Problem

The context a thinker sees is assembled in pieces and glued together per-thinker:

- `bin/context` turns a trajectory into a role-assigned messages array
  (head / tail / pins) for `llm -M`.
- `thinkers/_lib/common.sh` builds the rest separately: `_build_system_prompt`
  (identity + skills), `get_goals`, `_life_context` (→ `recap --context`),
  `_recent_stream`.
- each thinker's `step` glues those together — and the monolith and responder
  glue them *differently*. That divergence is exactly where drift and bugs crept
  in (the reply-context/double-reply issues).

No single component owns the whole window, so:

- **You can't auto-size memory to the model.** "How much window for rollups =
  window − everything else" needs one component that assembles *and measures*
  the rest.
- **Ordering, token budget, truncation, KV-cache stability** are re-derived
  ad-hoc in each thinker's bash.
- **Duplication → drift → bugs.**

## Proposal: `context` owns the whole window; split *build* from *assemble*

Two different jobs, deliberately kept apart:

- **BUILD** (summarize `F` steps → a rollup, seal, cache): stays in `recap`.
  Expensive, LLM-driven, lazy/incremental, cached immutable on disk. `context`
  **reads** sealed rollups; it never builds on read (or it inherits the
  cold-start backlog problem — see tiered_memory.md).
- **ASSEMBLE** (lay out and budget the whole window for a thinker in an active
  identity): moves **into `context`**. Cheap, deterministic, per-call.

Concretely: a new mode, `context --identity` (name TBD), assembles the full
window for the active identity. Plain `context` keeps its current
trajectory-window behavior for generic `shellm` sub-runs that aren't identity
thinkers.

## The layout (stable → volatile)

`context` lays the window out most-stable-first (so the KV-cache prefix stays
warm) and most-volatile-last (so only the churny tail invalidates):

```
<core identity: Name>                        # stable — rarely changes
<context from skills>
  <kernel skills — full markdown>            # stable
  <mem>
    <core values>                            # slow-changing
    <current objectives>                     # slow-changing
    <semantically relevant memories>         # query-dependent, small
  </mem>
  <non-kernel skills — 1-line index each>    # stable-ish
</context from skills>
<tiered memory rollups>                      # grows/decays with life
  <10× coarsest … 10× finest>
</tiered memory rollups>
<recent raw steps — the "now">               # most volatile
<the thinker's task prompt / function menu>  # supplied by the caller
```

- Identity + kernel skills early → long cache hits across wakeups.
- Rollups + raw tail last → only that region invalidates as life advances.
- Centralizing this ordering is itself a reason to move it here: it's a policy
  you want stated **once**, not re-derived per thinker.

## Budget: fill the window, don't guess

Because `context` assembles the whole prefix, it can measure it and size the
memory section to whatever's left:

```
W             = the inference model's context window (tokens)
prefix        = identity + skills + mem + task prompt      (measured)
memory_budget = round(W · FRACTION) − size(prefix)         # FRACTION leaves output headroom
```

Then fill the rollup staircase + raw tail into `memory_budget`: the coarse tiers
are tiny, so spend the remainder on more tiers shown verbatim and/or a longer
raw tail. This is tiered_memory's "grow to fill the window," now computed
**automatically** because one component sees both sides of the subtraction.

Token measurement can be a cheap approximation (~4 chars/token) or a real
tokenizer call; approximation is fine for sizing headroom.

## Interface

- The thinker calls `context` in identity mode and hands it the one
  thinker-specific piece — its **task prompt** (the function menu / persona of
  the moment) — on stdin or via a flag. `context` places that last-before-now
  and owns *everything else*.
- `context` returns what the caller feeds to `llm`: the assembled system-prompt
  text (`-s`) plus the messages array (`-M`), or a single rendered block.
- Thinkers shrink to **routing + tools**; all "what the model sees" lives in one
  place.

## Why here (the tradeoff, recapped)

**Pros**
- Auto-budget to the model window — the whole point; only the layout owner can
  do it.
- Single source of truth — kills the per-thinker duplication (and its bug
  class); every thinker gets identical, correct assembly.
- KV-cache ordering stated once (stable → volatile).
- Testable in one place; matches the "context is a paging problem" framing.

**Cons / things to get right**
- **Scope creep.** `context` grows from a tiny trajectory tool into an
  identity-aware assembler — it now needs the mem/skills/kernel dirs, a
  model→window table, and a token estimator.
- **Cost profile changes.** No longer "two streaming passes": semantic mem
  search + reading many rollup blocks + skill markdowns. Still bounded, and it's
  the same work the thinkers do today — just relocated.
- **Keep build ≠ read.** `recap` builds/seals; `context` only reads. Never
  summarize on-read.
- **Two modes.** Generic `shellm` sub-runs must keep the simple trajectory-window
  behavior; the rich assembly is an explicit identity mode.

## Migration

- Leave `recap --context` building/sealing rollups (already the case).
- Add `context --identity` that assembles the layout above — moving the
  `_build_system_prompt` / `get_goals` / `_life_context` / `_recent_stream`
  logic behind it (or having `context` call those helpers).
- Repoint the monolith (and responder) to build their prompt via
  `context --identity` + their task prompt, deleting the per-thinker glue.
- Retire the divergent per-thinker assembly.

## Open questions

1. Exact interface: a `--identity` flag vs a subcommand; how the task prompt is
   passed (stdin vs `--task-file`).
2. Token estimator: chars-approx (cheap) vs a real tokenizer (accurate) — and
   whether the model→window table lives here or is shared with tiered_memory.
3. Does the responder want the *full* identity assembly or a lighter,
   chat-focused window? (latency — replies must stay fast).
4. Where the persona / `prompt.md` sits: caller-supplied task prompt vs a
   `context`-owned template.
