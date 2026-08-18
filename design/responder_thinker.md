# Responder thinker (reverse-engineered)

Status: COMPLETE — thinkers/responder/{step,subscriptions.jsonl} implement it; merged via PR #31.

Related: [monolith_thinker.md](monolith_thinker.md) — its "History" section
predicted exactly this ("a dedicated low-latency `responder` for chat") as the
escape hatch if chat latency ever needed isolating. The prototype is that
escape hatch built — but with a different coordination mechanism than the doc
sketched (see Divergences).

## What it is

A dedicated, minimal **chat-reply thinker**: fire on an inbound message, reply
with a single `llm` call — no shellm agentic loop, no tools — so a reply lands
at the lowest possible latency. It's the "responder" half of the two-thinker
split (a `monolith` router for cognition + a `responder` for chat), meant to run
*alongside* the monolith.

**Subscription:** `{"types":["message"]}` — messages only. (No `trigger_self`;
it's purely reactive.)

## Step flow

1. **Guards.** Act only on `type=="message"` with `to == IDENTITY_NAME`. A
   message from us to us is a self-message → drop with an explanatory
   observation (replying would loop). Empty content → exit.
2. **Idempotency.** Scan the root trajectory: if this message's `step_id` was
   already handled — a reply stamped `reply_to == t`, a `reply_claim` with
   `trigger_step == t`, or *any* outgoing message from us to the sender appended
   after the trigger — skip. (This lets multiple responder firings, or a
   redelivered trigger, coexist without double-replying.)
3. **Claim.** Append a `reply_claim` step immediately (before composing),
   `{type:"reply_claim", trigger_step:t, source:"responder"}` — intended to tell
   the monolith router "this message is being handled, don't also reply."
4. **Compose.** One `llm` call. Context is built as a real chat: recent
   `message` steps mapped to `{role:user|assistant}` (last ~12, `-M` messages
   array), plus recent non-message steps as a short "inner life (context only)"
   block. The system prompt asks for a first-person, concise reply, forbids
   repeating an earlier reply, and allows the model to output exactly
   `NO_REPLY` when nothing needs saying.
5. **Deliver / record outcome.** On a real reply: `chat reply --reply-to <to>   <from>` and append an observation `decision:"replied"`. On `NO_REPLY`: append
   `decision:"no-reply"`. On send failure: append `decision:"reply-failed"` so
   the monolith can pick it up.

It reuses the monolith's chat conventions verbatim — the self-message guard, the
`reply_to` stamp, the `NO_REPLY` option, the `decision:` field on observations —
so it's clearly written to interoperate with the current monolith, not replace
its plumbing wholesale.

## The `reply_claim` protocol

`reply_claim` is a **new trajectory step type** the responder invents to
coordinate with the monolith: stake a claim the instant a message is picked up,
so that during the window while the responder is composing (an `llm` call), the
monolith router — which also wakes on that message — sees the claim and stands
down instead of composing a duplicate reply.

## The gap: coordination is one-sided

**The monolith does not honor `reply_claim`.** Verified: `reply_claim` appears
nowhere in `thinkers/monolith/step`, and it's not in `design/trajectory_spec.md`.
The monolith's own idempotency check keys on a stamped `reply_to` reply or an
outgoing message appended after the trigger — **not** on a `reply_claim`.

Consequences:

- The claim only protects the responder from *itself* (a second responder
  firing / a redelivered trigger), which its step already handles positionally
  anyway. It does **not** currently stop the monolith.
- So the monolith only defers once the responder's *actual reply* lands (stamped
  `reply_to`, or positionally after the trigger). In the window between claim
  and reply-sent, the monolith's fast-reply path could still compose its own
  reply → the double-reply the claim was meant to prevent.
- As written, running monolith + responder together is a **race**, not a clean
  split. Making it correct needs one of: (a) teach the monolith's idempotency
  check to treat a `reply_claim` for a trigger as "already handled"; or (b) run
  the monolith with its fast-reply path disabled so chat is *only* the
  responder's job.

## Divergences from the monolith doc's sketch

The `monolith_thinker.md` History imagined the split using a new **`say`** step
for monolith→human messages. The prototype instead:

- introduces **`reply_claim`** (responder→coordination), not `say`;
- keeps replies flowing through the existing `chat reply` + `reply_to` machinery
  rather than a new outbound type.

So it's a different, lighter coordination design than the doc predicted — worked
out in code, not written down first.

## Housekeeping already handled

- `reply_claim` is **auto-excluded from context**: it's in neither
  `_recent_stream`'s type allowlist nor recap's, so it won't pollute prompts or
  rollups. (Good — but that's by omission, not intent; a comment/test should
  pin it.)

## Open questions / before adopting

1. **Honor the claim, or split the duty.** Decide (a) vs (b) above; without one,
   monolith + responder can double-reply.
2. **Claim without reply.** If the responder claims then dies/fails before
   sending, the `reply_claim` persists — does anything retry, or is the message
   silently dropped? (The failure path appends a `reply-failed` observation the
   monolith could act on, but nothing wires that to a retry yet.)
3. **Document the step type.** `reply_claim` needs a `trajectory_spec.md` entry
   (and ideally `say` too if monolith-initiated messages are ever wanted).
4. **Model default.** `REPLY_MODEL` defaults to the full `THINK_MODEL`; the whole
   point of a responder is latency, so a fast model default is probably wanted.
5. **Provenance.** Commit it (with this note) or discard it — an untracked,
   unattributed thinker in the tree is a maintenance hazard.
