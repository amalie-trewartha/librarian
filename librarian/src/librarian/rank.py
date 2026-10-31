"""Ranking curated memories for a wake: a transparent weighted sum on summaries and tags.

Signals: IDF-weighted tag overlap with the request, BM25 over summary and
tags, recency with half-lives measured in days (a 7-day run must see a
difference), how often the memory was cited when shown, and a type-by-phase
prior. No model call by default: in the 2026-10 trials the Haiku cut ran on
93 to 99% of packs, its effect was never measured, and an omission from its
reply dropped strong tag matches. ``LIBRARIAN_RANK_LLM=1`` turns it back on,
and then an omission only demotes.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Optional

from . import db, llm, model, recall

PRIORS: dict[str, dict[str, float]] = {
    "skill": {"planning": 0.10, "building": 0.40, "debugging": 0.50, "reviewing": 0.10, "handoff": 0.00},
    "decision": {"planning": 0.30, "building": 0.10, "debugging": 0.10, "reviewing": 0.50, "handoff": 0.30},
    "retrospective": {"planning": 0.50, "building": 0.10, "debugging": 0.20, "reviewing": 0.30, "handoff": 0.40},
    "fact": {"planning": 0.30, "building": 0.40, "debugging": 0.20, "reviewing": 0.50, "handoff": 0.30},
}

# Half-lives in days on last_confirmed (else created). Short, because the runs are a week long.
HALF_LIFE_DAYS: dict[str, Optional[float]] = {"skill": 7.0, "decision": 7.0, "retrospective": 7.0, "fact": 5.0, "episode": 1.0}

W_TAG = 1.0
W_BM25 = 0.8
W_RECENCY = 0.4
W_USE = 0.6
PENALTY_PROBATIONARY = 0.10
PENALTY_EXCLUDED = 1.0
W_LLM = 1.0
LLM_MIN_SURVIVORS = 8
LLM_TOP = 40
LLM_MAX_TOKENS = 1500


@dataclass
class Ranked:
    node: model.Node
    score: float
    cut1: float
    relevance: Optional[int] = None
    reasons: dict = field(default_factory=dict)


def load_priors(store: db.Store) -> dict[str, dict[str, float]]:
    raw = store.meta_get("rank.priors")
    if not raw:
        return PRIORS
    try:
        override = json.loads(raw)
    except ValueError:
        return PRIORS
    merged = {k: dict(v) for k, v in PRIORS.items()}
    for t, row in override.items():
        merged.setdefault(t, {}).update({k: float(v) for k, v in row.items()})
    return merged


def prior(priors: dict, ntype: str, phase: Optional[str]) -> float:
    row = priors.get(ntype)
    if not row:
        return 0.0
    if phase and phase in row:
        return row[phase]
    return sum(row.values()) / float(len(row))


def recency(node: model.Node, ref=None) -> float:
    ref = ref or db.now()
    hl = HALF_LIFE_DAYS.get(node.type)
    if hl is None:
        return 1.0
    age = db.age_days(node.last_confirmed or node.created, ref)
    if age is None or age < 0:
        return 1.0
    return 0.5 ** (age / hl)


def use_rates(store: db.Store, ids: list[str]) -> dict[str, float]:
    """cited / shown per memory, smoothed: (cited + 1) / (shown + 4). A memory never shown
    starts at 0.25; one cited every time it was shown tends to 1."""
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    shown = {r[0]: r[1] for r in store.q(f"SELECT node_id, COUNT(*) FROM retrieval_log WHERE source = 'pack' AND section = 'task' AND node_id IN ({marks}) GROUP BY node_id", tuple(ids))}  # noqa: S608
    cited = {r[0]: r[1] for r in store.q(f"SELECT node_id, COUNT(*) FROM citations WHERE source = 'cite' AND node_id IN ({marks}) GROUP BY node_id", tuple(ids))}  # noqa: S608
    return {i: (cited.get(i, 0) + 1) / float(shown.get(i, 0) + 4) for i in ids}


def weighted_jaccard(a: set, b: set, idf: Optional[dict]) -> float:
    if not a and not b:
        return 0.0
    if not idf:
        return model.jaccard(a, b)
    w = lambda tags: sum(idf.get(t, 1.0) for t in tags)  # noqa: E731
    union = w(a | b)
    return w(a & b) / union if union else 0.0


def cut1(c: recall.Candidate, q: recall.Query, exclude: set, priors: dict, ref=None, idf: Optional[dict] = None, use: float = 0.25) -> tuple[float, dict]:
    n = c.node
    qt = set(model.parse_tags(q.tags))
    tj = weighted_jaccard(qt, set(n.tags), idf) if qt else 0.0
    rec = recency(n, ref)
    pr = prior(priors, n.type, q.phase)
    score = W_TAG * tj + W_BM25 * c.bm25_norm + W_RECENCY * rec + W_USE * use + pr
    if n.status == "probationary":
        score -= PENALTY_PROBATIONARY
    if n.id in exclude:
        score -= PENALTY_EXCLUDED
    reasons = {
        "tag_jaccard": round(tj, 3),
        "bm25_norm": round(c.bm25_norm, 3),
        "recency": round(rec, 3),
        "use": round(use, 3),
        "prior": round(pr, 3),
        "via": sorted(c.via),
    }
    return score, reasons


def llm_relevance(model_llm: llm.LLM, task: str, ranked: list[Ranked]) -> Optional[dict[str, int]]:
    """One call: rate each numbered (type, summary) 0–3 for the task; lenient JSON parse."""
    lines = [f"{i} | {r.node.type} | {r.node.summary}" for i, r in enumerate(ranked, start=1)]
    system = (
        "You rank memory summaries for relevance to a task. Answer with one JSON object mapping the number of "
        "each memory that is relevant to an integer 1-3 (1 marginal, 2 useful, 3 directly needed); leave out "
        "irrelevant ones. No prose."
    )
    prompt = "Task:\n" + task.strip()[:3000] + "\n\nMemories (number | type | summary):\n" + "\n".join(lines) + "\n\nJSON:"
    out = model_llm.complete(prompt, system=system, max_tokens=LLM_MAX_TOKENS)
    parsed = llm.parse_json_lenient(out)
    if not isinstance(parsed, dict):
        return None
    result: dict[str, int] = {}
    for k, v in parsed.items():
        try:
            i, iv = int(str(k).strip()), int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(ranked):
            result[ranked[i - 1].node.id] = max(0, min(3, iv))
    return result


def rank(
    store: db.Store,
    cands: list[recall.Candidate],
    q: recall.Query,
    exclude_ids: Optional[set] = None,
    use_llm: bool = False,
    top: int = LLM_TOP,
) -> tuple[list[Ranked], bool, Optional[str]]:
    """Returns (ranked, llm_used, note). The model cut runs only when asked for and
    LIBRARIAN_RANK_LLM=1; a memory it leaves out keeps its deterministic score."""
    exclude = set(exclude_ids or ())
    priors = load_priors(store)
    ref = db.now()
    idf = recall.tag_idf(store, recall.status_scope(q))
    use = use_rates(store, [c.node.id for c in cands])
    out: list[Ranked] = []
    for c in cands:
        s, reasons = cut1(c, q, exclude, priors, ref, idf, use.get(c.node.id, 0.25))
        out.append(Ranked(c.node, s, s, None, reasons))
    out.sort(key=lambda r: (-r.score, r.node.created))
    llm_used = False
    note = None
    if not (use_llm and os.environ.get("LIBRARIAN_RANK_LLM", "0").strip() == "1"):
        return out, False, "no model cut"
    survivors = [r for r in out if r.node.id not in exclude]
    if len(survivors) < LLM_MIN_SURVIVORS:
        return out, False, f"model cut skipped ({len(survivors)} candidates)"
    m = llm.get_llm("rank")
    if m is None:
        return out, False, "model cut skipped (no rank model)"
    judged = survivors[:top]
    rel = llm_relevance(m, q.task, judged)
    if rel is None:
        return out, False, "model cut skipped (no parsable answer)"
    llm_used = True
    for r in judged:
        if r.node.id in rel:
            r.relevance = rel[r.node.id]
            r.score = r.cut1 + W_LLM * (r.relevance / 3.0)
    out.sort(key=lambda r: (-r.score, r.node.created))
    return out, llm_used, note
