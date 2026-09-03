from types import SimpleNamespace

from headlong_slack import inbound


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
