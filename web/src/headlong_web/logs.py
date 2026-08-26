"""Thinker log tails and dispatcher.log event parsing."""

import re
from pathlib import Path
from typing import Any

DISPATCH_STEP_RE = re.compile(
    r"\[dispatcher\]\s+step:\s+type=(?P<type>\S+)(?:\s+source=(?P<source>\S+))?"
)
DISPATCH_FIRE_RE = re.compile(
    r"\[dispatcher\]\s+dispatch\s+->\s+(?P<thinker>\S+)(?:\s+\(active=(?P<active>\d+)\))?"
)


def list_logs(identity_dir: Path) -> list[dict[str, Any]]:
    logs_dir = identity_dir / "run" / "logs"
    if not logs_dir.is_dir():
        return []
    result = []
    for path in sorted(logs_dir.glob("*.log")):
        stat = path.stat()
        result.append({"name": path.name, "bytes": stat.st_size, "mtime": stat.st_mtime})
    return result


def tail_log(log_path: Path, tail_bytes: int) -> dict[str, Any]:
    total = log_path.stat().st_size
    with log_path.open("rb") as fh:
        if total > tail_bytes:
            fh.seek(total - tail_bytes)
        data = fh.read()
    content = data.decode("utf-8", errors="replace")
    if total > tail_bytes:
        # drop the (likely partial) first line
        content = content.split("\n", 1)[-1]
    return {
        "name": log_path.name,
        "content": content,
        "total_bytes": total,
        "truncated": total > tail_bytes,
    }


def _tail_lines(
    log_path: Path,
    max_lines: int,
    chunk_bytes: int = 1 << 16,
    max_bytes: int = 8 << 20,
) -> list[str]:
    """The newest max_lines non-blank lines, read backward from the end.

    dispatcher.log is never rotated and the endpoint above this is polled every
    couple of seconds, so the whole-file read this replaces cost 31s and ~1GB of
    allocation on a 190MB log to return the same 2000 events. tail_log solves
    the same problem for raw log tails; this one counts lines rather than bytes,
    because the caller's cap is in events.

    max_bytes is the hard ceiling on the read: a log whose tail never reaches
    max_lines non-blank lines (a few enormous lines, say) must not be scanned
    end to end at poll cadence. Past it, whatever whole lines are in hand are
    the answer.

    The stop condition counts complete lines only, kept as a running count per
    chunk: the fragment before the accumulated data's first newline is judged
    once more of the file arrives (or the loop reaches the file's start), never
    counted early — an early count would be dropped by the partial-line trim
    below and could return fewer lines than the file holds.
    """
    if max_lines <= 0:
        return []
    parts: list[bytes] = []  # chunks as read, i.e. reversed file order
    with log_path.open("rb") as fh:
        fh.seek(0, 2)
        pos = fh.tell()
        count = 0
        total = 0
        frag_nonblank = False  # the pending fragment: the data's first line so far
        at_eof_chunk = True
        while pos > 0:
            step = min(chunk_bytes, pos)
            pos -= step
            fh.seek(pos)
            chunk = fh.read(step)
            parts.append(chunk)
            total += step
            segs = chunk.split(b"\n")
            if at_eof_chunk:
                # The chunk holding the file's end: everything after its first
                # newline is complete lines (the file's own last line included,
                # trailing newline or not).
                count += sum(1 for s in segs[1:] if s.strip())
                frag_nonblank = bool(segs[0].strip())
                at_eof_chunk = False
            elif len(segs) == 1:
                # No newline: the chunk only extends the pending fragment.
                frag_nonblank = frag_nonblank or bool(segs[0].strip())
            else:
                # The last segment completes the pending fragment; the middle
                # segments are whole lines of their own.
                if frag_nonblank or segs[-1].strip():
                    count += 1
                count += sum(1 for s in segs[1:-1] if s.strip())
                frag_nonblank = bool(segs[0].strip())
            if count >= max_lines or total >= max_bytes:
                break
    text = b"".join(reversed(parts)).decode("utf-8", errors="replace")
    lines = text.splitlines()
    if pos > 0 and lines:
        lines = lines[1:]  # drop the (likely partial) first line
    return [line for line in lines if line.strip()][-max_lines:]


def parse_dispatch_log(identity_dir: Path, max_events: int = 2000) -> list[dict[str, Any]]:
    """Parse dispatcher.log into structured events (newest last).

    Only the tail is read: max_events bounds the work, not just the answer.
    """
    log_path = identity_dir / "run" / "logs" / "dispatcher.log"
    if not log_path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in _tail_lines(log_path, max_events):
        stripped = line.strip()
        if not stripped:
            continue
        if match := DISPATCH_STEP_RE.search(stripped):
            events.append(
                {
                    "kind": "step",
                    "type": match.group("type"),
                    "source": match.group("source"),
                    "raw": stripped,
                }
            )
        elif match := DISPATCH_FIRE_RE.search(stripped):
            active = match.group("active")
            events.append(
                {
                    "kind": "dispatch",
                    "thinker": match.group("thinker"),
                    "active": int(active) if active is not None else None,
                    "raw": stripped,
                }
            )
        else:
            events.append({"kind": "other", "raw": stripped})
    return events[-max_events:]
