Weekly ritual for project week {{week}}. This is the one function of this
wake (or of several wakes, if it needs them), and it outranks normal work.
Do the steps in order. The runtime tracks two files: the review and the
report.

1. Cold-eyes review. If project/reviews/week-{{week}}.md does not exist,
   create it with:
       blind --role coldeyes -f project/spec.md -f project/deliverable.md -f project/project-memory.md -f project/journal.md -f project/questions.md -f project/shared-values.md --out project/reviews/week-{{week}}.md
   The reviewer sees only those files. Do not add your own commentary to
   its file.
2. Reconcile the shared values across every brief so far: read
   project/shared-values.md whole, settle every CONFLICT row, and check
   that each brief's deliverable section uses the ledger's values (or
   states why it differs). Record what changed in project-memory.md.
3. Bring project/deliverable.md up to date with everything learned this
   week, including the cold-eyes findings you accept.
4. Check that each brief has its retrospective (`librarian search --type
   retrospective`). A brief whose whole answer is standing and that has
   none gets one: what you would redo, what cost the most, which shared
   values and methods carry to later briefs, and the failure classes its
   reviews found most.
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
   - Memory and shared values: what `librarian stats --week {{week}}`
     shows (facts, skills, lessons written; shared values and conflicts),
     which shared quantities were reconciled this week and how.
   - Cold-eyes review result: a summary of reviews/week-{{week}}.md,
     including anything it flagged that you disagree with and why. Turn
     each finding you accept into a journal entry with Status: in-progress.
   - Deliverable: what changed in it this week, and how far it is from a
     complete answer to the spec given the days left in the run.
   - Plan for next week, and what would change it.
