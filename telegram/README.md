# headlong-telegram-bridge

A Telegram Bot API bridge that connects one Headlong identity to Telegram.
Approved people DM the bot, their messages land in the identity's mind log
as `message` steps, and the identity's replies come back to the same chat.

## How it works

```
Telegram <=(long-poll getUpdates)=> headlong-telegram-bridge
    inbound:  message -> from_name "telegram-<user_id>-<chat_id>"
              -> POST <web>/api/identities/<id>/chat
    outbound: tail trajectory.jsonl -> message steps where from=<identity>
              and to=telegram-* -> sendMessage(chat_id)
```

The Telegram conversation is encoded into the chat `from` name, which the
reply path returns as `to`, so the trajectory schema and the agent need no
changes. The bridge is a pure client of the existing web API and
trajectory format, the same design as the Slack bridge in `slack/`.

Long polling is outbound only. Nothing listens on the network, which
keeps the zero-ingress deploy design.

The bridge is DM only and text only. It drops media, ignores bots, and
leaves any group it is added to. Group support would need a different
gate, because the allowlist cannot control who is in a group.

## The allowlist

Anyone on Earth can message a Telegram bot, so the bridge only forwards
messages from users you have approved, and only delivers replies to
those users. You manage the allowlist from your own Telegram chat with
the bot. When an unknown user messages the bot, the bridge stays silent
toward them and sends you one prompt per user per day with their id and
these commands:

- `/approve <id>` lets the user talk to the identity
- `/deny <id>` silences the request for good
- `/revoke <id>` removes an approved user
- `/list` shows approved and pending users

The admin (you) is approved automatically on first start.

## Running locally

```bash
export TELEGRAM_BOT_TOKEN=...       # from @BotFather
export TELEGRAM_ADMIN_ID=...        # your numeric user id; message the bot
                                    # once and read it from the bridge log
export HEADLONG_TELEGRAM_IDENTITY=ada  # optional; defaults to the `default`
                                       # identity link (legacy
                                       # SHELLM_TELEGRAM_IDENTITY still honored)
tools/headlong-telegram-bridge [ROOT]   # ROOT = serve root, default repo root
```

The launcher loads `<checkout>/.env` and then `$HEADLONG_HOME/.env` (default
`~/.headlong/.env`), the same two files `persona` and `llm` read, so the token
can live in an env file instead of the calling shell. Anything already exported
wins.

That is for local dev only. On a box the bridge runs from its systemd unit,
which does not use this launcher and reads the root-owned
`/etc/shellm/telegram.env` instead — the bot token stays out of the agent's
own environment, as described above.

The identity must exist (`identity new <name>`) with a running dispatcher
(`thinkers start monolith responder`), and headlong-web must be serving the same root
(default `http://127.0.0.1:8080`, override with `HEADLONG_WEB_URL`; legacy `SHELLM_WEB_URL` still honored).

Other settings are `HEADLONG_TELEGRAM_STATE_DIR`, legacy
`SHELLM_TELEGRAM_STATE_DIR` (allowlist, cursors, update offset, default
`<identity>/run/telegram-bridge/`).

## Enabling on a deployed box

This section describes the box provisioned by `deploy/` (it is how Laude
runs its own agent); for a local or hand-managed machine, the "Running
locally" steps above are all you need.

There is no bootstrap flag for this bridge, because the box's user_data
must never change (changing it replaces the instance and destroys the
identity). Instead, `deploy/update.sh` installs and starts the bridge
whenever `/etc/shellm/telegram.env` exists on the box.

1. Create the bot. Message @BotFather, `/newbot`, and save the token.
2. Find your numeric user id, e.g. by messaging @userinfobot.
3. Write the env file on the box:

   ```bash
   deploy/scripts/telegram-env
   ```

   The script prompts for the token (hidden) and the admin id, then
   creates the file root owned with mode 600. The token does transit
   the SSM command channel, whose history is readable in the AWS
   account for about 30 days. If that is ever a problem, open
   `deploy/scripts/shell` instead and write the file by hand:

   ```bash
   sudo mkdir -p /etc/shellm
   sudo tee /etc/shellm/telegram.env >/dev/null <<'ENV'
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_ADMIN_ID=...
   ENV
   sudo chown root:root /etc/shellm/telegram.env
   sudo chmod 600 /etc/shellm/telegram.env
   ```

4. Run a normal deploy (`deploy/scripts/update`). The update script
   creates the `shellm-telegram` user, syncs the venv, installs the
   systemd unit, and starts it.
5. Message your bot. You should see your message in the mind log, and
   the identity's reply in the chat.

The env file does not survive an instance rebuild. After a rebuild,
repeat step 3 and 4. `deploy/scripts/status` (which `rebuild` runs at
the end) prints a loud `telegram: NOT SET UP` reminder on the slack
stack whenever the env file is missing. To turn the bridge off, `sudo systemctl stop
headlong-telegram-bridge` mutes it without touching the agent, and
removing `/etc/shellm/telegram.env` keeps it from coming back on the
next deploy.

## Tests

```bash
uv run --project telegram pytest telegram/tests
```

## Security notes

The full comparison across the Slack, phone chat, and Telegram
integrations is in `deploy/SECURITY.md`. The short version for this
bridge is below.

- The allowlist is the whole perimeter, and it gates both directions.
  Unknown senders never reach the mind log, and replies addressed to
  unapproved users are dropped, so an injected agent cannot use the
  bridge to send data out.
- The bot token stays out of the agent's reach. The bridge runs as its
  own user (`shellm-telegram`), and the token lives in a root-owned env
  file that only systemd reads. The agent runs as `shellm` and can read
  the environment of processes with its own uid, which is why the bridge
  must not run as `shellm`.
- The allowlist file lives in `/var/lib/shellm-telegram`, which the
  agent's user cannot write. If the agent could write it, an injected
  agent could approve an attacker itself.
- Prompt injection from approved senders is still possible. Anything an
  approved person sends, including pasted or forwarded text, goes
  straight into the agent's context. The mitigations are the same as for
  Slack. The box is burnable, has no inbound network access, and holds a
  spend-capped key and few secrets.
- Do not put the bot token in the agent's env for the `skills/telegram`
  skill. That skill lets the agent drive the Telegram API itself, which
  undoes the token isolation above. Use a separate bot and token if you
  want the agent to have one.
- All conversations share one mind. Anything one person tells the
  identity may surface in replies to others, on any of the connected
  channels. Do not tell it secrets you would not post in a public
  channel.
