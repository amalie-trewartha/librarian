"""Outbound filter: only bin/chat speaks for the identity."""

import base64
import threading

from headlong_slack import outbound
from headlong_slack.config import Config


def _cfg(tmp_path):
    return Config(
        serve_root=tmp_path, identity="audel", identity_dir=tmp_path,
        bot_token="x", app_token="x", web_url="http://x", state_dir=tmp_path,
        thread_followups=True,
    )


def test_run_delivers_only_chat_sourced_messages(tmp_path, monkeypatch):
    """Message steps without source:"chat" (a thinker appending raw message
    steps to the trajectory) must not reach Slack."""
    steps = [
        {"type": "message", "from": "audel", "to": "slack-C1-U1",
         "source": "chat", "content": "real reply", "step_id": "aaa"},
        {"type": "message", "from": "audel", "to": "slack-C1-U1",
         "source": "responder", "content": "forged reply", "step_id": "bbb"},
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

    outbound.run(_cfg(tmp_path), FakeClient(), FakeThreads(), threading.Event())
    assert sent == ["real reply"]


def test_text_file_uploads_via_files_upload_v2(tmp_path, monkeypatch):
    """chat send-file stamps filename + content_b64; Slack must upload, not post."""
    body = b"hello file\n"
    steps = [
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "filename": "note.txt",
         "content": "hello file",
         "content_b64": base64.b64encode(body).decode("ascii"),
         "step_id": "fff"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []
    uploads = []

    class FakeClient:
        def chat_postMessage(self, channel, thread_ts, text, unfurl_links=False, **kw):
            sent.append(text)

        def files_upload_v2(self, **kw):
            uploads.append(kw)

    class FakeThreads:
        def touch(self, channel, thread_ts):
            pass

    outbound.run(_cfg(tmp_path), FakeClient(), FakeThreads(), threading.Event())
    assert sent == []
    assert len(uploads) == 1
    assert uploads[0]["filename"] == "note.txt"
    assert uploads[0]["content"] == body
    assert uploads[0]["channel"] == "C1"
    assert "thread_ts" not in uploads[0]


def test_png_uploads_bytes_in_thread(tmp_path, monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    steps = [
        {"type": "message", "from": "audel", "to": "slack-U1-C09XYZ-1722400000.123456",
         "source": "chat", "filename": "fig.png",
         "content": "[file: fig.png]",
         "content_b64": base64.b64encode(png).decode("ascii"),
         "step_id": "png"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []
    uploads = []

    class FakeClient:
        def chat_postMessage(self, channel, thread_ts, text, unfurl_links=False, **kw):
            sent.append(text)

        def files_upload_v2(self, **kw):
            uploads.append(kw)

    class FakeThreads:
        def touch(self, channel, thread_ts):
            pass

    outbound.run(_cfg(tmp_path), FakeClient(), FakeThreads(), threading.Event())
    assert sent == []
    assert uploads[0]["content"] == png
    assert uploads[0]["filename"] == "fig.png"
    assert uploads[0]["channel"] == "C09XYZ"
    assert uploads[0]["thread_ts"] == "1722400000.123456"


def test_file_upload_failure_falls_back_to_notice(tmp_path, monkeypatch):
    steps = [
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "filename": "note.txt", "content": "hi",
         "step_id": "fail"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []

    class FakeClient:
        def chat_postMessage(self, channel, thread_ts, text, unfurl_links=False, **kw):
            sent.append(text)

        def files_upload_v2(self, **kw):
            raise RuntimeError("upload rejected")

    class FakeThreads:
        def touch(self, channel, thread_ts):
            pass

    outbound.run(_cfg(tmp_path), FakeClient(), FakeThreads(), threading.Event())
    assert sent == ["(failed to deliver file note.txt)"]


def test_undecodable_file_falls_back_to_notice(tmp_path, monkeypatch):
    steps = [
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "filename": "note.txt",
         "content": "[file: note.txt]", "content_b64": "@@@bad@@@",
         "step_id": "bad"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []
    uploads = []

    class FakeClient:
        def chat_postMessage(self, channel, thread_ts, text, unfurl_links=False, **kw):
            sent.append(text)

        def files_upload_v2(self, **kw):
            uploads.append(kw)

    class FakeThreads:
        def touch(self, channel, thread_ts):
            pass

    outbound.run(_cfg(tmp_path), FakeClient(), FakeThreads(), threading.Event())
    assert uploads == []
    assert sent == ["(failed to deliver file note.txt)"]


def test_identical_file_steps_are_suppressed(tmp_path, monkeypatch):
    raw = b"same-bytes"
    b64 = base64.b64encode(raw).decode("ascii")
    other = b"other-bytes"
    steps = [
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "filename": "note.txt", "content_b64": b64,
         "step_id": "a"},
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "filename": "note.txt", "content_b64": b64,
         "step_id": "b"},
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "filename": "note.txt",
         "content_b64": base64.b64encode(other).decode("ascii"),
         "step_id": "c"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    uploads = []

    class FakeClient:
        def chat_postMessage(self, channel, thread_ts, text, unfurl_links=False, **kw):
            raise AssertionError("no text fallback")

        def files_upload_v2(self, **kw):
            uploads.append(kw["content"])

    class FakeThreads:
        def touch(self, channel, thread_ts):
            pass

    outbound.run(_cfg(tmp_path), FakeClient(), FakeThreads(), threading.Event())
    assert uploads == [raw, other]


def test_invalid_file_content_does_not_stop_later_replies(tmp_path, monkeypatch):
    steps = [
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "filename": "bad.bin",
         "content": {"x": "y"}, "step_id": "bad"},
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "content": "later reply", "step_id": "ok"},
    ]
    monkeypatch.setattr(outbound.mindlog, "find_trajectory", lambda d: tmp_path / "t.jsonl")
    monkeypatch.setattr(outbound.mindlog, "follow", lambda *a, **k: iter(steps))

    sent = []

    class FakeClient:
        def chat_postMessage(self, channel, thread_ts, text, unfurl_links=False, **kw):
            sent.append(text)

        def files_upload_v2(self, **kw):
            raise AssertionError("should not upload")

    class FakeThreads:
        def touch(self, channel, thread_ts):
            pass

    outbound.run(_cfg(tmp_path), FakeClient(), FakeThreads(), threading.Event())
    assert sent == ["(failed to deliver file bad.bin)", "later reply"]


def test_client_without_upload_posts_notice(tmp_path, monkeypatch):
    steps = [
        {"type": "message", "from": "audel", "to": "slack-U1-C1",
         "source": "chat", "filename": "note.txt", "content": "hi",
         "step_id": "n"},
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

    outbound.run(_cfg(tmp_path), FakeClient(), FakeThreads(), threading.Event())
    assert sent == ["(failed to deliver file note.txt)"]
