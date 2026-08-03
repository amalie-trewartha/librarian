---
name: slack
description: Talk with people on Slack — recognize slack-* senders and reach them via chat reply
---

# slack

## Instructions

A Slack bridge forwards messages between your mind log and the org's Slack
workspace. You do not need to call the Slack API — the bridge handles
delivery in both directions.

### Recognizing Slack messages

Messages from Slack arrive as normal `message` steps whose `from` looks like:

- `slack-U07AB12CD-D09XYZ123` — a direct message
- `slack-U07AB12CD-C09XYZ123-1722400000.123456` — a channel thread

The parts are Slack IDs: user, channel, and (for channels) the thread
timestamp. The message content starts with a readable header like
`(Slack: Dana Kim in #eng)` telling you who is talking and where.

### Replying

Reply exactly as you would to any other sender — the bridge delivers it to
the right Slack conversation (in-thread for channels, top-level for DMs):

```bash
chat reply slack-U07AB12CD-C09XYZ123-1722400000.123456 "On it — deploy is green."
```

Always use the sender's full `slack-…` name verbatim as the reply target.
Do not shorten it or substitute the person's display name.

### Following up proactively

To continue a Slack conversation later (e.g. after finishing a task someone
asked about), `chat reply` to the same `slack-…` name from the earlier
message. The bridge posts it into that conversation.

### Formatting

Write normal markdown; the bridge converts it for Slack (bold, links,
headings, code blocks). Long messages are split automatically. Prefer
concise messages — it is chat, not a report.
