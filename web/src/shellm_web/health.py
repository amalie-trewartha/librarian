"""Per-identity health: message response stats from the mind log.

Precise, not heuristic: outbound replies stamp reply_to with the inbound
step they answer (transport-level since 9d00f2e), and declines stamp
trigger_step on a decision:"no-reply" observation — so response time is
just the timestamp delta between the paired steps. Inbound messages in
the window with neither stamp are "undecided" (queued, in progress, or
dropped).
"""

import time
from pathlib import Path
from statistics import median

from shellm_web.activity import _iso
from shellm_web.llm_health import _parse_ts
from shellm_web.trajectory import parse_jsonl

WINDOW_DAYS = 7
RECENT_ROWS = 20


def _quantile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, round(q * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def response_stats(traj_dir: Path, identity_name: str) -> dict:
    now = time.time()
    cutoff = now - WINDOW_DAYS * 86400
    steps = parse_jsonl(traj_dir / "trajectory.jsonl")

    inbound: dict[str, dict] = {}  # step_id -> {"ts", "from"}
    events: list[dict] = []
    decided: set[str] = set()

    def _record(trigger_id: str, ts: float | None, outcome: str) -> None:
        src = inbound.get(trigger_id)
        if src is None or ts is None or trigger_id in decided:
            return
        decided.add(trigger_id)
        events.append(
            {
                "ts": _iso(ts),
                "from": src["from"],
                "outcome": outcome,
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
                _record(str(raw.get("reply_to") or ""), ts, "replied")
        elif step_type == "observation" and raw.get("decision") == "no-reply":
            _record(str(raw.get("trigger_step") or ""), ts, "declined")

    reply_times = sorted(
        e["response_s"] for e in events if e["outcome"] == "replied"
    )
    return {
        "window_days": WINDOW_DAYS,
        "replied": len(reply_times),
        "declined": sum(1 for e in events if e["outcome"] == "declined"),
        "undecided": len(inbound) - len(decided),
        "median_s": round(median(reply_times), 1) if reply_times else None,
        "p90_s": _quantile(reply_times, 0.9),
        "max_s": reply_times[-1] if reply_times else None,
        "recent": events[-RECENT_ROWS:][::-1],
    }
