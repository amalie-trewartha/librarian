# Output budget and tool cull: the mind reads in bash, so show it what it read

Status: 2026-09-04, proposal agreed with Nick. Part 1 (tool cull and skills
split) built the same day; parts 2 and 3 (budget sentence, block band) built
the same evening. Core at 9,747 lines. Nothing deployed yet.
Follows
[wake_prompt_delivery.md](wake_prompt_delivery.md), which fixed the wake
prompt and the sliding window; this document is about the other two things
the same investigation turned up. Relates to
[context_assembly.md](context_assembly.md),
[trajectory_spec.md](trajectory_spec.md), [providers.md](providers.md) for
the core-versus-tools rule.

## What we observed

A run of Audel's on 2026-09-03 (ad6da556, 04:11 to 06:14 UTC) took 313
model calls and two hours to produce one 135-line commit on PR 84, at a
cost of about $6.50. The work was real and the final was a clean handoff.
The steps were mostly reading: 622 reads, 131 edits, 363 test runs, 256
git inspections, and 1,238 `sed -n N,Mp` slice reads with echo markers.
The thought "I'll read the remaining sources in small slices" appears at
05:03, 05:23 and 05:48.

Two facts explain the re-reading.

1. **Every output the model saw had a hole in it.** `bin/context` cuts each
   field to 2K bytes: the first 1K, a stub, the last 1K. The trajectory
   keeps 4K inline (`SHELLM_STDOUT_INLINE_LIMIT`) and spills the rest to a
   blob. In that run 273 of 313 outputs hit the 4K inline cap, so the model
   saw the top and bottom of each slice and never the middle. It used the
   stub's `traj show --full` at most 32 times and re-sliced instead.
2. **The model does not know the budget.** The system prompt says "large
   outputs may be truncated with a stub" with no number, so it sizes reads
   by feel and pays twice.

Over 17 days (2026-08-18 to 09-04, 17,345 outputs, true sizes from the
blobs):

| Cap | Outputs seen whole | Read slices seen whole | Mean bytes seen | 25 outputs |
|---|---:|---:|---:|---:|
| 2K (today) | 21% | 7% | 1.8K | 43K |
| 4K | 39% | 25% | 3.2K | 78K |
| 8K | 67% | 58% | 5.0K | 123K |
| 16K | 90% | 87% | 6.6K | 161K |

Median output 5.2K, p90 16K. Of 2,107 read-slice steps, 958 (45%, an upper
bound that includes some repeated status commands) re-read a file already
read in the same run.

The same 17 days show which tools the mind actually uses:

| Tool | Lines | Calls | What it used instead |
|---|---:|---:|---|
| view | 70 | 212 | `sed -n` 3,067 times |
| put | 43 | 104 | `cat >`, python `write_text` |
| glob | 115 | 299 | `git ls-files`, `find` |
| sub | 119 | 41 | python heredoc edits, about 17,000 |
| focus | 260 | 233 | goals already go through `mem` |
| skills | 1,164 | 460 | the mind needs `prompt`, `list`, `show` only |

The Docker sandbox never mounted view, put, glob or sub. The monolith prompt
sends goals through `mem`, and `get_goals` in the shared library reads them
from memory frontmatter, not from `focus`. Audel's own scripts and skills on
the box call none of the five. Core is at 10,996 code lines against the
11,000 CI cap.

## What we propose

Three changes, shipped in this order. Each stands alone.

### 1. Cull the core tools

Delete `bin/view`, `bin/put`, `bin/glob`, `bin/sub` and `bin/focus`. Split
`bin/skills`: `prompt`, `list`, `list-json` and `show` stay in core (about
200 lines); `install`, `search`, `check`, `promote`, `init`, `kernel`,
`remove` and the remotes machinery move to `tools/headlong-skills`. Same rule as
providers: what the mind needs stays in core, everything else lives in
tools/.

References to fix: the file-tools line in the shellm system prompt, the tool
list in `deploy/slack-persona.md`, the tool arrays in
`thinkers/_lib/common.sh` and `bin/thinkers`, the required list in
`tests/test_thinker_tool_coupling.sh`, and `bin/README.md`.

The guarantees `sub` and `put` encoded (fail on a missing match, write
atomically) were not being delivered because the model did not call them.
One sentence in the system prompt replaces them: check that an edit matched
before writing, and write through a temp file when a half-written file
would matter. No compatibility stubs, as with the headlong rename. One line
in the release note for public installs.

Result: core at 9,706 lines (from 10,996). The manager is
`tools/headlong-skills`; it sources `bin/skills` for the shared helpers, and
`skills <manager subcommand>` forwards to it, so the mind's `skills install
...` keeps working outside Docker. Test: `tests/test_skills_split.sh`.

### 2. Tell the model the budget, and the mechanism

Replace "large outputs may be truncated with a stub" in the shellm system
prompt with the actual rule, kept in step with part 3:

- Outputs from your recent steps show whole up to 8K bytes, about 150
  lines. Size a read to fit.
- Older outputs keep their first and last 1K; the middle is what is cut, so
  head and tail are exact and the stub sits where the hole is.
- The stub names the byte count and the `traj show <id> --full` command
  that prints the whole output. Fetch, do not re-read.

The mechanism sentence matters: a model that knows the middle is missing
can trust the head and tail and reach for the one command instead of
re-slicing to find out what it lost.

### 3. Whole outputs for the current block

`bin/context` under run scope renders a 400-row window whose start snaps
to a 50-row grid (`--tail-block 50`), so the prefix changes once per 25
iterations and is otherwise byte-identical between calls. Split the window
into two bands on that same grid:

- **Current block**, the 50-row block containing the newest row: shell
  outputs render whole up to 8K bytes.
- **Older blocks**: rendered as today, 2K with the stub.

Rows are numbered from the start of the run and a row's block never
changes, so a block shrinks exactly once, on the call where the newest row
first crosses into the next block. Past 400 rows that is the same call on
which the window start jumps, so the two rewrites share one cache reset.
Before 400 rows it is a new rewrite, about 12K uncached tokens once per 25
iterations, about 2 cents at grok prices. The alternative, never shrinking,
costs a 313-step run about 136K extra cached tokens per call by its end;
shrinking amortizes to about 500 tokens per call.

`bin/context` already loads blob contents for truncated fields, so the 8K
render cap does not require raising the log's 4K inline limit.

Worst case at a full 400-row window is roughly 200K tokens today plus
about 20K for the 8K band. Grok 4.6 has a 500K window; observed input since
the 400-row deploy is p50 29K, p90 54K, p99 81K. The ceiling is cost and
attention, not context.

Knobs: `SHELLM_CONTEXT_BLOCK_LIMIT` (bytes, default 8192) for the current
block; the existing `SHELLM_STDOUT_PROMPT_LIMIT` (2048) for older blocks;
`SHELLM_CONTEXT_WHOLE_BLOCKS` (default 1) for how many newest blocks render
whole, in case one is too few. shellm passes them in both scopes: in traj
scope the tail block is 1, so the band is the newest row, which is the output
the model just produced. Built as `context --block-limit` and
`--whole-blocks`; test `tests/test_context_block_limit.sh`. The system prompt
sentence is built from the same variables, so the numbers cannot drift.

## Metrics

All three are computable from the trajectory with no new instrumentation,
because every output's true size is recorded (`stdout_bytes` on spilled
steps, string length otherwise), so the history backfills.

- **Seen whole**: share of outputs whose true size fits the band they were
  rendered in. Baseline 21%.
- **Repeat reads**: share of read steps (sed, cat, head, tail, nl on a file
  path) that name a path already read earlier in the same run. Baseline 37%
  over the whole log, 55% over the last 7 days.
- **Rendered bytes per output** and input tokens per call from the llm
  ledger, so the cost side moves with the other two.

Built 2026-09-04 as the "output budget" section of
`deploy/scripts/audel-metrics` (per day: outputs, whole at 2K and 8K, mean
true and rendered bytes, read steps, re-read share by file path). First run:
last 7 days before the deploy, 6,505 outputs, 15% whole at 2K, 69% at 8K,
re-reads 55% of read steps. Render-level
seen-whole for the 313-step run itself, from its recorded output sizes: 12%
at 2K, 38% at 4K, 63% at 8K, 91% at 16K. A live replay under the new render
is still the test that matters, since the model will size its reads to the
number once it is told. Read the
metrics for a week before widening to two blocks or 16K.

## Not doing yet

A soft iteration budget (a nudge at about 50 steps asking for a handoff
final). Audel's runs since 09-03: p50 4 shell steps, p90 27, 7 runs over 50,
one at 313. The long run's waste was re-reading, which parts 2 and 3
address at the cause. Revisit after a week of metrics.

## Open questions

- Whether 8K is the right cap once the model knows the number and sizes
  reads to it. The 17-day distribution is under a limit it was never told.
- Whether one whole block is enough or the model re-reads across the
  boundary. `SHELLM_CONTEXT_WHOLE_BLOCKS` exists for that.
- Whether repeat reads should be measured by file path or by command text;
  the baseline mixes both.
