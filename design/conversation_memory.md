# Conversation memory for the responder

Status: PROPOSED, 2026-09-02. Nothing here is built yet.

Related: [responder_thinker.md](responder_thinker.md) describes the thinker
this plan changes. [monolith_thinker.md](monolith_thinker.md) and
[monolith_run_health.md](monolith_run_health.md) cover the recent stream
filter the monolith shares with it. [tiered_memory.md](tiered_memory.md) is
the long term memory the monolith has and the responder does not.

## The problem

The agent forgets a conversation within minutes. On 2026-09-01 Andy sent
"sure!" to his identity cleo about three hours after cleo had asked him a
question. Cleo replied "I'll check the last few messages so I know what
you're saying yes to." Cleo had no context for the conversation, and it also
had no way to check anything, because the responder runs without tools.

The same thing happens on Audel every day. The examples below are real
replies Audel sent after a gap of one to six hours since the previous
exchange with that person.

- Andy asked how the Slack and Telegram bridge work was going. Audel had
  been doing that work. Audel replied "Honestly nothing recent from me, I've
  been idle."
- Andy said an SVG image was not rendering in Slack. Audel had sent that
  image four hours earlier. Audel replied "Ah, Slack ate it. Is it an image
  that never showed up?"
- Andy said "great! can you paste it into the top level of this channel?"
  three hours after Audel reviewed a launch draft for him. No reply was
  recorded at all.

## Why it happens

The responder builds the chat history from the recent stream. The function
`_recent_stream` in `thinkers/_lib/common.sh` takes the last 5,000 raw lines
of the trajectory, keeps eight step types (thought, action, observation,
message, idle, merge, final, reasoning), and returns the last 30 of them
(`THINK_CONTEXT_TAIL`, 20 by default and 30 under the dispatcher). The
responder then keeps only the messages between the identity and the sender,
capped at 12. There is no time window, no tiered memory, and no memory
lookup.

The window is measured in steps, not time, so conversational memory shrinks
whenever the mind is busy. On Audel the 30 steps before an inbound message
are on average 50 percent `reasoning` steps, 15 percent monolith `idle`
steps, 8 percent `final` steps, and 14 percent messages. Each monolith run
under Grok writes about 5.6 reasoning steps plus one final, so three or four
quiet wakes push every message out of the window. The reasoning and final
types were added to the filter on 2026-07-07, before the responder existed.
Nobody chose them for a chat context.

Two other parts of the design make it worse.

- The Slack bridge encodes the sender as user, channel, and thread
  timestamp. The same person is a different `from` in every channel thread,
  so the responder never sees a person's messages from another thread.
  Direct messages, the phone chat, and Telegram use stable names.
- The responder has no tools. When it says "I'm on it", nothing is
  obligated to follow. The monolith only sees an observation reading
  "Replied to Andy: I'll check...", and its prompt tells it never to reply.

The bridges are not the cause. Slack, Telegram, and the web chat all append
a plain message step, and the responder reads the same log for all of them.

## Measurements

The responder does not log its prompt, so the numbers below come from a
reconstruction. I took the last 60,000 raw lines of Audel's trajectory,
which cover 17 days and 402 real inbound messages, and re-ran the
responder's exact selection logic over them. For each inbound message I
counted how many earlier messages with that sender would have been in its
window. Six real cases in the one to six hour row were checked by hand
against the replies Audel sent, and all six matched.

The first table is a failure rate. Each row groups inbound messages by how
long it had been since the previous message exchanged with that sender. Each
percentage is the share of those messages where the responder had no earlier
message with that person in its prompt at all, so it was answering with no
memory of the conversation. 0% is the good outcome and means every message
in that row had at least one earlier message available. 100% means the
responder had nothing for every message in that row. The three percentage
columns are the same reconstruction run with three different ways of
building the context.

| Gap since last exchange | Inbound messages | Forgot, with today's filter | Forgot, if reasoning, final, and idle steps are dropped | Forgot, with a messages only 7 day window |
|---|---|---|---|---|
| under 2 min | 162 | 0% | 0% | 0% |
| 2 to 15 min | 107 | 7% | 0% | 0% |
| 15 to 60 min | 30 | 80% | 13% | 0% |
| 1 to 6 hours | 36 | 100% | 36% | 0% |
| 6 to 48 hours | 19 | 100% | 68% | 0% |

The second table shows how much history was available in the typical case,
as the median number of earlier messages with that person in the prompt. The
responder caps the conversation at 12 messages, so 12 is the most it can
have.

| Gap since last exchange | Today's filter | Reasoning, final, and idle dropped | Messages only 7 day window |
|---|---|---|---|
| under 2 min | 3 | 5 | 12 |
| 2 to 15 min | 4 | 12 | 12 |
| 15 to 60 min | 0 | 7 | 12 |
| 1 to 6 hours | 0 | 2.5 | 12 |
| 6 to 48 hours | 0 | 0 | 12 |

Read together, the tables say that today the responder has a few messages
of history only while a conversation is actively going, and nothing once
the person steps away for more than 15 minutes. Dropping the noisy step
types helps but still loses the conversation within a few hours. A messages
only history with a time window gives the responder the full 12 messages in
every case measured. Another way to state the same thing is that a reply
Audel sends stays visible to the responder for a median of 16 minutes with
today's filter and 105 minutes with the noisy types dropped, while with the
messages only window it stays visible for the whole 7 days.

The read cost was measured on the box on 2026-09-02. The trajectory was
1,322 MB and 107,637 lines.

| Read strategy | Data read | Wall time |
|---|---|---|
| Today, tail 5,000 lines then jq | 62 MB | 1.3 s |
| Widen the tail to 25,000 lines for a 7 day window | 270 MB | 4.9 s |
| grep for message lines over the whole file, page cached | 1,322 MB | 0.6 s |
| A messages only index, all 1,716 messages ever | 1.3 MB | milliseconds |

Widening the tail is the wrong fix. It repeats the 2026-08-11 context build
bottleneck and gets slower as the mind writes more. The grep is fast only
while the file is in the page cache, which the 2026-08-13 memory incident
showed is not dependable. The index is the answer.

## The plan

The work is six parts. Parts 1 to 3 fix the forgetting. Parts 4 and 5
improve on it. Part 6 makes the problem visible so it cannot return quietly.
Each part can ship on its own.

### Part 1. Messages only history from a derived index

Add `chat history --with <person> [--since <duration>] [-n N]` to
`bin/chat`. It reads from an index file, `messages.jsonl`, kept next to the
trajectory, plus a byte offset file. The trajectory stays the only source of
truth. The index is derived, rebuildable, and disposable.

The index maintains itself on read, so nothing that writes message steps has
to change.

- On each call, `chat history` reads the trajectory from the saved byte
  offset to the end of the file, appends any message lines it finds to the
  index, and saves the new offset. The trajectory is append only, so the
  offset is stable and the new bytes are usually a few MB.
- If the index or offset file is missing, or the trajectory header step no
  longer matches the one recorded in the index, it rebuilds from a full
  scan. On Audel that is about 10 seconds, once.
- Two responders racing can append duplicate lines. Reads deduplicate by
  step id, so duplicates are harmless.

The responder then calls `chat history --with <person> --since 7d -n 20` in
place of the message filter over `_recent_stream`. The inner life excerpt
(the last 8 non message steps) stays as it is until Part 3 changes the
filter.

For agents we do not control, the first responder call after the code
update builds the index and every call after that takes milliseconds. A
stale or corrupt index can only cost a rebuild, never a wrong answer. The
index also catches messages Audel appends with raw `traj append`, which a
hook inside `chat send` would miss.

Files touched: `bin/chat`, `thinkers/responder/step`, a new test under
`tests/`.

### Part 2. Person identity separate from routing identity

The `from` field stays the routing name, because the bridges need it to
deliver the reply. A new helper, `person_key`, maps a routing name to a
stable person key with no configuration.

| Routing name | Person key |
|---|---|
| slack-U0614H65RN3-C0BMVH6LM4K-1787508187.726149 | slack:U0614H65RN3 |
| slack-U0614H65RN3-D0BNW58GP5W | slack:U0614H65RN3 |
| telegram-8525624593-8525624593 | telegram:8525624593 |
| pwa-andy | pwa:andy |
| Andy | Andy |

`chat history --with` accepts either a routing name or a person key and
groups by person key. The responder passes the trigger's `from`, gets the
whole person's history back, and still replies to the trigger's `from`.
Since 2026-08-16 Audel has had 52 messages from one Slack user across 14
threads, and today each thread starts from nothing.

Linking the same human across channels is a second layer. The person
memory file from Part 4 gets an `aliases` list in its frontmatter, and
`chat history` merges every key listed there. The list can be filled three
ways, and unlinked aliases fall back to the first layer.

- The Slack bridge already puts the display name in the inbound header,
  e.g. "Andy Konwinski in #headlong-bot". Stamping a `display_name` field on
  the message step gives a cheap link to a phone chat name like pwa-andy.
- The agent learns it. When someone says "this is Andy from Slack" on the
  phone chat, the monolith's `learn` function adds the alias.
- For Audel, Nick can write the aliases by hand.

Files touched: a helper in `bin/chat` or `thinkers/_lib/common.sh`, the
Slack bridge for `display_name`, `thinkers/responder/step`.

### Part 3. A cleaner recent stream

Change `_recent_stream` so the responder's inner life excerpt and the
monolith's recent stream stop drowning in run scaffolding. The change has
three pieces.

- Drop `reasoning` steps. They are the model's prose between bash blocks
  during a shellm run, about 5.6 per run. Keep `final`, which is one per run
  and states what the run concluded, so the monolith still sees what its
  previous runs decided.
- Collapse a run of consecutive `idle` steps into one synthetic line with a
  count and duration, e.g. "idle x22 over 2h10m". Idle streaks are how the
  monolith knows time has passed, so they should stay visible but take one
  line, not 22.
- Add `error` steps to the filter, collapsed the same way. Today the mind
  never sees its own failed runs, which is already on the open items list.

The monolith is the only other caller. Its pacing and work probe read the
raw tail directly, so backoff is unaffected. Two of its routing hints will
fire differently. The "last three steps are all thoughts" hint will fire
more often because reasoning and idle lines no longer split up thought runs,
and the "last step is an action with no observation" hint is unchanged. The
monolith's prompt shrinks by roughly 22,000 characters per wake.

This part ships only after Experiment B below passes.

Files touched: `thinkers/_lib/common.sh`, `tests/`.

### Part 4. A rolling summary of each person

Give the responder a short summary of who it is talking to. The summary
lives in `memories/` as one file per person key with `type: person` in the
frontmatter. That reuses `mem` as it is, shows on the dash memories page,
and lets the monolith's recall and learn functions read and edit it with no
new tooling.

The responder writes it. After a reply is sent, the responder starts a
background `llm` call on a cheap model (`RECAP_MAP_MODEL`, the same model
the recap rollups use) that rewrites the person file from the previous
summary plus the last few exchanges. The call runs after the send, so the
human sees no extra latency, and it happens on every reply rather than
depending on the monolith choosing to do it.

The responder reads it. The system prompt gets a block, "What you know about
this person", above the conversation. The monolith gets the same file
through its normal recall.

I considered extending `recap` instead. It rolls up by trajectory position,
and per person threads are too sparse for that to fit.

Files touched: `thinkers/responder/step`, `bin/mem` only if the person type
needs anything new.

### Part 5. Deferrals that the monolith must pick up

When the responder decides it cannot answer without doing work, it says
"I'm on it" today and appends nothing that binds anyone. Change it so that
in that case it appends an `action` step describing the work, e.g. "Andy
asked whether the bridge work is done. Check and report back." The monolith
already has a routing hint for an action with no observation, so the work
gets routed on the next wake. The monolith is then allowed to `chat reply`
to the trigger, but only when a pending action from the responder exists
for it, which keeps the rule that the monolith does not answer chat on its
own. The responder's prompt should also stop promising to "check" things,
since it cannot.

Files touched: `thinkers/responder/step`, `thinkers/monolith/prompt.md`,
`thinkers/monolith/step` for the permission check.

### Part 6. Metrics, so the problem stays visible

Add fields to the responder's existing "Replied" and "no-reply"
observations. Each is a few bytes.

- `context_msgs`, the number of earlier messages with this person the
  responder had in its prompt.
- `gap_s`, seconds since the previous exchange with this person.
- `compose_ms`, time from wake to send.
- `model`, the model used.
- `context_steps`, the list of step ids that made up the conversation and
  the inner life excerpt. The ids are a few hundred bytes and let anyone
  rebuild the exact prompt from the trajectory later.

The full prompt text is not recorded. The identity and skills part is the
same on every call, and the monolith's `prompt` steps are already why the
trajectory is 91 percent repetition. For debugging, an env flag
`RESPONDER_LOG_PROMPT=1` writes the prompt to a rotated file under
`run/logs/`, not to the mind log.

`deploy/scripts/audel-metrics` gets one more series, the share of inbound
messages with `context_msgs` equal to zero when `gap_s` is under 48 hours
and a previous exchange existed. The Usage tab can show it as a tile.

## Experiments

### Experiment A. Reconstruction baseline, done

The reconstruction scripts used for the tables above live in the private
experiments repo at `headlong-experiments/responder-memory/`. They should
be re-run once after Parts 1 and 2 deploy to
confirm the zero context share drops to zero for every gap under 7 days.
After Part 6 ships the real `context_msgs` field replaces the
reconstruction.

### Experiment B. Replay of the recent stream change, before Part 3 ships

The 2026-08-29 ablations showed that Grok's behavior on the monolith
depends on accumulated prompt state in ways that are hard to predict, so
the filter change gets a controlled replay before it touches Audel. Use the
private replay harness at
`~/laude/repos/headlong-experiments/audel-proactivity/controlled-replay/`.

- Conditions. The current filter, and the Part 3 filter (no reasoning,
  collapsed idle and error, final kept).
- Snapshots. The two existing late Audel snapshots, plus one taken during
  an active conversation so the change to the circling hint is exercised.
- Trials. 10 per condition per snapshot, 60 total, Grok 4.6. Budget under
  $5. The 08-29 batches of 10 to 40 trials cost $0.63 to $4.40.
- What to measure. Function chosen, whether the run produced a durable
  step, prompt size in characters, and whether the run referred to
  something only visible in reasoning steps under the old filter. That last
  item is the risk, and it is checked by hand.
- Pass condition. The Part 3 filter is no worse on productive wakes and
  saved results, and no run loses a decision it needed from a dropped
  reasoning step.

### Experiment C. Responder quality after Part 1 and Part 4

A cheap side by side on the responder alone, which is one `llm` call and
needs no harness. Take 30 real inbound messages from Audel's log that
arrived more than an hour after the previous exchange with that person.
For each, build the prompt three ways and generate a reply.

- Today's prompt.
- Part 1, messages only history with a 7 day window.
- Part 1 plus Part 4, with a person summary written from the log.

Score each reply by hand on whether it shows awareness of the earlier
exchange and whether it promises work it cannot do. The 90 calls cost under
a dollar on Grok. The result decides whether Part 4 ships with Part 1 or
later.

### Experiment D. Live measurement after deploy

For two weeks after Parts 1, 2, and 6 are live on Audel, read the new
`context_msgs` field. Report the zero context share per gap bucket in the
same table shape as above. Also count replies that contain "I'll check" or
"let me look" while no action step was appended, which is the deferral
problem Part 5 addresses.

## Rollout order

1. Part 6 first, so there is a real baseline before anything changes. It is
   the smallest change and touches only observation fields.
2. Parts 1 and 2 together, since Part 2 is a small addition to the same
   code path. Run Experiment A after.
3. Experiment C, then Part 4.
4. Experiment B, then Part 3.
5. Part 5 last, since it changes the monolith's rules about chat.

Each deploy to Audel follows the normal runbook, `update` then thinker sync
of `responder` and `_lib` from a pristine tree. `bin/chat` takes effect on
the next exec with no restart. The box tree currently carries Audel's own
uncommitted edits to `bin/chat` and `thinkers/_lib/common.sh` (file step
rendering for Telegram), so they have to be stashed around the deploy and
merged or reviewed afterward.

## What this does not cover

- The monolith forging outbound chat with `source:"responder"`. Part 5
  narrows when the monolith may reply, but the fix for forged sources is
  still open.
- Cross channel alias linking for agents without a human to seed it. The
  agent can learn aliases, but nothing forces it to.
- Any change to the tiered memory the monolith uses. The responder gets a
  per person summary, not the life summary.
