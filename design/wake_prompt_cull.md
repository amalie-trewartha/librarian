# Wake prompt cull: skills section and stream pairs

Decided with Nick on 2026-09-04, from a real wake prompt rendered with every
section present (`~/laude/notes/20260904/wake-prompt-example.md` and the
commented copy next to it).

## What was wrong

- `skills prompt` had exited 1 with no output since 2026-08-15 20:08 UTC. A
  grep miss on a SKILL.md with no frontmatter (Audel wrote one that day)
  aborted the script under `set -e -o pipefail`. The thinker library ran it
  with stderr discarded and fell back to an empty string, so every wake prompt
  lost its skills section and nothing said so. 5,051 prompts.
- Had it worked, it would have been worse. With MEM_DIR set as in a real wake,
  the kernel mem skill's `mem list --short` block dumps every memory: 91K of a
  102K section on Audel, about 25K tokens a wake.
- The kernel goals skill's "current goals" block never printed anything: its
  printf format starts with a dash, bash reads it as an option, and the block
  hides stderr. The monolith's own active-goals section is the working one.
- The kernel chat skill told the mind to reply with `chat reply`. The monolith
  prompt says replying is not its job and the responder prompt says never
  write `chat reply`. Both thinkers got a section that contradicted them.
- The recent stream carried the same report twice per work run: the prompt
  asks for an observation after the work and a final at the end, and told the
  model the final "is all your next wakeup sees", so the model wrote the
  handoff into both. 7 of 20 stream slots, about 7K bytes a wake.

## What changed

1. `frontmatter_field` in `bin/skills` never fails. The prompt action uses it.
   A skill with no frontmatter is listed by directory name.
2. A wake prompt section that fails to build is loud. `_prompt_section` in
   `thinkers/_lib/common.sh` prints the failing command to stderr and appends
   an `error` step (reason `prompt-section-failed`) to the root trajectory, at
   most one per section per hour. `tests/test_prompt_section_failure.sh`.
3. The skills section is two lines and a list. No kernel body is inlined, the
   CLI table is gone, and each skill costs one line until `skills show` asks
   for it. Kernel skills are the identity's built-in set and are listed like
   the rest. About 2.5K bytes on Audel, down from 102K.
4. `skills/goals` and `skills/file-tools` are deleted. Goals live in the
   identity file and the monolith's active-goals section. file-tools
   advertised view, put, sub and glob, removed on 2026-09-04. `skills/mem`
   keeps its command reference and loses the memory dump.
5. The recent stream drops the observation that a final duplicates: when a
   final arrives, the nearest earlier observation with the same run id is
   removed. Earlier observations in a long run stay as milestones. An
   observation whose run never reached a final stays as its only record.
   The rule runs before the tail cut, so THINK_CONTEXT_TAIL still counts
   distinct events. `tests/test_recent_stream_filter.sh`.
6. The monolith prompt now asks for a one-line observation stating the fact,
   with the handoff in the final, and no longer claims the stream shows only
   finals.

## Deploy notes

On the box: remove the dangling `kernel/goals` and `skills/file-tools`
symlinks under `.identities/audel`. No dispatcher restart; the thinker
library is read per wake. Confirm a new prompt step contains `## Skills`
and no `prompt-section-failed` error step follows the deploy.

## Left open

- Memories: how to surface them in the wake prompt without a dump. Nick is
  thinking about it.
- The kernel chat skill still carries reply instructions that neither thinker
  should follow. It is now on demand only. Rewrite or delete later.
- Runs that never reach a final leave only their observations, and long
  observations survive the pairing rule. If they turn noisy, a lower content
  cap for observations in `_recent_stream` is one line.
