# Setting up project mode on a new machine

Project mode runs one Headlong agent on one research project for days or
weeks, unattended (see [design/long_autonomy.md](../design/long_autonomy.md)
for how it works). This guide takes a fresh Linux machine to a running
project. Every step below was run on a clean install. It assumes Claude on
Amazon Bedrock; the Anthropic API works too (see step 3).

The agent runs real shell commands and spends real money. Run it on a
dedicated machine or VM, with a spend-capped key, and give it no secrets
beyond its model credentials. Your organization's IT and security teams
set the rules for cloud credentials and for where agents may run, so
check with them before using work accounts.

## 1. The machine

- **Linux:** Ubuntu 22.04 or 24.04 was tested; macOS works for Headlong in
  general.
- **Always on:** the host must stay awake for the whole run. The project
  clock follows wall time, so if the host sleeps, the clock jumps ahead
  while no work happens. Laptops and VMs on laptops are a poor fit for long
  runs.
- **Packages:**

  ```bash
  sudo apt-get update
  sudo apt-get install -y git curl jq python3 rsync docker.io
  sudo usermod -aG docker "$USER"     # then log out and back in
  docker info >/dev/null && echo docker ok
  ```

  Docker is the sandbox for the agent's commands. Without it, those
  commands run directly on the machine as you. Keep Docker.
- **Optional:** the web dashboard needs [uv](https://docs.astral.sh/uv/) and
  bun or node. Everything in this guide works without it.

## 2. Get the code and install the tools

```bash
git clone https://github.com/amalie-trewartha/headlong.git ~/headlong
cd ~/headlong
git checkout project-mode-long-autonomy     # until it is merged to main
./install.sh --symlinks
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
command -v headlong-project llm blind delegate persona identity
```

`--symlinks` links the tools to the checkout, so a `git pull` updates them.
Do not use the `curl … | bash` one-liner here: it installs `main`, and its
interview does not set up Bedrock.

## 3. Model credentials

**Amazon Bedrock (what the live runs used).**

1. **Use a long-term credential for a long run.**
   - Best: an IAM role or a Bedrock service role. Use `AWS_ACCESS_KEY_ID`
     and `AWS_SECRET_ACCESS_KEY` (plus `AWS_SESSION_TOKEN`); requests are
     SigV4-signed.
   - Next best: a long-term Bedrock API key (it starts with `ABSK`).
   - Avoid short-term Bedrock tokens: they last at most 12 hours. In
     testing, two of them died hours early, one revoked when its successor
     was issued.
2. **Enable the models** for your account in the Bedrock console: Claude
   Opus 5.5 and Claude Haiku 4.5, and optionally a non-Claude reviewer
   such as Llama 4 Maverick.
3. **Store a bearer key in a file**, not in an environment variable, so you
   can rotate it later without a restart. `headlong-bedrock-env` (step 4)
   does this for you, or by hand:

   ```bash
   mkdir -p ~/.headlong
   ( umask 077; nano ~/.headlong/bedrock-token )   # paste the key alone, save
   ```

4. **Pick model ids that match your region.**
   - `us.anthropic.claude-opus-5-5` (a cross-region profile, through
     InvokeModel) works in every US region, us-west-1 included.
   - `anthropic.claude-opus-5-5` uses the newer `bedrock-mantle` endpoint,
     which exists in us-east-1, us-east-2 and us-west-2 but not us-west-1.

**Anthropic API instead:** put `ANTHROPIC_API_KEY=...` in `~/.headlong/.env`,
and use `claude-opus-5-5` and `claude-haiku-4-5` as the models in step 4.

## 4. Configure

If your credentials are in an `aws.env` file (`AWS_REGION` plus
`AWS_BEARER_TOKEN_BEDROCK`, or IAM keys), one command writes everything:

```bash
~/headlong/docs/headlong-bedrock-env ~/aws.env --check
# optional: --coldeyes bedrock-converse/us.meta.llama4-maverick-17b-instruct-v1:0
```

It writes three files and checks the models:
- the key to `~/.headlong/bedrock-token`, mode 600;
- `~/.headlong/.env`, which points at the token file and picks
  cross-region model ids for your region (`us.` or `eu.`);
- `~/.headlong/app_dir`.

With `--check`, it makes one tiny call per model. It never prints a secret
and will not overwrite an existing `.env` without `--force`. Then you can
delete `aws.env`, and skip to "Check that the models answer" below.

Or write `~/.headlong/.env` by hand (adjust the region and models):

```bash
cat > ~/.headlong/.env <<EOF
SHELLM_MODEL=us.anthropic.claude-opus-5-5
SHELLM_FAST_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
AWS_REGION=us-west-1
AWS_BEARER_TOKEN_BEDROCK_FILE=$HOME/.headlong/bedrock-token
SHELLM_REQUIRE_DOCKER=1
HEADLONG_TZ=UTC
LLM_PRICE_SCALE=1.1
# Optional: weekly cold-eyes reviews on another model family
# BLIND_MODEL_COLDEYES=bedrock-converse/us.meta.llama4-maverick-17b-instruct-v1:0
EOF
chmod 600 ~/.headlong/.env
echo "$HOME/headlong" > ~/.headlong/app_dir
```

What the settings do:
- `SHELLM_MODEL` runs the agent itself.
- `SHELLM_FAST_MODEL` runs cheap helpers (`delegate`) and utility calls.
- `LLM_PRICE_SCALE` scales the cost estimate. List prices are Anthropic's,
  and 1.1 covers Bedrock's regional premium. Check your actual Bedrock
  pricing.

Check that the models answer:

```bash
llm -t 16 -m us.anthropic.claude-opus-5-5 "Reply with one word: ready"
llm -t 16 -m us.anthropic.claude-haiku-4-5-20251001-v1:0 "Reply with one word: ready"
```

## 5. Create the agent and its project

Write the brief as a plain markdown file. Say what you want, what "done"
looks like, and any constraints, such as "open data only". Optionally,
provide an exemplar of the kind of end product you expect, for example an
open-access paper converted to markdown.

```bash
cd ~/headlong
identity new cns
headlong-project init cns --spec ~/brief.md --reference ~/exemplar.md \
    --days 14 --daily-usd 15 --total-usd 200
```

The `init` options:
- **`--days N`:** when the run ends. Alternatively `--end YYYY-MM-DD`. Move
  it later with `headlong-project deadline`.
- **`--daily-usd` / `--total-usd`:** estimated-dollar caps.
  - Set the run cap a little under your true limit, since the one wake
    that crosses it still finishes.
  - Pacing spreads the daily cap over the day.
  - Token caps (`--daily-tokens`, `--total-tokens`) also exist. They count
    cache reads at a tenth.
- **`--reference FILE`:** read-only material, such as an exemplar,
  repeatable.
- **`--time-scale N`:** runs the project clock N times faster, for tests
  only. For example, `--days 42 --time-scale 42` is six project weeks in
  24 hours.

From the live runs: Opus 5.5 at full speed costs roughly $10–12 an hour, so
the caps and pacing are what keep it inside a budget.

## 6. Run it

```bash
persona cns start                 # start the mind
headlong-project status cns       # health, deadline, spend, questions
persona cns stop                  # pause; start again to resume
```

`status` leads with any open questions for you. To answer one:

```bash
headlong-project questions cns                       # open and closed questions
headlong-project answer cns Q2 "Use the EU grid as the headline basis."
```

Every question carries a default and a date. If nobody answers by then,
the agent applies the default and records it. You never have to answer,
but the agent applies an answer on its next wake.

Other controls:
- **Rotate the key:** overwrite `~/.headlong/bedrock-token`. The next call
  uses the new key, with no restart.
- **Move the deadline:** `headlong-project deadline cns --days 21`. This
  reopens a finished run.
- **Change the charter or brief mid-run:** edit the files in
  `.identities/cns/project-pristine/`, then run
  `headlong-project update-pristine cns`. Edits made under `project/` are
  undone on the next wake.
- **Change budget settings:** edit `.identities/cns/.env`, then
  `persona cns stop; persona cns start`. Settings are read at start.

## 7. Read the results

Everything is in `~/headlong/.identities/cns/workdir/project/`, a git repo
with one commit per wake. Read in this order:

1. `reports/final.md`: the final report (after the end date).
2. `deliverable.md`: the current answer, kept usable at all times.
3. `questions-summary.md`: every question, and whether a human or a
   default closed it.
4. `reports/week-NN.md`: weekly reports.
5. `reviews/`: cold-eyes and adversarial reviews.

`git -C ~/headlong/.identities/cns/workdir/project log --oneline` is a
readable history of the run.

## Troubleshooting

- **`Cannot detect provider for model '…'`, or another wrong-tool error:**
  another program with the same name is running instead of Headlong's.
  Typically that's the Python `llm` CLI, or an older Headlong install.
  `type -a llm` lists them in PATH order. Re-running `./install.sh
  --symlinks` fixes it: it moves older Headlong copies and any other `llm`
  found ahead of `~/.local/bin` out of the way (renamed
  `<name>.pre-headlong-<date>`, so it can be undone). It warns about any
  other same-named program without touching it. Run `hash -r` afterwards.
- **`API error (HTTP 403): Authentication failed`:** the key is invalid or
  expired. Put a new one in the token file. The mind recovers on its own,
  because failed wakes back off and cost nothing.
- **`HTTP 000`:** the model endpoint could not be reached. Check the
  network, the region, and that the model id suits the region (step 3).
- **`last successful model call` is old in `status`:** the mind is failing
  or stopped. Check `.identities/cns/run/logs/monolith.log`.
- **After a `git pull`, tool changes do not reach the sandbox:** core tools
  are mounted into the sandbox container when it is created. Stop the
  mind, remove the container and the env record, then start again:

  ```bash
  persona cns stop
  docker rm -f $(docker ps -aq --filter name=shellm)
  rm -rf ~/headlong/.identities/cns/.shellm/envs/cns
  persona cns start
  ```

- **Spend flat and status shows a budget pause:** a cap was reached. Wakes
  skip the model until usage falls back under the cap.
- **Panic button:** `headlong-killall` stops every Headlong process on
  the machine.
