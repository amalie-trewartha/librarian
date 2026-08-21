"""Mind log -> Telegram.

Follows the identity's root trajectory and forwards message steps the
identity addressed to a telegram-* conversation name. The bridge's own
inbound steps have a telegram-* `from` (not the identity), so they never
match — no echo loop.

The allowlist gates this direction too: an injected agent that emits a
step addressed to an unapproved chat gets dropped here, so the bridge
can't be used as a courier out.
"""

from __future__ import annotations

import logging
import threading
import time

from . import mindlog, naming
from .allowlist import Allowlist
from .api import ApiError, Bot
from .config import Config
from .tgfmt import chunk, strip_leaked_command, to_html

log = logging.getLogger(__name__)

DUPLICATE_WINDOW_SECONDS = 300


class RecentPosts:
    """Transport-level dedupe: agents occasionally send the same reply twice
    (e.g. an agentic run re-executing its chat command). Posting an identical
    message to the same conversation twice within the window is never right.
    """

    def __init__(self, window: float = DUPLICATE_WINDOW_SECONDS):
        self._window = window
        self._last: dict[str, tuple[str, float]] = {}

    def is_duplicate(self, conversation: str, text: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        previous = self._last.get(conversation)
        if previous and previous[0] == text and now - previous[1] < self._window:
            return True
        self._last[conversation] = (text, now)
        return False


def run(cfg: Config, bot: Bot, allowlist: Allowlist, stop_event: threading.Event) -> None:
    traj = mindlog.find_trajectory(cfg.identity_dir)
    cursor = cfg.state_dir / "cursor"
    recent = RecentPosts()
    log.info("following %s", traj)
    for step in mindlog.follow(traj, cursor, should_stop=stop_event.is_set):
        if step.get("type") != "message" or step.get("from") != cfg.identity:
            continue
        if step.get("source") != "chat":
            # Only bin/chat speaks for the identity — it stamps source:"chat"
            # on every outgoing message. Thinkers sometimes append raw message
            # steps directly to the trajectory (thinking out loud, not a
            # reply); delivering those gives the user a second, unstamped
            # voice. Bridges are the mouth; the trajectory is the mind.
            log.warning(
                "dropping non-chat message step %s (source=%r)",
                step.get("step_id"),
                step.get("source"),
            )
            continue
        to = step.get("to")
        if not naming.is_telegram_name(to):
            continue
        conv = naming.decode(to)
        if not allowlist.is_approved(conv.user):
            log.warning("dropping reply to unapproved user %s", conv.user)
            continue
        text = strip_leaked_command(str(step.get("content") or "")).strip()
        if not text:
            continue
        if recent.is_duplicate(to, text):
            log.warning("skipping duplicate post to %s", to)
            continue
        for part in chunk(text):
            try:
                bot.send_message(conv.chat, to_html(part), html=True)
            except ApiError:
                # Bad HTML from an odd reply must not eat the message —
                # fall back to plain text before giving up.
                try:
                    bot.send_message(conv.chat, part)
                except ApiError:
                    log.exception("sendMessage failed for %s", to)
                    break


def start(
    cfg: Config, bot: Bot, allowlist: Allowlist, stop_event: threading.Event
) -> threading.Thread:
    thread = threading.Thread(
        target=run,
        args=(cfg, bot, allowlist, stop_event),
        name="telegram-outbound",
        daemon=True,
    )
    thread.start()
    return thread
