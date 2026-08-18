# Monolith thinker

Status: implemented (runs solo as the mind), with two revisions since this
draft: (1) chat moved to a dedicated `responder` thinker — the monolith no
longer subscribes to `message` or runs the fast-reply path described below; an
inbound chat reaches it as the responder's observation. (2) Loop pacing is now
the non-blocking scheduled-wake backoff in monolith_backoff.md
(`trigger_self:false` + a timer), not the in-loop `trigger_self:true` sleep
described here.
Replaces (when enabled): the multi-thinker roster (inner_monologue, actor,
goals_manager, learning, mind_wanderer, values_manager) with a single thinker,
`monolith`, that runs solo and handles every function.

## Motivation

The current roster runs six thinkers that mostly share one shape: wake on new
steps, read the recent stream, decide whether to do their one job, maybe write
a step. Coordination between them is emergent and occasionally pathological
(double replies, mimicked conventions, loops).

But most thinker "jobs" are alternatives, not parallel processes. At any given
wakeup the mind should mostly do ONE of: advance the monologue, execute an
action, reply to a message, store a lesson, recall a memory, tend goals/values,
or rest. That is a routing decision, not a concurrency problem — so collapse
the whole roster into one thinker that routes between functions each wakeup.

Keep it simple: one process, one root trajectory, one decision per wakeup.

## `monolith` — the one thinker

**Subscriptions**

```json
{"types":["thought","action","observation","merge","message","idle"],"trigger_self":true}
```

Same perpetual-loop pattern as today's inner_monologue: every step it (or
anything external, like an incoming message) appends re-triggers it, so it must
ALWAYS append at least one step per wakeup (see Loop liveness).

**Step flow (one wakeup)**

1. Read trigger step from stdin; stamp its `step_id` as `trigger_step` on
   whatever we append.
2. Build compact recent stream (`_recent_stream`, ~20-30 steps) + system
   prompt + goals, as thinkers do today.
3. ONE shellm agentic run. The prompt presents a function menu; the model's
   first job is to pick exactly one function for this wakeup, then carry it
   out in the same run. Routing is just the first tokens of the run — no
   separate classifier call, no second process.
4. Append the resulting step(s) and exit. The dispatcher re-fires on the
   append.

**Function menu** (the whole old roster, now including chat)

| function | was | behavior in-run |
|----------|-----|-----------------|
| `reply`  | actor (message path) | reply IMMEDIATELY: one `chat reply <from> "<text>"`, no thinking step, no tools |
| `act`    | actor (action path) | do the work with tools, append `observation` |
| `think`  | inner_monologue | append one `thought` step that advances the stream |
| `learn`  | learning | extract lesson from recent action/observation pairs → `mem add`, note as thought |
| `recall` | mind_wanderer | `mem search` for associative memories → surface 1-3 as thoughts |
| `goals`  | goals_manager | store emerging intentions / redirect drift via `mem` + thought |
| `values` | values_manager | same shape as goals, for values/beliefs |
| `idle`   | idle | append an `idle` step; nothing worth doing |

Everything happens inside the single agentic run: the old
inner_monologue→actor handoff (emit an `action:` line, wait for the actor to
be dispatched) collapses into one run — decide, do the work with tools, append
the observation. Likewise a reply is just the model choosing `reply` and
calling `chat reply` in its first bash block. The trajectory stays legible and
a whole dispatch round-trip disappears.

## Chat within the monolith

Chat is not a separate thinker — the monolith has `chat` in its `--bin`
allowlist and replies inline. Two rules carry over from today's actor so the
one loop stays well-behaved:

- **Reply immediately, no thinking, no tools.** When the `reply` route is
  chosen, the ONLY thing that run does is send the reply: a single
  `chat reply <from> "<text>"` in the first bash block, composed directly from
  the recent stream. No preceding `thought` step, no `mem`/web/file lookups, no
  multi-step agentic loop — the model answers with what it already knows so the
  human gets a response in the lowest possible latency the single-process
  design allows. If the message genuinely needs work (research, a file, a
  computation), reply first with what we know and acknowledge the follow-up;
  the work then happens on a LATER wakeup via the `act` route, which records an
  observation and can `reply` again with the result. Reply and act are separate
  routes precisely so that answering never waits on doing.
- **Exactly one reply per message.** `chat reply` is synchronous — exit 0 means
  it landed; never re-send a variant. New messages that arrive mid-run are NOT
  answered in this run; the dispatcher re-triggers us for them separately.

  This rule needs mechanical support, not just prompt text: the fast-reply's
  bookkeeping observation re-wakes the router (trigger_self), which then sees
  the conversation as the freshest thing in context and — across every model
  tried — tends to reply AGAIN with a paraphrase (the double-reply loop of
  2026-08-03). The support is layered, separating the FACT "this message has
  been answered" (machinery) from the JUDGMENT "does this message need a
  reply" (model):

  1. **The fact lives in the log.** `chat reply` stamps `reply_to` at the
     transport — inferred (latest unanswered inbound from the recipient)
     when the caller doesn't pass `--reply-to` — so a reply is a matchable
     fact no matter which path (fast-reply or an agentic run typing `chat
     reply`) sent it. See design/trajectory_spec.md.
  2. **The fast-reply's idempotency check trusts position as a net.** A
     redelivered or late-queued message trigger (e.g. one that waited FIFO
     behind a busy agentic run whose run answered the message meanwhile —
     the reworded double-reply of 2026-08-03) is skipped when a stamped
     reply matches the trigger exactly OR any outgoing message to that
     sender was appended after the trigger step.
  3. **The router gets a deterministic reply-state signal** computed from
     the recent stream: "answered" (a re-reply is noise; only new work
     results justify another message), "declined" (the fast-reply model
     chose NO_REPLY — don't reply unless something changed), or
     "unanswered" (the fast-reply may have failed — cover it).
  4. **The judgment belongs to the model.** The fast-reply prompt may output
     `NO_REPLY` instead of a message when the newest message is already
     answered, is a bare acknowledgment, or a reply would only repeat an
     earlier one. The decline is recorded as an observation stamped
     `decision:"no-reply"` (that's what feeds state 3), so staying quiet is
     a visible decision in the mind, not a silent drop.

  The fast-reply prompt likewise answers fully when it can, acknowledging-
  and-deferring ONLY when tool work is genuinely required — otherwise every
  simple question produces a contentless ack followed by the router's real
  answer.

**Self-loop guard.** `chat` stamps `source:"chat"` on BOTH incoming and
outgoing messages, so an outgoing reply is itself a `message` step that would
re-trigger us. Guard exactly as the actor does today: only treat a `message`
trigger as something to reply to when `to == IDENTITY_NAME`. Our own replies
(`from == IDENTITY_NAME`) are context, not triggers.

Latency note: replies no longer share the agentic-run path — the implemented
step has a dedicated FAST-REPLY path that short-circuits before the router
when the trigger is a message addressed to us: one `llm` call (optionally a
faster `MONOLITH_REPLY_MODEL`), no tools, straight to `chat reply`. The
router's `reply`/`act` routes remain for follow-ups that deliver results of
real work. The single process is kept; only the first response is fast-pathed.

## Routing hints, not rules

The step script MAY prepend cheap deterministic signals to the prompt (e.g.
"there is an unread message addressed to you in the tail", "an unexecuted
action step is pending", "last 3 steps are all thoughts", "an action/
observation pair just completed") but the choice stays with the model. No
hardcoded priority ladder — that is how we get stuck loops. The one soft
convention worth stating in the prompt: an unanswered message to us should
almost always win the routing decision.

## Shared root trajectory

Nothing new needed: the monolith writes through `traj append` against
`TRAJ_ID` (the root traj, per PR #14's inheritance work), and its shellm runs
pass `--traj "$TRAJ_ID"`. The single root trajectory remains the one source of
truth; incoming messages, replies, thoughts, actions, and observations all land
in the same stream the monolith reads back each wakeup.

## Loop liveness & pacing

- The monolith must append ≥1 step per wakeup even on LLM failure (placeholder
  thought + brief sleep, exactly like inner_monologue today).
- The perpetual loop is NOT guaranteed by this step script alone. Several
  paths deliberately consume a trigger without appending anything (own
  outgoing message re-trigger, already-replied skip, empty content), and an
  agentic run whose only mind-step is an outgoing message leaves such a
  consumed re-trigger as the last link — no wake source remains (the
  2026-08-04 03:17 UTC stall). The dispatcher's liveness watchdog (see
  THINKERS_spec.md) is the backstop: after `watchdog_secs` of quiet it
  synthesizes an idle trigger, which lands in the normal idle-backoff path
  here. Bare `exit 0` on a do-nothing wakeup is therefore correct — liveness
  is the dispatcher's job; the fast paths only owe latency.
- Idle backoff: when the TRIGGERING step is `idle` (i.e. we idled and are now
  re-fired by our own idle step), sleep `MONOLITH_IDLE_BACKOFF` seconds
  (default 5, doubling to a cap of ~60) before running; any non-idle trigger
  (a message, an external action) resets the backoff. Keeps the solo loop from
  burning tokens at rest while staying instantly responsive to real input.
- The backoff sleep is pre-emptible: it runs in 1s slices, each checking the
  dispatcher's pending dir for a queued message/action trigger (sleeping
  counts as busy, so the dispatcher queues rather than dispatches). If one is
  waiting the step exits without running the router — the dispatcher fires
  the queued trigger on its next tick and the fast-reply path handles it.
  Without this, a message arriving mid-rest waited out the remaining sleep
  plus a full router run before its reply. Pre-empt skips the doubling; the
  message trigger resets the backoff anyway.
- Concurrency: solo by definition — the dispatcher serializes per-thinker, so
  at most one monolith run at a time. This also means a long agentic `act` run
  blocks the next wakeup until it finishes; acceptable for a single-mind model.

## Migration

- Old thinkers stay on disk in `thinkers/`; this roster is opt-in by installing
  only `monolith/` into an identity's thinkers dir.
- Dispatcher changes: none required. Subscriptions, `trigger_self`, and `idle`
  are all existing mechanisms.
- New files: `thinkers/monolith/{step,prompt.md,subscriptions.jsonl}`.

## History

An earlier draft of this doc proposed TWO thinkers: a `cortex` router that did
everything except chat, plus a dedicated low-latency `responder` for chat (with
a new `say` step type for monolith-initiated messages). We simplified to a
single `monolith` that also chats, accepting slightly higher reply latency in
exchange for one process and no new step types. The split remains the natural
escape hatch if chat latency ever needs to be isolated.

## Open questions

1. Do `learn`/`goals`/`values` deserve a periodic nudge (e.g. the prompt hints
   toward them every N wakeups) or is model judgment enough?
2. Group chats / multiple correspondents: the reply guard keys on a single
   `IDENTITY_NAME`; multi-party threads need more thought.
