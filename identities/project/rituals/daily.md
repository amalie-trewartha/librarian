Daily ritual for {{date}}. This is the one function of this wake, and it
outranks normal work. It is bookkeeping, not research: do it in a few
steps (aim for five or fewer), touch only what changed today, and get back
to the work. (A cold-eyes review of an earlier run judged its week two
thirds process and one third substance.) Carry out all four steps, in order:

1. Curate project/journal.md. Merge or trim redundant entries from today.
   For each entry marked done, check that it meets the definition of done
   for its kind of task (a sourced number, a checked calculation, a
   reviewed section, not just "wrote something"). Re-tag as blocked
   anything that is really blocked. Do not delete history: mark superseded
   entries superseded.
2. Curate project/questions.md. Close questions the project has moved
   past as moot. Apply any human answer, and any default whose date has
   passed, exactly as the charter describes, with a Resolution line. Check
   that every open question has a Default-by line and still reads clearly
   to a human who has not followed the project, since humans see it in
   their status view.
3. Check the shared values: read project/shared-values.md (or `librarian
   shared`). Any row marked CONFLICT, or any quantity this brief uses that
   disagrees with an earlier brief's value, is settled now (supersede the
   wrong fact and fix the files that read it, or tag the fact
   `scope:reconciled` with the reason both stand) and recorded in
   project-memory.md. A quantity this brief established that later briefs
   will need, and that has no `shared:` fact yet, gets one.
4. Write project/daily/{{date}}.md, answering each of these:
   1. What did I actually finish today, in checkable terms? Not "worked on
      X", but what is now true that was not true this morning.
   2. What in today's work am I least confident about, and why?
   3. Did I make any assumption today that is not yet logged in
      project-memory.md or questions.md? Log it now.
   4. Would a skeptical reviewer push back on anything I did today? Answer
      the pushback, or flag it.
   5. Compare today's output with spec.md. Is anything drifting from what
      was actually asked?
   6. Rate today 1 to 5 on "did I make real, checkable progress" (output,
      not effort).
   7. Does a crude end-to-end model exist that produces the headline
      number? If not, building it is tomorrow's first task. Is
      project/deliverable.md current with what I know tonight? If
      not, say what it is missing (and fold it in before the next ritual).
   8. The single most valuable next step for tomorrow, toward the
      deliverable, concretely.

5. If today taught a lesson with evidence behind it that would change how
   you work, write at most one: `librarian propose --type retrospective
   --summary "When <situation>: <what to do>" --tags area:process ctx:<situation>
   fail:<class> --body-file <f>` naming the evidence (review files,
   commits). Usually none. A brief whose whole answer is standing and that
   has no retrospective yet gets one now.

The runtime counts the ritual as done when project/daily/{{date}}.md
exists, and commits project/ after the wake.
