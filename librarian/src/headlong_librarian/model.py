"""Node model, tags, tokens and the low-level node operations.

Nodes are immutable once written: a correction is a new node with a
``supersedes`` edge. The only mutable columns are confidence, the usage
counters, status (with ``known_to``), ``review_flag`` and an episode's
``outcome``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import db

NODE_TYPES = (
    "skill",
    "decision",
    "retrospective",
    "preference",
    "identity_core",
    "identity_working",
    "episode",
)
IDENTITY_TYPES = ("identity_core", "identity_working")
TASK_TYPES = ("skill", "decision", "retrospective", "episode")
STATUSES = ("probationary", "active", "superseded", "archived", "disputed")
LIVE_STATUSES = ("active", "probationary", "disputed")
PHASES = ("planning", "building", "debugging", "reviewing", "handoff")
OUTCOMES = ("success", "partial", "failure", "unknown")
EDGE_TYPES = (
    "derived_from",
    "supersedes",
    "contradicts",
    "applies_to",
    "caused",
    "informed",
    "co_retrieved",
    "part_of",
    "failed_in",
)
AUTHORS = ("main", "librarian", "human", "runtime")

TAG_NAMESPACES = ("pkg", "area", "ctx", "project", "person", "team", "src", "scope", "expect")
DEFAULT_CTX = (
    "code-review",
    "incident",
    "planning",
    "building",
    "debugging",
    "reviewing",
    "handoff",
    "ritual-daily",
    "ritual-weekly",
    "ritual-final",
    "ritual-freetime",
)
DEFAULT_AREA = (
    "build-system",
    "data-pipeline",
    "perception",
    "modeling",
    "sources",
    "review",
    "writing",
    "tooling",
    "analysis",
    "process",
)

# The same list bin/mem's BM25 prefilter drops.
STOPWORDS = frozenset(
    """the and for not from with that this are was what when how about into has
    have had its but all any can out one two then than they them will were been
    being also just only some such there their which while would could should""".split()
)

SUMMARY_MAX_TOKENS = 60
BODY_MAX_TOKENS = 1500
CHUNK_MAX_TOKENS = 1200


def estimate_tokens(text: str) -> int:
    """Cheap token estimate: about four characters per token."""
    return int(math.ceil(len(text or "") / 4.0))


_TAG_CLEAN = re.compile(r"[^a-z0-9_.:+/@-]+")


def normalize_tag(tag: str) -> str:
    t = (tag or "").strip().lower().replace(" ", "-")
    t = _TAG_CLEAN.sub("-", t).strip("-")
    return t


def tag_namespace(tag: str) -> Optional[str]:
    if ":" in tag:
        ns = tag.split(":", 1)[0]
        return ns or None
    return None


def tag_free(tag: str) -> str:
    return tag.split(":", 1)[1] if ":" in tag else tag


def parse_tags(value: Optional[str | Iterable[str]]) -> list[str]:
    """Accept a comma- or space-separated string or any iterable; dedupe, keep order."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\s]+", value)
    else:
        parts = []
        for v in value:
            parts.extend(re.split(r"[,\s]+", v or ""))
    out: list[str] = []
    for p in parts:
        t = normalize_tag(p)
        if t and t not in out:
            out.append(t)
    return out


def parse_ids(value: Optional[str | Iterable[str]]) -> list[str]:
    """Comma- or space-separated node ids (kept uppercase, order preserved, deduped)."""
    if value is None:
        return []
    parts = re.split(r"[,\s]+", value) if isinstance(value, str) else [p for v in value for p in re.split(r"[,\s]+", v or "")]
    out: list[str] = []
    for p in parts:
        p = p.strip().upper()
        if p and p not in out:
            out.append(p)
    return out


_TOKEN_RE = re.compile(r"[a-z0-9_#@.\-]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens of three or more characters, minus stopwords.

    Unstemmed on purpose so Jaccard comparisons behave the same with FTS5
    (which stems internally) and with the Python BM25 fallback.
    """
    out = []
    for tok in _TOKEN_RE.findall((text or "").lower()):
        tok = tok.strip(".-")
        if len(tok) >= 3 and tok not in STOPWORDS:
            out.append(tok)
    return out


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


_SENT_END = re.compile(r"(?<=[.!?])\s+")


def first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    first_para = text.split("\n\n", 1)[0].strip()
    return _SENT_END.split(first_para, 1)[0].strip()


@dataclass
class Node:
    id: str
    type: str
    summary: str
    body: str = ""
    status: str = "probationary"
    confidence: float = 0.5
    use_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    failures_since_success: int = 0
    unknown_citations: int = 0
    last_used: Optional[str] = None
    last_confirmed: Optional[str] = None
    outcome: Optional[dict] = None
    provenance: dict = field(default_factory=dict)
    project: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    known_from: str = ""
    known_to: Optional[str] = None
    created: str = ""
    review_flag: Optional[str] = None
    archived_reason: Optional[str] = None
    summary_tokens: int = 0
    body_tokens: int = 0
    tags: list[str] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)

    @property
    def is_identity(self) -> bool:
        return self.type in IDENTITY_TYPES

    @property
    def untrusted(self) -> bool:
        return "src:untrusted" in self.tags

    def to_json(self) -> dict:
        """The spec's serialized node, edges embedded."""
        out = {
            "id": self.id,
            "type": self.type,
            "summary": self.summary,
            "body": self.body,
            "tags": list(self.tags),
            "provenance": self.provenance,
            "confidence": round(self.confidence, 4),
            "use_count": self.use_count,
            "last_used": self.last_used,
            "last_confirmed": self.last_confirmed,
            "status": self.status,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "known_from": self.known_from,
            "known_to": self.known_to,
            "created": self.created,
            "edges": [
                {k: v for k, v in e.items() if k in ("type", "to", "weight", "provenance")} for e in self.edges
            ],
        }
        if self.type == "episode" or self.outcome is not None:
            out["outcome"] = self.outcome
        if self.project:
            out["project"] = self.project
        if self.review_flag:
            out["review_flag"] = self.review_flag
        if self.archived_reason:
            out["archived_reason"] = self.archived_reason
        out["counters"] = {
            "success": self.success_count,
            "failure": self.failure_count,
            "failures_since_success": self.failures_since_success,
            "unknown_citations": self.unknown_citations,
        }
        return out


def _loads(value: Optional[str], default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def node_from_row(row, tags: Optional[list[str]] = None, edges: Optional[list[dict]] = None) -> Node:
    d = db.row_dict(row)
    return Node(
        id=d["id"],
        type=d["type"],
        summary=d["summary"],
        body=d["body"] or "",
        status=d["status"],
        confidence=float(d["confidence"]),
        use_count=int(d["use_count"]),
        success_count=int(d["success_count"]),
        failure_count=int(d["failure_count"]),
        failures_since_success=int(d["failures_since_success"]),
        unknown_citations=int(d["unknown_citations"]),
        last_used=d["last_used"],
        last_confirmed=d["last_confirmed"],
        outcome=_loads(d["outcome"], None),
        provenance=_loads(d["provenance"], {}),
        project=d["project"],
        valid_from=d["valid_from"],
        valid_to=d["valid_to"],
        known_from=d["known_from"],
        known_to=d["known_to"],
        created=d["created"],
        review_flag=d["review_flag"],
        archived_reason=d["archived_reason"],
        summary_tokens=int(d["summary_tokens"]),
        body_tokens=int(d["body_tokens"]),
        tags=tags if tags is not None else [],
        edges=edges if edges is not None else [],
    )


# ── reads ────────────────────────────────────────────────────────────────────


def node_tags(store: db.Store, node_id: str) -> list[str]:
    return [r[0] for r in store.q("SELECT tag FROM tags WHERE node_id = ? ORDER BY tag", (node_id,))]


def node_edges(store: db.Store, node_id: str) -> list[dict]:
    rows = store.q(
        "SELECT from_id, to_id, type, weight, provenance, created FROM edges WHERE from_id = ? ORDER BY id",
        (node_id,),
    )
    return [
        {
            "type": r["type"],
            "to": r["to_id"],
            "from": r["from_id"],
            "weight": r["weight"],
            "provenance": _loads(r["provenance"], None),
            "created": r["created"],
        }
        for r in rows
    ]


def edges_to(store: db.Store, node_id: str, types: Optional[Iterable[str]] = None) -> list[dict]:
    rows = store.q("SELECT from_id, to_id, type, weight, provenance FROM edges WHERE to_id = ?", (node_id,))
    out = []
    for r in rows:
        if types and r["type"] not in types:
            continue
        out.append({"type": r["type"], "from": r["from_id"], "to": r["to_id"], "weight": r["weight"]})
    return out


def get_node(store: db.Store, node_id: str, with_edges: bool = True) -> Optional[Node]:
    row = store.q1("SELECT * FROM nodes WHERE id = ?", (node_id,))
    if row is None:
        return None
    return node_from_row(row, node_tags(store, node_id), node_edges(store, node_id) if with_edges else [])


def resolve_id(store: db.Store, ref: str) -> Optional[str]:
    """A full id, or a unique prefix of at least six characters."""
    ref = (ref or "").strip().upper()
    if not ref:
        return None
    if db.is_ulid(ref):
        row = store.q1("SELECT id FROM nodes WHERE id = ?", (ref,))
        return None if row is None else row[0]
    if len(ref) < 6:
        return None
    rows = store.q("SELECT id FROM nodes WHERE id LIKE ? LIMIT 2", (ref + "%",))
    return rows[0][0] if len(rows) == 1 else None


def nodes_where(store: db.Store, where: str = "1=1", params: tuple = (), with_tags: bool = True) -> list[Node]:
    rows = store.q(f"SELECT * FROM nodes WHERE {where}", params)  # noqa: S608 - internal fragments only
    out = []
    for r in rows:
        out.append(node_from_row(r, node_tags(store, r["id"]) if with_tags else []))
    return out


def tags_for_nodes(store: db.Store, ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {i: [] for i in ids}
    if not ids:
        return out
    for chunk_start in range(0, len(ids), 500):
        chunk = ids[chunk_start : chunk_start + 500]
        marks = ",".join("?" for _ in chunk)
        for r in store.q(f"SELECT node_id, tag FROM tags WHERE node_id IN ({marks})", tuple(chunk)):  # noqa: S608
            out.setdefault(r[0], []).append(r[1])
    return out


# ── writes ───────────────────────────────────────────────────────────────────


def upsert_vocab(store: db.Store, tag: str, status: str = "seen") -> None:
    ns = tag_namespace(tag) or "free"
    store.ex(
        "INSERT INTO tag_vocab(tag, namespace, status, added) VALUES (?, ?, ?, ?) ON CONFLICT(tag) DO NOTHING",
        (tag, ns, status, db.now_iso()),
    )


def seed_vocab(store: db.Store) -> None:
    for c in DEFAULT_CTX:
        upsert_vocab(store, f"ctx:{c}", "active")
    for a in DEFAULT_AREA:
        upsert_vocab(store, f"area:{a}", "active")


def vocab_status(store: db.Store, tag: str) -> Optional[str]:
    row = store.q1("SELECT status FROM tag_vocab WHERE tag = ?", (tag,))
    return None if row is None else row[0]


def insert_node(store: db.Store, node: Node) -> str:
    """Insert a node with its tags, FTS row and vocab entries. Caller holds the write."""
    if node.type not in NODE_TYPES:
        raise ValueError(f"bad node type {node.type}")
    if node.status not in STATUSES:
        raise ValueError(f"bad status {node.status}")
    ts = db.now_iso()
    node.created = node.created or ts
    node.known_from = node.known_from or ts
    node.valid_from = node.valid_from or ts
    node.summary_tokens = estimate_tokens(node.summary)
    node.body_tokens = estimate_tokens(node.body)
    if not node.project:
        for t in node.tags:
            if t.startswith("project:"):
                node.project = tag_free(t)
                break
    store.ex(
        """INSERT INTO nodes(id, type, summary, body, status, confidence, use_count, success_count, failure_count,
             failures_since_success, unknown_citations, last_used, last_confirmed, outcome, provenance, project,
             valid_from, valid_to, known_from, known_to, created, review_flag, archived_reason, summary_tokens, body_tokens)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            node.id,
            node.type,
            node.summary,
            node.body,
            node.status,
            node.confidence,
            node.use_count,
            node.success_count,
            node.failure_count,
            node.failures_since_success,
            node.unknown_citations,
            node.last_used,
            node.last_confirmed,
            json.dumps(node.outcome) if node.outcome is not None else None,
            json.dumps(node.provenance or {}),
            node.project,
            node.valid_from,
            node.valid_to,
            node.known_from,
            node.known_to,
            node.created,
            node.review_flag,
            node.archived_reason,
            node.summary_tokens,
            node.body_tokens,
        ),
    )
    for t in node.tags:
        store.ex("INSERT OR IGNORE INTO tags(node_id, tag) VALUES (?, ?)", (node.id, t))
        upsert_vocab(store, t, "seen")
    if store.fts_mode == "fts5":
        store.ex(
            "INSERT INTO nodes_fts(node_id, summary, tags) VALUES (?, ?, ?)",
            (node.id, node.summary, " ".join(tag_free(t).replace("-", " ") + " " + t for t in node.tags)),
        )
    for e in node.edges:
        add_edge(store, node.id, e["to"], e["type"], float(e.get("weight", 1.0)), e.get("provenance"))
    return node.id


def add_edge(
    store: db.Store,
    from_id: str,
    to_id: str,
    etype: str,
    weight: float = 1.0,
    provenance: Optional[dict] = None,
) -> None:
    if etype not in EDGE_TYPES:
        raise ValueError(f"bad edge type {etype}")
    store.ex(
        """INSERT INTO edges(from_id, to_id, type, weight, provenance, created) VALUES (?,?,?,?,?,?)
           ON CONFLICT(from_id, to_id, type) DO UPDATE SET weight = excluded.weight,
             provenance = COALESCE(excluded.provenance, edges.provenance)""",
        (from_id, to_id, etype, weight, json.dumps(provenance) if provenance is not None else None, db.now_iso()),
    )


def remove_edge(store: db.Store, from_id: str, to_id: str, etype: str) -> None:
    store.ex("DELETE FROM edges WHERE from_id = ? AND to_id = ? AND type = ?", (from_id, to_id, etype))


def set_status(
    store: db.Store,
    node_id: str,
    status: str,
    known_to: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    if status not in STATUSES:
        raise ValueError(f"bad status {status}")
    if status in ("superseded", "archived"):
        known_to = known_to or db.now_iso()
    elif known_to is None:
        known_to = None
    if status == "archived":
        store.ex(
            "UPDATE nodes SET status = ?, known_to = ?, archived_reason = COALESCE(?, archived_reason) WHERE id = ?",
            (status, known_to, reason, node_id),
        )
    else:
        store.ex("UPDATE nodes SET status = ?, known_to = ? WHERE id = ?", (status, known_to, node_id))


def supersede(store: db.Store, new_id: str, old_id: str, provenance: Optional[dict] = None) -> None:
    """Flip ``old`` to superseded, close its transaction time, link new → old."""
    set_status(store, old_id, "superseded", db.now_iso())
    add_edge(store, new_id, old_id, "supersedes", 1.0, provenance or {})


def supersession_chain(store: db.Store, node_id: str, limit: int = 50) -> list[str]:
    """Ids walking back through ``supersedes`` edges from ``node_id``."""
    out = []
    cur = node_id
    while cur and len(out) < limit:
        row = store.q1("SELECT to_id FROM edges WHERE from_id = ? AND type = 'supersedes' LIMIT 1", (cur,))
        if row is None:
            break
        out.append(row[0])
        cur = row[0]
    return out
