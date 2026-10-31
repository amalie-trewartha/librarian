# Librarian trials A to D: what they showed, and a leaner design for the next round

Status: analysis, 2026-10-31. Written before the VM was wiped and its disk
expanded for a fresh set of trials. The evidence files it rests on are kept
on the host in `~/librarian-trials-archive-2026-10-31/` (stores, usage
ledgers, trajectories, step logs, the `project/` git repos and the run notes
for A, B, C and D; the run-B evaluation is `run-b/EVAL-B.md` in the B
archive, the day-7 cross-project analysis is `EVALUATION-NOTES.md`). Code:
run B/C on `librarian-trial-control` (3115bb9), run D on `librarian-run-d`
(8aa30ed). Where a number below is from a run's own store it is marked [M];
judgments are marked [J].

## 1. Where the trials stood

| Run | Condition | Code | Ran | Ended how |
|---|---|---|---|---|
| A | memory, fixes 1-19 | run-A | 7 days, 6 briefs | day-7 cut, complete |
| B | memory, run-B package | 8190da2 | 7 days, 5 of 6 briefs | day-7 cut, complete (brief 5 lost to a scheduler collision) |
| C | no memory (control) | 3115bb9 | 2.5 days, brief 1 only | stalled 10-30 07:02Z: disk full, wake file never re-armed |
| D | memory, lessons redesign | 8aa30ed | 1 day of active time, brief 1 only | stalled 10-30 15:36Z: disk full for the second time |

The disk (61 GB) filled twice in two days. Both times the cause was shellm
container scratch under `/tmp` (12 to 14 GB per kit) plus three kits and
their archives on one disk. A wake that hits "No space left on device" cannot
re-arm `run/monolith.wake_at`, so the dispatcher sits idle until a human
writes the file by hand. Neither C nor D reached brief 2, so the comparison
the trials were built for (lessons compounding across briefs, D against C)
was never made. The planned evaluator pass (GPT-6.1 Sol over blinded day-7
snapshots) was piloted on A and never run on B.

## 2. What the measurements say

Evidence from A (day-7 analysis), B (EVAL-B, 884 wakes, $821) and D (first
103 wakes, $126).

**Files carry the work; memory carried tooling and shared-input facts.** In A,
every later brief got the earlier briefs' results by reading `results.json`
and the code, not through memory; 56 of 57 cross-brief cites were bash
tooling skills. In B, 39 of 53 cross-brief cites were facts about shared
inputs (one FHWA mileage fact alone had 17) [M].

**Episodes were half the pack at a 6% cite rate** (B), 70% of those cites to
the previous wake, which the journal tail already shows [M]. D removed them
and the pack fell from 4,474 to 2,055 tokens with no loss anyone measured [M].

**Lessons are used when shown.** B: retrospectives were cited in 31% of the
wakes they were shown in, against 11.5% for all rows [M]. D: the new
[LESSONS] section was cited in 93 of 224 showings (42%), the task section in
120 of 413 (29%) [M]. Shown is the whole game: B's end-of-brief
retrospectives were never shown and never cited.

**The credit signal was close to empty, and where it fired it was often
wrong.** B: 96% of credit rows were "partial" (zero); curated confidence sat
in 0.49 to 0.60 after 7 days; the only non-review failure credit blamed 7
memories for a guard script's intended MISS line [M]. D (next section) made
the sign problem worse rather than better.

**Half the machinery never ran.** Across A and B: `dismiss` 0 uses, identity
edits 0, probes never reached a decision, disputes 1 (stale for 7 days and
leaking into rest decisions), decision-point suggestions 13% accepted and
then turned off, the transfer section 5% cited and then turned off [M].

**Direct librarian spend is negligible; the overhead is in the mind.** The
Haiku rank cut cost $7.43 of B's $821 and $0.56 of D's $126 [M]. What costs
is the main model doing memory chores: D made 48 `propose` calls, wrote 19
retrospectives and 97 "Lessons applied" lines in 102 wakes, and its output
tokens per run were 21.4K against C's 17.6K; cost per run in the first day
was $0.99 (D), $0.86 (C), $0.83 (B) [M]. The librarian package is 6,800
lines of Python plus about 1,700 lines of shell hooks, 23 tables, schema
version 6.

## 3. Is run D the best version of the librarian?

D is the best-instrumented version and it fixed the two largest pack
problems: episodes out, lessons in by situation. Three of its new mechanisms
misfire, and one of them inverts the intent [J, with M evidence].

1. **Lesson judging is one-sided by construction.** A lesson named in a
   "Lessons applied" line gets `success` only when every claim in the review
   SURVIVES, `failure` when none survives, and in a mixed review `failure`
   for any lesson tagged with a class the review found. D's reviewer was
   told to use WEAKENED, and did: 0 of D's 23 adversary reviews were all
   SURVIVES. Result after one day: `lesson_judged` holds 36 failures and 1
   success; retrospective confidence fell to 0.29 to 0.50; no lesson can
   ever reach [PRACTICES] [M]. The mind also tags each lesson with 1 to 5
   `fail:` classes (median 2), so the mixed-review filter almost always
   matches. The signal rewards the mind for not naming lessons.
2. **LESSON DUE after every broken review over-produces.** 21 LESSON DUE
   rows were raised and cleared in one day; the mind wrote 19
   retrospectives (B wrote 7 in 7 days). Most are domain footnotes written
   as process ("When moving a choice model to nested logit with
   coefficients sourced at MNL scale: rescale ...") [M]. Nineteen lessons
   compete for three [LESSONS] slots, so the generic ones B found valuable
   (one rerun script on day 1; guard every hand-typed number) would be
   crowded out by brief 2.
3. **The in-run measures are confounded.** D's reviewer prompt differs from
   B's and C's (verdict block, classes, WEAKENED), so D's broken-claim counts
   cannot be compared with theirs; the plan knew this and relied on an
   evaluation-time re-review that has not happened. D also lost 12.7 hours
   to the disk outage and its day-7 stop was shifted, a confound the notes
   record.

What D got right and the next design should keep: no episodes in the pack;
a per-brief project tag; lessons chosen by situation and shown on every
wake of that situation; the reviewer's structured `Claim verdicts:` block
with a closed failure-class list (useful to the research process whether or
not memory exists); a pause-safe brief scheduler; a pre-mortem per brief;
the leak check and the pre-registered measures.

## 4. Why the overhead is high, mechanism by mechanism

| Mechanism | Visible to the mind? | Measured effect | Keep in v2? |
|---|---|---|---|
| Pack: identity core + preferences | yes, every wake | never cited (fixed text) | yes, as plain prompt text, not store nodes |
| Pack: task facts, decisions, skills | yes | facts 13 to 29% cited, the useful bulk | yes |
| Pack: episodes | yes | 6% cited, half the tokens | no |
| Pack: transfer section (BM25 on brief text) | yes, 3 wakes | 5% cited | no |
| [LESSONS] by situation | yes | 42% cited | yes |
| [PRACTICES] | yes | never formed | drop; fold into lessons with a "confirmed" mark |
| LESSON DUE per broken review | yes | 19 lessons/day, mostly domain footnotes | no; one lesson moment per brief close and per daily ritual |
| PREMORTEM DUE | yes | risks.md written for every brief | yes, as a charter step, no store state |
| Confidence, credit, decay, late upgrades | no (only through rank) | 96% zero; wrong sign twice | drop as a ranking input |
| Reviewer-judged lessons | no | 36 failure / 1 success | replace (section 5) |
| Haiku rank cut | no | 93 to 99% of packs cut; effect never measured | drop until an ablation shows it helps |
| Quality gate on propose | yes (refusals) | 1 refusal in 93 proposes | keep a minimal gate (summary, tag, body) |
| Dedup, consolidation, generalize, disputes | no | 0 duplicate pairs, 1 stale dispute | drop |
| Probes, working identity edits, identity queue | yes (commands) | 0 uses | drop |
| Captures and auto-draft | yes (signal) | 3 captures in B, one loop of 25 re-fetches in A | keep the signal, drop the auto-draft |
| Decision-point suggestions | yes | 13% accepted | drop (already off in D) |
| Recurrence detector on stdout signatures | no | one false blame of 7 memories, one miss | drop |
| Export mirrors (`project/skills/**`, `librarian.md`) | yes (files) | not measured; the mind reads files | keep a single `project/memory/` export, drop the identity-wide mirror |

## 4b. What a read of the run-D code adds

A code audit of `librarian/src/librarian/` at 8aa30ed (file:line references
are to that commit) found these points that the run data alone does not
show:

- **Confidence is not in the ranking score.** `rank.cut1` (rank.py:145-166)
  scores tag overlap, BM25, recency, reuse and a type-by-phase prior;
  confidence is only the sort tiebreak (rank.py:218, 243) and the pack text
  never shows it (pack.py:173-180). The whole credit, decay and late-upgrade
  apparatus (about 400 lines, 3 tables) therefore changes nothing the mind
  sees except the PROBATIONARY marker, which the first success removes.
- **Recency discriminates nothing in a 7-day run.** Half-lives are 30 to
  365 days (rank.py:30-38), so every node scores about 0.6 on recency.
- **A Haiku omission is a hard veto.** Any curated node the rank model does
  not name gets relevance 0 (rank.py:186) and pack.py:472 drops it, even
  with a strong tag or text match. Episodes are exempt. When the reply fails
  to parse, nodes that arrived only through the all-curated pool are dropped
  too. The cut ran on 93 to 99% of packs and its effect was never measured.
- **Two per-wake costs grow with the run, not the request.**
  `exchange.export_store` reloads every node and rewrites one file per node
  every wake (exchange.py:69-96; about 4,000 queries and 2,000 file writes
  at 2,000 episodes), and `_traj_steps` globs the whole trajectory tree
  (runtime.py:686-714). The `derived_from` lookup is a full scan on a JSON
  field with no index (runtime.py:932-935).
- **The "Lessons applied" channel mostly works through one path.** The
  verdict regex in `bin/blind` matches only lines starting with SURVIVES,
  BROKEN or UNVERIFIABLE, not WEAKENED or `C1: BROKEN`, and the
  committed-claims path derives a claims filename the mind could not have
  chosen in advance (runtime.py:632-634); only blind's ledger file carries
  the ids in practice.
- **Clock mismatch.** Late outcomes compare wall-clock git commit times with
  project-clock episode times (runtime.py:172-189), which is wrong under any
  time scale above 1; this is why the trial at 90x showed guard lessons
  "written after the review".
- **Citation scanning is permissive.** Any 26-character Crockford token in
  FINAL, thoughts, commands, added journal lines or a whole review file
  counts as a cite (runtime.py:857-872); a review file touched again
  re-cites every id in it.
- The audit's own estimate: what the mind sees is decided by about 1,300
  lines (recall, rank, pack, signals, gate); the remaining 5,000 or so
  mutate state that feeds back only through status promotion.

## 5. A leaner design for the next trials

Implemented on branch `librarian-v2` on 2026-10-31; the design as built is
`design/librarian.md`, and the trial that tests it against a no-memory
control is `trials/v2/PROTOCOL.md`.

Design rule: every mechanism must either change what the mind sees in its
prompt or be dropped. Bookkeeping that only moves a confidence number is
out. Target: under 1,500 lines, one table for nodes plus one for showings
and cites, no model calls inside `runtime pre` or `post`.

**Stated goal, for the mind and the librarian alike: the work must be
internally consistent across projects.** A quantity that two briefs share
(the city's population, the fleet size in 2035, a grid emission factor, a
discount rate, a scenario definition) must carry one value, one unit, one
year and one source everywhere it appears, or a documented reason for the
difference. The trials showed this is where cross-brief work goes wrong
(stale and basis breaks recurred in every brief of run B), and it is the
one thing the per-brief files cannot see on their own. It is made explicit
in four places:

- *Charter.* A sentence in `project/charter.md` naming consistency across
  briefs as a goal of the same rank as sourcing, and a rule: before a
  shared quantity is set in a new brief, look it up in the shared-values
  record and either reuse it or record why not.
- *Store.* `fact` nodes carry a `shared:<quantity>` tag when a value is used
  by more than one brief, plus the fields unit, year, scenario and the file
  that writes it. The librarian keeps `project/shared-values.md` as a
  generated ledger of these facts: one row per quantity, the value each
  brief uses, where it is read from, and a flag when two briefs disagree.
- *Pack.* A short [SHARED VALUES] section on every wake whose task text or
  files touch a shared quantity: the ledger rows for those quantities,
  before any other task memory. At a brief's start, the whole ledger.
- *Checks.* The reviewer's closed class list keeps `stale` and `basis`, and
  the adversary and cold-eyes roles get an explicit instruction to check
  every shared quantity against the ledger. The runtime runs a mechanical
  check at each ritual: every number in the ledger against the file it is
  read from, and every disagreement between briefs raised as a
  CONSISTENCY signal until a journal entry resolves it (same value, or a
  documented reason). The final evaluation's cross-brief consistency ledger
  (already in the A/B/C plan) measures the outcome.

**Store.** Four node types: `fact` (a sourced, reviewed value), `skill` (a
resolved failure), `decision`, `lesson`. Each has a summary, body, tags
(`brief:`, `area:`, `ctx:`, `fail:`), provenance (review file or run id),
created, and three counters: shown, cited, reviewer-confirmed. No
confidence, no status beyond active/superseded. Episodes are not stored;
the journal is the episode log.

**Writing, with the main model out of the loop where the runtime already
has the data.** The runtime parses the reviewer's `Claim verdicts:` block
today. It should also create the `fact` nodes from SURVIVES claims itself,
with the claims file line as the body and the review as provenance. That
removes most of D's 48 `propose` calls per day. The mind proposes only
skills (after a resolved failure) and decisions. Lessons are written at two
moments only: the daily ritual (at most one) and a brief's close (one
retrospective, tagged with that brief and the classes it saw).

**Pack, at most about 2,000 tokens.** Fixed order so the cached prefix
holds: identity and preferences as plain text from `project-pristine/`;
then [LESSONS]: up to 3 lessons for the wake's `ctx:` and the current
brief's recurring `fail:` classes, rotating ties by least recently shown;
then [FACTS AND SKILLS]: top 8 by a transparent score (tag match, then
cited/shown ratio, then recency with a half-life measured in hours, not
months), same brief first, earlier briefs' facts about shared inputs
allowed. Everything else by `search`. No LLM in the ranker; if a rank model
is ever added back, its omission must demote, never drop, a tag or text
hit. Export once per ritual, not per wake.

**Judging lessons without a sign error.** Judge the class, not the claim.
At each brief's close the runtime counts, per `fail:` class, broken or
weakened claims per review in that brief and compares with the previous
brief. A lesson tagged with a class whose rate fell is marked confirmed; one
whose class rose is marked for rewrite in the next retrospective. This uses
data the runtime already collects, costs no model call, and cannot blame a
lesson for a review that found an unrelated problem. "Lessons applied" lines
stay as the mind's record and as a measure, not as credit.

**Signals, three only.** CAPTURE (a failure resolved after two tries, cleared
by a skill or by naming an existing one), LESSON DUE (brief close without a
retrospective, shown at most 3 wakes), PREMORTEM DUE (brief start until
`risks.md` has the section). The prompt's memory instructions shrink from
about 900 words to about 250.

**Harness fixes before any trial starts**, because they ended C and D:
- Container scratch capped: run shellm containers with `--tmpfs /tmp:size=4g`
  or clean `/tmp` at each wake's end; one kit's scratch must not be able to
  fill the disk.
- A wake that fails to write `wake_at` must retry or the dispatcher must
  re-arm from a default; a disk-full error must raise an operator alert
  rather than silence.
- Disk at 256 GB, with a check in the hourly `status` that stops the run at
  90% instead of corrupting it.
- Both arms on the same reviewer prompt, with the control arm getting the
  verdict block too, so in-run broken-claim rates are comparable.
- Run the control and the memory arm to day 7 before changing the design
  again; one run per arm, reported as suggestive.

**Measures (unchanged from D's plan, with two additions).** M1 broken or
weakened claims per reviewed claim by brief; M2 per-class rates by brief;
M3 the slope across briefs. Add: per-wake tokens the memory system costs
the mind (output tokens spent on `propose`, `search`, `fetch`, lesson text)
and a count of `search` calls whose hit was cited in the same wake, the one
measure that distinguishes "memory helped" from "memory was shown".
