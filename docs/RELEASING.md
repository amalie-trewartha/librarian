# Releasing

How to cut a tagged release on GitHub before an announcement goes live.
This is a playbook, not automation: every step is a command a person runs.

## Why tag at all

An announcement points people at the repo. Without a tag, "the thing we
announced" is whatever `main` happens to be when they look, and it moves
the moment anyone merges. A tag fixes that:

- Readers and bug reports can name the exact version they tried.
- The install one-liner can be pinned to the tag, so a later change to
  `main` cannot break the command in the blog post.
- The GitHub Releases page gives the announcement a stable link with notes.
- If something lands on `main` after the tag that we regret, the tag is
  the known-good point to compare against or roll back to.

This is the normal practice for an open source launch: tag, write release
notes, then announce. The tag is cheap and can be deleted if needed.

## Naming

Use SemVer with a `v` prefix: `v0.1.0`. The manifests already say 0.1.0
(`web/pyproject.toml`, `slack/pyproject.toml`, `telegram/pyproject.toml`,
`tui/headlong/Cargo.toml`), so the first tag matches them. Below 1.0
signals "early, expect change", which is honest for a launch. Later
releases bump the middle number for features and the last for fixes.

There is no CHANGELOG file yet. Release notes live on the GitHub release;
start a `CHANGELOG.md` only if releases become regular.

## Before tagging: checklist

Work through this on the commit you intend to tag. Do not tag until every
line is true.

1. CI is green on that commit (`gh run list --limit 3`). Note that CI runs
   on pushes to `main` and on PRs, not on tags, so the green run is the one
   for the commit itself.
2. Audel's box is deployed to the same commit and healthy
   (`SHELLM_TF_STACK=terraform-slack deploy/scripts/status` shows the SHA).
   Announcing a version that differs from what the live demo runs invites
   confusion.
3. The secret scan is clean and the two keys it found still live (SerpAPI,
   NewsAPI, from the root commit `.env`) have been revoked. Tagging makes
   history easier to browse, not harder. If the history purge of that
   `.env` is ever going to happen, do it before the first tag, because a
   rewrite after tagging invalidates the tag.
4. README numbers and claims match the announcement draft (line count,
   install steps, model names). The install one-liner in the README works
   from a clean machine: `tests/smoke_install.sh` covers both modes, and a
   real run in a fresh container is the final proof.
5. The working tree is clean and `main` is pushed. The tag should point at
   a commit that exists on GitHub.
6. Decide what the announcement links to: the repo (floating), the tag
   (fixed), or both. Recommendation: link the repo for browsing and pin the
   install command to the tag.

## Cutting the release

Nick runs these (Claude drafts, Nick commits and pushes, as usual).

1. Pick the commit and create an annotated tag on it:

       git tag -a v0.1.0 <sha> -m "Headlong v0.1.0: first public release"
       git push origin v0.1.0

   An annotated tag (`-a`) records who tagged and when, and GitHub treats
   it as the release's own object. A lightweight tag works too, but the
   annotated one is the convention.

2. Write release notes by hand. `gh release create --generate-notes` would
   list every commit since the beginning of time (there is no earlier tag),
   which is noise. Keep notes short and aimed at a newcomer:

   - one paragraph on what Headlong is (reuse the README pitch)
   - the install command, pinned to the tag (see below)
   - three to six highlights worth knowing on day one
   - known limitations and the supported platforms (macOS, Ubuntu)
   - credits and the license

   Save them to a file, for example `/tmp/notes-v0.1.0.md`.

3. Create the release as a draft, so it can be reviewed and published at
   the moment the announcement goes live:

       gh release create v0.1.0 --draft --title "Headlong v0.1.0" \
         --notes-file /tmp/notes-v0.1.0.md

   No binary assets are needed: the project installs from source. The Rust
   TUI is built on the user's machine by `install.sh` when `cargo` exists.

4. Verify from the outside, as a reader would:

       gh release view v0.1.0
       git clone --branch v0.1.0 https://github.com/laude-institute/headlong.git /tmp/hl-v0.1.0
       cd /tmp/hl-v0.1.0 && bash tests/smoke_install.sh

   A clone by tag works because `git clone --branch` accepts tags, which is
   also how the installer pin below works.

5. Publish when the announcement goes out:

       gh release edit v0.1.0 --draft=false

   Publishing marks it "Latest" on the repo page.

## Pinning the install command to the tag

`install.sh` reads `HEADLONG_BRANCH` and passes it to `git clone --branch`,
so a tag works without code changes:

    curl -fsSL https://raw.githubusercontent.com/laude-institute/headlong/v0.1.0/install.sh \
      | HEADLONG_BRANCH=v0.1.0 bash

Both parts matter: the URL fetches the installer from the tag, and the
variable makes it clone the tag. Keep the unpinned `main` command in the
README for people who want the latest; use the pinned one in the
announcement and release notes so that text stays true.

One caveat: with a pinned clone, `install.sh` later runs
`git pull --ff-only origin v0.1.0` on updates, which stays on the tag. That
is the intended meaning of pinning. Users who want to follow `main` rerun
the unpinned command.

## After the announcement

- Watch issues and the CI runs for a day; fixes land on `main` as usual.
- If a fix is urgent for announced users, tag `v0.1.1` with the same
  playbook and update the release notes' install line.
- Consider adding `tags: ['v*']` to the CI `push` trigger if tags should
  get their own CI run. Not needed for the first release since the tag
  points at an already-green `main` commit.

## If something goes wrong

- Wrong commit tagged, release still a draft: `gh release delete v0.1.0`
  and `git push --delete origin v0.1.0`, then `git tag -d v0.1.0` locally,
  and tag again. Nobody saw it.
- Wrong commit tagged, release already published: do not move the tag.
  Moving a published tag breaks everyone who already cloned it. Cut
  `v0.1.1` on the right commit and say so in its notes.
- Announcement went out before the tag: tag the commit that was `main` at
  announce time (`git log --until="<time>" -1 main`) so the tag still
  means "what we announced".

## Open decisions before the first tag

- Revoke the two live keys from the secret scan (SerpAPI, NewsAPI) and
  decide on the `.env` history purge. Both are easier before a tag exists.
- Whether the announcement pins the install command to `v0.1.0` or keeps
  the `main` one-liner. Recommendation above: pin in the announcement, keep
  `main` in the README.
