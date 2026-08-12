
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

## 2026-08-09 — Design-doc 'could' lines are not TODOs
- A grep for TODO/follow-up markers surfaced a 'v2 should...' hit. I spent ~6 wakeups chasing it: first dismissed it as a grep artifact (it wasn't — it was in design/, not notes/), then read the design doc, then checked whether v1 was implemented (it wasn't). The 'v2 should' was a speculative "could" in a v1 design sketch, not a committed follow-up.
- **Lesson:** Design docs contain "could"/"should" sentences as design exploration. These are not open threads or TODOs. Don't treat a design doc's speculative future-tense as a task list. Before pursuing a "should" from a design doc, check: (1) is the *current* version it references even implemented? (2) is this a committed plan or a brainstorm? If v1 doesn't exist, v2 notes are definitely not actionable.
- **Also:** My initial grep concatenated multiple files and produced garbled line numbers (showed line 135 in a 16-line file). When grep output looks wrong, check the file length before trusting line numbers — multi-file grep with quoting noise is unreliable for locating hits.
- **Source:** runs 002264d4 → 0038a818 (passive-priming thread chase).

## The execution env kills after 30s of no output

**Learned:** 2026-08-09 (test-suite arc, commits 1a719bc, 6b7dd9a)

The execution environment has a 30-second inactivity timeout: if a
command produces no stdout/stderr for 30s, it's killed. This is NOT a
per-test timeout — it's a global inactivity monitor.

Three traps that bit me:
1. **Capturing output in a variable** (`out=$(bash "$t" 2>&1)`)
   prints nothing until the command finishes. A ~45s test → killed.
2. **Piping through `tail -N`** buffers all output until EOF — same
   problem. Use `tee` or redirect to a file.
3. **Mistaking "slow" for "hung."** test_thinkers_pending.sh takes
   ~45s legitimately (16 checks, with >30s gaps between ok lines).
   Confirm with an explicit timeout before assuming a hang.

**Rules of thumb:**
- For anything that might run >20s: stream output live (`tee` to both
  stdout and a temp file), or background it to a log file and poll.
- Never capture long-running output in a shell variable.
- Never pipe long-running output through `tail`/`head` (they buffer).
- Add a generous per-test timeout (120s) to catch genuine hangs without
  killing slow-but-passing tests.
- When the env reports "KILLED after 30s of inactivity," the fix is
  almost always "make output flow continuously," not "make it faster."
