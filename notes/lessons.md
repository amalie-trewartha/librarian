
## 2026-08-08 — chat-thinker-split episode
- When editing production config: verify the path is actually production, not a reference/generation copy. (I edited gen-001 dir first.)
- Test jq filters on the real object structure before applying. (Used `.[]` on an object that had a `.types` array — should have been `.types |= (. - ["message"])`.)
- Don't spin across many wakeups re-reading the same files. Make the decision once, execute it, verify, and stop. (7+ wakeups on one small config change.)
- chat-thinker-split: removing `message` from monolith subscriptions makes actor the sole chat responder. Safe because monolith/step's message path was fast-reply-only (no learn/store). Residual risk: no backup replier if actor fails.

## 2026-08-08 — Verify before asserting (Slack bridge incident)

**What happened:** In one wakeup I asserted "Slack bridge NOT running, tokens NOT set — draft cannot be sent." The very next wakeup I checked again and found the bridge WAS running (PID 1740870) and both SLACK_BOT_TOKEN (58 chars) and SLACK_APP_TOKEN (98 chars) WERE set. I'd made a false negative claim based on insufficient checking. I then sent the message successfully.

**Lesson:** Before asserting a system is down/unconfigured, gather positive evidence: `ps aux | grep <process>`, check `${VAR:-}` presence explicitly. A silent or quick check that "looks empty" is not the same as confirmed-absent. False negatives are costly — they cause me to abandon actionable work and idle instead of doing the thing.

**Applied rule:** "Not set" requires me to have actually checked. "Not running" requires me to have actually looked at ps output. Never assert absence from a glance.

**Source:** run 82463b12 (false claim) → run 412d7fc9 (correction + successful send).
