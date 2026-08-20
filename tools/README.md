# tools/

Everything you run around the mind rather than inside it. The mind's own
tools live in [bin/](../bin/).

- `shelly-init` is the one-time bootstrap: interview, first identity,
  first thoughts.
- `identity` creates and manages identities, and `persona` talks to and
  manages an identity by name from anywhere.
- `shelly-web` serves the dashboard, and `shelly-slack-bridge` and
  `shelly-telegram-bridge` connect chat platforms into the mind.
- `shellm-docker-broker` is the host-side policy server for brokered
  Docker. It is never present in the mind's environment.
- `shellm-explore` visualizes run trees, `pr-committee` runs multi-model
  PR reviews, and `shelly-killall` stops every Shelly-related process.

The `shellm-*` symlinks are back-compat aliases from the 2026-08-19
rename to `shelly-*` names.
