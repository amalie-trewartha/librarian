# Review: nj/shellm_term_demo

## Branch stats
- 3 commits: `9f3badd wip`, `f5367b6 another take; v8`, `7d419d3 wip`
- 175 files changed, ~412 insertions, ~14974 deletions
- Diverged from main

## What it does
This is a radical slimming of the web/viewer app — looks like a "terminal
demo" build that strips the viewer down to a minimal surface. Removes:
- `web/viewer/app/routes/recap.tsx`, `talk-chat.tsx`, `talk.tsx` (talk UI gone)
- `web/viewer/app/routes/identity.tsx` (identity UI gone)
- `web/viewer/app/components/model-config.tsx`, `push-bell.tsx`, `navbar.tsx`
  (heavily gutted)
- PWA artifacts: `manifest.webmanifest`, `sw.js`, all `public/icons/*`
- Large reductions in `api.ts`, `types.ts`, `timeline-model.ts`

## Assessment
- **Demo/throwaway build.** Commit messages ("wip", "another take; v8")
  suggest experimental exploration — a stripped viewer to demo the terminal
  concept. v8 indicates many iterations, not a polished feature.
- **Huge deletion surface (14974 lines).** If merged, it would remove
  talk, identity, recap, PWA support, model config — major features. Almost
  certainly NOT meant to merge as-is.
- **Not a safe-delete.** Despite being demo-y, it has 3 commits of work
  and may contain UI patterns Nick wants to revisit. But it's also not a
  candidate for merging — it's a sandbox.

## Recommendation
- **KEEP (for now), but flag as exploratory.** Nick should decide whether
  the terminal-demo concept is worth pursuing. If not, this branch can be
  deleted after extracting any useful patterns.
- **Do NOT merge to main.** This is a sandbox branch, not a feature branch.
- Suggest Nick extract any valuable UI/patterns, then delete if the demo
  direction is abandoned.

## Risk
- Deleting loses the demo work, but the deletions in the branch make
  accidental merge dangerous. Keep labelled clearly so no one merges it
  by accident.
