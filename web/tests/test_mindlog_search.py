"""Mind-log search + single-step endpoints."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from headlong_web.server import create_app

ROOT_TRAJ = "cdcdcdcd-8888-4888-8888-888888888888"
IDENTITY_ID = ".identities~srch"
URL = f"/api/identities/{IDENTITY_ID}/mindlog/search"


@pytest.fixture
def search_root(tmp_path: Path) -> Path:
    identity = tmp_path / ".identities" / "srch"
    identity.mkdir(parents=True)
    (identity / "info.txt").write_text(
        f"name=srch\ncreated=x\nroot_trajectory={ROOT_TRAJ}\n"
    )
    d = identity / "trajectories" / "cdcdcdcd-root"
    d.mkdir(parents=True)
    steps = [
        {"type": "trajectory", "step_id": ROOT_TRAJ, "ts": "t0"},
        {"type": "thought", "step_id": "t1", "source": "inner_monologue",
         "content": "pondering the Quantum biscuit problem", "ts": "t1"},
        {"type": "message", "step_id": "m1", "from": "braden", "to": "srch",
         "content": "any progress on quantum biscuits?", "ts": "t2"},
        # machinery: hidden from scope=thoughts, found by scope=all
        {"type": "shellm-run", "step_id": "run1",
         "command": "shellm --prompt 'bake quantum biscuits' ACTION: bake", "ts": "t3"},
        {"type": "shell-output", "step_id": "o1", "run_id": "run1",
         "stdout": "quantum oven preheated", "exit": 0, "ts": "t4"},
        {"type": "thought", "step_id": "t2", "source": "inner_monologue",
         "content": "unrelated musing about weather", "ts": "t5"},
    ]
    (d / "trajectory.jsonl").write_text(
        "".join(json.dumps(s) + "\n" for s in steps)
    )
    return tmp_path


def test_search_scopes_and_order(search_root: Path):
    client = TestClient(create_app(search_root))

    thoughts = client.get(f"{URL}?q=quantum").json()
    assert thoughts["total"] == 2  # machinery excluded
    assert [h["step_id"] for h in thoughts["hits"]] == ["m1", "t1"]  # newest first
    assert thoughts["hits"][0]["type"] == "message"
    assert "quantum biscuits" in thoughts["hits"][0]["snippet"]
    assert thoughts["step_count"] == 6

    everything = client.get(f"{URL}?q=quantum&scope=all").json()
    assert everything["total"] == 4
    assert [h["step_id"] for h in everything["hits"]] == ["o1", "run1", "m1", "t1"]
    assert everything["hits"][0]["field"] == "stdout"

    # case-insensitive both ways
    assert client.get(f"{URL}?q=QUANTUM").json()["total"] == 2
    assert client.get(f"{URL}?q=biscuit").json()["total"] == 2


def test_search_limit_and_validation(search_root: Path):
    client = TestClient(create_app(search_root))
    limited = client.get(f"{URL}?q=quantum&scope=all&limit=1").json()
    assert limited["total"] == 4  # total counts everything
    assert len(limited["hits"]) == 1

    assert client.get(f"{URL}?q=x").status_code == 422  # too short
    assert client.get(f"{URL}?q=quantum&scope=bogus").status_code == 422
    assert client.get(f"{URL}?q=nomatchesatall").json()["hits"] == []


def test_step_endpoint(search_root: Path):
    client = TestClient(create_app(search_root))
    payload = client.get(f"/api/identities/{IDENTITY_ID}/step/o1").json()
    assert payload["step"]["step_id"] == "o1"
    assert payload["index"] == 4
    assert payload["run"]["run_id"] == "run1"  # its run header rides along

    solo = client.get(f"/api/identities/{IDENTITY_ID}/step/t1").json()
    assert solo["run"] is None

    assert (
        client.get(f"/api/identities/{IDENTITY_ID}/step/nope").status_code
        == 404
    )


def test_search_read_only_mode(search_root: Path):
    """Search is a GET — must work for the read-only dash audience."""
    client = TestClient(create_app(search_root, read_only=True))
    assert client.get(f"{URL}?q=quantum").json()["total"] == 2
