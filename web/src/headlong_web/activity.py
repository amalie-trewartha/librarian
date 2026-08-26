"""Working-vs-stalled activity classification for an identity.

The "live" pip can't tell a healthy 50-minute agentic run from a hung
step: units are active and the dispatcher pid is alive in both. This
module combines the signals that do distinguish them — live step pids
(run/step_pids), mind-log growth (trajectory.jsonl mtime), the
identity's own recent step cadence, and the pending trigger queue —
into one classified payload:

- working: steps in flight and the mind log grew recently
- stalled: steps in flight but the log has been quiet past the threshold
- idle:    dispatcher up, nothing in flight
- asleep:  dispatcher down

"Recently" adapts to the identity: the stall threshold is a floor
raised to a multiple of the median gap between its own recent steps, so
a slow-thinking identity isn't flagged by its normal pace.
"""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from headlong_web import discovery, thinkers
from headlong_web.liveness import pid_alive
from headlong_web.llm_health import _parse_ts, _tail_steps

# Busy + no mind-log growth for this long -> stalled. Floor value; raised
# to STALL_CADENCE_FACTOR x the recent median step gap when known.
STALL_FLOOR_S = 300
STALL_CADENCE_FACTOR = 4.0

_CADENCE_WINDOW_STEPS = 60
_PREVIEW_CHARS = 120


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _step_cadence_s(steps: list[dict]) -> float | None:
    """Median gap between consecutive recent steps, any type."""
    times = [
        ts
        for step in steps[-_CADENCE_WINDOW_STEPS:]
        if (ts := _parse_ts(str(step.get("ts") or ""))) is not None
    ]
    gaps = [b - a for a, b in zip(times, times[1:]) if 0 < b - a < 3600]
    if len(gaps) < 5:
        return None
    return float(median(gaps))


def _parse_etime(text: str) -> float | None:
    """ps etime format: [[dd-]hh:]mm:ss."""
    text = text.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_part, _, text = text.partition("-")
        try:
            days = int(day_part)
        except ValueError:
            return None
    try:
        nums = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(nums) == 3:
        hours, minutes, seconds = nums
    elif len(nums) == 2:
        hours, (minutes, seconds) = 0, nums
    else:
        return None
    return float(((days * 24 + hours) * 60 + minutes) * 60 + seconds)


def _run_seconds(pids: list[int]) -> float | None:
    """Elapsed seconds of the oldest live step process, via ps etime."""
    if not pids:
        return None
    try:
        proc = subprocess.run(
            ["ps", "-o", "etime=", "-p", ",".join(str(p) for p in pids)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    elapsed = [
        secs for line in proc.stdout.splitlines()
        if (secs := _parse_etime(line)) is not None
    ]
    return max(elapsed) if elapsed else None


def _live_step_pids(run_dir: Path) -> list[int]:
    """Live pids from run/step_pids ("pid name" lines; the dispatcher prunes completed steps)."""
    pids = []
    try:
        lines = (run_dir / "step_pids").read_text().splitlines()
    except OSError:
        return pids
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if thinkers._pid_running(pid):
            pids.append(pid)
    return pids


def _queued_and_total(run_dir: Path, now: float) -> tuple[list[dict], int]:
    """Parse run/pending/: message-trigger entries (with sender + age from
    the queued step JSON the dispatcher writes) and the total flag count."""
    queued: list[dict] = []
    total = 0
    pending_dir = run_dir / "pending"
    if not pending_dir.is_dir():
        return queued, total
    for flag in sorted(pending_dir.iterdir()):
        if not flag.is_file():
            continue
        # <name>.<type>.<epoch>.<seq> (queued) or <name>.<type>.coalesced
        parts = flag.name.split(".")
        if len(parts) < 2:
            continue
        total += 1
        if parts[1] != "message":
            continue
        entry: dict = {
            "thinker": parts[0],
            "from": None,
            "preview": None,
            "ts": None,
            "age_s": None,
        }
        ts: float | None = None
        try:
            step = json.loads(flag.read_text())
        except (OSError, ValueError):
            step = None
        if isinstance(step, dict):
            sender = step.get("from")
            entry["from"] = str(sender) if sender is not None else None
            content = str(step.get("content") or "")
            entry["preview"] = content[:_PREVIEW_CHARS] or None
            ts = _parse_ts(str(step.get("ts") or ""))
        if ts is None:
            try:
                ts = flag.stat().st_mtime
            except OSError:
                ts = None
        if ts is not None:
            entry["ts"] = _iso(ts)
            entry["age_s"] = round(max(0.0, now - ts), 1)
        queued.append(entry)
    return queued, total


def identity_activity(identity: discovery.IdentityInfo) -> dict:
    now = time.time()
    run_dir = identity.path / "run"
    dispatcher_alive, _ = pid_alive(run_dir / "dispatcher.pid")
    live_steps = thinkers._live_steps_by_thinker(run_dir)
    steps_in_flight = sum(live_steps.values())

    last_append: float | None = None
    cadence: float | None = None
    traj_dir = discovery.find_root_traj_dir(identity)
    if traj_dir is not None:
        jsonl = traj_dir / "trajectory.jsonl"
        try:
            last_append = jsonl.stat().st_mtime
        except OSError:
            pass
        cadence = _step_cadence_s(_tail_steps(jsonl))

    stall_after = float(STALL_FLOOR_S)
    if cadence is not None:
        stall_after = max(stall_after, STALL_CADENCE_FACTOR * cadence)
    last_age = now - last_append if last_append is not None else None

    if not dispatcher_alive:
        state = "asleep"
    elif steps_in_flight == 0:
        state = "idle"
    elif last_age is not None and last_age > stall_after:
        state = "stalled"
    else:
        state = "working"  # busy; no log yet = benefit of the doubt

    queued, pending_total = _queued_and_total(run_dir, now)
    run_seconds = _run_seconds(_live_step_pids(run_dir)) if steps_in_flight else None

    return {
        "state": state,
        "dispatcher_running": dispatcher_alive,
        "steps_in_flight": steps_in_flight,
        "busy_thinkers": sorted(live_steps),
        "last_step_ts": _iso(last_append),
        "last_step_age_s": round(last_age, 1) if last_age is not None else None,
        "run_seconds": run_seconds,
        "stall_after_s": round(stall_after, 1),
        "cadence_s": round(cadence, 1) if cadence is not None else None,
        "queued_messages": queued,
        "pending_total": pending_total,
    }
