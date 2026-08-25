"""parse_dispatch_log: the event cap has to bound the read, not just the answer.

The endpoint behind this (GET /api/identities/{id}/dispatch) is polled every
2 seconds while an identity is live, and dispatcher.log is never rotated: a
real box has been recorded at 465M of them. Reading the whole file to return
the last 2000 events measured 31s and 1GB of allocation on a 190MB log, so
these tests pin both halves, the events returned AND the fact that the head of
the file is never touched.
"""

from pathlib import Path

import pytest

from headlong_web import logs


def _write_log(identity: Path, lines: list[str]) -> Path:
    log_path = identity / "run" / "logs" / "dispatcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n")
    return log_path


STEP = "2026-08-01T00:00:{:02d}Z [dispatcher] step: type=message source=chat"
FIRE = "2026-08-01T00:00:{:02d}Z [dispatcher] dispatch -> responder (active=1)"
OTHER = "2026-08-01T00:00:{:02d}Z [dispatcher] tick: nothing to do"


def test_parses_each_kind(tmp_path: Path) -> None:
    _write_log(tmp_path, [STEP.format(1), FIRE.format(2), OTHER.format(3)])
    events = logs.parse_dispatch_log(tmp_path)
    assert [e["kind"] for e in events] == ["step", "dispatch", "other"]
    assert events[0]["type"] == "message"
    assert events[0]["source"] == "chat"
    assert events[1]["thinker"] == "responder"
    assert events[1]["active"] == 1


def test_newest_last_and_capped(tmp_path: Path) -> None:
    _write_log(tmp_path, [OTHER.format(i % 60) for i in range(50)] + [STEP.format(59)])
    events = logs.parse_dispatch_log(tmp_path, max_events=10)
    assert len(events) == 10
    assert events[-1]["kind"] == "step"


def test_blank_lines_and_missing_trailing_newline(tmp_path: Path) -> None:
    log_path = tmp_path / "run" / "logs" / "dispatcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(f"{OTHER.format(1)}\n\n   \n{STEP.format(2)}")
    events = logs.parse_dispatch_log(tmp_path)
    assert [e["kind"] for e in events] == ["other", "step"]


def test_empty_and_missing(tmp_path: Path) -> None:
    assert logs.parse_dispatch_log(tmp_path) == []
    _write_log(tmp_path, [])
    assert logs.parse_dispatch_log(tmp_path) == []


def test_returns_the_newest_events_from_a_long_log(tmp_path: Path) -> None:
    """The oldest lines must not appear in the answer."""
    lines = ["OLDEST-CANARY [dispatcher] step: type=oldest source=head"]
    lines += [OTHER.format(i % 60) for i in range(5000)]
    lines += [STEP.format(59)]
    _write_log(tmp_path, lines)
    events = logs.parse_dispatch_log(tmp_path, max_events=100)
    assert len(events) == 100
    assert not any("OLDEST-CANARY" in e["raw"] for e in events)
    assert events[-1]["type"] == "message"


def test_does_not_read_the_whole_file(tmp_path: Path, monkeypatch) -> None:
    """The cap has to bound the read. A whole-file read fails this outright."""
    lines = ["OLDEST-CANARY [dispatcher] step: type=oldest source=head"]
    lines += [OTHER.format(i % 60) for i in range(20000)]
    lines += [STEP.format(59)]
    _write_log(tmp_path, lines)

    def _boom(*args, **kwargs):  # pragma: no cover - only runs on failure
        raise AssertionError("parse_dispatch_log read the entire file")

    monkeypatch.setattr(Path, "read_text", _boom)
    events = logs.parse_dispatch_log(tmp_path, max_events=50)
    assert len(events) == 50
    assert events[-1]["type"] == "message"


def test_reads_a_bounded_amount(tmp_path: Path) -> None:
    """Peak allocation tracks the cap, not the file."""
    tracemalloc = pytest.importorskip("tracemalloc")
    lines = [OTHER.format(i % 60) for i in range(200000)]
    _write_log(tmp_path, lines)
    file_bytes = (tmp_path / "run" / "logs" / "dispatcher.log").stat().st_size
    tracemalloc.start()
    logs.parse_dispatch_log(tmp_path, max_events=100)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < file_bytes / 4, f"peak {peak} against a {file_bytes} byte log"


def test_multibyte_across_a_chunk_boundary(tmp_path: Path) -> None:
    """Chunks are read backward and joined, so a character split across a
    boundary must not corrupt a line that is kept."""
    wide = "\u4e2d\u6587\u30c6\u30b9\u30c8"  # multibyte, 3 bytes per char
    lines = [f"2026-08-01T00:00:00Z [dispatcher] tick: {wide}{i}" for i in range(5000)]
    lines.append(STEP.format(59))
    _write_log(tmp_path, lines)
    events = logs.parse_dispatch_log(tmp_path, max_events=200)
    assert len(events) == 200
    assert all("\ufffd" not in e["raw"] for e in events), "a kept line was corrupted"
    assert all(wide in e["raw"] for e in events[:-1])
    assert events[-1]["type"] == "message"


def test_a_line_longer_than_the_chunk(tmp_path: Path) -> None:
    """One pathological line must not lose the lines after it."""
    _write_log(
        tmp_path,
        [
            "2026-08-01T00:00:00Z [dispatcher] tick: " + "x" * (1 << 17),
            STEP.format(1),
            FIRE.format(2),
        ],
    )
    events = logs.parse_dispatch_log(tmp_path, max_events=2)
    assert [e["kind"] for e in events] == ["step", "dispatch"]
