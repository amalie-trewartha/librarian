# Trial v2: a librarian arm against five independent fresh projects, 72 hours, five briefs

Written 2026-10-31, before the runs start. Measures and decisions are fixed
here; anything changed after the start is recorded under "Deviations".

## The question

Does a memory system that carries facts, lessons and shared values across
projects make a series of related projects better and more consistent
than the same projects done independently? The comparison point for the
librarian is not "one agent without memory doing five projects in a row"
but five projects done independently, across time, by fresh agents: that
is what a research group without shared memory looks like.

## Arms

Every brief is a **fresh project** in both arms: a new `project/`
directory initialized from the brief as its spec, the previous project
archived out of the mind's reach (`<kit>/archive/`). What carries across
briefs:

| Kit | Arm | Carries across briefs |
|---|---|---|
| `~/kit-a` | memory | the librarian store only: facts (including those the runtime wrote from reviewer verdicts), skills, decisions, lessons, and the shared-values ledger rendered into each new project |
| `~/kit-b` | control | nothing (`librarian-project init --no-memory` each time): five independent projects |

Everything else is identical: the same five briefs at the same project
times, the same charter (which states the consistency goal and asks for
a parameter table in both arms), the same rituals minus librarian steps,
the same adversary role and `Claim verdicts:` block, Opus 5.5 main and
Haiku 4.5 delegate on Bedrock, $200 per rolling real 24 hours with the
budget hold at 0.8, pacing off, a 14-day project clock per project and a
stop at project day 7 of the kit's clock. The kit names are neutral
because the kit path appears in every wake prompt; `<kit>/trial/ARM`
says which is which.

One known leak, symmetric across arms: the identity's trajectory (the
mind's stream) persists across briefs, so the first wake of a new brief
sees the last few steps of the old one. The old project's files do not.

## Clock

`PROJECT_TIME_SCALE=2.3333`: 7 project days in 72 real hours. A project
day is 10 h 17 min real; the daily ritual (21:00 project time) comes
about every 10.3 real hours. Briefs start at kit project days 0, 1.5,
3.0, 4.25 and 5.5, so each brief gets 1.5, 1.5, 1.25, 1.25 and 1.5
project days (15.4, 15.4, 12.9, 12.9 and 15.4 real hours). Both arms
start within a few minutes of each other. The scheduler is pause-safe:
a VM pause shifts every unstarted brief and the stop by the same amount,
per kit.

## The briefs

Five standalone briefs about one program: Fort Collins, Colorado
(named, so independent projects are about the same place), three futures
described in the same words in every brief (Baseline, Electrify, Shared)
and the same reporting years. No brief refers to another or tells the
agent to reuse anything. They overlap by construction: each needs the
city's households, fleet by powertrain, travel, price paths and futures
quantified, and the later ones also need a tariff, a charging profile,
a grid emission factor, a discount rate and a social cost of carbon.

1. Fleet and travel to 2045.
2. EV charging and the local grid.
3. Energy, emissions and air quality of travel.
4. What households pay, and who gains.
5. A policy package for the city council: one scorecard across travel,
   grid, emissions and household costs, with an inputs register.

A memory arm that works will quantify the futures once and reuse them;
five fresh projects will quantify them five times.

## What the memory arm has

- A pack of at most 2,000 tokens every wake: core identity and
  preferences (the control gets these as files), up to three lessons
  chosen by the wake's situation, the shared values the wake touches,
  and up to eight facts, skills or decisions ranked by tag and text
  match, use rate and recency. No episodes, no model call in the ranker.
- Facts written by the runtime from every claim the adversary marks
  SURVIVES, tagged with the brief and any `shared:` tag the claim carried.
- `project/shared-values.md`, generated from facts tagged `shared:`,
  present from a new project's first wake; CONSISTENCY signals until a
  conflict between briefs is reconciled; the cold-eyes reviewer gets the
  ledger as a file.
- LESSON DUE once per brief close, PREMORTEM DUE per brief start,
  CAPTURE after a resolved repeated failure; lessons judged at a brief's
  close by whether the failure class they guard against fell or rose.

## Measures (fixed before the start)

Primary, at evaluation time, blind, the same frozen reviewer prompt for
both arms (the earlier A/B/C evaluator setup: a non-Anthropic model on
Bedrock, labels shuffled, three scorings):

- **M1 Consistency across projects.** From each arm's five project
  snapshots, a ledger of every quantity two or more projects use
  (households, fleet by powertrain and year, VKT, price paths, tariff,
  charging profile, grid factor, discount rate, social cost of carbon,
  the futures' defining numbers): the share of shared quantities that
  agree across projects or differ with a recorded reason, and the number
  of unexplained contradictions that reach a headline number. Computed
  by the evaluator from the deliverables and parameter tables, not from
  either arm's own register.
- **M2 Broken-claim rate by brief.** A fixed random sample of each
  project's deliverable claims re-reviewed blind; broken or weakened per
  claim reviewed, by brief, and its slope across briefs.
- **M3 Rubric per brief** (1 to 5, each with a quote): answers the brief;
  method soundness; evidence; validation and uncertainty; clarity.
  Reproducibility scripted (clean clone, documented command, exit code).
- **M4 Time to a crude end-to-end answer** per brief, from the project
  git history, and whether a rerun script exists at the end.

Secondary, in-run, from the stores, trajectories, ledgers and git:

- Memory arm: `shared:` facts written; conflicts raised and reconciled
  and the wakes between; pack tokens per wake; same-wake cite rate by
  section; searches whose hit was cited in the same wake; lessons
  written, shown, cited, confirmed or recurred; facts the runtime wrote
  from verdicts and how many were later cited.
- Both: in-run broken or weakened claims per reviewed claim by brief
  (same reviewer prompt), cost per wake, output tokens per wake, blind
  review share of spend, budget-hold hours, wakes per brief.

One run per arm. Differences are reported as suggestive, with the
confounds below.

## Known confounds

- One run per arm; no estimate of between-run variance.
- Both arms share the VM, the Bedrock account and the clock; the VM has
  8 GB for two minds.
- The memory arm's prompt is longer (one section on the pack); its cached
  prefix pays once per wake.
- A control agent may reach consistency by re-deriving from the same
  public sources. That is a legitimate way for independent projects to
  agree, and M1 counts it.

## The 2-hour smoke trial

Before the real run, the same two kits at `TIME_SCALE=84` (7 project
days in 2 hours; briefs at real minutes 26, 51, 73 and 94; stop at 120)
with `SCRATCH_GB=8`, on the VM, to check: wakes flow in both arms; the
scheduler starts each brief as a fresh project and the old one is
archived; the memory arm's store survives the switch and its new project
has `shared-values.md`; facts appear from SURVIVES claims; the control
arm has no store and no librarian lines in its prompt; the end-at stop
drains both arms; the guard logs disk and scratch; cost per wake is in
the range of runs B to D. Pass criteria are checked by
`trials/v2/check.py` on both kits. The smoke kits are then removed and
the real run set up fresh.

## Running it

```bash
# on the VM, from /agent-workspace (branch librarian-v2)
cp trials/v2/bedrock.env.example trials/v2/bedrock.env   # fill in the key
for k in kit-a kit-b; do trials/v2/launch.sh $k check && trials/v2/launch.sh $k setup; done
for k in kit-a kit-b; do
  trials/v2/launch.sh $k start
  nohup trials/v2/scheduler.sh --kit ~/$k >/dev/null 2>&1 &
  nohup setsid trials/v2/end-at.sh --kit ~/$k >/dev/null 2>&1 &
done
nohup trials/v2/guard.sh >/dev/null 2>&1 &
trials/v2/scheduler.sh --kit ~/kit-a --dry-run         # the brief times, project and real
python3 trials/v2/check.py ~/kit-a ~/kit-b              # health and pass criteria
```

For the smoke trial, prefix `setup` with `TIME_SCALE=84 SCRATCH_GB=8`.

Hourly check: `launch.sh <kit> status` for both, `tail ~/trial-guard.log`,
disk under 85%, both schedulers alive, no NO MODEL CALL line.

## Deviations

(none yet)
