"""Inbound reaction filter: only our messages (and DMs) land in the mind log."""

from headlong_slack.inbound import reaction_text, reaction_to_inbound
from types import SimpleNamespace

from headlong_slack import inbound

BOT = "U_BOT"


def _event(
    *,
    user="U_NICK",
    reaction="thumbsup",
    channel="C_CHAN",
    ts="111.222",
    item_user="U_BOT",
    item_type="message",
    bot_id=None,
):
    event = {
        "type": "reaction_added",
        "user": user,
        "reaction": reaction,
        "item_user": item_user,
        "item": {"type": item_type, "channel": channel, "ts": ts},
        "event_ts": "999.000",
    }
    if bot_id is not None:
        event["bot_id"] = bot_id
    return event


def test_channel_reaction_on_our_message():
    got = reaction_to_inbound(_event(), bot_user_id=BOT)
    assert got == ("U_NICK", "C_CHAN", "111.222", "thumbsup", True)


def test_channel_reaction_on_someone_else_dropped():
    assert (
        reaction_to_inbound(_event(item_user="U_OTHER"), bot_user_id=BOT) is None
    )


def test_dm_reaction_on_anyone():
    got = reaction_to_inbound(
        _event(channel="D_DM", item_user="U_OTHER"), bot_user_id=BOT
    )
    assert got == ("U_NICK", "D_DM", "111.222", "thumbsup", False)


def test_bot_reacting_dropped():
    assert reaction_to_inbound(_event(user=BOT), bot_user_id=BOT) is None


def test_non_message_item_dropped():
    assert reaction_to_inbound(_event(item_type="file"), bot_user_id=BOT) is None


def test_missing_reaction_dropped():
    event = _event()
    del event["reaction"]
    assert reaction_to_inbound(event, bot_user_id=BOT) is None


def test_bot_id_dropped():
    assert reaction_to_inbound(_event(bot_id="B123"), bot_user_id=BOT) is None


def test_plus_one_name_preserved():
    got = reaction_to_inbound(_event(reaction="+1"), bot_user_id=BOT)
    assert got[3] == "+1"


def test_reaction_text_same_item_is_just_emoji():
    assert reaction_text("thumbsup", "111.222", "111.222") == ":thumbsup:"
    assert reaction_text("+1", "111.222", None) == ":+1:"


def test_reaction_text_nested_item_keeps_line():
    assert (
        reaction_text("thumbsup", "111.333", "111.222")
        == ":thumbsup: (on 111.333)"
    )


# -- worker-path coverage (Nick #88 review) ---------------------------------

import logging
import time

import httpx
import pytest

from headlong_slack.config import Config
from headlong_slack.inbound import Inbound
from headlong_slack.state import ActiveThreads


BOT = "U_BOT"
NICK = "U_NICK"
CHAN = "C_CHAN"
DM = "D_DM"
PARENT = "111.222"
REPLY = "111.333"


class _FakeApp:
    def __init__(self, client):
        self.client = client
        self.handlers = {}

    def event(self, name):
        def deco(fn):
            self.handlers[name] = fn
            return fn
        return deco


class _FakeClient:
    def __init__(self, message=None, raise_exc=False, delay=0.0, permalink_delay=0.0):
        self.message = message
        self.raise_exc = raise_exc
        self.delay = delay
        self.permalink_delay = permalink_delay
        self.reactions_get_calls = []
        self.permalink_calls = []
        self._live = 0
        self.max_live = 0
        self._lock = __import__("threading").Lock()

    def reactions_get(self, *, channel, timestamp):
        self.reactions_get_calls.append((channel, timestamp))
        with self._lock:
            self._live += 1
            if self._live > self.max_live:
                self.max_live = self._live
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.raise_exc:
                raise RuntimeError("lookup failed")
            return {"ok": True, "message": dict(self.message or {})}
        finally:
            with self._lock:
                self._live -= 1

    def users_info(self, user):
        return {
            "user": {
                "profile": {"display_name": "Nick Jalbert"},
                "real_name": "Nick Jalbert",
                "name": "nick",
            }
        }

    def chat_getPermalink(self, *, channel, message_ts):
        self.permalink_calls.append((channel, message_ts))
        if self.permalink_delay:
            time.sleep(self.permalink_delay)
        return {"permalink": f"https://slack.test/{channel}/p{message_ts}"}

    def conversations_info(self, channel):
        if channel.startswith("D"):
            return {"channel": {"is_im": True, "user": NICK}}
        return {"channel": {"name": "headlong-bot", "is_im": False}}

    def chat_postMessage(self, **kwargs):
        raise AssertionError(f"unexpected chat_postMessage {kwargs}")


def _cfg(tmp_path, followups=True):
    serve = tmp_path / "serve"
    ident = serve / "audel"
    ident.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    return Config(
        serve_root=serve,
        identity="audel",
        identity_dir=ident,
        bot_token="xoxb-test",
        app_token="xapp-test",
        web_url="http://127.0.0.1:9",
        state_dir=state,
        thread_followups=followups,
    )


def _reaction_event(*, channel=CHAN, item_ts=PARENT, event_ts="999.000",
                    user=NICK, item_user=BOT, reaction="thumbsup"):
    return {
        "type": "reaction_added",
        "user": user,
        "reaction": reaction,
        "item_user": item_user,
        "item": {"type": "message", "channel": channel, "ts": item_ts},
        "event_ts": event_ts,
        "channel_type": "im" if channel.startswith("D") else "channel",
    }


class _Posted:
    def __init__(self):
        self.items = []

    def __call__(self, url, json=None, timeout=None):
        self.items.append({"url": url, "json": json, "timeout": timeout})
        class _R:
            def raise_for_status(self_inner):
                return None
        return _R()


@pytest.fixture
def posted(monkeypatch):
    p = _Posted()
    monkeypatch.setattr("headlong_slack.inbound.httpx.post", p)
    return p


def _run_reaction(tmp_path, client, event, posted, followups=True):
    cfg = _cfg(tmp_path, followups=followups)
    threads = ActiveThreads(cfg.state_dir / "threads.json")
    ib = Inbound(cfg, _FakeApp(client), BOT, threads)
    logger = logging.getLogger("test")
    try:
        ib._on_reaction(event, logger)
        deadline = time.time() + 2
        while time.time() < deadline and not posted.items:
            time.sleep(0.02)
        # small extra settle for a second unexpected post
        time.sleep(0.05)
    finally:
        ib.stop()
        ib._worker.join(timeout=1)
    return threads


def test_reaction_on_threaded_reply_rewrites_from_name_and_body(tmp_path, posted):
    client = _FakeClient(message={"ts": REPLY, "thread_ts": PARENT, "text": "hi"})
    event = _reaction_event(item_ts=REPLY)
    threads = _run_reaction(tmp_path, client, event, posted)
    assert client.reactions_get_calls == [(CHAN, REPLY)]
    assert len(posted.items) == 1
    body = posted.items[0]["json"]
    assert body["from_name"] == f"slack-{NICK}-{CHAN}-{PARENT}"
    assert ":thumbsup: (on 111.333)" in body["content"]
    assert "reply with: chat reply slack-U_NICK-C_CHAN-111.222" in body["content"]
    # A reaction must not open the un-mentioned-reply gate.
    assert not threads.is_active(CHAN, PARENT)


def test_reaction_lookup_empty_falls_back_to_item_ts(tmp_path, posted):
    client = _FakeClient(message={})
    event = _reaction_event(item_ts=PARENT)
    _run_reaction(tmp_path, client, event, posted)
    assert client.reactions_get_calls == [(CHAN, PARENT)]
    assert len(posted.items) == 1
    body = posted.items[0]["json"]
    assert body["from_name"] == f"slack-{NICK}-{CHAN}-{PARENT}"
    assert ":thumbsup:" in body["content"]
    assert "(on " not in body["content"]


def test_reaction_lookup_raising_falls_back_without_exception(tmp_path, posted):
    client = _FakeClient(raise_exc=True)
    event = _reaction_event(item_ts=PARENT)
    _run_reaction(tmp_path, client, event, posted)
    assert client.reactions_get_calls == [(CHAN, PARENT)]
    assert len(posted.items) == 1
    body = posted.items[0]["json"]
    assert body["from_name"] == f"slack-{NICK}-{CHAN}-{PARENT}"
    assert ":thumbsup:" in body["content"]


def test_reaction_lookup_timeouts_share_one_worker(tmp_path, posted, monkeypatch):
    """Nick #88: do not queue stale lookups after a timeout.

    One in-flight reactions.get; later reactions fail open immediately
    instead of submitting more work. A human message after the burst
    is delivered after at most one short timeout.
    """
    monkeypatch.setattr(inbound, "ITEM_LOOKUP_TIMEOUT", 0.05)
    client = _FakeClient(delay=0.8)
    cfg = _cfg(tmp_path)
    threads = ActiveThreads(cfg.state_dir / "threads.json")
    ib = Inbound(cfg, _FakeApp(client), BOT, threads)
    logger = logging.getLogger("test")
    try:
        t0 = time.time()
        for i in range(8):
            ib._on_reaction(_reaction_event(event_ts=f"999.{i:03d}"), logger)
        ib._on_event(
            {
                "type": "message",
                "user": NICK,
                "text": "hello after burst",
                "channel": DM,
                "ts": "200.000",
                "channel_type": "im",
            },
            logger,
        )
        deadline = t0 + 3
        while time.time() < deadline and len(posted.items) < 9:
            time.sleep(0.02)
        elapsed = time.time() - t0
        assert len(posted.items) == 9, posted.items
        assert client.max_live == 1
        # Only the first lookup is submitted; the rest skip while it runs.
        assert len(client.reactions_get_calls) == 1
        # Eight 2s waits would be 16s; one 50ms timeout plus delivery is far less.
        assert elapsed < 1.0, elapsed
        assert "hello after burst" in posted.items[-1]["json"]["content"]
        for item in posted.items[:-1]:
            assert item["json"]["from_name"] == f"slack-{NICK}-{CHAN}-{PARENT}"
            assert ":thumbsup:" in item["json"]["content"]
    finally:
        ib.stop()
        ib._worker.join(timeout=1)


def test_reaction_permalink_does_not_stall_later_message(tmp_path, posted):
    """Nick #88: reaction permalink must not run on the drain thread."""
    client = _FakeClient(permalink_delay=0.8)
    cfg = _cfg(tmp_path)
    threads = ActiveThreads(cfg.state_dir / "threads.json")
    ib = Inbound(cfg, _FakeApp(client), BOT, threads)
    logger = logging.getLogger("test")
    try:
        ib._on_reaction(_reaction_event(channel=DM, item_ts=PARENT), logger)
        ib._on_event(
            {
                "type": "message",
                "user": NICK,
                "text": "human after reaction",
                "channel": DM,
                "ts": "200.001",
                "channel_type": "im",
            },
            logger,
        )
        t0 = time.time()
        deadline = t0 + 3
        while time.time() < deadline and len(posted.items) < 2:
            time.sleep(0.02)
        elapsed = time.time() - t0
        assert len(posted.items) == 2, posted.items
        # Reaction skipped permalink; only the human waits 0.8s.
        assert elapsed < 1.2, elapsed
        assert client.permalink_calls == [(DM, "200.001")]
        assert "source_url" not in posted.items[0]["json"]
        assert posted.items[1]["json"].get("source_url")
        assert "human after reaction" in posted.items[1]["json"]["content"]
        assert ":thumbsup:" in posted.items[0]["json"]["content"]
    finally:
        ib.stop()
        ib._worker.join(timeout=1)


def test_dm_reaction_skips_lookup(tmp_path, posted):
    client = _FakeClient(message={"ts": PARENT, "thread_ts": PARENT})
    event = _reaction_event(channel=DM, item_ts=PARENT)
    _run_reaction(tmp_path, client, event, posted)
    assert client.reactions_get_calls == []
    assert len(posted.items) == 1
    body = posted.items[0]["json"]
    assert body["from_name"] == f"slack-{NICK}-{DM}"
    assert ":thumbsup:" in body["content"]
    assert "(on " not in body["content"]


def test_duplicate_reaction_envelope_dropped_by_dedupe(tmp_path, posted):
    client = _FakeClient(message={"ts": PARENT})
    cfg = _cfg(tmp_path)
    threads = ActiveThreads(cfg.state_dir / "threads.json")
    ib = Inbound(cfg, _FakeApp(client), BOT, threads)
    logger = logging.getLogger("test")
    event = _reaction_event(event_ts="999.000")
    try:
        ib._on_reaction(event, logger)
        ib._on_reaction(event, logger)
        deadline = time.time() + 2
        while time.time() < deadline and not posted.items:
            time.sleep(0.02)
        time.sleep(0.1)
    finally:
        ib.stop()
        ib._worker.join(timeout=1)
    assert len(posted.items) == 1
    assert len(client.reactions_get_calls) == 1

class OkResponse:
    def raise_for_status(self):
        pass


class Names:
    def user(self, _user):
        return "Dana"

    def place(self, _channel):
        return "#agents"


def make_inbound(client):
    bridge = inbound.Inbound.__new__(inbound.Inbound)
    bridge.bot_user_id = "UBOT"
    bridge.names = Names()
    bridge.app = SimpleNamespace(client=client)
    bridge._chat_url = "http://headlong.test/chat"
    return bridge


def test_deliver_records_slack_permalink(monkeypatch):
    posts = []

    class Client:
        def chat_getPermalink(self, channel, message_ts):
            assert (channel, message_ts) == ("C123", "1788451200.123456")
            return {
                "permalink": "https://laudesters.slack.com/archives/C123/p1788451200123456"
            }

    monkeypatch.setattr(
        inbound.httpx,
        "post",
        lambda url, json, timeout: posts.append((url, json, timeout)) or OkResponse(),
    )

    bridge = make_inbound(Client())
    bridge._deliver(
        inbound.InboundMessage(
            "slack-U123-C123-1788451200.123456",
            "U123",
            "C123",
            "1788451200.123456",
            "1788451200.123456",
            "<@UBOT> can you check this?",
        )
    )

    assert posts[0][1]["source_url"] == (
        "https://laudesters.slack.com/archives/C123/p1788451200123456"
    )
    assert posts[0][1]["from_name"] == "slack-U123-C123-1788451200.123456"


def test_permalink_failure_does_not_drop_message(monkeypatch):
    posts = []

    class Client:
        def chat_getPermalink(self, **_kwargs):
            raise RuntimeError("Slack is unavailable")

    monkeypatch.setattr(
        inbound.httpx,
        "post",
        lambda url, json, timeout: posts.append(json) or OkResponse(),
    )

    bridge = make_inbound(Client())
    bridge._deliver(
        inbound.InboundMessage(
            "slack-U123-D123",
            "U123",
            "D123",
            None,
            "1788451200.123456",
            "hello",
        )
    )

    assert len(posts) == 1
    assert "source_url" not in posts[0]
