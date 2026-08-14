# Operating shellm as a coding agent

This file is for coding agents (Claude Code, Cursor, and similar) working
in or with this repo. It covers installing shellm without a tty, checking
that it is healthy, and the sharp edges that are not obvious from the code.

## What you are operating

shellm creates a persistent identity (a "person") whose mind is a loop of
LLM calls run by a dispatcher. The identity has a name (default `ada`),
and that name becomes a shell command. A local web dash shows the mind's
trajectory.

## Install without a tty

The installer asks no questions when there is no tty; every answer comes
from an environment variable or a default. A key must be in the
environment:

```bash
export OPENROUTER_API_KEY=sk-or-...   # or ANTHROPIC_/OPENAI_/GEMINI_API_KEY
curl -fsSL https://raw.githubusercontent.com/laude-institute/shellm/main/install.sh | bash
```

Optional variables: `SHELLM_IDENTITY_NAME`, `SHELLM_IDENTITY_VIBE`,
`SHELLM_IDENTITY_FOCUS`, `SHELLM_IDENTITY_USER` (the interview answers),
`SHELLM_MODEL` (pins the model; otherwise picked per provider),
`SHELLM_NO_DASH=1`, `SHELLM_NO_THINKERS=1`. The installer never uses
sudo. In a container as root it apt-installs its own dependencies.

Warning: the installer symlinks tools into `~/.local/bin`. On a machine
where those names already link into a development checkout, the one-liner
repoints them to `~/.shellm/app`. Do not run it against a HOME you did
not create for it.

## Check the outcome

`~/.shellm/status.json` is written at the end of every install run:

```bash
jq -r '.identity, .mind.status, .dash.status, .dash.url' ~/.shellm/status.json
```

`mind.status` and `dash.status` are `ok`, `failed`, or `skipped`. The
file is a snapshot of that run; the live check is the pid files it names
(`.mind.pid_file`, `.dash.pid_file`) — a pid that is present and alive
means the process is running. `<name> status` prints the same picture for
humans.

`dash.url` works from wherever shellm is installed. When `container` is
true, the URL is container-internal: from the host, use localhost with
whatever host port was published (`docker run -p <host>:8080`) — the
container cannot know that number.

## Talk to the identity

```bash
ada hello                  # bare words are a message; waits for the reply
ada say "longer message"   # same, explicit
ada status                 # mind and dash state
ada stop / ada start       # pause and resume the mind
ada dash                   # print or open the dash URL
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
- `chat send` dies without a sender name; it comes from the identity's
  own chatrc (`<identity>/chat/.chatrc`, seeded by shellm-init), not from
  a `.chatrc` in the current directory.
- The installer and shellm-init are idempotent: re-running is safe, keeps
  the key and the identity, skips the interview, and restarts the mind
  and dash. Re-runs never block on a prompt when a key already worked
  once, so unattended restarts (for example a restarted container) are
  safe.
- The dash binds localhost by default and `0.0.0.0` in a container.
  A failed dash does not fail the install; check `dash.status` in
  `status.json` and `~/.shellm/logs/web.log`.
