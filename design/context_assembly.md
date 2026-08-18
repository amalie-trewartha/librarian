# Context assembly — the microharness window

Status: PARTIAL — the identity+skills+`recap --context` plumbing exists and is composed in the thinker glue, but the core `bin/context` porcelain-pipe refactor and `traj messages` are NOT done (bin/context is still the old messages-array policy layer).
Relates to: [tiered_memory.md](tiered_memory.md) (the rollups this fits),
[recap.md](recap.md) (builds them, and does the fitting),
[monolith_thinker.md](monolith_thinker.md), and the skill system.

## The clunk we're removing

An earlier draft gave `context` a `--identity` mode: one tool that in one mode
sliced a trajectory into a messages array, and in another assembled the whole
identity window. Two personalities in one program, chosen by a flag — a smell.
The fix isn't a better flag. It's to stop overloading one tool: split by
altitude and compose.

## Microharness

Keep the harness tiny. `context` should depend on the **minimal** set of things
and know nothing about the rest. That set is exactly three:

1. **Core identity** — the name and the few things that define who this mind is
   (`identity prompt`).
2. **The skill system's prompt** — whatever the installed skills contribute
   (`skills prompt`).
3. **Recap** — the tiered memory, which is also the budget-fitter (below).

In particular, **`context` does not know about `mem`.** `mem` is a skill. Core
values, current objectives, semantically-relevant memories, the kernel-skill
markdowns, the one-line index of non-kernel skills — all of that is the *skill
system's* job, emitted by `skills prompt`. If a mind needs a capability, it's a
skill, and the skill contributes its slice of the prompt. The harness never
grows a dependency per capability; it just includes "whatever skills say." That
is the microharness move: a small core plus pluggable servers (skills), not a
kernel that imports every subsystem.

## Plumbing vs porcelain

The pieces are plumbing that already (mostly) exists as standalone commands:

- `identity prompt` — core identity.
- `skills prompt` — the skill system's contribution (including `mem`).
- `recap --context` — tiered rollups + raw tail, and the fitter.

The composition — the one line that wires them into "the window a thinker sees"
— is porcelain, and a pipeline is a program. **That program is `context`.**

And the thing `context` does *today* (trajectory → role-tagged messages array,
head/tail/pins) is a lower, different job — it belongs to `traj`. Move it to
`traj messages`. Then:

- `traj messages` — plumbing: a trajectory → a messages array, for generic
  `shellm` sub-runs.
- `context` — porcelain: the assembled identity window, which is just a pipe.

No modes anywhere. `traj` slices trajectories; `context` means "the context this
mind sees." The word finally means what it says.

## The pipe

```sh
{ identity prompt        # core identity
  skills prompt          # everything skills contribute — mem, values, objectives,
                         # semantic memories, kernel markdowns, non-kernel index
} | recap --context --window "$W"
```

`context` (the porcelain) is essentially those four lines. `recap --context` is
the **terminal fitter**: it passes the prefix through, measures it, and appends
the rollup staircase + recent raw tail sized to `W − prefix`. The budget isn't
computed by a coordinator that owns everything — it falls out of the pipe,
because the one elastic stage is last and can read everything before it.

## Layout (stable → volatile)

The pipe order keeps the KV-cache prefix warm: stable identity + skills first,
the growing/decaying memory + raw tail last.

```
<core identity: Name>                         # stable
<skills prompt>                               # skills own this whole block:
  <kernel skills — full markdown>             #   stable
  <mem>  values · objectives · semantic hits  #   slow / query-dependent (a skill!)
  <non-kernel skills — 1-line index>          #   stable-ish
<tiered rollups: coarsest … finest>           # grows/decays with life  (recap)
<recent raw steps — the "now">                # most volatile           (recap)
```

This matches the hand-drawn layout from our discussion — `mem` was already
*inside* the skills block. That nesting is the point: `mem` is a skill, so it
lives in the skill contribution, not as a `context` dependency.

## Budget

```
W      = the model's context window (tokens)
prefix = identity + skills            (measured — whatever arrived on stdin)
memory = round(W · FRACTION) − size(prefix)
```

`recap --context` fills `memory` with the staircase + tail (coarse tiers are
tiny; spend the rest on more tiers verbatim and/or a longer raw tail). Token
size is a cheap char approximation unless a tokenizer is worth it.

## The maximal-microharness option: recap as a skill

If we're strict, even `recap` is a capability — so make it a **skill**, installed
into a mind like any other. Then `context`'s dependency set shrinks to two —
**identity + skills** — and the pipe is just:

```sh
identity prompt | skills prompt
```

…where one installed skill (recap) is the **terminal fitter**: it must be
ordered last, read the accumulated prefix, and fill `W − prefix`. That's the
cleanest microharness — the harness knows only "core identity" and "run the
skills." The cost: "skills" is no longer a flat bag of independent emitters —
one of them is privileged (it reads everyone else's output and owns the budget),
so the skill system needs an ordering/terminal convention.

Decision deferred; both shapes keep `context` free of `mem` and free of any
per-capability dependency. Start with recap as a tool `context` calls (three
deps); promote it to a terminal skill (two deps) once the skill system grows a
terminal convention anyway.

## Interchange format

The stages must pipe cleanly, so pick one stream. Simplest: **plain text** —
each emitter writes its slice as text, the recent chat tail is rendered as text
("Andy: … / you: …"), and role-tagging (a messages array) stays the concern of
whoever needs it (the responder can call `traj messages` for its fast chat
window). Fewest moving parts. If a thinker genuinely needs roles, the whole
window becomes a messages stream with the stable sections as one system message
— uniform, just JSON instead of text.

## Migration

- Move `context`'s current behavior to `traj messages` (trajectory → messages);
  repoint `shellm` sub-runs and docs.
- `context` becomes the porcelain pipe:
  `{ identity prompt; skills prompt; } | recap --context --window "$W"`.
- Ensure `skills prompt` emits the `mem` block (values / objectives / semantic)
  — that's a skill-system concern, not `context`'s.
- Teach `recap --context` to read a prefix on stdin and fit to `--window`.
- Repoint thinkers to run `context`; delete the per-thinker
  `_build_system_prompt` / `_recent_stream` / `_life_context` glue.

## Open questions

1. `recap`: a tool `context` calls, or a terminal skill (maximal microharness)?
   Decide when the skill system gets a terminal/ordering convention.
2. Token estimator: char-approx vs a real tokenizer call.
3. Does the responder want the full window, or a lighter chat window (latency)?
4. Interchange: commit to plain text, or messages-array everywhere?
