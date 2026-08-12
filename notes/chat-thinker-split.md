# Design: Split chat fast-path into its own thinker

## Problem
monolith/step handles both:
- (a) FAST-REPLY: chat messages → single LLM call + chat reply (low latency)
- (b) ROUTER: shellm agentic run (slow, tools, agentic loop)

Because both paths run in one thinker process, a chat message that arrives
while monolith is busy with a slow shellm job is queued (pending/) and doesn't
fire until the slow job finishes. Chat latency is blocked behind agentic work.

## Seam (confirmed)
monolith/step lines 1-30 document the two paths. The branch point is
`is_human_chat` (source=chat, from != self). When true → fast-reply block
(~lines 190-230: REPLY_MODEL, convo_json context, llm call, chat reply).
When false → router path (shellm agentic run with function menu).

## Proposed split
1. New thinker dir: `thinkers/chat/` with:
   - `step` script: only the fast-reply block (extract lines ~190-230)
   - `subscriptions.jsonl`: types=["message"] only, trigger_self=false
   - `prompt.md`: chat-reply-focused system prompt
   - REPLY_MODEL config (can use a faster model than THINK_MODEL)
2. Modify monolith:
   - Remove fast-reply block from monolith/step
   - Drop "message" from monolith subscriptions.jsonl types
   - monolith keeps: thought, action, observation, merge, idle
3. Dispatcher change: NONE — _start_dispatcher already routes by step type
   via sub_map. Two thinkers subscribing to different types just works.

## What the chat thinker needs
- REPLY_MODEL (env: CHAT_REPLY_MODEL, default THINK_MODEL or a fast model)
- Context assembly: convo_json (recent messages in the conversation)
- `chat reply` command (or whatever delivery mechanism monolith uses)
- The reply system prompt (lines ~210-217)

## What monolith keeps
- Router path (shellm agentic run)
- All non-message step types
- Idle backoff logic

## Risk / open questions
- Does anything else trigger on "message" type? (check other thinkers' subs)
- Does the fast-reply path need access to memory/retrieval? (currently it
  only uses convo_json — check if retrieval is injected)
- Pending coalescing: message steps for chat thinker should coalesce
  (last-wins) so a rapid burst of messages doesn't queue up stale replies.
  Check _fire_pending coalescing logic in dispatcher.

## Next step
Read the full fast-reply block + check other thinkers' subscriptions for
"message" type, then write the chat thinker step script.

## Multi-thinker message subscription (2026-08-08)

**Risk identified:** `message` steps currently fire FOUR thinkers:
- `monolith` — does fast-reply (chat reply) + router
- `actor` — subscribes to action,message
- `inner_monologue` — subscribes to thought,action,observation,merge,message,idle
- `retrieval` — subscribes to thought,message,observation

A dedicated `chat` thinker subscribing to `message` would run alongside these.
Need to confirm: do actor/inner_monologue/retrieval also reply to messages,
or do they just observe/log? If they only observe, the split is clean —
chat thinker handles replies, others continue their observer role.
If any also reply, there's a conflict to resolve.

## UPDATE 2026-08-08: This is a bug fix, not just a refactor

**Pre-existing double-reply bug:** Both `monolith` and `actor` subscribe to
`message` steps AND both attempt to reply:
- `monolith/step` line 7-8: fast-reply path replies immediately via `chat reply`
- `actor/step` line 5-8: "message steps addressed to this identity (reply to them)"

The dispatcher sends each message step to ALL subscribed thinkers, so both
fire on the same message. This is a race condition TODAY — two thinkers may
each emit a `chat reply` for the same incoming message.

Splitting chat into a dedicated thinker that is the SOLE replier (with both
monolith and actor dropping `message` from subscriptions) fixes this.

## CONCLUSION (2026-08-08)

Double-reply bug is CONFIRMED from source:
- monolith/step: is_human_chat branch → llm call → chat reply
- actor/step: message branch → shellm run → chat reply in first bash block
- Both subscribe to 'message' type
- Dispatcher fans out to ALL subscribers

No guard logic found that prevents double replies.

NEXT STEP: Write a proposal for gen-003 (or a direct fix) that:
1. Creates thinkers/chat/ with sole responsibility for message replies
2. Removes 'message' from both monolith and actor subscriptions
3. actor continues to handle 'action' steps only
4. monolith handles thinking/inner life (no message replies)
