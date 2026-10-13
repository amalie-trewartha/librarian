"""Stage 2: salience ranking on summaries and envelopes only.

Cut 1 is a deterministic weighted sum. Cut 2, when a model is available,
adds an LLM relevance judgment (0–3) over the top survivors in one call.
Both read summaries only; bodies are fetched by the packer afterwards.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

from . import db, llm, model, recall

# Type × phase priors. Retrospectives up in planning; skills in building and
# debugging; decisions in reviewing. Overridable through meta 'rank.priors'.
PRIORS: dict[str, dict[str, float]] = {
    "skill": {"planning": 0.10, "building": 0.40, "debugging": 0.50, "reviewing": 0.10, "handoff": 0.00},
    "decision": {"planning": 0.30, "building": 0.10, "debugging": 0.10, "reviewing": 0.50, "handoff": 0.30},
    "retrospective": {"planning": 0.50, "building": 0.10, "debugging": 0.20, "reviewing": 0.30, "handoff": 0.40},
    "preference": {"planning": 0.30, "building": 0.20, "debugging": 0.10, "reviewing": 0.40, "handoff": 0.30},
    "episode": {"planning": 0.20, "building": 0.00, "debugging": 0.20, "reviewing": 0.10, "handoff": 0.30},
}

# Ranking half-lives on last_confirmed (days); None = no decay.
HALF_LIFE_DAYS: dict[str, Optional[float]] = {
    "skill": 365.0,
    "decision": 180.0,
    "retrospective": 180.0,
    "episode": 30.0,
    "preference": None,
    "identity_core": None,
    "identity_working": None,
}

W_TAG = 1.0
W_BM25 = 0.8
W_RECENCY = 0.6
W_REUSE = 0.5
W_HOP = 0.1
PENALTY_PROBATIONARY = 0.15
PENALTY_EXCLUDED = 1.0
W_LLM = 2.0
LLM_MIN_SURVIVORS = 8
LLM_TOP = 30


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
    if node.type == "decision" and node.valid_to:
        vt, vf = db.parse_ts(node.valid_to), db.parse_ts(node.valid_from or node.created)
        if vt and vf and vt > vf:
            remaining = (vt - ref).total_seconds() / (vt - vf).total_seconds()
            return max(0.0, min(1.0, remaining))
    hl = HALF_LIFE_DAYS.get(node.type)
    if hl is None:
        return 1.0
    age = db.age_days(node.last_confirmed or node.created, ref)
    if age is None or age < 0:
        return 1.0
    return 0.5 ** (age / hl)


def reuse(node: model.Node) -> float:
    s, f = node.success_count, node.failure_count
    share = s / float(s + f) if (s + f) > 0 else 0.5
    return (math.log1p(node.use_count) / math.log1p(10)) * (0.5 + 0.5 * share)


def cut1(c: recall.Candidate, q: recall.Query, exclude: set, priors: dict, ref=None) -> tuple[float, dict]:
    n = c.node
    qt = set(model.parse_tags(q.tags))
    tj = model.jaccard(qt, n.tags) if qt else 0.0
    rec = recency(n, ref)
    reu = reuse(n)
    pr = prior(priors, n.type, q.phase)
    score = W_TAG * tj + W_BM25 * c.bm25_norm + W_RECENCY * rec + W_REUSE * reu + pr + W_HOP * c.hop
    if n.status == "probationary":
        score -= PENALTY_PROBATIONARY
    if n.id in exclude:
        score -= PENALTY_EXCLUDED
    reasons = {
        "tag_jaccard": round(tj, 3),
        "bm25_norm": round(c.bm25_norm, 3),
        "recency": round(rec, 3),
        "reuse": round(reu, 3),
        "prior": round(pr, 3),
        "hop": round(c.hop, 3),
        "via": sorted(c.via),
    }
    return score, reasons


def llm_relevance(model_llm: llm.LLM, task: str, ranked: list[Ranked]) -> Optional[dict[str, int]]:
    """One call: rate each (id, type, summary) 0–3 for the task; lenient JSON parse."""
    lines = [f"{r.node.id} | {r.node.type} | {r.node.summary}" for r in ranked]
    system = (
        "You rank memory summaries for relevance to a task. Answer with one JSON object mapping each id to an "
        "integer 0-3 (0 irrelevant, 3 directly needed). No prose."
    )
    prompt = "Task:\n" + task.strip()[:3000] + "\n\nMemories (id | type | summary):\n" + "\n".join(lines) + "\n\nJSON:"
    out = model_llm.complete(prompt, system=system, max_tokens=400)
    parsed = llm.parse_json_lenient(out)
    if not isinstance(parsed, dict):
        return None
    result: dict[str, int] = {}
    for k, v in parsed.items():
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        result[str(k).strip().upper()] = max(0, min(3, iv))
    return result or None


def rank(
    store: db.Store,
    cands: list[recall.Candidate],
    q: recall.Query,
    exclude_ids: Optional[set] = None,
    use_llm: bool = True,
    top: int = LLM_TOP,
) -> tuple[list[Ranked], bool, Optional[str]]:
    """Returns (ranked, llm_used, note)."""
    exclude = set(exclude_ids or ())
    priors = load_priors(store)
    ref = db.now()
    out: list[Ranked] = []
    for c in cands:
        s, reasons = cut1(c, q, exclude, priors, ref)
        out.append(Ranked(c.node, s, s, None, reasons))
    out.sort(key=lambda r: (-r.score, -r.node.confidence, r.node.body_tokens))
    llm_used = False
    note = None
    survivors = [r for r in out if r.node.id not in exclude]
    if use_llm and len(survivors) >= LLM_MIN_SURVIVORS:
        m = llm.get_llm("rank")
        if m is not None:
            rel = llm_relevance(m, q.task, survivors[:top])
            if rel is None:
                note = "llm relevance cut skipped (no parsable answer)"
            else:
                llm_used = True
                for r in survivors[:top]:
                    if r.node.id in rel:
                        r.relevance = rel[r.node.id]
                        r.score = r.cut1 + W_LLM * (r.relevance / 3.0)
                out.sort(key=lambda r: (-r.score, -r.node.confidence, r.node.body_tokens))
    return out, llm_used, note
