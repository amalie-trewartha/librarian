"""Parse and normalize shellm trajectory JSONL files.

Produces the wire shape the viewer renders:
- steps: normalized steps (preview one-liner, source, fork/writeback links)
- runs: inline shellm-run groups. Grouping is exact: every machinery step
  written by shellm since 2026-07-10 carries `run_id` (the step_id of its
  `shellm-run` header), so membership is a lookup even when concurrent runs
  interleave in one shared mind log. Machinery steps without `run_id`
  (pre-2026-07-10 logs) are left ungrouped and render as plain stream steps.
"""

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from headlong_web.env import getenv

# Cap on the SOURCE bytes of raw step records kept parsed in memory, per
# cached trajectory (Python dicts run ~6x the jsonl bytes — audel's 590MB
# mind log parsed whole was ~3.5GB RSS and repeatedly OOMed the box,
# 2026-08-13). Older steps keep their normalized wrapper (preview,
# ids, run links) but drop `raw`; any window rehydrates with one
# contiguous disk read via the recorded byte spans (append-only file, so
# spans never move).
_RAW_BUDGET_BYTES = int(getenv("HEADLONG_WEB_RAW_CACHE_MB", "48")) * 1024 * 1024

# Cold-parse read size: refresh streams the jsonl in chunks this big,
# evicting between chunks, so first-load peak memory is O(budget + chunk)
# — never O(file).
_REFRESH_CHUNK = 8 * 1024 * 1024

# Step types written by the shellm loop itself (never carry `source`).
MACHINERY_TYPES = {
    "shellm-run",
    "prompt",
    "reasoning",
    "shell-output",
    "feedback",
    "final",
    "run-summary",
}

_WS_RE = re.compile(r"\s+")

# Run commands embed the whole prompt (100s of KB each) and thousands of
# runs ship on an initial mindlog load — truncate on the wire, keeping the
# head and the tail (the trailing "ACTION: ..." is what titles a run). The
# full text stays in the cache, served by the per-run command endpoint.
_CMD_HEAD = 800
_CMD_TAIL = 1200


def _truncate_command(command: str) -> tuple[str, bool]:
    if len(command) <= _CMD_HEAD + _CMD_TAIL + 200:
        return command, False
    omitted = len(command) - _CMD_HEAD - _CMD_TAIL
    return (
        command[:_CMD_HEAD]
        + f"\n[… {omitted} chars truncated …]\n"
        + command[-_CMD_TAIL:],
        True,
    )


def _collapse(text: str, limit: int = 200) -> str:
    return _WS_RE.sub(" ", text).strip()[:limit]


def _first_str(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def step_preview(raw: dict[str, Any]) -> str:
    """One-line preview per step type (ports bin/traj's formatter)."""
    step_type = raw.get("type", "")
    if step_type == "reasoning":
        thought = _collapse(_first_str(raw, "thought", "content"), 100)
        cmd = _collapse(_first_str(raw, "cmd"), 120)
        return f"{thought} | {cmd}" if thought and cmd else thought or cmd
    if step_type == "shell-output":
        exit_code = raw.get("exit")
        head = _collapse(_first_str(raw, "stdout") or _first_str(raw, "stderr"), 120)
        return f"exit {exit_code} · {head}" if exit_code is not None else head
    if step_type == "shellm-run":
        return _collapse(_first_str(raw, "command"), 160)
    if step_type == "run-summary":
        return _collapse(_first_str(raw, "tldr"), 160)
    if step_type == "final":
        content = _collapse(_first_str(raw, "content", "thought"), 100)
        cmd = _collapse(_first_str(raw, "cmd"), 120)
        return f"{content} | {cmd}" if content and cmd else content or cmd
    if step_type == "fork":
        return f"-> {_first_str(raw, 'child_ref', 'child')}"
    if step_type == "merge":
        content = _collapse(_first_str(raw, "content"), 140)
        return f"<- {content}" if content else f"<- {_first_str(raw, 'from_traj')}"
    if step_type == "trajectory":
        parent = _first_str(raw, "parent_traj")
        return f"<- parent: {parent[:8]}" if parent else "root"
    if step_type == "message":
        sender = _first_str(raw, "from")
        content = _collapse(_first_str(raw, "content"), 140)
        return f"{sender}: {content}" if sender else content
    return _collapse(_first_str(raw, "content", "thought"), 160)


@dataclass
class RunGroup:
    run_id: str  # = shellm-run step_id
    trigger_step_id: str | None = None  # step that triggered the run (any type)
    launched_by: str | None = None  # thinker that launched the run
    step_ids: list[str] = field(default_factory=list)
    started_ts: str = ""
    ended_ts: str | None = None
    status: str = "running"  # running | done
    # Stored TRUNCATED (commands embed the whole prompt; thousands of runs
    # times 100s of KB was a large share of the cache's memory). The full
    # text is rehydrated from header_span by TrajectoryCache.run_command.
    command: str = ""
    command_truncated: bool = False
    header_span: tuple[int, int] | None = None  # shellm-run step's jsonl bytes
    model: str | None = None
    tldr: str | None = None
    # index into steps of the last step that mutated this run — lets the
    # mindlog endpoint ship only changed runs on ?since= deltas (a run's
    # command is heavy, so unchanged runs are dead weight)
    last_touch: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trigger_step_id": self.trigger_step_id,
            "launched_by": self.launched_by,
            "step_ids": self.step_ids,
            "started_ts": self.started_ts,
            "ended_ts": self.ended_ts,
            "status": self.status,
            "command": self.command,
            "command_truncated": self.command_truncated,
            "model": self.model,
            "tldr": self.tldr,
            "last_touch": self.last_touch,
        }


def iter_jsonl(path: Path, offset: int = 0):
    """Stream raw records from a trajectory.jsonl (skipping malformed
    lines), optionally from a byte offset — O(1) memory, unlike
    parse_jsonl which materializes the whole log."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if offset:
                fh.seek(offset)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def parse_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a trajectory.jsonl whole, skipping malformed lines. Only for
    logs known to be small — big ones want iter_jsonl or the CACHE."""
    return list(iter_jsonl(path))


def _action_suffix(command: str) -> str | None:
    """Extract the trailing 'ACTION: <text>' from a shellm-run command."""
    idx = command.rfind("ACTION:")
    if idx == -1:
        return None
    return _collapse(command[idx + len("ACTION:") :])


# Step types the chat view renders (mirrored by chat.py).
CHAT_MESSAGE_TYPES = {"message", "human-msg", "agent-msg"}

# Compact chat-index fields copied per message step so the chat endpoints
# never need the (possibly evicted) raw record, let alone a full reparse.
_CHAT_FIELDS = ("type", "ts", "step_id", "content", "from", "to", "reply_to", "filename")


class _Normalizer:
    """Stateful step normalizer: feed raw steps in order, read results any
    time. The state (open runs, unmatched actions, seen ids) is exactly what
    lets a cache continue where it left off when the jsonl grows."""

    def __init__(self, traj_dir: Path) -> None:
        self.traj_dir = traj_dir
        self.steps: list[dict[str, Any]] = []
        # steps[i]'s byte range in trajectory.jsonl (None when unknown, e.g.
        # via the span-less normalize() path) — how an evicted raw rehydrates
        self.spans: list[tuple[int, int] | None] = []
        # compact copies of chat-relevant steps (messages + reply outcomes)
        self.chat_index: list[dict[str, Any]] = []
        self.runs: list[RunGroup] = []
        self._runs_by_id: dict[str, RunGroup] = {}
        self._unmatched_actions: list[dict[str, Any]] = []
        self._seen_step_ids: set[str] = set()

    def ingest(self, raw: dict[str, Any], span: tuple[int, int] | None = None) -> None:
        step_type = raw.get("type", "")
        source = raw.get("source")
        step_id = raw.get("step_id", "")
        ts = raw.get("ts", "")

        normalized: dict[str, Any] = {
            "step_id": step_id,
            "ts": ts,
            "type": step_type,
            "source": source,
            "preview": step_preview(raw),
            "raw": raw,
            "run_id": None,
        }

        # Fork / write-back links
        if step_type == "fork" and raw.get("child"):
            child_ref = raw.get("child_ref", "")
            slug = child_ref.split("/")[0] if child_ref else str(raw["child"])[:8]
            resolved = bool(child_ref) and (self.traj_dir / child_ref).is_file()
            if not resolved:
                # child_ref missing or stale: try the hex8 glob
                matches = list(
                    self.traj_dir.glob(f"{str(raw['child'])[:8]}-*/trajectory.jsonl")
                )
                if matches:
                    slug = matches[0].parent.name
                    resolved = True
            normalized["fork"] = {
                "child_traj_id": raw["child"],
                "slug": slug,
                "resolved": resolved,
            }
        if raw.get("from_traj"):
            normalized["writeback"] = {
                "from_traj": raw["from_traj"],
                "from_step": raw.get("from_step"),
            }

        # Inline-run grouping (machinery steps carry no source)
        if source is None and step_type in MACHINERY_TYPES:
            if step_type == "shellm-run":
                full_command = raw.get("command", "")
                command, truncated = _truncate_command(full_command)
                run = RunGroup(
                    run_id=step_id,
                    started_ts=ts,
                    command=command,
                    command_truncated=truncated,
                    header_span=span,
                    model=raw.get("model"),
                    launched_by=raw.get("launched_by"),
                )
                # trigger -> run join. Exact when the run carries trigger_step
                # (thinkers export the triggering step's id; any step type can
                # trigger); otherwise fall back to the legacy ACTION:
                # command-suffix prefix match against action steps.
                trigger = raw.get("trigger_step")
                if trigger:
                    if trigger in self._seen_step_ids:
                        run.trigger_step_id = trigger
                        # consume so a later legacy run can't prefix-match it
                        self._unmatched_actions[:] = [
                            a for a in self._unmatched_actions if a["step_id"] != trigger
                        ]
                else:
                    suffix = _action_suffix(full_command)
                    if suffix:
                        for action in reversed(self._unmatched_actions):
                            action_text = _collapse(str(action["raw"].get("content", "")))
                            if action_text and (
                                action_text.startswith(suffix[:200])
                                or suffix.startswith(action_text[:200])
                            ):
                                run.trigger_step_id = action["step_id"]
                                self._unmatched_actions.remove(action)
                                break
                self.runs.append(run)
                self._runs_by_id[run.run_id] = run
                run.step_ids.append(step_id)
                run.last_touch = len(self.steps)
                normalized["run_id"] = run.run_id
            else:
                # Membership is explicit: the step's own run_id field points
                # at its shellm-run header. Steps without one (pre-run_id
                # logs) or with an unknown id stay ungrouped.
                run = self._runs_by_id.get(raw.get("run_id") or "")
                if run is not None:
                    run.step_ids.append(step_id)
                    run.last_touch = len(self.steps)
                    normalized["run_id"] = run.run_id
                    if step_type == "run-summary":
                        run.tldr = raw.get("tldr") or run.tldr
                    elif step_type == "final":
                        run.status = "done"
                        run.ended_ts = ts
        elif step_type == "action":
            self._unmatched_actions.append(normalized)

        # Chat index: message steps whole (human-scale content), plus the
        # observation outcomes chat.py folds into typing indicators. Kept
        # compact so chat polls never touch raw records.
        if step_type in CHAT_MESSAGE_TYPES and raw.get("content"):
            self.chat_index.append({k: raw[k] for k in _CHAT_FIELDS if k in raw})
        elif step_type == "observation" and raw.get("trigger_step"):
            self.chat_index.append(
                {
                    "type": "observation",
                    "trigger_step": raw.get("trigger_step"),
                    "decision": raw.get("decision"),
                    "content": str(raw.get("content") or "")[:100],
                }
            )

        if step_id:
            self._seen_step_ids.add(step_id)
        self.steps.append(normalized)
        self.spans.append(span)


def normalize(raw_steps: list[dict[str, Any]], traj_dir: Path) -> dict[str, Any]:
    """Normalize steps and group inline runs. Returns {steps, runs}."""
    normalizer = _Normalizer(traj_dir)
    for raw in raw_steps:
        normalizer.ingest(raw)
    return {
        "steps": normalizer.steps,
        "runs": [run.to_dict() for run in normalizer.runs],
    }


class _CacheEntry:
    def __init__(self, traj_dir: Path) -> None:
        self.normalizer = _Normalizer(traj_dir)
        self.offset = 0        # bytes consumed, through the last complete line
        self.inode: int | None = None
        self.traj_id = ""
        # Raw-eviction bookkeeping: steps[:hydrated_from] have raw=None
        # (rehydratable via spans); hydrated_bytes sums the SOURCE span
        # lengths of the still-hydrated steps.
        self.hydrated_from = 0
        self.hydrated_bytes = 0


class TrajectoryCache:
    """Append-aware parse cache. Trajectories are append-only, so a refresh
    reads only the new bytes and continues normalizing from saved state —
    O(new steps) per poll instead of O(log). A shrunken or replaced file
    (different inode, or size below the consumed offset) resets the entry.
    A trailing partial line (a step mid-append) is left unconsumed and picked
    up whole on the next refresh.

    Memory is bounded: only the newest raw_budget SOURCE bytes of raw
    records stay parsed per entry (older steps keep their wrapper, drop
    `raw`); window() rehydrates any evicted range with one contiguous
    disk read."""

    def __init__(self, max_entries: int = 8, raw_budget: int = _RAW_BUDGET_BYTES) -> None:
        self._entries: dict[Path, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self._raw_budget = raw_budget

    def _fresh_entry(self, traj_dir: Path) -> _CacheEntry:
        """Get-or-create the entry and refresh it. Caller holds the lock."""
        entry = self._entries.get(traj_dir)
        if entry is None:
            if len(self._entries) >= self._max_entries:
                # Drop the entry with the fewest parsed steps (cheapest
                # to rebuild); good enough for a handful of identities.
                victim = min(
                    self._entries, key=lambda k: len(self._entries[k].normalizer.steps)
                )
                del self._entries[victim]
            entry = _CacheEntry(traj_dir)
            self._entries[traj_dir] = entry
        self._refresh(entry, traj_dir)
        return entry

    def load(self, traj_dir: Path) -> dict[str, Any]:
        """Wire dict like load_trajectory; steps list is shared with the
        cache — callers must treat it as read-only and build their own
        response envelope."""
        traj_dir = traj_dir.resolve()
        with self._lock:
            entry = self._fresh_entry(traj_dir)
            return {
                "steps": entry.normalizer.steps,
                "runs": [run.to_dict() for run in entry.normalizer.runs],
                "traj_id": entry.traj_id,
                "step_count": len(entry.normalizer.steps),
            }

    def run_command(self, traj_dir: Path, run_id: str) -> str | None:
        """Full (untruncated) command of one run, for on-demand fetches.
        The cache stores commands truncated; the full text is re-read from
        the run's shellm-run line on disk."""
        traj_dir = traj_dir.resolve()
        with self._lock:
            entry = self._fresh_entry(traj_dir)
            run = entry.normalizer._runs_by_id.get(run_id)
            if run is None:
                return None
            if not run.command_truncated:
                return run.command
            if run.header_span is None:
                return run.command  # span-less (shouldn't happen via cache)
            raw = self._read_spans(traj_dir, [run.header_span])[0]
            if raw is None:
                return run.command
            return raw.get("command", run.command)

    def window(
        self,
        traj_dir: Path,
        since: int | None = None,
        until: int | None = None,
        tail: int | None = None,
        max_hydrate: int | None = None,
    ) -> dict[str, Any]:
        """Wire dict for a step window [since, until), every step hydrated
        (evicted raws re-read from disk in one contiguous read; those steps
        are shallow copies — the cache's own lists stay evicted). ?tail=N
        maps to the last N steps when since is None. max_hydrate caps the
        rehydration read in SOURCE bytes, dropping raws oldest-first —
        for endpoints that ship a whole (possibly huge) trajectory.
        The response's `since` echoes the effective window start."""
        traj_dir = traj_dir.resolve()
        with self._lock:
            entry = self._fresh_entry(traj_dir)
            norm = entry.normalizer
            count = len(norm.steps)
            if since is None and tail is not None:
                since = max(0, count - tail)
            lo = 0 if since is None else max(0, min(since, count))
            hi = count if until is None else max(lo, min(until, count))
            steps = norm.steps[lo:hi]

            missing = [
                i
                for i in range(lo, hi)
                if norm.steps[i]["raw"] is None and norm.spans[i] is not None
            ]
            if max_hydrate is not None:
                budget = max_hydrate
                keep: list[int] = []
                for i in reversed(missing):  # newest raws win the budget
                    start, end = norm.spans[i]  # type: ignore[misc]
                    budget -= end - start
                    if budget < 0:
                        break
                    keep.append(i)
                missing = list(reversed(keep))
            if missing:
                raws = self._read_spans(
                    traj_dir, [norm.spans[i] for i in missing]  # type: ignore[list-item]
                )
                for i, raw in zip(missing, raws):
                    if raw is not None:
                        steps[i - lo] = {**norm.steps[i], "raw": raw}

            return {
                "steps": steps,
                "runs": [run.to_dict() for run in norm.runs],
                "traj_id": entry.traj_id,
                "step_count": count,
                "since": since,
            }

    def chat_steps(self, traj_dir: Path) -> list[dict[str, Any]]:
        """Compact chat-relevant steps (see _Normalizer.chat_index) —
        read-only, shared with the cache."""
        traj_dir = traj_dir.resolve()
        with self._lock:
            entry = self._fresh_entry(traj_dir)
            return entry.normalizer.chat_index

    def offset_of(self, traj_dir: Path, index: int) -> int | None:
        """Byte offset in trajectory.jsonl where step `index` starts —
        lets callers stream-parse a suffix of the log (see health.py)."""
        traj_dir = traj_dir.resolve()
        with self._lock:
            entry = self._fresh_entry(traj_dir)
            spans = entry.normalizer.spans
            if 0 <= index < len(spans) and spans[index] is not None:
                return spans[index][0]
            return None

    def hydrated_from(self, traj_dir: Path) -> tuple[list[dict[str, Any]], int]:
        """(steps, first_hydrated_index) — lets search scan the in-memory
        tail directly and stream older windows via window()."""
        traj_dir = traj_dir.resolve()
        with self._lock:
            entry = self._fresh_entry(traj_dir)
            return entry.normalizer.steps, entry.hydrated_from

    @staticmethod
    def _read_spans(
        traj_dir: Path, spans: list[tuple[int, int]]
    ) -> list[dict[str, Any] | None]:
        """Parse the raw records at the given byte spans. One contiguous
        read covering min..max — spans come from adjacent steps, so the
        range is dense; bounded by the caller's window/max_hydrate."""
        if not spans:
            return []
        base = min(start for start, _ in spans)
        top = max(end for _, end in spans)
        try:
            with (traj_dir / "trajectory.jsonl").open("rb") as fh:
                fh.seek(base)
                buf = fh.read(top - base)
        except OSError:
            return [None] * len(spans)
        out: list[dict[str, Any] | None] = []
        for start, end in spans:
            piece = buf[start - base : end - base]
            try:
                record = json.loads(piece.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                record = None
            out.append(record if isinstance(record, dict) else None)
        return out

    def _refresh(self, entry: _CacheEntry, traj_dir: Path) -> None:
        jsonl = traj_dir / "trajectory.jsonl"
        try:
            stat = jsonl.stat()
        except OSError:
            entry.normalizer = _Normalizer(traj_dir)
            entry.offset = 0
            entry.inode = None
            entry.traj_id = ""
            entry.hydrated_from = 0
            entry.hydrated_bytes = 0
            return

        if entry.inode != stat.st_ino or stat.st_size < entry.offset:
            entry.normalizer = _Normalizer(traj_dir)
            entry.offset = 0
            entry.inode = stat.st_ino
            entry.hydrated_from = 0
            entry.hydrated_bytes = 0

        if stat.st_size == entry.offset:
            return  # nothing new

        # Stream in bounded chunks, evicting as we go — a cold parse of a
        # 500MB+ log must never hold the whole file (let alone its dicts)
        # at once. Only complete lines are consumed; a torn tail (or the
        # remainder of a line longer than a chunk) waits in `pending` and,
        # at EOF, for the next poll.
        try:
            with jsonl.open("rb") as fh:
                fh.seek(entry.offset)
                pending = b""
                while True:
                    chunk = fh.read(_REFRESH_CHUNK)
                    if not chunk:
                        break
                    pending += chunk
                    last_newline = pending.rfind(b"\n")
                    if last_newline == -1:
                        continue
                    consumed = pending[: last_newline + 1]
                    pending = pending[last_newline + 1 :]

                    # Split on bytes (not decoded text) so each step's byte
                    # span in the file is exact — spans are what rehydrate
                    # evicted raws later.
                    cursor = entry.offset
                    for line_bytes in consumed.split(b"\n"):
                        start = cursor
                        cursor += len(line_bytes) + 1  # +1: the newline
                        line = line_bytes.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(record, dict):
                            entry.normalizer.ingest(
                                record, span=(start, start + len(line_bytes))
                            )
                            entry.hydrated_bytes += len(line_bytes)
                    entry.offset += len(consumed)
                    self._evict_to_budget(entry)
        except OSError:
            return

        if not entry.traj_id and entry.normalizer.steps:
            # wrapper key, not raw — step 0's raw may already be evicted
            entry.traj_id = entry.normalizer.steps[0].get("step_id", "")

    def _evict_to_budget(self, entry: _CacheEntry) -> None:
        """Drop oldest raws down to the budget; wrappers and spans stay, so
        window() can bring any of them back with one disk read."""
        norm = entry.normalizer
        while (
            entry.hydrated_bytes > self._raw_budget
            and entry.hydrated_from < len(norm.steps)
        ):
            index = entry.hydrated_from
            span = norm.spans[index]
            if span is not None and norm.steps[index]["raw"] is not None:
                norm.steps[index]["raw"] = None
                entry.hydrated_bytes -= span[1] - span[0]
            entry.hydrated_from += 1


# Process-wide cache used by the API endpoints.
CACHE = TrajectoryCache()


def load_trajectory(traj_dir: Path) -> dict[str, Any]:
    """Load and normalize a trajectory directory. Returns wire dict."""
    jsonl = traj_dir / "trajectory.jsonl"
    raw_steps = parse_jsonl(jsonl)
    traj_id = raw_steps[0].get("step_id", "") if raw_steps else ""
    result = normalize(raw_steps, traj_dir)
    result["traj_id"] = traj_id
    result["step_count"] = len(result["steps"])
    return result
