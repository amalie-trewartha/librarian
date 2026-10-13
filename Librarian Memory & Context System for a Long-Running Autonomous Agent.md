# Librarian: Memory & Context System for a Long-Running Autonomous Agent

Oct 9, 2026 · @Amalie Trewartha

## Executive summary

This design gives a fully autonomous, weeks-long agent a memory that grows without bound while what enters its context window stays small, ranked, and auditable.

- **Memory is a typed, tagged knowledge graph.** Each node has a short summary for ranking, a full body fetched only on selection, typed edges, and provenance. Nothing is overwritten; every change is a supersession carrying both valid time and transaction time.
- **Two paths into context.** A librarian pushes a budgeted pack at task start, at phase boundaries, and when a trigger fires. The main agent pulls anything else through `memory_search` and `memory_fetch`. Ranking runs on summaries only, so full text is paid for only when it earns its place.
- **Confirmation comes from outcomes, not opinions.** New nodes are probationary until an episode that cited them ends in a measurable result; the agent's own helpful rating is a weak prior.
- **Identity has two tiers.** Core commitments change only with human approval; working identity is the agent's own to revise within size, rate, and consistency bounds, and is reversible.
- **Four gated phases**, from a hand-fed store to the full identity and group model.

Open decisions: which model runs the librarian, the default context budget, SQLite versus a graph database to start, and how much of the group model to seed by hand.

## Overview

The system exists to let one agent run for weeks, learn across projects, and still be recognizably itself, without a human in the loop day to day.

**Goals**

- Consistent identity across months of unprompted operation: the same values, voice, and commitments at the start of project 40 as at project 1.
- Skill accumulation: concrete, reusable procedures (how to use package X, how to debug problem Y) that get better with each use.
- A deepening model of the group: its priorities, standards, recurring needs, and the reasons behind past choices.
- Honest retrospection: records of what went well and badly that actually change future behavior.

**Non-goals**

- Storing raw transcripts for replay. The raw activity log is kept, but it is a source for memories, not a memory itself.
- Perfect recall. The design accepts forgetting as a feature; what it does not accept is silent inconsistency.
- Replacing in-window context management or crash recovery. Compaction and tool-result clearing manage what is inside the current window, and task-state checkpoints let a run resume after a failure; the memory store is a third, complementary layer that moves durable knowledge out of the window so it survives across projects.

**The core tension.** A long-lived agent accumulates far more than fits in one context window. Every design choice below follows from one rule: the store can grow without bound, but what enters the context window is a budgeted, ranked selection, and the ranking is done over short summaries so the expensive full text is only paid for when it earns its place.

## Memory model

A memory is a node with a short summary used for ranking, a full body used for reading, and typed edges to other nodes. Every memory carries the same envelope regardless of type.

### Node schema

| Field | Purpose | Notes |
| --- | --- | --- |
| `id` | Stable identifier | ULID, never reused |
| `type` | One of the seven types below | Drives retrieval weights and lifecycle rules |
| `summary` | 1–3 sentences, ≤ 60 tokens | The only text read at ranking time; written to answer "when would I want this?" |
| `body` | Full content, ≤ \~1,500 tokens | Longer content is split into linked child nodes |
| `tags` | Controlled vocabulary + free tags | e.g. `pkg:pytorch`, `area:perception`, `ctx:code-review`, `project:p-0412` |
| `embedding` | Vector of summary + tags | Used for candidate recall, not final ranking |
| `provenance` | Where it came from | Project id, episode span, author (main agent, librarian, human), extraction method |
| `confidence` | 0–1 | The writer's initial estimate; afterward moved only by outcome-backed confirmation or contradiction |
| `use_count`, `last_used`, `last_confirmed` | Usage signals | `last_confirmed` advances only on a positive outcome from an episode that cited the node |
| `status` | `probationary` / `active` / `superseded` / `archived` / `disputed` | New nodes start `probationary` and are retrieved with that marker until one outcome confirms them |
| `outcome` | Episodes only: `success` / `partial` / `failure` / `unknown`, plus the criterion used | The exogenous signal that credit assignment runs on |
| `valid_from`, `valid_to` | Valid time: when the content was true in the world | Decisions and preferences can expire |
| `known_from`, `known_to` | Transaction time: when the system believed it | Set on write and on supersession; answers "what did the agent believe on day 12?" when debugging a long run |
| `created` | Write timestamp | Equals `known_from` for the first version |

### Memory types

| Type | What it holds | Example summary |
| --- | --- | --- |
| **Skill** | A reusable procedure, recipe, or gotcha | "Building ROS 2 Humble packages against a custom Eigen: pin CMake ≥ 3.22 and set `Eigen3_DIR` explicitly or colcon picks the system copy." |
| **Decision** | A choice made, the alternatives, and why | "Chose Parquet over SQLite for episode logs in p-0412 because downstream analysis is columnar; revisit if write latency matters." |
| **Retrospective** | What went well or badly, and the lesson | "p-0398 overran by 3 days because integration tests were left to the end; start them by day 2 on multi-service projects." |
| **Preference / ethos** | A standard, value, or taste of the group | "The team prefers small reviewable PRs over large feature branches, even at the cost of more merge steps." |
| **Identity: core** | Commitments and constraints the agent holds; changed only with human approval | "I flag safety-relevant uncertainty explicitly rather than hedging it into prose." |
| **Identity: working** | How the agent currently operates; the agent edits these itself within bounds | "I write the integration test scaffold before the first feature commit on multi-service projects; it has saved time three times." |
| **Episode** | A compressed record of a bounded stretch of work | "Days 1–3 of p-0412: scoped the data pipeline, hit the Eigen build issue, resolved it, handed off to review." |

Episodes are the raw material. Skills, decisions, retrospectives, and preferences are distilled from them. Identity nodes are few and loaded every time; core identity changes only through human review, working identity is the agent's own to revise.

### Edges

Edges are typed and directed, and each carries a weight and a provenance.

| Edge | Meaning | Typical use |
| --- | --- | --- |
| `derived_from` | Distilled memory → source episode(s) | Audit trail; re-derive if the source is corrected |
| `supersedes` | Newer node → older node it replaces | Keeps history without retrieving stale content |
| `contradicts` | Two active nodes that disagree | Surfaces for consolidation; both marked `disputed` until resolved |
| `applies_to` | Skill or preference → tag, project, or area | Fast path for "everything about package X" |
| `caused` / `informed` | Decision → outcome, retrospective → later decision | Lets the librarian explain *why* a memory is relevant |
| `co_retrieved` | Nodes often useful together | Learned from retrieval logs; strengthens with co-use |
| `part_of` | Child chunk → parent memory | Splits long bodies without losing the whole |

Tags are the primary index for fast lookup; edges are what make the store a graph rather than a filing cabinet. A retrieval that lands on one node can walk `applies_to`, `co_retrieved`, and `supersedes` edges one hop out to find its neighbors cheaply.

## Storage architecture

Three stores back one logical graph: a graph database for nodes, edges, and tags; a vector index over summaries for fuzzy recall; and a document store for full bodies and the raw activity log. The librarian and the main agent's pull tools read them; only the consolidation pipeline writes them.

&#91;embedded content: system architecture · 4 components, 3 stores\]

The main agent sends task context and progress to the librarian and receives a context pack back, and can search and fetch from the store directly; its activity log flows to the consolidator, which writes new and superseding nodes. The librarian flags contradictions it notices during retrieval back to the consolidator.

### Why three stores

| Store | Holds | Answers |
| --- | --- | --- |
| Graph (e.g. SQLite + adjacency tables to start; a graph DB if edge queries dominate) | Node envelopes, edges, tag index | "Everything tagged `pkg:pytorch` that is active", "what supersedes this", one-hop neighborhoods |
| Vector index (any ANN library) | Embedding of `summary + tags` per active or probationary node | "Nodes semantically near this task description" when tags miss |
| Document store (object storage or a plain table) | `body` text, split chunks, the raw activity log | Full text once a node is selected; re-derivation of memories |

The split keeps the hot path cheap. Ranking touches only summaries and tags (a few hundred bytes per node), so the librarian can score thousands of candidates per request. Bodies are fetched for the handful that survive.

### Tag taxonomy

Tags are namespaced to keep them searchable and to stop drift.

| Namespace | Examples | Governance |
| --- | --- | --- |
| `pkg:` | `pkg:ros2`, `pkg:pytorch`, `pkg:colcon` | Open; normalized to lowercase canonical names |
| `area:` | `area:perception`, `area:build-system`, `area:data-pipeline` | Closed list, extended by the consolidator with a review note |
| `ctx:` | `ctx:code-review`, `ctx:incident`, `ctx:planning`, `ctx:handoff` | Closed list |
| `project:` | `project:p-0412` | One per project, assigned automatically |
| `person:` / `team:` | `team:robotics-sw` | Used for preference and ethos nodes; no personal data beyond role |
| free | anything else | Allowed, but periodically folded into a namespace or dropped |

### Versioning and supersession

Nodes are immutable once written. A correction or update creates a new node with a `supersedes` edge to the old one and flips the old node to `superseded`. Retrieval defaults to active nodes only but can walk back through the chain when the agent asks "how did we get here?" This keeps the audit trail intact and makes rollback a status change rather than a restore.

### What the store is not

The memory store holds durable knowledge. Two neighboring concerns are deliberately kept out of it and handled by their own mechanisms:

- **In-window management.** Compaction of long histories and clearing of stale tool results keep the current context usable during a task. They operate on the window, not the store, and are configured on the main agent.
- **Task-state checkpoints.** A weeks-long run will crash. Versioned snapshots of the main agent's task state (plan, open subtasks, pending tool results) live in an object store keyed by run and step, so a failure resumes from the last checkpoint rather than from the start of the task. Episodes are written from checkpoints, but checkpoints are not memories and are discarded when the task closes.

## The librarian agent

The librarian is a separate, smaller model loop that decides what the main agent should know at task start and at phase boundaries, and what to push unprompted when a trigger fires. It owns the context pack, the budget, and proactive suggestion; it is not the only path to memory, because the main agent also pulls directly through two tools described below.

&#91;embedded content: librarian retrieval loop · 6 steps\]

Recall is cheap and wide; ranking is done on summaries alone; bodies are fetched last. The loop restarts whenever the main agent reports a phase change or a proactive trigger fires.

### Inputs

| Input | From | When |
| --- | --- | --- |
| Context request | Main agent | Task start, phase change, explicit ask ("anything on colcon build failures?") |
| Progress update | Main agent | Every N tool calls or on milestone; a 2–5 sentence status plus current tags |
| Activity log stream (raw tool calls and outputs; distinct from \`episode\` nodes, which are its compressed summaries) | Main agent | Continuous; the librarian reads it only to detect triggers, not to answer |
| Store change events | Consolidator | New or superseded nodes, so cached rankings invalidate |

### Stage 1: candidate recall

The librarian frames the request as a small structured query: task description, current tags, project id, phase (`planning` / `building` / `debugging` / `reviewing` / `handoff`). It then unions three cheap sources and caps the result around 200 candidates:

1. **Tag match**: active and probationary nodes sharing ≥ 1 tag with the query, weighted by tag specificity (`pkg:colcon` is worth more than `area:build-system`).
2. **Vector recall**: top-k nearest summaries to the task description.
3. **Graph hop**: one hop from the above along `applies_to`, `co_retrieved`, and `informed` edges.

Identity nodes and active group-preference nodes bypass recall and are always in the candidate set.

### Stage 2: salience ranking on summaries

Ranking is two cuts, both over summaries and envelopes only. The first cut, roughly 200 candidates down to 30, uses a cheap cross-encoder reranker over tag overlap and summary text, with no LLM call. The second cut, 30 down to what fits the budget, adds an LLM relevance judgment. The score is a weighted sum of the signals below; weights are per memory type and per phase and are tuned from the retrieval log (see Evaluation). If the eval set shows the LLM cut adds little over the reranker, drop it: for a run measured in weeks, the per-request token cost compounds.

| Signal | What it measures | Notes |
| --- | --- | --- |
| Relevance | LLM judgment of summary vs. task, 0–3 | Second cut only, on the \~30 survivors of the reranker; the dominant term when present |
| Tag overlap | Jaccard over namespaced tags | Cheap prior before the LLM call |
| Recency / confirmation | Decay on `last_confirmed` | Skills decay slowly; decisions decay toward their `valid_to` |
| Reuse history | `use_count` and whether the episodes that cited it ended in a positive outcome | Prevents one-off notes from crowding out proven skills |
| Type × phase prior | Retrospectives up in planning; skills up in building and debugging; decisions up in reviewing | Static table, overridable |
| Novelty to session | Down-weight anything already in the current context pack | Avoids re-sending |

Ties and near-ties favor the node with the higher `confidence` and the shorter body.

### Stage 3: packing to budget

The librarian is given a token budget per request (e.g. 8k of a 200k window, adjustable by phase). It fills in this order:

1. Identity nodes, core then working (always, \~500 tokens total, cached verbatim so the prefix hits the prompt cache).
2. Active group preferences relevant to the tags (\~1k).
3. Ranked task memories, highest score first, fetching each body and stopping when the budget is hit.
4. One line naming the tags the pack was built from, so the main agent knows what it can pull for itself if the pack missed something.

If a top-ranked body is too long for the remaining budget, the librarian includes its summary plus the first child chunk and marks it as truncated.

### Pull: the main agent's own memory tools

Mid-task, the main agent knows what it needs better than the librarian can infer from a progress update, so it has two tools that read the store directly. Pull is cheap and precise because the agent already knows the tags; push stays rare by design.

| Tool | Input | Returns | Cost |
| --- | --- | --- | --- |
| `memory_search` | `tags[]`, optional free text, optional `type`, `limit` (default 10) | Summaries only: id, type, tags, summary, confidence, `last_confirmed` | One tag lookup plus one vector query; no LLM call |
| `memory_fetch` | `ids[]` | Full bodies, truncated to the caller's stated remaining budget | One document-store read per id |

Rules that keep pull parsimonious:

- Search never returns bodies, so a speculative search costs a few hundred tokens, not thousands.
- Fetch is logged exactly like a pack entry: the id lands in the episode log, which is how `use_count` and confirmation are recorded for pulled memories too.
- The librarian sees every pull. A pull for tags the pack did not cover is a signal that the pack missed something and feeds the miss-rate metric; a pull the main agent repeats across tasks is a candidate for a higher type × phase prior.
- The librarian never replaces a call the main agent could have made. It fills the gap the main agent does not know it has: identity, preferences, triggers, and the task-start pack.

### Progress feed and proactive suggestion

Between requests the librarian watches the progress updates and activity stream for triggers. Each trigger has a cooldown so suggestions stay rare and worth reading.

| Trigger | Detection | Suggestion |
| --- | --- | --- |
| Repeated failure | Same error signature or tool failing ≥ 3 times | Skill or retrospective nodes matching the error tags |
| Decision point | Progress text contains alternatives being weighed | Prior `decision` nodes on the same tags, with their outcomes |
| Deviation from preference | Current action contradicts an active preference node (e.g. opening a very large PR) | The preference node, with its provenance |
| Phase drift | Elapsed effort in a phase exceeds the retrospective-derived expectation | The retrospective that set the expectation |
| Contradiction found | Two retrieved nodes disagree | Both nodes flagged `disputed` for the consolidator; main agent told which is newer |
| New tag seen | A tag never seen before appears in progress | Nothing to suggest; the librarian notes it as a likely new skill to capture later |

A suggestion is delivered as a short, labeled interjection the main agent can accept, defer, or dismiss; the response is logged and feeds the trigger thresholds. The librarian never interrupts more than once per cooldown window (default 15 minutes of wall-clock work or 50 tool calls).

## Memory lifecycle

Memories are written at well-defined moments, distilled from episodes rather than dumped from transcripts, consolidated on a schedule, and allowed to fade. The store grows, but the active set stays curated.

### Capture: when memories are written

| Moment | Who writes | What is written |
| --- | --- | --- |
| End of a work session or checkpoint | Main agent (reflection step, \~2 minutes of budget) | One `episode` node summarizing the span; candidate `skill` and `decision` nodes flagged `confidence < 0.7` |
| Resolved failure | Main agent, prompted by the librarian's repeated-failure trigger | A `skill` node: symptom, cause, fix, tags; linked `derived_from` the episode |
| Decision made | Main agent at the moment of choice | A `decision` node with alternatives considered and the reason; `valid_to` if the choice is provisional |
| Project close | Main agent, guided by a fixed retrospective template | 2–5 `retrospective` nodes: what went well, what went badly, what to do differently, each with the evidence |
| Human feedback received | Consolidator, parsing the feedback | `preference` nodes with the human's words as provenance; existing conflicting preferences marked `disputed` |
| Pattern across projects | Consolidator (nightly) | Promoted `preference`, `identity`, or generalized `skill` nodes with `derived_from` edges to ≥ 3 sources |

Every write passes a quality gate before it is stored, and enters as `probationary` rather than `active`:

- Summary answers "when would I want this?" in ≤ 60 tokens and does not repeat the body's first sentence.
- At least one namespaced tag.
- No near-duplicate: cosine similarity to an existing active summary below a threshold (start at 0.92), or else the write becomes a `supersedes` or `co_retrieved` edge instead of a new node.
- Body contains the specifics (commands, versions, numbers, names) rather than the lesson alone.
- `provenance` points at a real episode span.

### Confirmation: outcomes, not opinions

The loop from write to retrieval to reuse is otherwise closed: the agent writes a memory, retrieves it, uses it, and rates it helpful because it used it. Confirmation is therefore tied to the one signal that comes from outside the system, the measurable outcome of the episode that cited the memory.

| Outcome evidence | Recorded by | Example criterion |
| --- | --- | --- |
| Verification passed | Main agent, from tool results | Test suite green; build succeeded; linter clean |
| Failure did not recur | Librarian, from error signatures | The signature that triggered a skill's use is absent for the rest of the project |
| Effort within expectation | Librarian, from progress updates | Phase closed within the retrospective-derived estimate |
| Deliverable accepted | Consolidator, from human feedback or downstream use | A PR merged, a handoff taken up, no correction received within the review window |
| None available | Main agent | `outcome: unknown`; the episode confirms nothing |

**Credit assignment** runs at episode close, before consolidation:

1. Every memory id cited in the episode (from the pack or from `memory_fetch`) is a candidate for credit.
2. On `success`, each cited node gets `last_confirmed` set to the episode date and a small confidence increase; a `probationary` node with its first confirmation becomes `active`.
3. On `failure`, each cited node gets a small confidence decrease and a `contradicts`-style note linking it to the failed episode; two failures with no intervening success flag the node for consolidator review.
4. On `partial` or `unknown`, nothing moves. The agent's own helpful rating is logged and used as a tie-breaker in ranking, never as confirmation.
5. Credit is split, not duplicated: an episode that cites eight memories confirms each less than one that cites two, so a pack stuffed with marginal nodes does not inflate them all.
6. Outcomes can arrive late. A merged PR or a correction received during the review window amends the episode's `outcome` after close, and credit assignment re-runs for that episode, reversing any credit the earlier value gave.

Probationary nodes are still retrieved when relevant, but the pack and the search results mark them, so the main agent knows it is acting on something the world has not yet checked. Probation has an exit in both directions: a node still unconfirmed after 90 days or 10 citations in `unknown`-outcome episodes is archived as unproven, and the consolidator may lift a node to `active` early when a human endorses it.

### Consolidation (nightly or per project close)

A batch job run by the consolidator with a small model and a bounded budget:

1. **Merge**: cluster near-duplicate active nodes; write one merged node that supersedes the cluster. The merged body is written from the cluster's \`derived\_from\` episodes, never from the previous merged text, so fidelity does not erode with each consolidation pass.
2. **Generalize**: when ≥ 3 skills share tags and shape, draft a general skill and link the specifics as `part_of` examples.
3. **Resolve disputes**: for each `contradicts` pair, prefer the newer, higher-confidence, more-used node; mark the other `superseded` with a note. If neither dominates, keep both `disputed` and queue a question for the next human check-in.
4. **Promote**: retrospectives whose lesson has been confirmed in two later projects become preferences; preferences stable for 90 days with no contradiction become candidates for identity.
5. **Re-embed**: summaries that changed get new vectors; `co_retrieved` edges are strengthened from the retrieval log and pruned below a floor.

### Decay and archival

Nothing is deleted. Nodes move from `active` to `archived` when their salience floor is not met, and archived nodes are excluded from recall unless the query explicitly asks for history.

| Type | Default half-life on `last_confirmed` | Floor |
| --- | --- | --- |
| Skill | 365 days | Archive after 2 half-lives with `use_count` = 0 |
| Decision | Until `valid_to`, else 180 days | Archive when the project it belongs to is closed and no later decision cites it |
| Retrospective | 180 days | Archive once promoted to a preference |
| Episode | 30 days | Archive once every derived node is active |
| Preference / ethos | None | Archive only by human instruction or supersession |
| Identity | None | Never archived; only superseded (core by human approval, working by the agent within its rules) |

A node is confirmed only by the credit-assignment step above or by explicit human endorsement. Confirmation resets the decay clock and raises `confidence` by a small step; retrieval and use on their own do not.

## Identity and ethos layer

Identity is a small, always-loaded set of nodes in two tiers: a core the agent cannot change without human approval, and a working layer the agent revises itself within bounds. The group's ethos is a larger set of preference nodes loaded by relevance. All of it runs through the same lifecycle as other memory, with stricter gates.

### The self-model

The agent's identity is 10–20 nodes totaling roughly 500 tokens, loaded verbatim at the top of every context pack, in two tiers with different change rules.

| Tier | Covers | Who can change it | Bound |
| --- | --- | --- | --- |
| **Core** (`identity.core`) | Commitments on uncertainty, safety-relevant findings, and disagreement with a request; standing constraints the group has set; the non-negotiable parts of voice (US English, lead with the answer) | Humans only. The consolidator and the agent may propose; a change is applied only when approved in the check-in queue | \~300 tokens, 5–10 nodes |
| **Working** (`identity.working`) | How the agent currently operates: planning habits, when it asks versus proceeds, how it reports, self-observed strengths and recurring mistakes, operational heuristics about itself | The agent, autonomously, through `write_candidate` with the usual quality gate | \~300 tokens, 5–10 nodes; an edit that would exceed the bound must supersede an existing node |

**Rules for autonomous working-identity edits**

- Every edit is a supersession with `provenance` pointing at the episodes that motivated it, so the chain of "why I changed how I work" is auditable.
- A working node may not contradict a core node. The quality gate checks each working edit against the core set and refuses it if it does, queuing the conflict for humans instead; core always wins at retrieval time.
- At most one working-identity edit per project close, plus one per resolved repeated-failure trigger. The rate limit stops a bad day from rewriting the agent's self-model.
- Working edits are reversible by status flip. The monthly consistency probes cover both tiers; a probe drift traced to a working edit reverts it and notes the reversion in the check-in queue.
- A working node stable for 90 days, confirmed in three or more projects, and never reverted becomes a candidate for core, proposed through the check-in queue with its evidence attached.
- When a working edit and a pending core proposal cover the same behavior, the working edit is held until the proposal is decided: approved, the working node is superseded by the core node; rejected, the working edit proceeds under its normal rules. The agent is told in the pack's librarian notes that the behavior is under review.

Core nodes change only through supersession, and a proposed change is queued for human review rather than applied. The consolidator can propose one when a preference or working-identity node has been stable for 90 days and the retrospective log shows the agent already acting on it; the proposal carries its `derived_from` evidence.

Consistency is enforced at retrieval time as well as at write time. When the librarian notices a progress update that contradicts an identity node of either tier, it raises the deviation-from-preference trigger with the identity node attached, so drift is caught in the act rather than in a retrospective.

### The group model

The group's ethos lives in `preference` nodes tagged by `team:` and `area:`, each with provenance back to a human statement, a code review comment, an accepted retrospective, or a pattern the consolidator found. The model has three layers, loaded in this order when relevant:

| Layer | Examples | Source of truth |
| --- | --- | --- |
| Stated values | "Safety-relevant uncertainty is reported, not smoothed over"; "Prefer boring, well-understood tools" | Human statements and onboarding docs the group has provided |
| Observed standards | Review comments that recur; conventions the agent was corrected on | Consolidator patterns over ≥ 3 episodes |
| Recurring needs | The kinds of projects that come up, the outputs the group keeps asking for, the handoff formats that worked | Project close retrospectives |

Stated values outrank observed standards when they conflict; an observed standard that contradicts a stated value is flagged for the group rather than silently adopted. Preferences keep the human's own words in their body so the agent can quote the source when it explains a choice.

### Human check-ins

Full autonomy does not mean no human contact; it means the system runs without needing it. A lightweight check-in queue collects items only a human can settle: proposed core-identity changes, working-identity edits that were refused for contradicting core or reverted by a probe, unresolved disputed preferences, and new `area:` tags. The queue is surfaced on whatever cadence the group chooses, and the agent proceeds with its best current understanding in the meantime, noting in its episode log which choices depended on an open question.

## Interfaces

The main agent, librarian, and consolidator talk over seven message types; the context pack has a fixed layout so the main agent can rely on where things are.

### Messages

| Message | Direction | Payload |
| --- | --- | --- |
| `context_request` | Main → Librarian | `task`, `tags[]`, `project`, `phase`, `budget_tokens`, `exclude_ids[]` (already in context) |
| `progress_update` | Main → Librarian | `status` (2–5 sentences), `tags[]`, `phase`, `tool_calls_since_last`, `errors[]` (signatures only) |
| `context_pack` | Librarian → Main | The pack below, plus `request_id` |
| `suggestion` | Librarian → Main | `trigger`, `memory_ids[]`, one-line rationale; main replies `accept` / `defer` / `dismiss` |
| `memory_search` | Main → Store (tool call, observed by the librarian) | `tags[]`, `text?`, `type?`, `limit`; returns summaries only |
| `memory_fetch` | Main → Store (tool call, observed by the librarian) | `ids[]`, `budget_tokens`; returns bodies |
| `write_candidate` | Main → Consolidator | A draft node; consolidator applies the quality gate and replies with the final id or the merge target |

### Memory node, serialized

```json
{
  "id": "01J9W8K2M3N4P5Q6R7S8T9V0WX",
  "type": "skill",
  "summary": "colcon builds that pick up the system Eigen instead of a vendored one: set Eigen3_DIR explicitly and require CMake >= 3.22.",
  "body": "Symptom: link errors against Eigen symbols after a clean build...\nCause: ...\nFix: ...\nVerified on: ROS 2 Humble, Ubuntu 22.04, 2026-09-14",
  "tags": ["pkg:colcon", "pkg:eigen", "pkg:ros2", "area:build-system", "ctx:debugging", "project:p-0412"],
  "provenance": {"episode": "01J9W8...", "span": [142, 171], "author": "main", "method": "resolved-failure"},
  "confidence": 0.85,
  "use_count": 3,
  "last_used": "2026-10-02",
  "last_confirmed": "2026-10-02",
  "status": "active",
  "valid_from": "2026-09-14",
  "valid_to": null,
  "known_from": "2026-09-14",
  "known_to": null,
  "created": "2026-09-14T18:41:07Z",
  "edges": [
    {"type": "derived_from", "to": "01J9W8..."},
    {"type": "applies_to", "to": "tag:pkg:colcon", "weight": 1.0},
    {"type": "co_retrieved", "to": "01J9X1...", "weight": 0.6}
  ]
}
```

A freshly written node differs in three fields: `status` is `probationary`, `last_confirmed` is null, and `use_count` is 0. An `episode` node additionally carries `outcome`, e.g. `{"value": "success", "criterion": "test suite green at close", "recorded": "2026-10-02"}`.

### Context pack layout

The pack is plain text with fixed section markers, in this order. The main agent's system prompt documents the layout once so each pack needs no preamble.

```markdown
[IDENTITY: CORE]      ~300 tokens, verbatim, every time; human-approved
[IDENTITY: WORKING]   ~300 tokens, verbatim, every time; agent-maintained
[GROUP PREFERENCES]   relevant preference nodes, each: id · summary · body
[TASK MEMORIES]       ranked nodes, each: id · type · status (PROBATIONARY marked) · tags · summary · body (or summary + first chunk, marked TRUNCATED)
[COVERAGE]            one line: the tags this pack was built from — pull with memory_search for anything else
[LIBRARIAN NOTES]     0–3 lines: disputed pairs, open human questions touching this task, cooldown state
```

Ids appear on every entry so the main agent can cite a memory in its episode log (which is how `use_count` and confirmation get recorded) and so a `write_candidate` can point at what it supersedes.

## Evaluation

The system is working when the main agent reuses what it learned, stays consistent under probing, and the memories it is given are cited in episodes that succeed. Every retrieval, suggestion, and outcome is logged, so most metrics come for free.

| Question | Metric | How measured | Target to start |
| --- | --- | --- | --- |
| Are the right memories retrieved? | Pack precision | Share of task-memory entries cited in episodes that closed with a positive outcome; the agent's own helpful rating is reported alongside as a weak signal | ≥ 50% |
| Are important memories missed? | Pull rate and misses | How often the main agent pulls memories on tags the pack did not cover, and how often a post-hoc review finds an active node that should have been in the pack | Uncovered-pull rate falling over time; miss rate < 10% |
| Are skills actually reused? | Skill reuse | Fraction of resolved failures where a matching skill existed, whether it was retrieved before the fix, and whether the fix held (no recurrence of the error signature) | Retrieved-before-fix ≥ 70% |
| Do retrospectives change behavior? | Lesson adherence | For each promoted retrospective, whether later projects on the same tags show the recommended behavior | Rising per project |
| Is identity consistent? | Consistency probes | A fixed set of 20–30 probe prompts run monthly against the agent with only the identity nodes loaded; answers compared to the previous month's | Semantic drift below a set threshold; any change traceable to a reviewed identity supersession |
| Are suggestions welcome? | Suggestion acceptance | `accept` / (`accept` + `dismiss`), per trigger type | ≥ 40%; triggers below 20% get their threshold raised |
| Is the store healthy? | Duplicate and dispute rates | Near-duplicate pairs found per consolidation run; disputed nodes older than 30 days | Both trending to near zero |
| Does it fit? | Budget utilization | Tokens used vs. budget; truncation frequency | Truncation on < 5% of packs |

### Offline evaluation set

Keep a frozen set of past tasks with hand-labeled "should have been retrieved" memories. Re-run the librarian against it whenever ranking weights, the embedding model, or the summary-writing prompt changes. This is the regression test for retrieval; the live metrics above are the production monitor.

### Ablations worth running early

- Tags-only recall vs. tags + vectors vs. tags + vectors + graph hop.
- Summary-only ranking vs. ranking with bodies (to confirm the two-stage design is not losing much).
- Fixed type × phase priors vs. learned ones.
- Push-only (librarian pack, no tools) vs. pull-only (tools, no pack) vs. the hybrid, on the frozen eval set and on token cost per task.

## Risks, failure modes, and open questions

The largest risks are memory that is wrong but confident, memory that quietly reshapes identity, and a librarian that is either silent or noisy. Each has a mitigation in the design; none is fully solved.

| Risk | What it looks like | Mitigation in this design | Residual |
| --- | --- | --- | --- |
| Confident wrong memory | A skill with a stale fix keeps getting retrieved and applied | `last_confirmed` decay; `contradicts` edges; quality gate requires specifics and provenance; new nodes are probationary until an outcome confirms them, and failures lower confidence; supersession on correction | A wrong memory used only in episodes with no measurable outcome persists until decay |
| Identity drift | Preferences promoted to identity change how the agent acts without anyone deciding that | Core changes are human-reviewed; working tier is bounded, rate-limited, checked against core, and reversible (see Identity); monthly probes cover both tiers; deviation trigger at retrieval time | Slow drift inside the probe threshold; working-tier edits that are individually sound but cumulatively shift behavior |
| Overfitting to the group's past | The agent reproduces old choices in new situations | Decisions carry alternatives and reasons so they can be re-argued; `valid_to` on provisional choices; type × phase priors down-weight decisions outside review | Judgment call left to the main agent |
| Librarian too quiet or too loud | Missed suggestions, or interruptions that get dismissed | Per-trigger cooldowns and acceptance-rate feedback; the main agent's pull tools give a passive channel that does not depend on the librarian guessing right | Needs tuning per group |
| Prompt injection via memory | Content that reached the store (e.g. from a web page in an episode) is later loaded as instructions | Bodies are data, not instructions, and the pack layout labels them; provenance records the author; nodes authored from untrusted sources carry a tag the main agent is told to treat as untrusted | Main agent must honor the labeling |
| Store growth | Candidate recall slows; consolidation runs lengthen | Archival; two-stage ranking caps work at \~200 summaries; consolidation is incremental over changed nodes | Vector index rebuilds at scale |
| Summary quality | Bad summaries make good bodies unreachable | Summary written to a fixed question; quality gate; periodic re-summarization of high-value nodes with low retrieval | Depends on the writing model |
| Sensitive content | Human statements, names, or internal details end up in preference bodies | `person:` tags limited to role; provenance stored as references not quotes where policy requires; retention follows the group's data policy | The group's information-security team should review what the store may hold |

### Open questions

- [ ] Who is the librarian? A smaller, cheaper model with a fixed prompt, or the same model class as the main agent with a narrower role?
- [ ] Budget split: how much of the window goes to the pack by default, and does the main agent get to negotiate it per phase?
- [ ] Graph store choice: start with SQLite and adjacency tables, or commit to a graph database from the outset?
- [ ] Does the main agent write memories itself, or only propose them for the consolidator to accept? The design above has it propose; writing directly is faster but weakens the quality gate.
- [ ] How much of the group model should be seeded by hand before the agent runs, versus learned?
- [ ] Multi-agent future: if several main agents share one store, how are identity nodes scoped?

## Phased implementation plan

Build the store and capture first with packs assembled by hand, so the schema is proven on real memories before any retrieval logic exists. Each later phase adds one layer and is gated on a metric from the Evaluation section.

&#91;embedded content: implementation roadmap, 4 phases and 4 gates\]

Phases run in order; the gate under each boundary is the result that opens the next phase.

| Phase | Delivers | Deliberately leaves out |
| --- | --- | --- |
| Store and capture | Node schema, tag namespaces, document and graph stores, episode capture at checkpoints with an outcome field, the quality gate, a CLI to inspect nodes, task-state checkpointing for crash recovery; packs assembled by a person | Any automatic retrieval; vector index |
| Librarian v1 | Tag and vector recall, two-cut summary ranking with static priors, budget packing, the memory\_search and memory\_fetch tools, context\_request / context\_pack messages, the frozen eval set | Progress feed, suggestions, consolidation |
| Lifecycle | Nightly consolidation (merge, generalize, resolve, re-embed), outcome-based credit assignment and probation, decay and archival, supersession on correction, progress updates and the trigger table, acceptance logging | Identity promotion, human queue |
| Identity and group | Seeded core identity nodes, agent-editable working identity with its rate limits and core check, three-layer group model, monthly consistency probes, promotion rules, human check-in queue, untrusted-source tagging | Multi-agent scoping (see open questions) |

Durations are not set here; each phase should be sized by the team once the store choice and librarian model are decided.
