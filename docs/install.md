# Installing Headlong

The short version is in the [README](../README.md). This page has every
variant.

## The one-liner

```bash
curl -fsSL https://headlong.ai/install.sh | bash
```

It clones the repo to `~/.headlong/app`, symlinks the tools into
`~/.local/bin`, asks for an LLM API key, and runs a short optional
interview: a name, a few words of personality, what they should think
about when idle. The answers become the agent's core identity and first
memories. Then their mind starts and the dashboard opens. Their name
becomes a command:

```bash
ada                  # chat with them
ada hello            # one message, wait for the reply
ada stop / ada start # pause / resume their mind
ada dash             # open the dashboard
ada bugreport        # bundle logs + trajectory (keys scrubbed) for a bug report
```

Use a dedicated, spend-capped API key: the agent executes real shell
commands and calls the LLM continuously.

Re-running the one-liner updates everything in place. The installer never
uses sudo, and the piped script only clones the repo and re-runs the
installer from the checkout, so what executes is the same code you can
read here. To read first:

```bash
curl -fsSLO https://headlong.ai/install.sh
less install.sh && bash install.sh --init
```

## Docker: a long-lived agent

The same installer works inside a container. Nothing touches your
machine, and the agent's shell commands run in the container too. The
installer apt-installs its own dependencies (as root in a fresh
container) and the dashboard binds `0.0.0.0` so the published port works.

```bash
docker run -it --name headlong --restart unless-stopped -p 8080:8080 buildpack-deps:curl \
  bash -c 'curl -fsSL https://headlong.ai/install.sh | bash; exec bash'
```

Paste your key, answer the interview, then open http://localhost:8080 on
your host to watch the mind run. Typing `exit` does not end the world:
Docker restarts the container in the background, the installer re-runs
prompt-free (it keeps your key and identity and pulls the latest code),
and the mind and dashboard come back up on their own.

Day-to-day:

```bash
docker exec -it headlong bash -l   # drop back into your agent's world
docker stop headlong               # pause everything
docker start headlong              # resume
docker rm -f headlong              # delete the agent and its whole world
```

Pasting the run command a second time fails with "name headlong already in
use". That means your agent already exists; `docker exec` is how you get
back to it.

For a throwaway sandbox instead, drop `--name` and `--restart` and add
`--rm`. Exiting the shell then deletes everything.

## Non-interactive install (CI and coding agents)

With no tty, every question falls back to an environment variable or a
default, so a script or a coding agent can install with no interaction:

```bash
export OPENROUTER_API_KEY=sk-or-...   # or ANTHROPIC_/OPENAI_/GEMINI_API_KEY
export HEADLONG_IDENTITY_NAME=ada       # optional; the interview's answers
export HEADLONG_IDENTITY_VIBE="curious, warm, and plainspoken"
export HEADLONG_IDENTITY_FOCUS="learning how their own mind works"
export HEADLONG_IDENTITY_USER="I'm Sam, a programmer trying Headlong out"
curl -fsSL https://headlong.ai/install.sh | bash
```

A key must be in the environment; everything else is optional.
`HEADLONG_NO_DASH=1` and `HEADLONG_NO_THINKERS=1` skip those parts. The
installer writes `status.json` in the state home (`~/.headlong`) with
the outcome:

```bash
jq -r '.mind.status, .dash.status, .dash.url' ~/.headlong/status.json
```

[AGENTS.md](../AGENTS.md) covers operating a running identity: paths,
logs, health checks, and the sharp edges.

## From a checkout

```bash
git clone https://github.com/laude-institute/headlong.git
cd headlong
./install.sh            # add --init to also bootstrap an identity + dash
```

This copies the tools in `bin/` and `tools/` to `~/.local/bin`, the core
skills to `~/.skills/core-skills`, the bundled thinker templates to
`~/.headlong-thinkers`, and builds the Rust TUI if cargo is present. Use `--symlinks` to
symlink instead (edits take effect without reinstalling), or
`--prefix /usr/local/bin` for a different location.

## Reporting a bug

If something goes wrong, run

```bash
ada bugreport        # or: persona <name> bugreport
```

and attach the `.tgz` it prints (it lands in your home directory) to a
GitHub issue or a message to us. The bundle holds what we need to see what
happened: the agent's trajectory and rollups, memories, thinker logs, the
dash and install logs, and a `report.txt` with versions and status. Your
`.env` is not included, and API keys or other credential-looking values are
scrubbed before the file is written: keys and tokens keep their first and
last four characters (`<redacted sk-o...cdef>`) so two keys can be told
apart, passwords are masked whole. The agent's
`workdir/` is left out unless you pass `--include-workdir`. Look inside
first if you want: `tar tzf <file>` lists it; unpack it with `tar xzf
<file>` and read `headlong-bugreport-*/report.txt` for the summary.

Where things live, if you would rather pick files by hand: the state home is
`~/.headlong/` (`logs/`, `status.json`, `.env`), the checkout is
`~/.headlong/app/`, and the agent is `~/.headlong/app/.identities/<name>/`
with the root trajectory at `trajectories/*-root/trajectory.jsonl` and the
thinker logs under `run/logs/`.

## Stopping and uninstalling

`ada stop` pauses the mind (the thinkers) and `ada start` resumes it. If
something is running away, `headlong-killall` stops every Headlong process on
the machine (dispatchers, thinker steps, shellm runs, the dashboard);
`headlong-killall --dry-run` shows what it would stop.

The installer touches these places, and removing them uninstalls Headlong:

- `~/.headlong/` — the state home: `.env` (your API key), `status.json`,
  logs, and, for the one-liner, the checkout itself in `~/.headlong/app/`.
  Identities live inside the checkout at `<app>/.identities/`, so this is
  also where your agent's memories and trajectory are. Copy that directory
  first if you want to keep them.
- `~/.local/bin/` — one symlink (or copy) per tool, plus a symlink named
  after each identity (`ada`) that points at `persona`. `ls -l
  ~/.local/bin | grep -i headlong` finds them.
- `~/.skills/core-skills/` and `~/.headlong-thinkers/` — the bundled
  skills and thinker templates.
- A `PATH` line the installer offered to add to your shell rc file
  (`~/.zshrc` or `~/.bashrc`).

Run `headlong-killall` first so nothing is writing while you delete. For the
Docker variant, `docker rm -f headlong` removes the container and everything
in it.
