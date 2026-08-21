"""Per-identity health: message response stats from the mind log.

Precise, not heuristic: outbound replies stamp reply_to with the inbound
step they answer (transport-level since 9d00f2e), and declines stamp
trigger_step on a decision:"no-reply" observation — so response time is
just the timestamp delta between the paired steps. Inbound messages in
the window with neither stamp are "undecided" (queued, in progress, or
dropped).

Three further signals ride the same pass:

- Reply path: a reply carrying run_id was composed inside an agentic run
  ("inline"); one without came from the fast-reply path ("fast").
- Injection events: a dispatcher feedback step (source:"dispatcher",
  trigger_step) marks a message that queued behind a busy run. Its reply
  chain decomposes into inject (message -> note), wait (note -> the next
  run append, i.e. the in-flight model call finishing), and model (that
  boundary -> the reply).
- Model calls: llm_s / token stamps on reasoning steps (written by
  bin/shellm + bin/llm) aggregate into call counts, durations, and daily
  token spend.
"""

import time
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from headlong_web.activity import _iso
from headlong_web.llm_health import _parse_ts
from headlong_web import trajectory

WINDOW_DAYS = 7
RECENT_ROWS = 20
INJECTION_ROWS = 20


def _quantile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, round(q * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def _path_stats(times: list[float]) -> dict:
    ordered = sorted(times)
    return {
        "n": len(ordered),
        "median_s": round(median(ordered), 1) if ordered else None,
        "p90_s": _quantile(ordered, 0.9),
    }


def response_stats(traj_dir: Path, identity_name: str) -> dict:
    now = time.time()
    cutoff = now - WINDOW_DAYS * 86400
    # Every aggregate below is windowed to the last WINDOW_DAYS, so only
    # stream-parse the log from where that window starts (found by walking
    # the cache's step wrappers back from the tail) — parsing the WHOLE
    # jsonl here was one of the O(log) request paths behind the 2026-08-13
    # OOM incident. Downstream ts >= cutoff filters stay authoritative.
    wrappers = trajectory.CACHE.load(traj_dir)["steps"]
    start = len(wrappers)
    for i in range(len(wrappers) - 1, -1, -1):
        ts = _parse_ts(str(wrappers[i].get("ts") or ""))
        if ts is not None and ts < cutoff:
            break
        start = i
    if start >= len(wrappers):
        steps = iter(())  # nothing within the window
    else:
        # span-less steps can't happen via the cache; fall back to a full
        # stream from 0 rather than miss data if they somehow do
        offset = trajectory.CACHE.offset_of(traj_dir, start) or 0
        steps = trajectory.iter_jsonl(traj_dir / "trajectory.jsonl", offset)

    inbound: dict[str, dict] = {}  # step_id -> {"ts", "from"}
    events: list[dict] = []
    decided: set[str] = set()
    reply_counts: Counter = Counter()  # inbound step_id -> stamped replies
    replies: dict[str, dict] = {}  # inbound step_id -> {"ts", "path"}
    fb_events: list[tuple[str, float]] = []  # (trigger_step, feedback ts)
    run_appends: list[float] = []  # reasoning/shell-output append times
    llm_times: list[float] = []
    tokens: dict[str, int] = {"in_tok": 0, "out_tok": 0, "think_tok": 0}
    daily: dict[str, dict] = {}  # utc day -> {calls, in_tok, out_tok, think_tok}

    def _record(trigger_id: str, ts: float | None, outcome: str, path: str | None) -> None:
        src = inbound.get(trigger_id)
        if src is None or ts is None or trigger_id in decided:
            return
        decided.add(trigger_id)
        events.append(
            {
                "ts": _iso(ts),
                "from": src["from"],
                "outcome": outcome,
                "path": path,
                "response_s": round(max(0.0, ts - src["ts"]), 1),
            }
        )

    for raw in steps:
        step_type = raw.get("type")
        ts = _parse_ts(str(raw.get("ts") or ""))
        if step_type == "message":
            from_name = str(raw.get("from") or "")
            to_name = str(raw.get("to") or "")
            if to_name == identity_name and from_name and from_name != identity_name:
                step_id = str(raw.get("step_id") or "")
                if step_id and ts is not None and ts >= cutoff:
                    inbound[step_id] = {"ts": ts, "from": from_name}
            elif from_name == identity_name:
                reply_to = str(raw.get("reply_to") or "")
                path = "inline" if raw.get("run_id") else "fast"
                if reply_to and reply_to in inbound:
                    reply_counts[reply_to] += 1
                    if ts is not None and reply_to not in replies:
                        replies[reply_to] = {"ts": ts, "path": path}
                _record(reply_to, ts, "replied", path)
        elif step_type == "observation" and raw.get("decision") == "no-reply":
            _record(str(raw.get("trigger_step") or ""), ts, "declined", None)
        elif (
            step_type == "feedback"
            and raw.get("source") == "dispatcher"
            and raw.get("trigger_step")
        ):
            if ts is not None:
                fb_events.append((str(raw.get("trigger_step")), ts))
        elif step_type in ("reasoning", "shell-output"):
            if ts is None:
                continue
            if raw.get("run_id"):
                run_appends.append(ts)
            if step_type == "reasoning" and ts >= cutoff:
                llm_s = raw.get("llm_s")
                if isinstance(llm_s, (int, float)):
                    llm_times.append(float(llm_s))
                    day = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
                    row = daily.setdefault(
                        day, {"calls": 0, "in_tok": 0, "out_tok": 0, "think_tok": 0}
                    )
                    row["calls"] += 1
                    for key in ("in_tok", "out_tok", "think_tok"):
                        val = raw.get(key)
                        if isinstance(val, (int, float)):
                            tokens[key] += int(val)
                            row[key] += int(val)

    # Injection chains (window-scoped via the inbound dict).
    run_appends.sort()
    injections: list[dict] = []
    for trigger_id, fb_ts in fb_events:
        src = inbound.get(trigger_id)
        if src is None:
            continue
        reply = replies.get(trigger_id)
        idx = bisect_right(run_appends, fb_ts)
        boundary = run_appends[idx] if idx < len(run_appends) else None
        event = {
            "ts": _iso(src["ts"]),
            "from": src["from"],
            "inject_ms": int(round((fb_ts - src["ts"]) * 1000)),
            "wait_s": None,
            "model_s": None,
            "total_s": None,
            "path": None,
        }
        if reply:
            event["total_s"] = round(reply["ts"] - src["ts"], 1)
            event["path"] = reply["path"]
            if reply["path"] == "inline" and boundary is not None and boundary <= reply["ts"]:
                event["wait_s"] = round(boundary - fb_ts, 1)
                event["model_s"] = round(reply["ts"] - boundary, 1)
        injections.append(event)

    reply_times = sorted(
        e["response_s"] for e in events if e["outcome"] == "replied"
    )
    llm_sorted = sorted(llm_times)
    return {
        "window_days": WINDOW_DAYS,
        "replied": len(reply_times),
        "declined": sum(1 for e in events if e["outcome"] == "declined"),
        "undecided": len(inbound) - len(decided),
        "duplicates": sum(1 for n in reply_counts.values() if n >= 2),
        "median_s": round(median(reply_times), 1) if reply_times else None,
        "p90_s": _quantile(reply_times, 0.9),
        "max_s": reply_times[-1] if reply_times else None,
        "paths": {
            "fast": _path_stats(
                [e["response_s"] for e in events if e.get("path") == "fast"]
            ),
            "inline": _path_stats(
                [e["response_s"] for e in events if e.get("path") == "inline"]
            ),
        },
        "injections": injections[-INJECTION_ROWS:][::-1],
        "model": {
            "calls": len(llm_sorted),
            "llm_p50_s": round(median(llm_sorted), 1) if llm_sorted else None,
            "llm_p90_s": _quantile(llm_sorted, 0.9),
            "in_tok": tokens["in_tok"],
            "out_tok": tokens["out_tok"],
            "think_tok": tokens["think_tok"],
            "daily": [
                {"day": day, **counts} for day, counts in sorted(daily.items())
            ],
        },
        "recent": events[-RECENT_ROWS:][::-1],
    }
