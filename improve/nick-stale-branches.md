# Nick's stale branches — 2026-08-05

_audel audit. 4 nj/* branches already merged into main (ahead=0). Safe to delete; Nick may want to rebase if any contain unmerged local work._

| Branch | Last commit | Behind main | Last message |
|--------|-------------|-------------|--------------|
| nj/admin_dash | 2026-07-15 | 90 | deploy cleanup |
| nj/less_jq_calls_in_context | 2026-07-07 | 145 | context: render trajectory in a single jq pass instead of forking per line |
| nj/model_resolution | 2026-07-15 | 88 | fix some default-to-claude settings to enable full openrouter |
| nj/web_viewer | 2026-07-11 | 108 | minor fallback fix in step labeling |

## Notes

- All 4 branches are fully merged into main (ahead=0). No unique commits.
- "Behind" counts show how far main has advanced since the branch was last touched — purely informational.
- **Rebase status:** none needed. These are merge candidates for deletion.
- Suggested action: `git push origin --delete <branch>` for each, after Nick confirms.

## Alive branches (not stale, for reference)

See `improve/nick-branch-digest.md` for the 4 alive nj/* branches with review notes.
