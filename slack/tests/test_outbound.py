"""Outbound filter: only bin/chat speaks for the identity."""

import threading

from headlong_slack import outbound
from headlong_slack.config import Config


def test_run_delivers_only_chat_sourced_messages(tmp_path, monkeypatch):
    """Message steps without source:"chat" (a thinker appending raw message
    steps to the trajectory) must not reach Slack."""
    steps = [
        # legit reply, stamped by bin/chat
        {"type": "message", "from": "audel", "to": "slack-C1-U1",
         "source": "chat", "content": "real reply", "step_id": "aaa"},
        # forged: thinker-appended, wrong source
        {"type": "message", "from": "audel", "to": "slack-C1-U1",
         "source": "responder", "content": "forged reply", "step_id": "bbb"},
        # forged: no source at all
        {"type": "message", "from": "audel", "to": "slack-C1-U1",
         "content": "unstamped reply", "step_id": "ccc"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []

    class FakeClient:
        def chat_postMessage(self, channel, thread_ts, text, unfurl_links=False, **kw):
            sent.append(text)

    class FakeThreads:
        def touch(self, channel, thread_ts):
            pass

    cfg = Config(
        serve_root=tmp_path, identity="audel", identity_dir=tmp_path,
        bot_token="x", app_token="x", web_url="http://x", state_dir=tmp_path,
        thread_followups=True,
    )
    outbound.run(cfg, FakeClient(), FakeThreads(), threading.Event())

    assert sent == ["real reply"]
