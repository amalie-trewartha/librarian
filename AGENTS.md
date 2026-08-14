# Operating shellm as a coding agent

This file is for coding agents (Claude Code, Cursor, and similar). It
covers installing shellm without a tty, checking that it is healthy, and
the sharp edges that are not obvious from the code.

shellm creates a persistent identity whose mind is a loop of LLM calls
run by a dispatcher. The identity has a name (default `ada`), and that
name becomes a shell command. A local web dashboard shows the mind's
trajectory.

## Install without a tty

With no tty the installer asks nothing; every answer comes from an
environment variable or a default. A key must be in the environment:

```bash
export OPENROUTER_API_KEY=sk-or-...   # or ANTHROPIC_/OPENAI_/GEMINI_API_KEY
curl -fsSL https://raw.githubusercontent.com/laude-institute/shellm/main/install.sh | bash
```

Optional variables: `SHELLM_IDENTITY_NAME`, `SHELLM_IDENTITY_VIBE`,
`SHELLM_IDENTITY_FOCUS`, `SHELLM_IDENTITY_USER` (the interview answers),
`SHELLM_MODEL` (otherwise picked per provider), `SHELLM_NO_DASH=1`,
`SHELLM_NO_THINKERS=1`. The installer never uses sudo. In a container as
root it apt-installs its own dependencies.

Warning: the installer symlinks tools into `~/.local/bin`. If those names
already link into a development checkout, the one-liner repoints them to
`~/.shellm/app`. Do not run it against a HOME you did not create for it.

## Check the outcome

The installer writes `~/.shellm/status.json` at the end of every run:

```bash
jq -r '.identity, .mind.status, .dash.status, .dash.url' ~/.shellm/status.json
```

`mind.status` and `dash.status` are `ok`, `failed`, or `skipped`. The
file is a snapshot of that run; the live source of truth is the pid files
it names (`.mind.pid_file`, `.dash.pid_file`). `<name> status` prints the
same picture for humans.

`dash.url` works from wherever shellm is installed. When `container` is
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

- `~/.shellm/` — state root (`SHELLM_HOME`): `.env` (key + model),
  `status.json`, `logs/` (`init.log`, `web.log`), `run/web.pid`,
  `app_dir` (path to the checkout).
- `~/.shellm/app/` — the checkout, when installed by the one-liner.
- `<app>/.identities/<name>/` — the identity: persona, memories,
  trajectory, `run/dispatcher.pid`, and its `activate` script.

## Sharp edges

- Any script that sources an identity's `activate` must first load
  `<app>/.env` and then `~/.shellm/.env` (see `_load_env` in
  `bin/persona`). Sourcing `activate` bare makes the think model fall
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
  `status.json` and `~/.shellm/logs/web.log`.
