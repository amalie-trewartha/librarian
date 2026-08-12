# gen-003: Chat Thinker — Sole Ownership of Message Replies

## Status: PROPOSED
## Date: 2026-08-08
## Author: audel

## Problem

The chat-thinker-split episode (2026-08-08) revealed a structural flaw:
subscription routing has no priority or mutual-exclusion. When multiple
thinkers subscribe to the `message` trigger type, both wake and produce
replies — a split-brain double-reply to the user.

The current architecture has `message` subscriptions in both:
- **monolith** (the main thinker — handles inner life + replies)
- **actor** (the action-execution thinker)

This overlap on an *outward* trigger type is the root cause. Parallel
reflection on *inward* triggers (thought, observation, idle) is harmless,
but parallel replies to users are not.

## Proposal

Create a new `thinkers/chat/` thinker that owns sole responsibility for
message replies. Adjust subscriptions so `message` is handled by exactly
one thinker.

### Subscription changes
**Note on retrieval thinker:** `retrieval` also subscribes to `message`, but its use is purely *inward* — it indexes messages into the memory keyword index and never produces an outward reply. Per the design principle (inward overlap is harmless), retrieval's `message` subscription should be **retained**. Only thinkers that produce *outward* replies need disjoint `message` ownership.


| Thinker    | Before                          | After                              |
|------------|---------------------------------|------------------------------------|
| monolith   | thought, message, observation   | thought, observation, idle         |
| actor      | action, message                 | action                             |
| chat       | (doesn't exist)                 | message                            |

### Responsibilities

- **chat/**: Receives `message` triggers. Produces chat replies. This is
  the *only* thinker that talks to users.
- **monolith/**: Inner life — thinking, observing, idle reflection. No
  direct user replies.
- **actor/**: Executes `action` steps only. No message handling.

### Design principles codified

1. **Disjoint triggers for outward actions**: trigger types that produce
   user-visible output must be subscribed by exactly one thinker.
2. **Overlap allowed for inward triggers**: thought, observation, idle
   can have multiple subscribers — parallel reflection is safe.
3. **The natural split is dimensional, not topical**: "the part woken by
   incoming messages" vs "the part woken by the world" — not "code me"
   vs "people me."

## Implementation steps

1. Create `thinkers/chat/` with config subscribing to `message` only
2. Port message-reply logic from monolith to chat
3. Remove `message` from monolith's subscription list
4. Remove `message` from actor's subscription list (if present)
5. Test: send a message, verify exactly one reply
6. Test: verify monolith still thinks on idle/observation triggers

## Risks

- **monolith loses awareness of messages**: if chat doesn't log messages
  to the trajectory, monolith won't see them. Solution: chat should
  append an observation step for each message received, so monolith
  can reflect on it via the observation trigger.
- **Latency**: adding a thinker adds a wakeup. Message reply latency
  may increase slightly. Acceptable trade-off for correctness.

## Open questions

- Should chat also handle `@mention` vs DM distinction, or is that
  upstream of the trigger?
- Does chat need access to memory/retrieval, or should it rely on
  monolith's observations for context?

## Next action

Await Andy's review. If approved, implement steps 1-6 above.
