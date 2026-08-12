
## 2026-08-08 — Subscription routing has no priority or mutual-exclusion

From the chat-thinker-split episode:

The architecture's only routing mechanism is subscription by trigger type.
There is no priority, no "first responder wins," no mutual-exclusion. If two
thinkers subscribe to the same trigger type, both wake.

Design principle discovered:
- For trigger types that produce an *outward* action (message → chat reply),
  subscriptions must be DISJOINT across thinkers. Otherwise you get a split
  brain (double replies).
- For trigger types that are purely *inward* (thought, observation, idle),
  overlap is fine — parallel reflection is harmless and can even be useful.

The functional seam I cut was not topical ("code me" vs "people me") but
dimensional: "the part woken by incoming messages" vs "the part woken by the
world." That's the natural way to split a mind in this architecture.
