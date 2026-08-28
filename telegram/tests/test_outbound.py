import threading

from headlong_telegram import outbound
from headlong_telegram.config import Config


def test_forged_source_is_not_posted(tmp_path, monkeypatch):
    steps = [
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


def test_file_step_uses_send_document_not_message(tmp_path, monkeypatch):
    steps = [
        {"type": "message", "from": "audel", "to": "telegram-1-1",
         "source": "chat", "content": "<svg xmlns=\"x\">",
         "filename": "walk.svg", "caption": "thought walk",
         "step_id": "fff"},
        {"type": "message", "from": "audel", "to": "telegram-1-1",
         "source": "chat", "content": "plain after", "step_id": "ggg"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []
    docs = []

    class FakeBot:
        def send_message(self, chat, text, html=False):
            sent.append(text)

        def send_document(self, chat, content, filename, caption=None):
            docs.append((filename, content, caption))

    class ApproveAll:
        def is_approved(self, user):
            return True

    cfg = Config(
        serve_root=tmp_path, identity="audel", identity_dir=tmp_path,
        bot_token="x", admin_id=1, web_url="http://x", state_dir=tmp_path,
    )
    outbound.run(cfg, FakeBot(), ApproveAll(), threading.Event())

    assert docs == [("walk.svg", b"<svg xmlns=\"x\">", "thought walk")]
    assert sent == ["plain after"]


def test_png_uses_send_photo(tmp_path, monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    steps = [
        {"type": "message", "from": "audel", "to": "telegram-1-1",
         "source": "chat", "content": png,
         "filename": "fig.png", "step_id": "fff"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []
    photos = []

    class FakeBot:
        def send_message(self, chat, text, html=False):
            sent.append(text)

        def send_photo(self, chat, content, filename, caption=None):
            photos.append((filename, content, caption))

        def send_document(self, chat, content, filename, caption=None):
            raise AssertionError("png should use send_photo")

    class ApproveAll:
        def is_approved(self, user):
            return True

    cfg = Config(
        serve_root=tmp_path, identity="audel", identity_dir=tmp_path,
        bot_token="x", admin_id=1, web_url="http://x", state_dir=tmp_path,
    )
    outbound.run(cfg, FakeBot(), ApproveAll(), threading.Event())

    assert photos == [("fig.png", png, None)]
    assert sent == []
