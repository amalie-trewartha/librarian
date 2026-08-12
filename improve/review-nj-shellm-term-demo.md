# Review notes: nj/shellm_term_demo

_Pre-read corrected 2026-08-05T22:40:29Z. Branch verified alive (3 commits ahead, 89 behind main)._

## ⚠️ Diff direction matters

The first version of these notes used `git diff main..branch` and described a
"large structural refactor" deleting `bin/identity` (371 lines), `bin/recap`
(453 lines), etc. **That was wrong.** Because the branch is 89 commits BEHIND
main, `diff main..branch` shows all of main's recent work as "deletions" —
none of that is Nick's work.

The correct diff is from the **merge-base** (fork point) to the branch tip:

    git diff $(git merge-base main origin/nj/shellm_term_demo)..origin/nj/shellm_term_demo

## Commits ahead of main (Nick's 3 commits)
7d419d3 wi
f5367b6 another take; v8
9f3badd wip

## Nick's ACTUAL work (merge-base diff)
2 files changed, 45 insertions(+), 19 deletions(-)

### Files
- **TERMINAL_DEMO.md** (new, 1 line) — a pointer: "See ~/laude/notes/20260714/demo/NOTES.md"
- **bin/shellm** (modified, +44/-19) — changes to the system prompt and run_loop

### What bin/shellm actually changes
- Adds a "Current run" section to the system prompt with transient run dir,
  trajectory ID, and reminder that traj/sub-run monitoring use $TRAJ_DIR/$TRAJ_ID.
- Removes "Show the code being executed" logic (code_lines display) from run_loop.
- Removes progress lines: "Trajectory: ..." and "Workdir: ..." from run_loop.
- Minor doc/table edits in the system prompt (e.g. workdir default phrasing).

## Review points
1. Removing the "Show the code being executed" and progress output — is this
   intentional for the demo (cleaner terminal output) or should it stay?
2. TERMINAL_DEMO.md points to a local path that only exists on Nick's machine —
   fine for a WIP demo branch, but worth noting before merge.
3. All 3 commit messages are WIP ("wi", "another take; v8", "wip") — will need
   squashing/cleanup before merge.
4. The branch is 89 commits behind main — Nick will need to rebase/merge before
   this is reviewable.
5. The system-prompt additions look reasonable and additive. No obvious risk.
6. The removed progress lines may affect debugging — worth confirming Nick
   has another way to see traj/workdir info.

## Open questions for Nick
- Is this branch meant to be a demo-specific build of shellm, or a permanent
  change to bin/shellm?
- Should the progress/code-display removals stay or are they demo-only?
- When you've finished iterating, want me to do a focused review of the
  bin/shellm changes?
