# Review notes: nj/run_local_llm

_Pre-read 2026-08-05T22:43:30Z. Branch verified alive (not merged into main)._

**Diff method:** merge-base diff (`6757865f7354cfea57592ed3d0c244c0ab85e441..branch`), NOT `main..branch`.
Branch is 1 ahead, 101 BEHIND main — `main..branch` would show ~all of main's
recent work as misleading deletions. Lesson saved 2026-08-05.

## Commits ahead of main (merge-base..branch)
b69408b wip

## What the branch actually does
Adds support for running a local LLM (mlx_lm server) as shellm's backend
instead of a cloud API. Intended for local development / demos on macOS
(Apple Silicon).

## Files changed (4 files, +92/-15)
- **RUN_LOCAL.md** (new, +24): Setup instructions — start mlx_lm server
  (Qwen3.5-0.8B-4bit), configure .identities/localnick/.env with
  SHELLM_API_URL pointing at the local server, set think_model.
- **bin/llm** (+25): Adds local-LLM request path. Reads SHELLM_API_URL
  env var; when set, routes the request to the local server instead of
  the default cloud provider. Handles the response shape from mlx_lm.
- **thinkers/_lib/common.sh** (+20): Helper(s) to support the local LLM
  path — likely request formatting / response parsing shared across
  thinkers.
- **thinkers/inner_monologue/step** (+38/-15): Adapted to work with the
  local model's response format. Notable change: removes the "repeat"
  suffix logic — duplicates are now appended verbatim because
  _recent_stream collapses repeats with a count, and a mutated suffix
  would defeat that equality check. Also removes a `sleep 1` backoff
  on empty responses.

## Review points
1. **bin/llm local path**: Does it correctly detect when SHELLM_API_URL
   is set? What happens if the local server is down — does it fall back
   to cloud, error clearly, or hang? Check timeout handling.
2. **RUN_LOCAL.md**: The .env snippet references a specific IP
   (192.168.1.7) — should it be templated or documented as
   example-only? Is the chat-template-args (enable_thinking: false)
   compatible with shellm's thinker design?
3. **inner_monologue repeat-suffix removal**: The comment says
   _recent_stream collapses repeats — verify that's actually how
   _recent_stream works (if it doesn't, removing the suffix loses the
   signal that a step was a duplicate). Trace the code path.
4. **Removed `sleep 1` backoff**: Was this backoff important for
   avoiding tight loops on API failures? With a local model, is there
   a different backoff strategy, or none needed?
5. **common.sh additions**: Are the helpers generic enough to work
   with other thinkers, or inner_monologue-specific? Should they be
   in inner_monologue/ instead of _lib/common.sh?
6. **Model choice**: Qwen3.5-0.8B-4bit is very small — is this just
   for demo/local-dev, or intended for real use? Document the
   quality/speed tradeoff.

## Open questions for Nick
- Is this meant to land on main, or is it a personal local-dev branch?
  (RUN_LOCAL.md reads like personal notes.)
- Does the local-LLM path need to be production-quality (timeouts,
  fallbacks) or is best-effort fine for now?
- Is the repeat-suffix removal a separate concern from the local-LLM
  work, or are they coupled (local model produces more duplicates)?
