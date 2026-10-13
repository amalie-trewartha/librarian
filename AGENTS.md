# Operating Librarian as a coding agent

This file is for coding agents (Claude Code, Cursor, and similar). It
covers installing Librarian without a tty, checking that it is healthy, and
the sharp edges that are not obvious from the code.

Naming: **Librarian** is the agent framework — identities, thinkers, the
mind log, bridges, the dash — and `librarian` (bare) is its memory system,
the store and context packer in `librarian/` (design/librarian.md).
**shellm** is one tool inside it: the CLI implementation of Recursive
Language Models in bash (`bin/shellm`), plus its run machinery
(`shellm-docker`, `shellm-explore`). Use "Librarian" for the system,
"the librarian" or "the memory system" for the store, and "shellm" only for
that tool. Framework commands are `librarian-*` (`librarian-init`,
`librarian-web`, ...) and framework env vars are `LIBRARIAN_*`.

Librarian was Headlong until 2026-10-13 and keeps back-compat with that
era (design/rename-to-librarian.md): the `headlong-*` command names are
symlinks to the `librarian-*` tools; `HEADLONG_*` env vars are mapped to
`LIBRARIAN_*` by `bin/librarian-env`, which every entry script sources
(`HEADLONG_LIBRARIAN` → `LIBRARIAN_MEMORY`, `HEADLONG_LIBRARIAN_SRC` →
`LIBRARIAN_SRC`); the state home defaults to `~/.librarian`, or
`~/.headlong` when only that exists; the thinker templates likewise prefer
an existing `~/.headlong-thinkers`; the Python packages keep `headlong-web`,
`headlong-slack-bridge` and `headlong-telegram-bridge` as console-script
aliases. Explicit `LIBRARIAN_HOME` or `HEADLONG_HOME` overrides the
default. Systemd units are `librarian-*`; a box provisioned under Headlong
(or earlier) is migrated once with `deploy/migrate-units.sh`, which keeps
both `thinkersctl` wrapper names. Older `SHELLM_*` framework spellings are
honored only where they were before. What deliberately keeps an older name:
the `/opt/shellm` deploy path, the `shellm` and `shellm-telegram` UNIX
users, `~shellm/.shellm`, the per-identity `.shellm/` subdirectory, the
`*.shellm.net` domains, `/var/lib/headlong/identities` on provisioned
boxes, the audit key `headlong-sig`, and the `.pre-headlong-<date>` backup
suffix the installer uses for displaced copies. If you take one of those on,
or any other structural change to a live box, read `deploy/MIGRATIONS.md`
first — it lists the couplings that fail *silently*.

Librarian creates a persistent identity whose mind is a loop of LLM calls
run by a dispatcher. The identity has a name (default `ada`), and that
name becomes a shell command. A local web dashboard shows the mind's
trajectory.

## Install without a tty

With no tty the installer asks nothing; every answer comes from an
environment variable or a default. A key must be in the environment:

```bash
export OPENROUTER_API_KEY=sk-or-...   # or ANTHROPIC_/OPENAI_/GEMINI_API_KEY
curl -fsSL https://raw.githubusercontent.com/amalie-trewartha/librarian/main/install.sh | bash
```

Optional variables: `LIBRARIAN_IDENTITY_NAME`, `LIBRARIAN_IDENTITY_VIBE`,
`LIBRARIAN_IDENTITY_FOCUS`, `LIBRARIAN_IDENTITY_USER` (the interview answers),
`SHELLM_MODEL` (otherwise picked per provider; a tool var, so no LIBRARIAN_
spelling), `LIBRARIAN_NO_DASH=1`,
`LIBRARIAN_NO_THINKERS=1`. The installer never uses sudo. In a container as
root it apt-installs its own dependencies.

Warning: the installer symlinks tools into `~/.local/bin`. If those names
already link into a development checkout, the one-liner repoints them to
`<state-home>/app`. Do not run it against a HOME you did not create for it.

## Check the outcome

The installer writes `status.json` in the state home (`~/.librarian`, or
`~/.shellm` on pre-rename installs) at the end of every run:

```bash
jq -r '.identity, .mind.status, .dash.status, .dash.url' ~/.librarian/status.json
```

`mind.status` and `dash.status` are `ok`, `failed`, or `skipped`. The
file is a snapshot of that run; the live source of truth is the pid files
it names (`.mind.pid_file`, `.dash.pid_file`). `<name> status` prints the
same picture for humans.

`dash.url` works from wherever Librarian is installed. When `container` is
true, the URL is container-internal: from the host, use localhost with
whatever host port was published (`docker run -p <host>:8080`). The
container cannot know that number.

## Talk to the identity

```bash
ada hello                  # bare words are a message; waits for the reply
ada say "longer message"   # same, explicit
ada status                 # mind and dash state
ada stop / ada start       # pause and resume the mind
ada dash                   # print or open the dashboard URL
ada shell                  # a shell inside the identity's environment
```

If the name collides with an existing command, the installer refuses to
stomp it and everything is reachable as `persona <name> ...` instead.
Replies take 15 to 45 seconds while the monolith thinker wakes.

## Where things live

- `~/.librarian/` — state root (`LIBRARIAN_HOME`, legacy `SHELLM_HOME`;
  pre-rename installs use `~/.shellm`): `.env` (key + model),
  `status.json`, `logs/` (`init.log`, `web.log`), `run/web.pid`,
  `app_dir` (path to the checkout).
- `~/.librarian/app/` — the checkout, when installed by the one-liner.
- `~/.local/bin/` — the installed tools (symlinks for the one-liner).
- `~/.skills/core-skills/` and `~/.librarian-thinkers/` — the bundled skills
  and thinker templates that new identities are seeded from.
- `<app>/.identities/<name>/` — the identity: persona, memories,
  trajectory, `run/dispatcher.pid`, and its `activate` script.
- `<identity>/librarian/store.sqlite` — the Librarian memory store for
  project-mode minds (design/librarian.md), with a markdown mirror under
  `librarian/export/`. The code is the stdlib-only Python package in
  `librarian/`, called through `tools/librarian`; the monolith step calls
  `librarian runtime pre` and `runtime post` around every project wake.
  `project/addenda.md`, `project/skills/**` and `project/librarian.md` are
  generated mirrors of the store: never edit them, propose through
  `librarian` instead.

## Project mode

`librarian-project init <name> --spec FILE` turns an identity into an
unattended research agent (design/long_autonomy.md). Its files are in
`<identity>/workdir/project/` (a git repo, committed every wake). The
read-only originals are in `<identity>/project-pristine/`: edit charter
or spec there and run `librarian-project update-pristine <name>`. Never
edit them under `project/`, because the next wake restores them.
`librarian-project status <name>` is the health check, and `ada status`
leads with open questions. Init sets a 2M tokens/day budget
(`PROJECT_DAILY_TOKENS`) and a 14-day end (`librarian-project deadline`
moves it). Budgets can be in tokens (cache reads weighted at a tenth) or in
estimated dollars (`--daily-usd`, `--total-usd`). Humans answer questions with `librarian-project answer`. Do not
write Answer lines yourself: provenance comes from git authorship.
Memory in project mode is the Librarian (design/librarian.md): every wake
gets a budgeted context pack from `<identity>/librarian/store.sqlite`, the
runtime closes an episode with an outcome derived from artifacts, and the
human check-in queue (`librarian-project queue <name>`) decides core-identity
changes. `librarian-project init --preferences FILE` seeds the group's
stated values. The 20,000-line cloc cap on `bin/` + `thinkers/` is checked
in CI; `librarian/`, `tools/` and `tests/` are not counted.

## Sharp edges

- Any script that sources an identity's `activate` must first load
  `<app>/.env` and then the state home's `.env` (see `_load_env` in
  `tools/persona`). Sourcing `activate` bare makes the think model fall
  back to an expensive default with no key.
- `chat send` dies without a sender name. It comes from the identity's
  own chatrc (`<identity>/chat/.chatrc`, seeded by the installer), not
  from a `.chatrc` in the current directory.
- The installer is idempotent: re-running keeps the key and identity,
  skips the interview, restarts the mind and dashboard, and never blocks
  on a prompt once a key has worked, so unattended re-runs (a restarted
  container) are safe.
- The dashboard binds localhost by default and `0.0.0.0` in a container.
  A failed dashboard does not fail the install; check `dash.status` in
  `status.json` and `<state-home>/logs/web.log`.
