# The Shell is Back at the Center of Computing
## Philosophy and Introduction to Headlong

_Slop warning: authored by Claude with aggressive prompting by the Laude Institute team._

In 1971, Ken Thompson wrote the first Unix shell. It was a command interpreter — a thin loop that read a line, found a program, ran it, and waited. That's all it did. That was enough.

Over the next decade, the shell became the connective tissue of an entire philosophy of computing. Doug McIlroy articulated it most concisely: write programs that do one thing well, write programs to work together, write programs that handle text streams because that is a universal interface. These weren't arbitrary aesthetic choices. They were engineering observations about what made systems composable, debuggable, and resilient.

Then the world moved on. GUIs won. The web won. The shell retreated to a power-user niche — beloved by sysadmins and backend engineers, ignored by everyone else. For most of the software industry, the terminal became a place you visited reluctantly to run `git push` or restart a Docker container.

I think LLMs are bringing it back. And I think the shell isn't just a good environment for AI agents — I think it's the *right* one. The one that will win.

## Why the shell fits LLMs better than you'd expect

There's a structural alignment between how LLMs work and how the Unix shell works that I don't think has been fully appreciated yet.

An LLM is, at its core, a thing that reads text and writes text. The Unix shell is an environment where *everything* is text. Stdin, stdout, stderr, environment variables, files, pipes — the universal interface is streams of bytes, and in practice that means streams of text. An LLM dropped into a shell can immediately talk to every tool in the environment using the protocol those tools already speak.

Compare this to the current dominant paradigm for LLM tool use: hand-crafted function schemas, JSON argument marshaling, bespoke API wrappers. Every tool needs an adapter. Every adapter needs maintenance. The function-calling approach treats the LLM as a dispatcher that picks from a curated menu of capabilities.

The shell treats the LLM as an *operator* — someone sitting at a terminal with access to the entire system. `curl` is the HTTP client. `jq` is the JSON processor. `python3 -c` is the escape hatch for anything else. No schemas to define. No wrappers to write. The LLM composes tools the same way a human would: by piping them together.

This is McIlroy's vision, realized through a medium he couldn't have anticipated. The "universal interface" of text streams turns out to be exactly the interface LLMs are native to.

## Composition over enumeration

The function-calling approach to LLM tooling has an enumeration problem. You define the tools the model can use ahead of time: `search_web`, `read_file`, `run_sql`. The model picks from the list. If your list doesn't include something, the model can't do it.

The shell inverts this. Instead of enumerating capabilities, you provide a *composable environment* and let the model figure out what to do. Need to fetch a webpage, extract all the links, filter them by domain, and count them? That's a one-liner:

```bash
curl -s "$URL" | grep -oP 'href="\K[^"]+' | grep "$DOMAIN" | wc -l
```

No one defined a `count_links_by_domain` tool. The capability emerged from composition. This is the GNU philosophy in action — small, sharp tools connected by pipes — and it turns out to be an incredibly natural fit for how LLMs reason about multi-step tasks. The model doesn't need to know every tool in advance; it knows the *grammar* of composition, and that's enough.

## shellm: an LLM that lives in bash

This line of thinking led me to build [shellm](https://github.com/laude-institute/headlong) — a recursive LLM that operates inside a bash shell. It takes the recursive language model idea — the early [Recursive LLM](https://github.com/andyk/recursive_llm) experiment and Alex Zhang's [Recursive Language Models](https://alexzhang13.github.io/blog/2025/rlm/) — and reimplements it in bash, for bash.

The idea is simple. shellm runs a loop:

1. Send context to an LLM with a system prompt that says "write bash code"
2. The model responds with a ```bash code block
3. Execute the code (in Docker if available, locally otherwise)
4. Stream the output back as the next message
5. Repeat until the code signals completion or hits the iteration limit

The LLM has full shell access. It can curl APIs, parse JSON with jq, write Python scripts on the fly, install packages, read and write files — whatever the task requires. When it has an answer, it sets `FINAL="the answer"` and the loop terminates.

The entire thing is a single bash script. The only dependencies are bash, jq, and curl. There's no framework, no package.json, no virtual environment. It's a shell tool built out of shell tools.

```bash
# Set your API key and go
export ANTHROPIC_API_KEY="sk-ant-..."

# Ask a question
shellm what is the mass of jupiter in kilograms

# Pipe data in
cat dataset.csv | shellm summarize this data and find outliers

# Pass files as context
shellm -f paper.pdf -f notes.txt compare these documents
```

## Watching it think

One of the things I find most compelling about this approach is the transparency. Every iteration, you see exactly what the LLM is doing — the bash commands it writes, the output it gets back, and how it adapts. There's no black box.

```
▶ Iteration 1 — calling Claude API...
▶ Executing bash (12 lines):
    curl -s "https://api.example.com/data" | jq '.results'
    ...
  $ curl -s 'https://api.example.com/data'
  $ jq '.results'
  │ {"count": 42, "items": [...]}
  $ FINAL="Found 42 results"
  Exit 0

▶ Final answer received
Found 42 results
```

This is closer to how you'd debug a colleague's work than how you'd debug an AI agent. You can see the reasoning embodied in the commands: why it chose to curl that endpoint, what it did with the response, when it decided it had enough information.

## Recursion: LLMs calling LLMs

Code generated by shellm can call shellm itself. A `shellm "prompt"` inside generated code starts a fresh sub-loop with its own env. It's a clean delegation — give a subtask to a new agent, get the result back through stdout.

This is recursive decomposition using the shell's own primitives. The parent process delegates a subtask, the child process runs its own think-execute loop, and the result flows back through stdout — exactly like any other Unix pipeline. No orchestration framework required. The shell's process model *is* the orchestration framework.

There is no orchestration framework and no special depth limit baked in; a spend-capped API key and shellm's inactivity timeouts are the guard rails. Within that, you get genuine multi-agent behavior: a shellm process that researches a topic can spawn sub-agents to handle different aspects in parallel, each with their own env, all coordinated through the filesystem and stdout.

## Docker as a sandbox

By default, if Docker is running, shellm executes all generated code inside a container. The LLM can `apt-get install` whatever it needs, write files anywhere, run services — none of it touches your host system. The workdir is bind-mounted in, so files persist across iterations and flow back to the host.

This matters because the whole point is to give the LLM real autonomy. If you're going to let it run arbitrary bash, you want a sandbox. Docker provides exactly that, and shellm detects it automatically — no configuration needed.

## From tool to agent: mem, skills, and a mind that keeps thinking

shellm is a powerful primitive, but it's stateless. Each run starts fresh. It has no memory of what happened last time, no learned abilities, no persistent identity. It's a tool, not an agent.

To get from a tool to an agent, you need memory, skills, a record of everything the agent has done, and a loop that keeps generating the next thought when nobody is talking to it. And you need visibility into what the agent actually did. So I built more shell tools.

### mem: identity as text files

`mem` is a CLI memory store. It saves memories as individual markdown files with YAML frontmatter — a summary, a type (fact, belief, value, todo, preference...), and a timestamp. That's it. No database. No vector store. Just files in a directory.

```bash
mem add --type fact "My dad's name is Andy"
mem add --type preference "I prefer concise answers"
mem add --type todo "Learn how to write a SKILL.md"
mem search "what do I know about Andy"
mem list
```

The search command pipes all memories through shellm itself for semantic matching — the tool composes with the tool. But you can also just `grep` the memories directory, because they're text files. Every piece of infrastructure is inspectable, greppable, and editable with any text editor.

This is the Ken Thompson way. Memory isn't a feature of a monolithic agent framework. It's a directory of files managed by a small, sharp program that reads stdin and writes stdout.

### skills: learned abilities as markdown

`skills` manages a local directory of skills following the [Agent Skills open standard](https://agentskills.io). Each skill is a directory with a `SKILL.md` file — YAML frontmatter for metadata, markdown for instructions. Skills can be installed from GitHub repos, created locally, searched, and listed.

```bash
skills install owner/repo       # install from GitHub
skills init my-new-skill        # scaffold a new one
skills show code-review         # read a skill's instructions
skills                          # list what's installed
```

Skills are to an agent what recipes are to a cook. They're reusable instruction sets that encode how to do specific things well. The key insight: skills don't require any special runtime. A skill is a text file that the LLM reads and follows. The "execution engine" for a skill is the LLM's ability to read instructions and generate code. No plugin API, no SDK, no registration step.

### shellm-explore: seeing what the agent did

When shellm runs a complex task, it often spawns nested sub-runs — child shellm processes that each handle a subtask. The result is a tree of trajectory files linked by fork/merge steps, each with its own conversation history, generated code, and output. This is powerful, but it's also opaque if you can't see the tree.

`shellm-explore` solves this. Point it at any run (by hex ID or slug) and it walks the fork/merge references in the trajectory, displaying each run with a one-line summary:

```
abc12345: Research the AI coding agent market and write a report
  ├──── def45678: Gather pricing and feature data for top AI coding agents
  └──── ghi78901: Synthesize findings into a comparative report
```

The summaries come from a `run-summary` step that shellm appends to each trajectory at the start of every run. A background process calls a fast model with all the input context — CLI arguments, stdin, file contents — and produces a TLDR and optional full summary. This runs asynchronously so it doesn't slow down the main loop, and it gives every run a human-readable label.

With `--report`, shellm-explore goes further: it sends the entire tree — summaries, context, relationships — to an LLM and generates an analysis explaining what the run tree accomplished, why each sub-run exists, and how they connect. It's a post-hoc audit of the agent's reasoning, built from the same primitives as everything else.

### Headlong: a mind that keeps thinking

Everything above is still a tool: you run it, it finishes, it forgets. Headlong is what turns the tools into an agent. Its defining feature is **persistent agency**. The agent keeps thinking between external interactions in a self-guided loop, the way a person's inner monologue keeps going when nobody is talking to them. A message from a human does not start a session. It lands in the agent's thought stream as one more observation, and the agent decides if and when to respond.

Three more small tools make that work:

- `traj` records the agent's trajectory — its life so far — as append-only JSONL that forks and merges into a DAG. Every thought, action, message, and sub-run is a step in it.
- `context` turns that trajectory into the messages array for the next LLM call. Nothing is compacted away in place: recent steps appear verbatim, older ones are summarized at exponentially decaying resolution, and the tiers double as an index the agent can use to pull raw steps back up.
- `thinkers` is the mind. A dispatcher watches the trajectory and wakes small thought processes — the monolith, which generates the next thought (think, act, learn, recall, set goals, or idle), and the responder, which replies to messages. Each wakeup is itself a shellm run.

An identity is a directory, and it is all text:

```
.identities/ada/
├── activate                  # environment for running as this identity
├── core_identity_prompt.md   # the persona
├── memories/                 # mem's markdown files
├── skills/                   # its skills
├── thinkers/                 # its thought processes
├── trajectories/             # its life, as append-only jsonl
└── run/                      # dispatcher pid and logs
```

`headlong-init` creates the first identity by interviewing you, and the agent's name becomes a command:

```bash
ada hello!           # one message, wait for the reply
ada                  # chat
ada stop / ada start # pause / resume its mind
ada dash             # watch it think in the browser
```

Everything the dispatcher wakes is a shellm run, so the agent thinks by writing bash all the way down. A thought that decides to act spawns a sub-run, the sub-run's trajectory forks from the mind log and merges back, and the agent can later read any of it with the same `traj` it writes with. The Slack and Telegram bridges inject messages into the same stream, so there is one mind no matter which channel you reach it through.

The result is an agent that can:

- Remember things across days, not turns (`mem`, and `learn` / `recall` in its own loop)
- Learn new skills at runtime (`skills install`)
- Read its own source code and its own trajectory to understand how it works
- Run arbitrary shell commands to accomplish tasks
- Compose with any tool in the Unix ecosystem

And it's all bash scripts. The whole stack — shellm, llm, traj, context, thinkers, mem, skills, and the tools around them — installs with:

```bash
curl -fsSL https://headlong.ai/install.sh | bash
```

or `./install.sh` from a checkout. The core needs nothing but bash, curl, jq, and git. No Docker required (though shellm uses it for sandboxing when available). A directory of small executables on your PATH. The only non-bash piece is the optional dashboard, a small Python and React app for watching the mind run.

## The Thompson test

Here's how I think about whether an agent architecture is on the right track. I call it the Thompson test, after Ken:

1. **Can you understand every component in an afternoon?** Each of these tools is a single bash script. The whole core — the executables the mind runs plus the thinkers — is under 10K lines, and shellm, the largest, is under 3K. You can read every line of code that comprises the entire agent.

2. **Can you compose the pieces in ways the author didn't anticipate?** mem is just a CLI that manages files. You can pipe its output into anything. Skills are markdown files — editable, greppable, version-controllable. shellm can call itself. None of these composition patterns were "designed in" — they fall out of the Unix interface naturally.

3. **Is the state inspectable?** Every piece of state is a text file on disk. The trajectory is JSONL. Memories are markdown with YAML frontmatter. The persona is a markdown file you can cat. There's nothing hidden in a database, nothing serialized in a binary format, nothing locked behind an API.

4. **Can you swap any component?** Want a different memory system? Point `MEM_DIR` at a different directory. Want a different LLM? Set `SHELLM_MODEL`. Want a different personality? Edit the identity's `core_identity_prompt.md`. Want to skip Docker? `--env local`. The architecture is decoupled because the coupling mechanism is the filesystem and environment variables — the oldest, most battle-tested integration protocol in computing.

Most modern agent frameworks fail the Thompson test. They have opaque state management, non-composable architectures, heavy runtimes, and components that only work together through proprietary interfaces. They're building cathedrals when we need bazaars.

## The terminal is the agent runtime

There's a broader argument here that I think matters: the terminal isn't just a *good* environment for AI agents — it might be the *winning* one.

The agent paradigm we're entering needs a few things: a way for LLMs to take actions in the world, a way to compose those actions, a way to persist state across interactions, and a way to keep humans in the loop. The terminal provides all of these, and it provides them through mechanisms that have been debugged over fifty years.

The action layer is the shell itself — every program on the system is a potential tool. The composition layer is pipes and process substitution. The state layer is the filesystem. The human-in-the-loop layer is the terminal's native interactivity — you can watch every command, interrupt with Ctrl-C, inspect any file.

Compare this to the web-based agent paradigm: browser automation through Playwright or Puppeteer, actions defined through API schemas, state managed by application-specific databases, human oversight through dashboards and approval queues. It works, but every piece is bespoke. The terminal's version of each layer is universal and pre-existing.

I'm not arguing that every agent should be a bash script. I'm arguing that the *design principles* of Unix — small composable tools, text as the universal interface, the filesystem as the state layer, transparency as a first-class property — are the right principles for building agent systems. And the easiest way to honor those principles is to actually use the system that embodies them.

Ken Thompson's shell was a thin loop: read a line, find a program, run it, wait. shellm is a thin loop too: read a message, ask the LLM, run the code, repeat. Headlong wraps that loop in a mind that never stops: thinkers generate the next thought, traj records it, context projects it back into the next call. Fifty-five years later, the pattern still works. It just needed a new kind of user.

The shell is back. This time, it's the agent runtime.
