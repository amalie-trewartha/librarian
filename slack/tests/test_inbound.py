"""Inbound reaction filter: only our messages (and DMs) land in the mind log."""

from headlong_slack.inbound import reaction_text, reaction_to_inbound

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
    def __init__(self, message=None, raise_exc=False):
        self.message = message
        self.raise_exc = raise_exc
        self.reactions_get_calls = []

    def reactions_get(self, *, channel, timestamp):
        self.reactions_get_calls.append((channel, timestamp))
        if self.raise_exc:
            raise RuntimeError("lookup failed")
        return {"ok": True, "message": dict(self.message or {})}

    def users_info(self, user):
        return {
            "user": {
                "profile": {"display_name": "Nick Jalbert"},
                "real_name": "Nick Jalbert",
                "name": "nick",
            }
        }

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
