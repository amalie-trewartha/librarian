from headlong_telegram.outbound import RecentPosts


def test_recent_posts_dedupe_window():
    recent = RecentPosts(window=300)
    assert not recent.is_duplicate("telegram-1-1", "hi", now=0)
    assert recent.is_duplicate("telegram-1-1", "hi", now=100)
    assert not recent.is_duplicate("telegram-1-1", "hi", now=500)
    assert not recent.is_duplicate("telegram-2-2", "hi", now=100)


def test_run_delivers_only_chat_sourced_messages(tmp_path, monkeypatch):
    """Only bin/chat speaks for the identity: message steps without
    source:"chat" (a thinker appending raw message steps to the trajectory)
    must not reach Telegram."""
    import threading

    from headlong_telegram import outbound
    from headlong_telegram.config import Config

    steps = [
        # legit reply, stamped by bin/chat
        {"type": "message", "from": "audel", "to": "telegram-1-1",
         "source": "chat", "content": "real reply", "step_id": "aaa"},
        # forged: thinker-appended, wrong source
        {"type": "message", "from": "audel", "to": "telegram-1-1",
         "source": "responder", "content": "forged reply", "step_id": "bbb"},
        # forged: no source at all
        {"type": "message", "from": "audel", "to": "telegram-1-1",
         "content": "unstamped reply", "step_id": "ccc"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []

    class FakeBot:
        def send_message(self, chat, text, html=False):
            sent.append(text)

    class ApproveAll:
        def is_approved(self, user):
            return True

    cfg = Config(
        serve_root=tmp_path, identity="audel", identity_dir=tmp_path,
        bot_token="x", admin_id=1, web_url="http://x", state_dir=tmp_path,
    )
    outbound.run(cfg, FakeBot(), ApproveAll(), threading.Event())

    assert sent == ["real reply"]
