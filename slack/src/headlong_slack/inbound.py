"""Slack events -> mind log.

Handlers return immediately (bolt acks the envelope); a worker thread
drains an internal queue and POSTs each message to the local shellm web
API, which appends it to the identity's trajectory via `bin/chat`.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from slack_bolt import App

from . import naming
from .config import Config
from .slackfmt import clean_inbound
from .state import ActiveThreads, Deduper

log = logging.getLogger(__name__)

DELIVERY_ATTEMPTS = 3
DELIVERY_ERROR_TEXT = (
    "(bridge error: I couldn't reach my mind just now — please try again in a bit)"
)


@dataclass
class InboundMessage:
    from_name: str
    user: str
    channel: str
    thread_ts: str | None  # where an error notice would go; None = top level
    text: str


class SlackNames:
    """Cached display names for the '(Slack: Dana Kim in #eng)' header."""

    def __init__(self, client: Any):
        self._client = client
        self._users: dict[str, str] = {}
        self._channels: dict[str, str] = {}

    def user(self, user_id: str) -> str:
        if user_id not in self._users:
            name = user_id
            try:
                profile = self._client.users_info(user=user_id)["user"]
                name = (
                    profile.get("profile", {}).get("display_name")
                    or profile.get("real_name")
                    or user_id
                )
            except Exception:
                log.warning("users_info failed for %s", user_id, exc_info=True)
            self._users[user_id] = name
        return self._users[user_id]

    def place(self, channel_id: str) -> str:
        if channel_id.startswith("D"):
            return "DM"
        if channel_id not in self._channels:
            name = channel_id
            try:
                info = self._client.conversations_info(channel=channel_id)["channel"]
                name = "#" + info.get("name", channel_id)
            except Exception:
                log.warning("conversations_info failed for %s", channel_id, exc_info=True)
            self._channels[channel_id] = name
        return self._channels[channel_id]


class Inbound:
    def __init__(
        self,
        cfg: Config,
        app: App,
        bot_user_id: str,
        threads: ActiveThreads,
    ):
        self.cfg = cfg
        self.app = app
        self.bot_user_id = bot_user_id
        self.bot_mention = f"<@{bot_user_id}>"
        self.threads = threads
        self.names = SlackNames(app.client)
        self.dedupe = Deduper()
        self.queue: queue.Queue[InboundMessage | None] = queue.Queue()
        self._chat_url = (
            f"{cfg.web_url}/api/identities/{cfg.identity_api_id}/chat"
        )
        app.event("app_mention")(self._on_event)
        app.event("message")(self._on_event)
        self._worker = threading.Thread(
            target=self._drain, name="slack-inbound", daemon=True
        )
        self._worker.start()

    # -- event intake (bolt handler thread; must return fast) ----------------

    def _on_event(self, event: dict[str, Any], logger: logging.Logger) -> None:
        if event.get("bot_id") or event.get("subtype"):
            return
        user = event.get("user")
        text = event.get("text") or ""
        if not user or user == self.bot_user_id:
            return
        channel = event.get("channel")
        ts = event.get("ts")
        if not channel or not ts:
            return
        if not self.dedupe.add(f"{channel}:{ts}"):
            return

        if event.get("channel_type") == "im":
            # DMs: everything is for us; replies go top-level.
            from_name = naming.encode(user, channel)
            thread_ts = None
        else:
            mentioned = event.get("type") == "app_mention" or self.bot_mention in text
            if mentioned:
                # Anchor the conversation at the existing thread, or start
                # one at the mention itself.
                thread_ts = event.get("thread_ts") or ts
            elif self.cfg.thread_followups and self.threads.is_active(
                channel, event.get("thread_ts")
            ):
                thread_ts = event["thread_ts"]
            else:
                return
            from_name = naming.encode(user, channel, thread_ts)
            self.threads.touch(channel, thread_ts)

        self.queue.put(InboundMessage(from_name, user, channel, thread_ts, text))

    # -- delivery worker -----------------------------------------------------

    def _drain(self) -> None:
        while True:
            msg = self.queue.get()
            if msg is None:
                return
            try:
                self._deliver(msg)
            except Exception:
                log.exception("failed delivering %s", msg.from_name)

    def _deliver(self, msg: InboundMessage) -> None:
        content = clean_inbound(msg.text, self.bot_user_id)
        if not content:
            return
        # The reply-to name is spelled out because agent-typed replies (the
        # agentic path, unlike the mechanical fast-reply) must use the full
        # routing key, not the human display name.
        header = (
            f"(Slack: {self.names.user(msg.user)} in {self.names.place(msg.channel)}"
            f" — reply with: chat reply {msg.from_name})"
        )
        body = {"content": f"{header} {content}", "from_name": msg.from_name}
        for attempt in range(1, DELIVERY_ATTEMPTS + 1):
            try:
                response = httpx.post(self._chat_url, json=body, timeout=30)
                response.raise_for_status()
                return
            except httpx.HTTPError:
                log.warning(
                    "chat POST failed (attempt %d/%d)",
                    attempt,
                    DELIVERY_ATTEMPTS,
                    exc_info=True,
                )
                if attempt < DELIVERY_ATTEMPTS:
                    time.sleep(2 * attempt)
        try:
            self.app.client.chat_postMessage(
                channel=msg.channel,
                thread_ts=msg.thread_ts,
                text=DELIVERY_ERROR_TEXT,
            )
        except Exception:
            log.exception("failed posting delivery error to slack")

    def stop(self) -> None:
        self.queue.put(None)
