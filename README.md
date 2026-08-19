```
███      █████ ██  ██ █████ ██    ██    ██  ██
  ███    ██    ██  ██ ██    ██    ██    ██  ██
    ███  █████ ██▀▀██ ████  ██    ██    ▀████▀
  ███       ██ ██  ██ ██    ██    ██      ██
███      █████ ██  ██ █████ █████ █████   ██
```

**Shelly** is an open-source microharness agent framework — a handful of
small, composable bash tools that add up to
**persistent agency**: an agent with a continuous, self-guided inner
monologue. You give them a name and a personality; they keep thinking
whether or not you're talking to them, decide their own interests and
priorities, start their own projects, and ping you when they have
something to say. Every interaction — Slack, Telegram, chat, their own
idle thoughts — lands in one unified inner experience.

At the heart of Shelly is **shellm**, a CLI implementation of
[Recursive Language Models](https://alexzhang13.github.io/blog/2025/rlm/)
in bash: the agent thinks by writing shell commands, running them, and
iterating. There is one tool, and it is bash.

## Get started

One line installs everything, interviews you to bring a shelly agent to life,
and opens a dashboard where you can watch their mind run:

```bash
curl -fsSL https://raw.githubusercontent.com/laude-institute/shelly/main/install.sh | bash
```

You'll need an LLM API key (Anthropic, OpenAI, Gemini, or OpenRouter) —
use a dedicated, spend-capped one: your agent runs real shell commands
and thinks around the clock.

Their name becomes a command:

```bash
ada hello!           # one message, wait for the reply
ada                  # chat
ada stop / ada start # pause / resume their mind
ada dash             # open the dashboard
```

Prefer a sandbox? The same flow in a long-lived docker container:

```bash
docker run -it --name shelly --restart unless-stopped -p 8080:8080 buildpack-deps:curl \
  bash -c 'curl -fsSL https://raw.githubusercontent.com/laude-institute/shelly/main/install.sh | bash; exec bash'
```

Details, non-interactive/CI installs, and the from-a-checkout path:
[docs/install.md](docs/install.md).

## Key ideas

- **Minimal composable tools.** In the spirit of Ken Thompson's Unix
  philosophy: small CLI executables (`shellm`, `traj`, `llm`, `context`,
  `mem`, `skills`, ...), each pure bash, each doing one thing well,
  composing through pipes, files, and environment variables.
- **All tool calling via bash.** No tool schemas, no function menus. The
  model writes shell commands; `curl` is the HTTP client, `jq` is the
  JSON processor, `python3 -c` is the escape hatch.
- **Docker by default.** Execution auto-sandboxes into a container when
  Docker is available; container reuse keeps it light. Local mode
  supported.
- **Trajectories are a DAG.** A trajectory is an append-only jsonl file
  with fork and merge, so sub-sub-\*-agents branch off and merge back —
  and can use the viewer to understand how they fit into the big picture.
- **Context is a non-destructive function of the trajectory.** Nothing is
  ever compacted away in place. Exponentially tiered summarization keeps
  the agent's full life experience in context at gracefully decaying
  resolution — the further in the past, the more summarized.
- **The full past stays explorable.** The agent has tooling to dive
  arbitrarily deep into its own history, down to any single step.
- **Recursive self-awareness and improvement.** An agent can spin up new
  agents — clones or clean slates — and merging life experiences is
  trivial, because they're just trajectories.
- **python-env-like semantics.** Each identity has an `activate` script;
  humans and agents co-work in the same familiar paradigm.
- **Turn-taking or continuous thought.** Works as a classic
  request/response tool, or as an autoregressive next-thought loop where
  human messages are simply observations injected into the thought
  stream.

The full backstory and design philosophy:
[philosophy.md](philosophy.md).

## The tools

| Tool | What it does |
|------|-------------|
| **shellm** | The RLM core — sends context to an LLM, executes the bash it writes back, repeats |
| **llm** | Multi-provider LLM CLI — Anthropic, OpenAI, Gemini, OpenRouter behind one interface |
| **traj** | Trajectory operations — append-only jsonl DAGs with fork and merge |
| **context** | Renders a trajectory into an LLM messages array with tiered compaction |
| **thinkers** | The mind — reactive thought processes run by a dispatcher |
| **identity** | Create and manage identities (persona, memories, activate script) |
| **persona** | Talk to and manage an identity by name, from anywhere |
| **chat** / **focus** | Messages and goals on an identity's trajectory |
| **mem** / **skills** | File-based memory store; SKILL.md-based abilities |
| **recap** | Summarize a trajectory into themes and episodes |
| **shellm-explore** | Visualize run trees; LLM-powered reports on what happened and why |
| **shelly-web** | The dashboard — watch a mind think in the browser |
| **bridges** | Slack and Telegram connectors into the same inner experience |

## Learn more

- [philosophy.md](philosophy.md) — why the shell, and the full design story
- [docs/shellm.md](docs/shellm.md) — the shellm engine reference: the loop,
  context passing, Docker sandboxing, envs, the `llm` tool, options
- [docs/install.md](docs/install.md) — every install variant, including
  CI/non-interactive and long-lived Docker
- [AGENTS.md](AGENTS.md) — operating a running identity (for humans and
  coding agents): paths, logs, health checks, sharp edges

## Acknowledgements

shellm is a port of [Recursive Language Models
(RLM)](https://alexzhang13.github.io/blog/2025/rlm/) by Alex Zhang to
bash, for bash.

## License

[Apache 2.0](LICENSE)
