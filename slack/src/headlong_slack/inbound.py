"""Slack events -> mind log.

Handlers return immediately (bolt acks the envelope); a worker thread
drains an internal queue and POSTs each message to the local shellm web
API, which appends it to the identity's trajectory via `bin/chat`.
"""

from __future__ import annotations

import concurrent.futures
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
# Bound reaction parent-lookups so a hung reactions.get cannot stall
# the single inbound drain thread. Fail open rather than wait.
ITEM_LOOKUP_TIMEOUT = 2


def reaction_text(reaction: str, item_ts: str, thread_ts: str | None) -> str:
    """Body for a reaction inbound.

    Routing uses the parent thread so a reply lands in the right Slack
    thread. When the reacted-to message is a reply inside that thread,
    keep `item_ts` in the body so the mind log still names the line.
    """
    body = f":{reaction}:"
    if thread_ts and item_ts != thread_ts:
        body = f"{body} (on {item_ts})"
    return body


@dataclass
class InboundMessage:
    from_name: str
    user: str
    channel: str
    thread_ts: str | None  # where an error notice would go; None = top level
    message_ts: str
    text: str
    # True for channel reactions: resolve parent thread_ts in the worker
    # so the bolt handler never blocks on reactions.get.
    resolve_parent: bool = False


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


def reaction_to_inbound(
    event: dict[str, Any], *, bot_user_id: str
) -> tuple[str, str, str, str, bool] | None:
    """Decide whether a reaction_added event should reach the mind log.

    Returns (user, channel, item_ts, reaction, want_thread) or None to drop.
    want_thread is True for channels (lookup parent thread_ts); False for DMs.
    """
    if event.get("bot_id"):
        return None
    user = event.get("user")
    if not user or user == bot_user_id:
        return None
    reaction = event.get("reaction")
    if not reaction:
        return None
    item = event.get("item") or {}
    if item.get("type") != "message":
        return None
    channel = item.get("channel")
    item_ts = item.get("ts")
    if not channel or not item_ts:
        return None
    is_im = channel.startswith("D")
    item_user = event.get("item_user")
    # DMs: every reaction is for us. Channels: only reactions on our messages.
    if not is_im and item_user != bot_user_id:
        return None
    return (user, channel, item_ts, reaction, not is_im)


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
        app.event("reaction_added")(self._on_reaction)
        self._worker = threading.Thread(
            target=self._drain, name="slack-inbound", daemon=True
        )
        self._worker.start()

    # -- event intake (bolt handler thread; must return fast) ----------------

    def _on_reaction(self, event: dict[str, Any], logger: logging.Logger) -> None:
        """Land emoji reactions on our messages (and all DM reactions) in the mind log.

        Channel reactions on other people's messages are dropped — same gate as
        un-mentioned channel traffic. Body is `:name:`, plus `(on <item_ts>)`
        when the reacted-to line is a reply inside a thread.

        Thread parent lookup happens in the delivery worker, not here: bolt
        must ack the envelope without waiting on the Web API.
        """
        msg = reaction_to_inbound(event, bot_user_id=self.bot_user_id)
        if msg is None:
            return
        user, channel, item_ts, reaction, want_thread = msg
        event_ts = event.get("event_ts") or ""
        if not self.dedupe.add(f"reaction:{channel}:{item_ts}:{user}:{reaction}:{event_ts}"):
            return
        if want_thread:
            thread_ts = item_ts
            from_name = naming.encode(user, channel, thread_ts)
        else:
            thread_ts = None
            from_name = naming.encode(user, channel)
        self.queue.put(
            InboundMessage(
                from_name,
                user,
                channel,
                thread_ts,
                item_ts,
                f":{reaction}:",
                resolve_parent=want_thread,
            )
        )

    def _item_thread_ts(self, channel: str, ts: str) -> str | None:
        """Parent thread_ts for the reacted-to message, if it is in a thread.

        conversations.history only returns parent-channel messages, so a
        reaction on a reply looks up empty there. conversations.replies is
        keyed by the thread parent, not the item. reactions.get returns the
        item itself (including thread_ts) for both roots and replies.

        Bound to ITEM_LOOKUP_TIMEOUT so a hung Web API call cannot stall
        the single drain thread. Fail open to None so the caller uses
        item_ts as the thread root.
        """
        found = self._lookup_item_message(channel, ts)
        if not found:
            return None
        return found.get("thread_ts") or None

    def _lookup_item_message(self, channel: str, ts: str) -> dict[str, Any] | None:
        def _call() -> dict[str, Any] | None:
            resp = self.app.client.reactions_get(channel=channel, timestamp=ts)
            msg = resp.get("message") or {}
            return msg or None

        # Do not use `with ThreadPoolExecutor`: shutdown(wait=True) would
        # re-block the drain thread on a hung reactions.get after timeout.
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            return pool.submit(_call).result(timeout=ITEM_LOOKUP_TIMEOUT)
        except Exception:
            log.warning(
                "reactions.get failed for %s ts=%s", channel, ts, exc_info=True
            )
            return None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

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

        self.queue.put(InboundMessage(from_name, user, channel, thread_ts, ts, text))

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
        if msg.resolve_parent and msg.thread_ts:
            item_ts = msg.thread_ts
            parent = self._item_thread_ts(msg.channel, item_ts)
            thread_ts = parent or item_ts
            # Body starts as ":emoji:". Nested replies keep item_ts in the
            # body so the mind log names the line, not just the thread.
            reaction = msg.text[1:-1] if msg.text.startswith(":") and msg.text.endswith(":") else msg.text
            text = reaction_text(reaction, item_ts, thread_ts)
            if thread_ts != item_ts or text != msg.text:
                msg = InboundMessage(
                    naming.encode(msg.user, msg.channel, thread_ts),
                    msg.user,
                    msg.channel,
                    thread_ts,
                    msg.message_ts,
                    text,
                    resolve_parent=False,
                )
            # A reaction is not request intent. Do not create or resurrect an
            # active thread — that would open the un-mentioned-reply gate.
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
        try:
            permalink = self.app.client.chat_getPermalink(
                channel=msg.channel, message_ts=msg.message_ts
            ).get("permalink")
            if permalink:
                body["source_url"] = permalink
        except Exception:
            # Permalink lookup is best-effort: a Slack outage or missing
            # scope must never keep a human message out of the mind log.
            log.warning("chat_getPermalink failed for %s", msg.from_name, exc_info=True)
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
