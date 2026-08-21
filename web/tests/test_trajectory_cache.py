"""Append-aware trajectory cache + incremental mindlog endpoint."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from headlong_web import trajectory
from headlong_web.server import create_app

ROOT_TRAJ = "fbfbfbfb-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def _step(i: int, **extra) -> dict:
    return {"type": "thought", "step_id": f"s{i:04d}", "content": f"idea {i}",
            "source": "inner_monologue", "ts": f"2026-07-17T10:{i % 60:02d}:00", **extra}


def _write(jsonl: Path, steps: list[dict], append: bool = False) -> None:
    mode = "a" if append else "w"
    with jsonl.open(mode) as fh:
        for s in steps:
            fh.write(json.dumps(s) + "\n")


@pytest.fixture
def traj_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fbfbfbfb-root"
    d.mkdir()
    _write(d / "trajectory.jsonl", [{"type": "trajectory", "step_id": ROOT_TRAJ, "ts": "t0"}])
    return d


def test_incremental_matches_full_reparse(traj_dir: Path):
    jsonl = traj_dir / "trajectory.jsonl"
    cache = trajectory.TrajectoryCache()

    # grow the log in stages, including a run with trigger joins
    _write(jsonl, [_step(i) for i in range(1, 4)], append=True)
    first = cache.load(traj_dir)
    assert first["step_count"] == 4

    _write(jsonl, [
        {"type": "action", "step_id": "act1", "content": "do the thing",
         "source": "inner_monologue", "ts": "t"},
    ], append=True)
    cache.load(traj_dir)

    _write(jsonl, [
        {"type": "shellm-run", "step_id": "run1", "command": "shellm ...",
         "trigger_step": "act1", "ts": "t"},
        {"type": "reasoning", "step_id": "r1", "thought": "hm", "cmd": "ls",
         "run_id": "run1", "ts": "t"},
        {"type": "final", "step_id": "f1", "content": "done", "run_id": "run1", "ts": "t"},
    ], append=True)
    incremental = cache.load(traj_dir)
    full = trajectory.load_trajectory(traj_dir)

    assert incremental["step_count"] == full["step_count"] == 8
    assert incremental["steps"] == full["steps"]
    assert incremental["runs"] == full["runs"]
    # the run resolved its trigger and closed, across separate refreshes
    assert incremental["runs"][0]["trigger_step_id"] == "act1"
    assert incremental["runs"][0]["status"] == "done"


def test_torn_tail_deferred(traj_dir: Path):
    jsonl = traj_dir / "trajectory.jsonl"
    cache = trajectory.TrajectoryCache()
    _write(jsonl, [_step(1)], append=True)
    with jsonl.open("a") as fh:
        fh.write('{"type":"thought","step_id":"torn","content":"half')  # no newline
    body = cache.load(traj_dir)
    assert body["step_count"] == 2  # torn line not consumed
    with jsonl.open("a") as fh:
        fh.write(' written"}\n')
    body = cache.load(traj_dir)
    assert body["step_count"] == 3
    assert body["steps"][-1]["raw"]["content"] == "half written"


def test_replaced_file_resets(traj_dir: Path):
    jsonl = traj_dir / "trajectory.jsonl"
    cache = trajectory.TrajectoryCache()
    _write(jsonl, [_step(i) for i in range(1, 10)], append=True)
    assert cache.load(traj_dir)["step_count"] == 10

    # rewrite shorter (e.g. restored from backup)
    _write(jsonl, [{"type": "trajectory", "step_id": ROOT_TRAJ, "ts": "t0"}, _step(1)])
    assert cache.load(traj_dir)["step_count"] == 2


# ---------------------------------------------------------------------------
# Endpoint: ?since= deltas
# ---------------------------------------------------------------------------


@pytest.fixture
def ident_root(tmp_path: Path) -> Path:
    identity = tmp_path / ".identities" / "scaly"
    identity.mkdir(parents=True)
    (identity / "info.txt").write_text(
        f"name=scaly\ncreated=x\nroot_trajectory={ROOT_TRAJ}\n"
    )
    d = identity / "trajectories" / "fbfbfbfb-root"
    d.mkdir(parents=True)
    _write(
        d / "trajectory.jsonl",
        [{"type": "trajectory", "step_id": ROOT_TRAJ, "ts": "t0"}]
        + [_step(i) for i in range(1, 6)],
    )
    return tmp_path


def test_mindlog_since(ident_root: Path):
    client = TestClient(create_app(ident_root))
    url = "/api/identities/.identities~scaly/mindlog"

    full = client.get(url).json()
    assert full["step_count"] == 6
    assert len(full["steps"]) == 6
    assert full["since"] is None

    delta = client.get(f"{url}?since=6").json()
    assert delta["step_count"] == 6
    assert delta["steps"] == []
    assert delta["since"] == 6

    jsonl = (
        ident_root / ".identities" / "scaly" / "trajectories"
        / "fbfbfbfb-root" / "trajectory.jsonl"
    )
    _write(jsonl, [_step(6), _step(7)], append=True)
    delta = client.get(f"{url}?since=6").json()
    assert delta["step_count"] == 8
    assert [s["step_id"] for s in delta["steps"]] == ["s0006", "s0007"]
    assert delta["identity"]["name"] == "scaly"

    # runs ship as deltas too: only those touched by unseen steps
    _write(jsonl, [
        {"type": "shellm-run", "step_id": "runA", "command": "shellm big-prompt", "ts": "t"},
        {"type": "final", "step_id": "finA", "content": "done", "run_id": "runA", "ts": "t"},
    ], append=True)
    delta = client.get(f"{url}?since=8").json()
    assert [r["run_id"] for r in delta["runs"]] == ["runA"]
    assert delta["runs"][0]["status"] == "done"
    # once seen, an untouched run drops out of later deltas
    assert client.get(f"{url}?since=10").json()["runs"] == []
    # full fetches still carry every run
    assert [r["run_id"] for r in client.get(url).json()["runs"]] == ["runA"]

    # since beyond the log is an empty delta, not an error
    assert client.get(f"{url}?since=999").json()["steps"] == []
    # negative rejected
    assert client.get(f"{url}?since=-1").status_code == 422


def test_mindlog_tail_and_window(ident_root: Path):
    client = TestClient(create_app(ident_root))
    url = "/api/identities/.identities~scaly/mindlog"

    # ?tail=N ships only the newest N; `since` echoes the window start
    tail = client.get(f"{url}?tail=2").json()
    assert tail["step_count"] == 6
    assert tail["since"] == 4
    assert [s["step_id"] for s in tail["steps"]] == ["s0004", "s0005"]

    # a tail larger than the log is the whole log
    assert len(client.get(f"{url}?tail=99").json()["steps"]) == 6

    # ?since+?until loads an older [A, B) window
    window = client.get(f"{url}?since=1&until=3").json()
    assert [s["step_id"] for s in window["steps"]] == ["s0001", "s0002"]
    assert window["since"] == 1

    # explicit since wins over tail
    both = client.get(f"{url}?since=5&tail=2").json()
    assert [s["step_id"] for s in both["steps"]] == ["s0005"]


def test_run_command_truncated_and_fetchable(ident_root: Path):
    jsonl = (
        ident_root / ".identities" / "scaly" / "trajectories"
        / "fbfbfbfb-root" / "trajectory.jsonl"
    )
    big = "PROMPT " * 1000 + "ACTION: do the dance"  # ~7KB
    _write(jsonl, [
        {"type": "shellm-run", "step_id": "runbig", "command": big, "ts": "t"},
        {"type": "shellm-run", "step_id": "runsmall", "command": "shellm tiny", "ts": "t"},
    ], append=True)
    client = TestClient(create_app(ident_root))

    runs = client.get("/api/identities/.identities~scaly/mindlog").json()["runs"]
    by_id = {r["run_id"]: r for r in runs}
    assert by_id["runsmall"]["command"] == "shellm tiny"
    assert by_id["runsmall"]["command_truncated"] is False
    truncated = by_id["runbig"]
    assert truncated["command_truncated"] is True
    assert len(truncated["command"]) < 3000
    # head and the titling ACTION tail both survive truncation
    assert truncated["command"].startswith("PROMPT ")
    assert truncated["command"].endswith("ACTION: do the dance")

    full = client.get(
        "/api/identities/.identities~scaly/runs/runbig/command"
    ).json()
    assert full["command"] == big
    assert (
        client.get(
            "/api/identities/.identities~scaly/runs/nope/command"
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Raw eviction: bounded memory, windows rehydrate from disk
# ---------------------------------------------------------------------------


def test_eviction_and_window_rehydration(traj_dir: Path):
    jsonl = traj_dir / "trajectory.jsonl"
    _write(jsonl, [_step(i) for i in range(1, 40)], append=True)
    cache = trajectory.TrajectoryCache(raw_budget=600)  # a few steps' worth
    body = cache.load(traj_dir)
    steps = body["steps"]
    assert body["step_count"] == 40
    # oldest raws evicted, newest retained; wrappers survive either way
    assert steps[0]["raw"] is None
    assert steps[-1]["raw"] is not None
    assert steps[1]["step_id"] == "s0001"
    assert steps[1]["preview"]
    # a window rehydrates exactly what a full reparse sees
    full = trajectory.load_trajectory(traj_dir)
    window = cache.window(traj_dir, 1, 5)
    assert [s["raw"] for s in window["steps"]] == [s["raw"] for s in full["steps"][1:5]]
    # ...as copies: the cache's own entry stays evicted
    assert cache.load(traj_dir)["steps"][1]["raw"] is None
    # tail + since semantics mirror the mindlog endpoint
    tail = cache.window(traj_dir, tail=3)
    assert tail["since"] == 37
    assert [s["step_id"] for s in tail["steps"]] == ["s0037", "s0038", "s0039"]
    assert all(s["raw"] is not None for s in tail["steps"])


def test_search_spans_evicted_history(traj_dir: Path):
    from headlong_web import search

    jsonl = traj_dir / "trajectory.jsonl"
    _write(jsonl, [_step(i) for i in range(1, 60)], append=True)
    cache = trajectory.TrajectoryCache(raw_budget=600)
    cache.load(traj_dir)
    assert cache.load(traj_dir)["steps"][3]["raw"] is None  # deep history evicted

    result = search.search_cache(cache, traj_dir, "idea 3", scope="thoughts", limit=5)
    # matches: idea 3, idea 30..39 = 11 total, newest first, limit honored
    assert result["total"] == 11
    assert len(result["hits"]) == 5
    assert result["hits"][0]["index"] == 39
    assert result["hits"][0]["step_id"] == "s0039"
    assert "idea 39" in result["hits"][0]["snippet"]


def test_run_command_rehydrates_after_eviction(traj_dir: Path):
    jsonl = traj_dir / "trajectory.jsonl"
    big = "PROMPT " * 1000 + "ACTION: dance"
    _write(jsonl, [{"type": "shellm-run", "step_id": "runbig", "command": big, "ts": "t"}],
           append=True)
    _write(jsonl, [_step(i) for i in range(1, 30)], append=True)
    cache = trajectory.TrajectoryCache(raw_budget=500)
    body = cache.load(traj_dir)
    assert body["steps"][1]["raw"] is None  # the run header's raw is gone
    by_id = {r["run_id"]: r for r in body["runs"]}
    assert by_id["runbig"]["command_truncated"] is True
    assert cache.run_command(traj_dir, "runbig") == big


def test_chat_index_survives_eviction(traj_dir: Path):
    from headlong_web import chat

    jsonl = traj_dir / "trajectory.jsonl"
    _write(jsonl, [
        {"type": "message", "step_id": "m1", "content": "hello audel",
         "from": "slack-nick", "to": "audel", "ts": "t1"},
    ], append=True)
    _write(jsonl, [_step(i) for i in range(1, 40)], append=True)
    cache = trajectory.TrajectoryCache(raw_budget=400)
    assert cache.load(traj_dir)["steps"][1]["raw"] is None  # message raw evicted
    view = chat.chat_view(cache.chat_steps(traj_dir), "audel")
    assert view["messages"][0]["content"] == "hello audel"
    assert view["messages"][0]["from"] == "slack-nick"


def test_step_endpoint_hydrates_evicted(ident_root: Path, monkeypatch):
    monkeypatch.setattr(trajectory, "CACHE", trajectory.TrajectoryCache(raw_budget=300))
    jsonl = (
        ident_root / ".identities" / "scaly" / "trajectories"
        / "fbfbfbfb-root" / "trajectory.jsonl"
    )
    _write(jsonl, [_step(i) for i in range(6, 40)], append=True)
    client = TestClient(create_app(ident_root))
    url = "/api/identities/.identities~scaly"

    mindlog = client.get(f"{url}/mindlog?tail=3").json()
    assert all(s["raw"] is not None for s in mindlog["steps"])

    got = client.get(f"{url}/step/s0001").json()
    assert got["index"] == 1
    assert got["step"]["raw"]["content"] == "idea 1"

    window = client.get(f"{url}/mindlog?since=1&until=4").json()
    assert [s["raw"]["content"] for s in window["steps"]] == [
        "idea 1", "idea 2", "idea 3",
    ]
