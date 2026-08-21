"""Chat conversation filter and PWA static-file route tests."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from headlong_web.server import create_app

ROOT_TRAJ = "ffffffff-6666-4666-8666-666666666666"


def _msg(step_id: str, from_name: str, to_name: str, content: str, **extra) -> dict:
    return {
        "type": "message",
        "step_id": step_id,
        "from": from_name,
        "to": to_name,
        "content": content,
        "ts": f"t{step_id}",
        **extra,
    }


@pytest.fixture
def chat_identity(tmp_path: Path) -> Path:
    """Identity whose mind log mixes a pwa conversation with slack traffic."""
    identity = tmp_path / ".identities" / "chatty"
    identity.mkdir(parents=True)
    (identity / "info.txt").write_text(
        f"name=chatty\ncreated=2026-08-05T00:00:00\nroot_trajectory={ROOT_TRAJ}\n"
    )
    traj_dir = identity / "trajectories" / "ffffffff-root"
    traj_dir.mkdir(parents=True)
    steps = [
        {"type": "trajectory", "step_id": ROOT_TRAJ, "ts": "t0"},
        _msg("m1", "pwa-nick", "chatty", "hello from phone"),
        _msg("m2", "chatty", "pwa-nick", "hi nick", reply_to="m1"),
        _msg("m3", "slack-U1-C1", "chatty", "slack says hi"),
        _msg("m4", "chatty", "slack-U1-C1", "hi slack", reply_to="m3"),
        _msg("m5", "pwa-boss", "chatty", "boss checking in"),
        _msg("m6", "chatty", "pwa-boss", "hello boss", reply_to="m5"),
        _msg("m7", "pwa-nick", "chatty", "just an ack, thanks"),
        {
            "type": "observation",
            "step_id": "o1",
            "source": "monolith",
            "content": "Chose not to reply to pwa-nick — bare acknowledgment",
            "decision": "no-reply",
            "trigger_step": "m7",
            "ts": "to1",
        },
        _msg("m8", "pwa-boss", "chatty", "does this work?"),
        {
            "type": "observation",
            "step_id": "o2",
            "source": "monolith",
            "content": "reply failed: could not send a reply to pwa-boss",
            "trigger_step": "m8",
            "ts": "to2",
        },
    ]
    # Enough slack chatter that an unfiltered tail would push out the pwa
    # conversation — proves the filter runs before the tail slice.
    steps += [
        _msg(f"s{i}", "slack-U1-C1", "chatty", f"noise {i}") for i in range(50)
    ]
    (traj_dir / "trajectory.jsonl").write_text(
        "".join(json.dumps(s) + "\n" for s in steps)
    )
    return identity


@pytest.fixture
def client(chat_identity: Path) -> TestClient:
    return TestClient(create_app(chat_identity.parent.parent))


def test_chat_unfiltered_returns_all(client: TestClient):
    body = client.get("/api/identities/.identities~chatty/chat").json()
    froms = {m["from"] for m in body["messages"]}
    assert {"pwa-nick", "pwa-boss", "slack-U1-C1", "chatty"} <= froms


def test_chat_with_filters_conversation(client: TestClient):
    body = client.get(
        "/api/identities/.identities~chatty/chat", params={"with": "pwa-nick"}
    ).json()
    assert [m["step_id"] for m in body["messages"]] == ["m1", "m2", "m7"]
    for m in body["messages"]:
        assert "pwa-nick" in (m["from"], m["to"])


def test_chat_with_filter_applies_before_tail(client: TestClient):
    body = client.get(
        "/api/identities/.identities~chatty/chat",
        params={"with": "pwa-boss", "tail": 5},
    ).json()
    assert [m["step_id"] for m in body["messages"]] == ["m5", "m6", "m8"]


def test_chat_reply_to_surfaced(client: TestClient):
    body = client.get(
        "/api/identities/.identities~chatty/chat", params={"with": "pwa-nick"}
    ).json()
    by_id = {m["step_id"]: m for m in body["messages"]}
    assert by_id["m1"]["reply_to"] is None
    assert by_id["m2"]["reply_to"] == "m1"


def test_chat_outcomes(client: TestClient):
    body = client.get(
        "/api/identities/.identities~chatty/chat", params={"with": "pwa-nick"}
    ).json()
    # m1 was replied to (m2 stamps reply_to), m7 was explicitly declined,
    # m8 hit a reply failure. Absent = still undecided.
    assert body["outcomes"]["m1"] == "replied"
    assert body["outcomes"]["m7"] == "no-reply"
    assert body["outcomes"]["m8"] == "failed"
    assert "s0" not in body["outcomes"]


def test_chat_with_rejects_bad_name(client: TestClient):
    resp = client.get(
        "/api/identities/.identities~chatty/chat", params={"with": "no spaces"}
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PWA static routes: must serve real bytes, not the SPA catch-all's index.html
# ---------------------------------------------------------------------------


@pytest.fixture
def static_client(chat_identity: Path, tmp_path: Path) -> TestClient:
    static = tmp_path / "static"
    (static / "icons").mkdir(parents=True)
    (static / "index.html").write_text("<html>spa</html>")
    (static / "manifest.webmanifest").write_text('{"name": "Audel"}')
    (static / "sw.js").write_text("// sw")
    (static / "icons" / "icon-192.png").write_bytes(b"\x89PNG192")
    (static / "icons" / "apple-touch-icon.png").write_bytes(b"\x89PNGapple")
    return TestClient(create_app(chat_identity.parent.parent, static))


def test_manifest_served_with_type(static_client: TestClient):
    resp = static_client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")
    assert resp.json()["name"] == "Audel"


def test_service_worker_served_from_root(static_client: TestClient):
    resp = static_client.get("/sw.js")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/javascript")
    assert resp.text == "// sw"


def test_icons_served(static_client: TestClient):
    resp = static_client.get("/icons/icon-192.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG192"
    assert static_client.get("/apple-touch-icon.png").content == b"\x89PNGapple"


def test_icon_traversal_and_missing_404(static_client: TestClient):
    # Traversal paths normalize away before routing and land on the SPA
    # catch-all, never the icon route; bad names and non-png 404.
    assert static_client.get("/icons/../index.html").text == "<html>spa</html>"
    assert static_client.get("/icons/nope.png").status_code == 404
    assert static_client.get("/icons/evil.js").status_code == 404


def test_spa_catch_all_still_works(static_client: TestClient):
    resp = static_client.get("/talk")
    assert resp.text == "<html>spa</html>"
