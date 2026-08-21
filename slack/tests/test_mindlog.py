import json

from headlong_slack.mindlog import find_trajectory, read_new


def _append(path, obj, newline=True):
    with path.open("a") as f:
        f.write(json.dumps(obj) + ("\n" if newline else ""))


def test_read_new_only_complete_lines(tmp_path):
    traj = tmp_path / "trajectory.jsonl"
    traj.write_text("")
    steps, off = read_new(traj, 0)
    assert steps == [] and off == 0

    _append(traj, {"type": "message", "content": "one"})
    steps, off = read_new(traj, off)
    assert [s["content"] for s in steps] == ["one"]

    # Partial line is not consumed until its newline arrives.
    with traj.open("a") as f:
        f.write('{"type": "message", "content": "tw')
    steps, off2 = read_new(traj, off)
    assert steps == [] and off2 == off
    with traj.open("a") as f:
        f.write('o"}\n')
    steps, off = read_new(traj, off)
    assert [s["content"] for s in steps] == ["two"]


def test_read_new_skips_corrupt_lines(tmp_path):
    traj = tmp_path / "trajectory.jsonl"
    traj.write_text('not json\n{"type": "message", "content": "ok"}\n')
    steps, _ = read_new(traj, 0)
    assert [s["content"] for s in steps] == ["ok"]


def test_read_new_resets_on_truncation(tmp_path):
    traj = tmp_path / "trajectory.jsonl"
    _append(traj, {"content": "a"})
    _append(traj, {"content": "b"})
    _, off = read_new(traj, 0)
    traj.write_text('{"content": "fresh"}\n')
    steps, _ = read_new(traj, off)
    assert [s["content"] for s in steps] == ["fresh"]


def test_find_trajectory(tmp_path):
    identity = tmp_path / "audel"
    traj_dir = identity / "trajectories" / "deadbeef-mind"
    traj_dir.mkdir(parents=True)
    (traj_dir / "trajectory.jsonl").write_text("")
    (identity / "info.txt").write_text(
        "name=audel\nroot_trajectory=deadbeef-1234-5678-9abc-def012345678\n"
    )
    assert find_trajectory(identity) == traj_dir / "trajectory.jsonl"
