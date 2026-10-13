"""The human check-in queue: items only a person can settle.

Kinds: ``core_proposal``, ``working_conflict``, ``held_working_edit``,
``dispute``, ``new_area_tag``, ``reversion_note``, ``probe_drift``,
``repeated_failure_review``. Decisions and their side effects live in
:mod:`identity` (``decide``); this module is the storage so the gate and the
consolidator can enqueue without importing identity.
"""

from __future__ import annotations

import json
from typing import Optional

from . import db

KINDS = (
    "core_proposal",
    "working_conflict",
    "held_working_edit",
    "dispute",
    "new_area_tag",
    "reversion_note",
    "probe_drift",
    "repeated_failure_review",
)


def enqueue(store: db.Store, kind: str, payload: dict, dedupe_key: Optional[str] = None) -> Optional[str]:
    """Add an item; returns its id, or None when a pending item with the same key exists."""
    if kind not in KINDS:
        raise ValueError(f"bad queue kind {kind}")
    if dedupe_key:
        row = store.q1(
            "SELECT id FROM checkin_queue WHERE dedupe_key = ? AND status = 'pending'", (dedupe_key,)
        )
        if row is not None:
            return None
    qid = "Q" + db.ulid()[-8:]
    store.ex(
        "INSERT INTO checkin_queue(id, kind, payload, dedupe_key, status, created) VALUES (?,?,?,?,'pending',?)",
        (qid, kind, json.dumps(payload), dedupe_key, db.now_iso()),
    )
    return qid


def list_items(store: db.Store, status: Optional[str] = "pending", kind: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM checkin_queue WHERE 1=1"
    params: list = []
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY created"
    out = []
    for r in store.q(sql, tuple(params)):
        d = db.row_dict(r)
        try:
            d["payload"] = json.loads(d["payload"])
        except (TypeError, ValueError):
            pass
        out.append(d)
    return out


def get_item(store: db.Store, qid: str) -> Optional[dict]:
    r = store.q1("SELECT * FROM checkin_queue WHERE id = ?", (qid,))
    if r is None:
        return None
    d = db.row_dict(r)
    try:
        d["payload"] = json.loads(d["payload"])
    except (TypeError, ValueError):
        pass
    return d


def mark(store: db.Store, qid: str, status: str, note: Optional[str] = None) -> None:
    store.ex(
        "UPDATE checkin_queue SET status = ?, decided = ?, note = ? WHERE id = ?",
        (status, db.now_iso(), note, qid),
    )


def pending_count(store: db.Store) -> int:
    row = store.q1("SELECT COUNT(*) FROM checkin_queue WHERE status = 'pending'")
    return int(row[0]) if row else 0
