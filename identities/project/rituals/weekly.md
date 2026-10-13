Weekly ritual for project week {{week}}. This is the one function of this
wake (or of several wakes, if it needs them), and it outranks normal work.
Do the steps in order. The runtime tracks two files: the review and the
report.

1. Cold-eyes review. If project/reviews/week-{{week}}.md does not exist,
   create it with:
       blind --role coldeyes --out project/reviews/week-{{week}}.md
   The reviewer sees only spec.md, project-memory.md, journal.md and
   questions.md. Do not add your own commentary to its file.
2. Promote a project skill to generic only if it is genuinely
   project-agnostic: `librarian propose --type skill --tags scope:generic
   ... --supersedes <project skill id>`, reworded away from any
   project-specific assumption. Lean toward cutting.
3. Introspect on your working identity (`librarian identity list
   --working`). For each node, ask whether it has actually changed your
   behavior or is only aspirational. Retire or supersede with `librarian
   identity edit --occasion weekly ...` (one edit per week at most). When in
   doubt, change nothing.
4. Bring project/deliverable.md up to date with everything learned this
   week, including the cold-eyes findings you accept.
5. Write project/reports/week-{{week}}.md with these sections:
   - Summary: three to five plain sentences on what moved forward.
   - Completed this week: specific, checkable items, each pointing at its
     journal entry.
   - Deviations from plan, and why.
   - Questions closed this week: for each, whether a human answered or a
     default was used, and what it changed (project/questions-summary.md
     has the full list). Every default applied and every interpretation
     call made this week, with its risk.
   - Open questions: blocking ones first, each with its Default-by date
     and the default that will apply.
   - Self-assessed confidence: what you are sure of and what is tentative.
   - Changes to memory and working identity: what `librarian stats --week
     {{week}}` shows (memories proposed, confirmed, disputed; suggestions
     accepted), what changed and why, or "none".
   - Cold-eyes review result: a summary of reviews/week-{{week}}.md,
     including anything it flagged that you disagree with and why. Turn
     each finding you accept into a journal entry with Status: in-progress.
   - Deliverable: what changed in it this week, and how far it is from a
     complete answer to the spec given the days left in the run.
   - Plan for next week, and what would change it.
