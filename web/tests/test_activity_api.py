"""Activity endpoint: working / stalled / idle / asleep classification."""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from headlong_web.activity import _parse_etime
from headlong_web.server import create_app

ROOT_TRAJ = "ffffffff-6666-4666-8666-666666666666"
IDENTITY_ID = ".identities~act"

# A pid no real process should hold (beyond default pid_max on Linux and
# macOS's ~99998 ceiling), so os.kill(pid, 0) fails -> "not running".
DEAD_PID = 4194304


def _write_traj(identity: Path, gap_s: float = 60, count: int = 10) -> Path:
    """Mind log whose steps end now, spaced gap_s apart."""
    traj_dir = identity / "trajectories" / "ffffffff-root"
    traj_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    lines = [json.dumps({"type": "trajectory", "step_id": ROOT_TRAJ, "ts": "t0"})]
    for i in range(count):
        ts = now - timedelta(seconds=gap_s * (count - 1 - i))
        lines.append(
            json.dumps(
                {"type": "reasoning", "step_id": f"s{i}", "ts": ts.isoformat()}
            )
        )
    jsonl = traj_dir / "trajectory.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")
    return jsonl


@pytest.fixture
def act_root(tmp_path: Path) -> tuple[Path, Path]:
    """(serve root, identity dir) with a mind log ending now."""
    identity = tmp_path / ".identities" / "act"
    identity.mkdir(parents=True)
    (identity / "info.txt").write_text(
        f"name=act\ncreated=2026-08-07T00:00:00\nroot_trajectory={ROOT_TRAJ}\n"
    )
    _write_traj(identity)
    (identity / "run").mkdir()
    return tmp_path, identity


def _get(root: Path) -> dict:
    client = TestClient(create_app(root))
    response = client.get(f"/api/identities/{IDENTITY_ID}/activity")
    assert response.status_code == 200
    return response.json()


def _wake(identity: Path) -> None:
    (identity / "run" / "dispatcher.pid").write_text(str(os.getpid()))


def _busy(identity: Path) -> None:
    (identity / "run" / "step_pids").write_text(
        f"{os.getpid()} monolith\n{DEAD_PID} monolith\n"
    )


def test_asleep_when_no_dispatcher(act_root):
    root, _identity = act_root
    payload = _get(root)
    assert payload["state"] == "asleep"
    assert payload["dispatcher_running"] is False


def test_idle_when_dispatcher_up_and_nothing_in_flight(act_root):
    root, identity = act_root
    _wake(identity)
    payload = _get(root)
    assert payload["state"] == "idle"
    assert payload["steps_in_flight"] == 0
    assert payload["run_seconds"] is None


def test_working_when_busy_and_log_growing(act_root):
    root, identity = act_root
    _wake(identity)
    _busy(identity)
    payload = _get(root)
    assert payload["state"] == "working"
    assert payload["steps_in_flight"] == 1  # dead pid not counted
    assert payload["busy_thinkers"] == ["monolith"]
    assert payload["last_step_age_s"] < 60
    assert payload["cadence_s"] == pytest.approx(60, abs=5)
    assert payload["run_seconds"] is not None and payload["run_seconds"] >= 0


def test_stalled_when_busy_but_log_quiet(act_root):
    root, identity = act_root
    _wake(identity)
    _busy(identity)
    jsonl = identity / "trajectories" / "ffffffff-root" / "trajectory.jsonl"
    old = time.time() - 400  # past the 300s floor (cadence keeps it at 300)
    os.utime(jsonl, (old, old))
    payload = _get(root)
    assert payload["state"] == "stalled"
    assert payload["last_step_age_s"] > payload["stall_after_s"]


def test_slow_cadence_raises_stall_threshold(act_root):
    root, identity = act_root
    jsonl = _write_traj(identity, gap_s=200)  # 4x200 = 800s threshold
    _wake(identity)
    _busy(identity)
    old = time.time() - 400
    os.utime(jsonl, (old, old))
    payload = _get(root)
    assert payload["state"] == "working"  # quiet 400s but within its own pace
    assert payload["stall_after_s"] == pytest.approx(800, abs=40)


def test_queued_messages_parsed_from_pending(act_root):
    root, identity = act_root
    _wake(identity)
    _busy(identity)
    pending = identity / "run" / "pending"
    pending.mkdir()
    sent = datetime.now(timezone.utc) - timedelta(seconds=120)
    (pending / "monolith.message.1786136238.000294").write_text(
        json.dumps(
            {
                "type": "message",
                "content": "hey audel, quick question",
                "from": "pwa-nick",
                "to": "act",
                "ts": sent.isoformat(),
            }
        )
    )
    (pending / "monolith.idle.coalesced").write_text("{}")
    payload = _get(root)
    assert payload["pending_total"] == 2
    queued = payload["queued_messages"]
    assert len(queued) == 1
    assert queued[0]["thinker"] == "monolith"
    assert queued[0]["from"] == "pwa-nick"
    assert queued[0]["preview"] == "hey audel, quick question"
    assert queued[0]["age_s"] == pytest.approx(120, abs=10)


def test_unknown_identity_404(act_root):
    root, _identity = act_root
    client = TestClient(create_app(root))
    response = client.get("/api/identities/.identities~nope/activity")
    assert response.status_code == 404


def test_parse_etime():
    assert _parse_etime("05:06") == 306
    assert _parse_etime("01:02:03") == 3723
    assert _parse_etime("2-01:02:03") == 2 * 86400 + 3723
    assert _parse_etime("") is None
    assert _parse_etime("garbage") is None
