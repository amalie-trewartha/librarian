# Providers

Status: DECIDED 2026-08-27 — the policy below governs provider additions.
The `openai-compatible` provider is shipped; the adapter seam is
specified here but not yet implemented.

Headlong keeps getting asked to support more model providers (PR #46,
issues #65 and #71). Each one is easy on its own, but core grows with
every provider we absorb, and there are a lot of providers. The policy
in this document says which providers go into core, which stay outside
it, and what the boundary between them is.

## The decision

1. `bin/llm` is the only code in the repo that calls a model provider.
   Every other tool (shellm, the thinkers, the bridges, the web dash)
   makes completions through it. Code elsewhere that calls a provider
   endpoint directly is wrong, with one standing exception: the dash
   reads OpenRouter's catalog and credit endpoints for display, which
   is not a completion path.

2. Core supports providers that speak plain HTTP and JSON. Most of them
   are covered by the generic `openai-compatible` provider, which is
   configured with a URL, a model name, and an optional key. After
   that, supporting a new compatible provider (Ollama, vLLM, LM Studio,
   Together, a corporate proxy) is a documentation entry, not code. A
   provider with a genuinely different wire format (the way Gemini has
   one) can still be added to core, but that is a maintainer decision,
   and the bar is high because the generic provider covers so much.

3. A provider that needs a subprocess, another language, an SDK, or
   auth that is not a key in a header lives outside core, behind the
   adapter contract below. The adapter carries its own dependencies.
   Core never gains a runtime dependency on an interpreter because of a
   provider.

4. Installer prompts, dash panels, and other integration beyond the
   completion path are decided per provider, case by case. Completion
   support is cheap and open; deeper integration is earned. An adapter
   gets no installer or dash integration by default.

## The openai-compatible provider

The provider is never auto-detected, because arbitrary model names
(`qwen3:8b`, `llama3.2`) imply nothing. Name it explicitly and give it
a URL:

```bash
LLM_PROVIDER=openai-compatible \
LLM_API_URL=http://localhost:11434/v1/chat/completions \
llm -m qwen3:8b "hello"
```

| Variable | Meaning |
|---|---|
| `LLM_PROVIDER=openai-compatible` | Selects the provider (or pass `--provider openai-compatible`) |
| `LLM_API_URL` | The chat-completions endpoint. Required, no default |
| `LLM_API_KEY` | Optional. When set, sent as `Authorization: Bearer` |

Everything else in `bin/llm` applies unchanged: streaming, retries,
network guards, truncation warnings, the usage ledger, and the health
marker. Unknown model names get a 16384 default output cap under this
provider (the global 4096 fallback starves agentic steps);
`LLM_MAX_TOKENS` or `-t` overrides it.

Inside the Docker sandbox, `localhost` is the container, not the host.
A local inference server running on the host is reached at
`host.docker.internal` on macOS, or the docker bridge address on Linux.

## The adapter contract

An adapter is one executable that turns a completion request into
provider output. `bin/llm` will run it in place of curl when the
operator configures it:

```bash
LLM_PROVIDER=adapter
LLM_ADAPTER=/path/to/executable
```

The contract, which the invoker in `bin/llm` will implement:

- `bin/llm` runs `$LLM_ADAPTER` with these flags: `--model NAME`,
  `--max-tokens N`, and, when set, `--effort LEVEL`, `--thinking
  [LEVEL]`, and `--no-stream`. The system prompt arrives via
  `--system-prompt-file PATH`. The messages array (the same JSON shape
  `llm -M` takes) arrives on stdin.
- The adapter writes response text to stdout, streamed as it is
  produced, and diagnostics to stderr. It exits 0 on success and
  nonzero on failure with a one-line reason on stderr. It must not
  print partial text and then exit nonzero unless the failure really
  happened mid-generation.
- Usage reporting: when the environment carries `LLM_USAGE_FILE`, the
  adapter writes one JSON object to that path, with any of `in_tok`,
  `out_tok`, `think_tok` as integers. `bin/llm` stamps the ledger from
  it. An adapter that cannot count tokens writes nothing.
- `bin/llm` wraps the adapter in its own wall-clock deadline
  (`LLM_MAX_TIME`), kills it on expiry, and reports that as an error.
  The adapter does not need its own outer timeout, but it should pass
  reasonable deadlines to whatever it calls.
- Retries stay in `bin/llm` and follow the existing rule: a nonzero
  exit before any stdout bytes is retryable, and nothing is retried
  after output has been emitted.
- The health marker (`llm_health.json`) is written by `bin/llm` from
  the exit status, never by the adapter, and `ok` is only recorded
  after the adapter exits 0.
- Sandbox: the adapter path is resolved through symlinks the way
  `bin/shellm` resolves its own location, and it must exist inside the
  container for sandboxed callers, which means the operator mounts it.
  A missing adapter fails with a clear message before anything runs.

Language, dependencies, packaging, and auth storage are the adapter's
business. An adapter that needs `python3`, an npm package, or a
logged-in vendor CLI declares that in its own documentation, and a
machine without those things loses that adapter and nothing else.

## Why the line is drawn here

The completion path is one choke point, so an adapter seam in `bin/llm`
covers every caller at once. The expensive part of an in-core provider
was never the payload builder, which for OpenAI-compatible providers is
a one-line alias. The expensive part is everything around it: the
installer's key detection and default-model tables, the dash's model
config, the sandbox mount list, the docs, and the review surface of new
code on the path every thought travels. Keeping core to "HTTP and JSON,
one generic entry for the compatible majority" caps that cost at
roughly its current size while keeping every provider reachable.
