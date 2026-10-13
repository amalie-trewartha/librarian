"""Stage 1: candidate recall. Cheap and wide; ranking comes after.

Three sources are unioned and capped: namespaced tag match weighted by tag
specificity, BM25 over summary+tags (FTS5, or the same formula in Python
when FTS5 is unavailable), and one graph hop along ``applies_to``,
``co_retrieved`` and ``informed`` edges. Identity nodes and active
preferences bypass recall.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

from . import db, model

RECALL_CAP = 200
TEXT_K = 100
HOP_SEEDS = 50
HOP_EDGES = ("applies_to", "co_retrieved", "informed")


@dataclass
class Query:
    task: str = ""
    tags: list[str] = field(default_factory=list)
    project: Optional[str] = None
    phase: Optional[str] = None
    type: Optional[str] = None
    include_probationary: bool = True
    include_history: bool = False


@dataclass
class Candidate:
    node: model.Node
    tag_score: float = 0.0
    bm25: float = 0.0
    bm25_norm: float = 0.0
    hop: float = 0.0
    via: set = field(default_factory=set)


def status_scope(q: Query) -> tuple:
    s = ["active", "disputed"]
    if q.include_probationary:
        s.append("probationary")
    if q.include_history:
        s += ["superseded", "archived"]
    return tuple(s)


def _scope_sql(scope: tuple) -> str:
    return "status IN (" + ",".join("?" for _ in scope) + ")"


def tag_idf(store: db.Store, scope: tuple) -> dict[str, float]:
    """``log((N+1)/(df+1)) + 1``: ``pkg:colcon`` is worth more than ``area:build-system``."""
    n = store.q1(f"SELECT COUNT(*) FROM nodes WHERE {_scope_sql(scope)}", scope)[0]  # noqa: S608
    rows = store.q(
        f"SELECT t.tag, COUNT(*) FROM tags t JOIN nodes n ON n.id = t.node_id WHERE {_scope_sql(scope)} GROUP BY t.tag",  # noqa: S608
        scope,
    )
    return {r[0]: math.log((n + 1) / (r[1] + 1)) + 1.0 for r in rows}


def tag_match(store: db.Store, q: Query, scope: tuple, idf: dict[str, float]) -> dict[str, float]:
    tags = [t for t in model.parse_tags(q.tags) if t in idf]
    if not tags:
        return {}
    denom = sum(idf[t] for t in tags) or 1.0
    marks = ",".join("?" for _ in tags)
    rows = store.q(
        f"SELECT t.node_id, t.tag FROM tags t JOIN nodes n ON n.id = t.node_id "  # noqa: S608
        f"WHERE t.tag IN ({marks}) AND {_scope_sql(scope)}",
        (*tags, *scope),
    )
    acc: dict[str, float] = {}
    for r in rows:
        acc[r[0]] = acc.get(r[0], 0.0) + idf.get(r[1], 0.0)
    return {k: v / denom for k, v in acc.items()}


def python_bm25(docs: dict[str, str], terms: list[str], k1: float = 1.2, b: float = 0.75) -> dict[str, float]:
    """The ``bin/mem`` BM25: IDF ``log(1 + (N - df + 0.5)/(df + 0.5))``, saturating tf, length-normalized."""
    if not docs or not terms:
        return {}
    n = len(docs)
    lengths = {k: len(v) + 1 for k, v in docs.items()}
    avg = sum(lengths.values()) / float(n)
    lowered = {k: v.lower() for k, v in docs.items()}
    out: dict[str, float] = {}
    for term in terms:
        counts = {k: v.count(term) for k, v in lowered.items()}
        df = sum(1 for c in counts.values() if c > 0)
        if df == 0:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for k, tf in counts.items():
            if tf > 0:
                out[k] = out.get(k, 0.0) + idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * lengths[k] / avg))
    return out


_FTS_SAFE = re.compile(r"[^a-z0-9_]+")


def text_match(store: db.Store, text: str, scope: tuple, k: int = TEXT_K) -> dict[str, float]:
    terms = model.tokenize(text)
    if not terms:
        return {}
    terms = list(dict.fromkeys(terms))[:40]
    if store.fts_mode == "fts5":
        safe = [t for t in (_FTS_SAFE.sub(" ", t).strip() for t in terms) if t]
        if not safe:
            return {}
        match = " OR ".join(f'"{t}"' for t in safe)
        try:
            rows = store.q(
                f"SELECT f.node_id, bm25(nodes_fts, 0, 1.0, 0.5) AS s FROM nodes_fts f "  # noqa: S608
                f"JOIN nodes n ON n.id = f.node_id WHERE nodes_fts MATCH ? AND {_scope_sql(scope)} "
                f"ORDER BY s LIMIT ?",
                (match, *scope, k),
            )
            return {r[0]: -float(r[1]) for r in rows}
        except db.sqlite3.OperationalError:
            pass  # fall through to the Python path on a bad MATCH
    rows = store.q(f"SELECT id, summary FROM nodes WHERE {_scope_sql(scope)}", scope)  # noqa: S608
    ids = [r[0] for r in rows]
    tags_by = model.tags_for_nodes(store, ids)
    docs = {r[0]: r[1] + " " + " ".join(model.tag_free(t).replace("-", " ") for t in tags_by.get(r[0], [])) for r in rows}
    scores = python_bm25(docs, terms)
    return dict(sorted(scores.items(), key=lambda kv: -kv[1])[:k])


def graph_hop(store: db.Store, seed_ids: list[str], scope: tuple) -> dict[str, float]:
    """One hop from the seeds along HOP_EDGES, both directions; ``applies_to`` targets resolve tags."""
    if not seed_ids:
        return {}
    acc: dict[str, float] = {}
    marks = ",".join("?" for _ in seed_ids)
    emarks = ",".join("?" for _ in HOP_EDGES)
    rows = store.q(
        f"SELECT from_id, to_id, type, weight FROM edges WHERE type IN ({emarks}) "  # noqa: S608
        f"AND (from_id IN ({marks}) OR to_id IN ({marks}))",
        (*HOP_EDGES, *seed_ids, *seed_ids),
    )
    seeds = set(seed_ids)
    tag_targets: dict[str, float] = {}
    for r in rows:
        w = float(r["weight"])
        for other in (r["from_id"], r["to_id"]):
            if other in seeds:
                continue
            if other.startswith("tag:"):
                tag_targets[other[4:]] = max(tag_targets.get(other[4:], 0.0), w)
            else:
                acc[other] = max(acc.get(other, 0.0), w)
    if tag_targets:
        tmarks = ",".join("?" for _ in tag_targets)
        trows = store.q(
            f"SELECT t.node_id, t.tag FROM tags t JOIN nodes n ON n.id = t.node_id "  # noqa: S608
            f"WHERE t.tag IN ({tmarks}) AND {_scope_sql(scope)}",
            (*tag_targets.keys(), *scope),
        )
        for r in trows:
            if r[0] in seeds:
                continue
            acc[r[0]] = max(acc.get(r[0], 0.0), tag_targets[r[1]] * 0.8)
    if not acc:
        return {}
    # Keep only nodes in scope.
    ids = list(acc)
    kept: dict[str, float] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        cm = ",".join("?" for _ in chunk)
        for r in store.q(f"SELECT id FROM nodes WHERE id IN ({cm}) AND {_scope_sql(scope)}", (*chunk, *scope)):  # noqa: S608
            kept[r[0]] = acc[r[0]]
    return kept


def always_included(store: db.Store) -> list[model.Node]:
    """Identity nodes (live) and active preferences; they bypass recall and the cap."""
    rows = store.q(
        "SELECT * FROM nodes WHERE (type IN ('identity_core','identity_working') AND status IN ('active','probationary','disputed'))"
        " OR (type = 'preference' AND status = 'active') ORDER BY type, created"
    )
    tags_by = model.tags_for_nodes(store, [r["id"] for r in rows])
    return [model.node_from_row(r, tags_by.get(r["id"], [])) for r in rows]


def recall(store: db.Store, q: Query, cap: int = RECALL_CAP) -> tuple[list[model.Node], list[Candidate]]:
    scope = status_scope(q)
    idf = tag_idf(store, scope)
    tscores = tag_match(store, q, scope, idf)
    text = q.task + " " + " ".join(model.tag_free(t).replace("-", " ") for t in model.parse_tags(q.tags))
    bscores = text_match(store, text, scope)
    bmax = max(bscores.values()) if bscores else 0.0
    bmin = min(bscores.values()) if bscores else 0.0
    span = (bmax - bmin) or 1.0
    union: dict[str, Candidate] = {}

    def cand(nid: str) -> Optional[Candidate]:
        if nid in union:
            return union[nid]
        return None

    pre = {nid: tscores.get(nid, 0.0) + ((bscores[nid] - bmin) / span if nid in bscores else 0.0) for nid in set(tscores) | set(bscores)}
    seeds = [nid for nid, _ in sorted(pre.items(), key=lambda kv: -kv[1])[:HOP_SEEDS]]
    hops = graph_hop(store, seeds, scope)
    all_ids = list(set(pre) | set(hops))
    if not all_ids:
        return always_included(store), []
    rows: list = []
    for start in range(0, len(all_ids), 500):
        chunk = all_ids[start : start + 500]
        cm = ",".join("?" for _ in chunk)
        rows += store.q(f"SELECT * FROM nodes WHERE id IN ({cm})", tuple(chunk))  # noqa: S608
    tags_by = model.tags_for_nodes(store, all_ids)
    for r in rows:
        node = model.node_from_row(r, tags_by.get(r["id"], []))
        if node.type in model.IDENTITY_TYPES or node.type == "preference":
            continue  # handled by always_included / the preference section
        if q.type and node.type != q.type:
            continue
        c = Candidate(node)
        c.tag_score = tscores.get(node.id, 0.0)
        if node.id in bscores:
            c.bm25 = bscores[node.id]
            c.bm25_norm = (bscores[node.id] - bmin) / span
            c.via.add("text")
        if c.tag_score > 0:
            c.via.add("tags")
        if node.id in hops:
            c.hop = hops[node.id]
            c.via.add("hop")
        union[node.id] = c
    ranked = sorted(union.values(), key=lambda c: -(c.tag_score + c.bm25_norm + 0.5 * c.hop))
    return always_included(store), ranked[:cap]
