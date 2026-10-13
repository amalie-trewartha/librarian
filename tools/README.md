# tools/

Everything you run around the mind rather than inside it. The mind's own
tools live in [bin/](../bin/).

- `librarian-init` is the one-time bootstrap: interview, first identity,
  first thoughts.
- `identity` creates and manages identities, and `persona` talks to and
  manages an identity by name from anywhere.
- `librarian-web` serves the dashboard, and `librarian-slack-bridge` and
  `librarian-telegram-bridge` connect chat platforms into the mind.
- `shellm-docker-broker` is the host-side policy server for brokered
  Docker. It is never present in the mind's environment.
- `librarian-skills` is the skills package manager (search, install, check,
  init, promote, kernel, remotes). The mind's own `skills` only lists,
  shows, and renders skills, and forwards those subcommands here.
- `shellm-explore` visualizes run trees, `pr-committee` runs multi-model
  PR reviews, and `librarian-killall` stops every Librarian-related process.

The `shellm-*` symlinks are back-compat aliases from the 2026-08-19
rename to `librarian-*` names.
