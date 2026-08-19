# Installing Shelly

The short version is in the [README](../README.md). This page has every
variant.

## The one-liner

```bash
curl -fsSL https://raw.githubusercontent.com/laude-institute/shelly/main/install.sh | bash
```

It clones the repo to `~/.shelly/app` (or `~/.shellm/app` on installs
that predate the rename), symlinks the tools into
`~/.local/bin`, asks for an LLM API key, and runs a short optional
interview: a name, a few words of personality, what they should think
about when idle. The answers become the agent's core identity and first
memories. Then their mind starts and the dashboard opens. Their name
becomes a command:

```bash
ada                  # chat with them
ada hello!           # one message, wait for the reply
ada stop / ada start # pause / resume their mind
ada dash             # open the dashboard
```

Use a dedicated, spend-capped API key: the agent executes real shell
commands and calls the LLM continuously.

Re-running the one-liner updates everything in place. The installer never
uses sudo, and the piped script only clones the repo and re-runs the
installer from the checkout, so what executes is the same code you can
read here. To read first:

```bash
curl -fsSLO https://raw.githubusercontent.com/laude-institute/shelly/main/install.sh
less install.sh && bash install.sh --init
```

## Docker: a long-lived agent

The same installer works inside a container. Nothing touches your
machine, and the agent's shell commands run in the container too. The
installer apt-installs its own dependencies (as root in a fresh
container) and the dashboard binds `0.0.0.0` so the published port works.

```bash
docker run -it --name shelly --restart unless-stopped -p 8080:8080 buildpack-deps:curl \
  bash -c 'curl -fsSL https://raw.githubusercontent.com/laude-institute/shelly/main/install.sh | bash; exec bash'
```

Paste your key, answer the interview, then open http://localhost:8080 on
your host to watch the mind run. Typing `exit` does not end the world:
Docker restarts the container in the background, the installer re-runs
prompt-free (it keeps your key and identity and pulls the latest code),
and the mind and dashboard come back up on their own.

Day-to-day:

```bash
docker exec -it shelly bash -l   # drop back into your agent's world
docker stop shelly               # pause everything
docker start shelly              # resume
docker rm -f shelly              # delete the agent and its whole world
```

Pasting the run command a second time fails with "name shelly already in
use". That means your agent already exists; `docker exec` is how you get
back to it.

For a throwaway sandbox instead, drop `--name` and `--restart` and add
`--rm`. Exiting the shell then deletes everything.

## Non-interactive install (CI and coding agents)

With no tty, every question falls back to an environment variable or a
default, so a script or a coding agent can install with no interaction:

```bash
export OPENROUTER_API_KEY=sk-or-...   # or ANTHROPIC_/OPENAI_/GEMINI_API_KEY
export SHELLY_IDENTITY_NAME=ada       # optional; the interview's answers
export SHELLY_IDENTITY_VIBE="curious, warm, and plainspoken"
export SHELLY_IDENTITY_FOCUS="learning how their own mind works"
export SHELLY_IDENTITY_USER="I'm Sam, a programmer trying Shelly out"
curl -fsSL https://raw.githubusercontent.com/laude-institute/shelly/main/install.sh | bash
```

A key must be in the environment; everything else is optional.
`SHELLY_NO_DASH=1` and `SHELLY_NO_THINKERS=1` skip those parts. The
installer writes `status.json` in the state home (`~/.shelly`, or
`~/.shellm` on pre-rename installs) with the outcome:

```bash
jq -r '.mind.status, .dash.status, .dash.url' ~/.shelly/status.json
```

[AGENTS.md](../AGENTS.md) covers operating a running identity: paths,
logs, health checks, and the sharp edges.

## From a checkout

```bash
git clone https://github.com/laude-institute/shelly.git
cd shelly
./install.sh            # add --init to also bootstrap an identity + dash
```

This copies the tools in `bin/` to `~/.local/bin`. Use `--symlinks` to
symlink instead (edits take effect without reinstalling), or
`--prefix /usr/local/bin` for a different location.
