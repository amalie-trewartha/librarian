"""Mind-log search: case-insensitive substring scan over the parse cache.

Grep, not a search engine — no index, no ranking, newest hit first. The
trajectory cache already holds every normalized step in memory, so a
query is a linear scan over the fields that carry text. Huge fields
(stdout, run commands embedding whole prompts) are scanned only in
their first _FIELD_CAP chars so one giant step can't blow up a query.

scope="thoughts" skips run-machinery step types (prompts, model
reasoning, shell output) — the mind-level log Braden means by "thought
log". scope="all" searches everything.
"""

from typing import Any

from headlong_web.trajectory import MACHINERY_TYPES

_FIELD_CAP = 16 * 1024
_SNIPPET_RADIUS = 60

# Searched in this order; the first matching field names the hit.
_TEXT_FIELDS = ("content", "thought", "cmd", "tldr", "command", "stdout", "stderr")


def _snippet(text: str, pos: int, needle_len: int) -> str:
    start = max(0, pos - _SNIPPET_RADIUS)
    end = min(len(text), pos + needle_len + _SNIPPET_RADIUS)
    body = " ".join(text[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{body}{suffix}"


def search_cache(cache, traj_dir, q: str, scope: str = "thoughts", limit: int = 50) -> dict:
    """Search a cached trajectory, newest first. The hydrated tail is
    scanned in memory; older (raw-evicted) history streams from disk in
    bounded chunks via cache.window(), so a search never re-materializes
    the whole log. `total` still counts every match in the full log."""
    steps, hydrated_from = cache.hydrated_from(traj_dir)
    result = search_steps(steps[hydrated_from:], q, scope, limit)
    hits = result["hits"]
    total = result["total"]
    for hit in hits:
        hit["index"] += hydrated_from

    chunk = 4000
    hi = hydrated_from
    while hi > 0:
        lo = max(0, hi - chunk)
        window = cache.window(traj_dir, lo, hi)
        part = search_steps(window["steps"], q, scope, limit)
        total += part["total"]
        for hit in part["hits"]:
            hit["index"] += lo
        room = limit - len(hits)
        if room > 0:
            hits.extend(part["hits"][:room])
        hi = lo
    return {"q": q, "scope": scope, "total": total, "hits": hits}


def search_steps(
    steps: list[dict[str, Any]],
    q: str,
    scope: str = "thoughts",
    limit: int = 50,
) -> dict:
    needle = q.lower()
    hits: list[dict] = []
    total = 0
    for index in range(len(steps) - 1, -1, -1):  # newest first
        step = steps[index]
        step_type = str(step.get("type") or "")
        if scope != "all" and step_type in MACHINERY_TYPES:
            continue
        raw = step.get("raw") or {}
        matched_field: str | None = None
        matched_pos = -1
        haystack = ""
        for field in _TEXT_FIELDS:
            value = raw.get(field)
            if not isinstance(value, str) or not value:
                continue
            capped = value[:_FIELD_CAP]
            pos = capped.lower().find(needle)
            if pos != -1:
                matched_field, matched_pos, haystack = field, pos, capped
                break
        if matched_field is None:
            preview = str(step.get("preview") or "")
            pos = preview.lower().find(needle)
            if pos != -1:
                matched_field, matched_pos, haystack = "preview", pos, preview
        if matched_field is None:
            continue
        total += 1
        if len(hits) < limit:
            hits.append(
                {
                    "index": index,
                    "step_id": step.get("step_id"),
                    "ts": step.get("ts"),
                    "type": step_type,
                    "source": step.get("source"),
                    "run_id": step.get("run_id"),
                    "field": matched_field,
                    "snippet": _snippet(haystack, matched_pos, len(needle)),
                }
            )
    return {"q": q, "scope": scope, "total": total, "hits": hits}
