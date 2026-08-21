"""Health endpoint: reply_to-paired response stats over the mind log."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from headlong_web.server import create_app

ROOT_TRAJ = "abababab-7777-4777-8777-777777777777"
IDENTITY_ID = ".identities~hl"


def _ts(seconds_ago: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    ).isoformat()


@pytest.fixture
def health_root(tmp_path: Path) -> Path:
    """One identity whose mind log holds a replied, a declined, an
    undecided, and a stale (out-of-window) inbound message."""
    identity = tmp_path / ".identities" / "hl"
    identity.mkdir(parents=True)
    (identity / "info.txt").write_text(
        f"name=hl\ncreated=2026-08-07T00:00:00\nroot_trajectory={ROOT_TRAJ}\n"
    )
    traj_dir = identity / "trajectories" / "abababab-root"
    traj_dir.mkdir(parents=True)
    steps = [
        {"type": "trajectory", "step_id": ROOT_TRAJ, "ts": "t0"},
        # out of the 7-day window: must not count as undecided
        {"type": "message", "step_id": "m0", "from": "slack-U0-D0", "to": "hl",
         "content": "ancient", "ts": _ts(8 * 86400)},
        # replied after 60s
        {"type": "message", "step_id": "m1", "from": "slack-U1-D1", "to": "hl",
         "content": "hi", "ts": _ts(3600)},
        {"type": "message", "step_id": "r1", "from": "hl", "to": "slack-U1-D1",
         "content": "hello!", "reply_to": "m1", "ts": _ts(3540)},
        # declined after 10s
        {"type": "message", "step_id": "m2", "from": "pwa-nick", "to": "hl",
         "content": "thanks", "ts": _ts(1800)},
        {"type": "observation", "step_id": "o2", "trigger_step": "m2",
         "decision": "no-reply", "content": "Chose not to reply", "ts": _ts(1790)},
        # replied after 300s
        {"type": "message", "step_id": "m3", "from": "slack-U1-D1", "to": "hl",
         "content": "and this?", "ts": _ts(900)},
        {"type": "message", "step_id": "r3", "from": "hl", "to": "slack-U1-D1",
         "content": "this too", "reply_to": "m3", "ts": _ts(600)},
        # still undecided
        {"type": "message", "step_id": "m4", "from": "pwa-nick", "to": "hl",
         "content": "anyone home?", "ts": _ts(120)},
        # outbound with no reply_to (self-initiated): no pairing
        {"type": "message", "step_id": "r4", "from": "hl", "to": "pwa-nick",
         "content": "unprompted share", "ts": _ts(60)},
        # mid-run injection chain: message queues behind a busy run, the
        # dispatcher writes the note, the in-flight call finishes 30s later
        # (run append), and the run replies inline 45s after that.
        {"type": "message", "step_id": "m5", "from": "slack-U2-D2", "to": "hl",
         "content": "quick q", "ts": _ts(500)},
        {"type": "feedback", "step_id": "f5", "source": "dispatcher",
         "trigger_step": "m5", "content": "a message arrived", "ts": _ts(499.8)},
        {"type": "reasoning", "step_id": "b5", "run_id": "run-1",
         "llm_s": 40, "in_tok": 1000, "out_tok": 200, "think_tok": 50,
         "ts": _ts(470)},
        {"type": "shell-output", "step_id": "b5o", "run_id": "run-1",
         "exec_s": 2, "ts": _ts(469)},
        {"type": "message", "step_id": "r5", "from": "hl", "to": "slack-U2-D2",
         "content": "10", "reply_to": "m5", "run_id": "run-1", "ts": _ts(425)},
    ]
    (traj_dir / "trajectory.jsonl").write_text(
        "".join(json.dumps(s) + "\n" for s in steps)
    )
    (identity / "run").mkdir()
    return tmp_path


def test_response_stats(health_root: Path):
    client = TestClient(create_app(health_root))
    response = client.get(f"/api/identities/{IDENTITY_ID}/health")
    assert response.status_code == 200
    payload = response.json()

    assert payload["identity"]["name"] == "hl"
    assert payload["activity"]["state"] == "asleep"  # no dispatcher here

    stats = payload["responses"]
    assert stats["replied"] == 3
    assert stats["declined"] == 1
    assert stats["undecided"] == 1  # m4 only; m0 is out of window
    assert stats["duplicates"] == 0

    recent = stats["recent"]  # newest first
    assert [e["outcome"] for e in recent] == [
        "replied", "replied", "declined", "replied"
    ]
    assert recent[1].get("path") == "fast"  # r3 has no run_id
    assert recent[0]["from"] == "slack-U2-D2"
    assert recent[0]["path"] == "inline"  # r5 carries run_id

    # path split: two fast replies (60s, 300s), one inline (75s)
    assert stats["paths"]["fast"]["n"] == 2
    assert stats["paths"]["inline"]["n"] == 1
    assert stats["paths"]["inline"]["median_s"] == pytest.approx(75, abs=15)

    # injection chain decomposition for m5
    inj = stats["injections"]
    assert len(inj) == 1
    assert inj[0]["from"] == "slack-U2-D2"
    assert inj[0]["path"] == "inline"
    assert inj[0]["inject_ms"] == pytest.approx(200, abs=150)
    assert inj[0]["wait_s"] == pytest.approx(30, abs=5)
    assert inj[0]["model_s"] == pytest.approx(45, abs=5)
    assert inj[0]["total_s"] == pytest.approx(75, abs=5)

    # model call aggregates from the stamped reasoning step
    model = stats["model"]
    assert model["calls"] == 1
    assert model["llm_p50_s"] == 40
    assert model["in_tok"] == 1000 and model["out_tok"] == 200
    assert model["think_tok"] == 50
    assert len(model["daily"]) == 1 and model["daily"][0]["calls"] == 1


def test_health_unknown_identity_404(health_root: Path):
    client = TestClient(create_app(health_root))
    assert (
        client.get("/api/identities/.identities~nope/health").status_code == 404
    )
