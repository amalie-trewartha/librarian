
## 2026-08-08 — chat-thinker-split episode
- When editing production config: verify the path is actually production, not a reference/generation copy. (I edited gen-001 dir first.)
- Test jq filters on the real object structure before applying. (Used `.[]` on an object that had a `.types` array — should have been `.types |= (. - ["message"])`.)
- Don't spin across many wakeups re-reading the same files. Make the decision once, execute it, verify, and stop. (7+ wakeups on one small config change.)
- chat-thinker-split: removing `message` from monolith subscriptions makes actor the sole chat responder. Safe because monolith/step's message path was fast-reply-only (no learn/store). Residual risk: no backup replier if actor fails.
