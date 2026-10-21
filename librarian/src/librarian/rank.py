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
    # Sourced, often adversary-checked claims: wanted while building and most of all in review.
    "fact": {"planning": 0.30, "building": 0.40, "debugging": 0.20, "reviewing": 0.50, "handoff": 0.30},
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
# Episodes carry the request tags of the wake that wrote them, so their tag
# overlap with the next wake is about 1 by construction; half weight.
W_TAG_EPISODE = 0.5
W_BM25 = 0.8
W_RECENCY = 0.6
W_REUSE = 0.5
W_HOP = 0.1
PENALTY_PROBATIONARY = 0.15
PENALTY_EXCLUDED = 1.0
W_LLM = 2.0
LLM_MIN_SURVIVORS = 8
LLM_TOP = 30
# Curated memories all go to the LLM cut (up to recall.CURATED_ALL_MAX), on top
# of the LLM_TOP best others: in the 2026-10 live run the cut parsed in 4 of
# 1,095 packs (replies cut at max_tokens), so curated memory was ranked on tags
# that matched nearly everything.
LLM_MAX_TOKENS = 1500
# Dismissals (librarian dismiss) push a memory down for its project: each recent
# one since the memory was last cited costs W_DISMISS, up to DISMISS_CAP.
W_DISMISS = 0.4
DISMISS_CAP = 1.2
DISMISS_WINDOW_DAYS = 3.0


def dismissal_penalty(store: db.Store, project: Optional[str]) -> dict[str, float]:
    since = db.iso(db.now() - db.dt.timedelta(days=DISMISS_WINDOW_DAYS))
    rows = store.q(
        """SELECT d.node_id, COUNT(*) FROM dismissals d
           WHERE d.project IS ? AND d.ts >= ?
             AND d.ts > COALESCE((SELECT MAX(e.created) FROM citations c JOIN nodes e ON e.id = c.episode_id
                                  WHERE c.node_id = d.node_id AND c.source = 'cite'), '')
           GROUP BY d.node_id""",
        (project, since),
    )
    return {r[0]: min(DISMISS_CAP, W_DISMISS * r[1]) for r in rows}


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
    # Uses that carried evidence (a success or failure), not use_count: every pack citation
    # bumps use_count, so ranking on it would keep repacking whatever was packed before.
    s, f = node.success_count, node.failure_count
    share = s / float(s + f) if (s + f) > 0 else 0.5
    return (math.log1p(s + f) / math.log1p(10)) * (0.5 + 0.5 * share)


def weighted_jaccard(a: set, b: set, idf: Optional[dict]) -> float:
    """Jaccard with each tag weighted by its IDF: a tag on nearly every node counts for little."""
    if not a and not b:
        return 0.0
    if not idf:
        return model.jaccard(a, b)
    w = lambda tags: sum(idf.get(t, 1.0) for t in tags)  # noqa: E731
    union = w(a | b)
    return w(a & b) / union if union else 0.0


def cut1(c: recall.Candidate, q: recall.Query, exclude: set, priors: dict, ref=None, idf: Optional[dict] = None) -> tuple[float, dict]:
    n = c.node
    qt = set(model.parse_tags(q.tags))
    tj = weighted_jaccard(qt, set(n.tags), idf) if qt else 0.0
    rec = recency(n, ref)
    reu = reuse(n)
    pr = prior(priors, n.type, q.phase)
    score = (W_TAG_EPISODE if n.type == "episode" else W_TAG) * tj + W_BM25 * c.bm25_norm + W_RECENCY * rec + W_REUSE * reu + pr + W_HOP * c.hop
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
    """One call: rate each numbered (type, summary) 0–3 for the task; lenient JSON parse.

    Short numbers instead of 26-character ids keep the reply small (one 400-token
    reply limit truncated 438 of 467 calls in the 2026-10 live run).
    """
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
    result: dict[str, int] = {r.node.id: 0 for r in ranked}
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
    use_llm: bool = True,
    top: int = LLM_TOP,
) -> tuple[list[Ranked], bool, Optional[str]]:
    """Returns (ranked, llm_used, note)."""
    exclude = set(exclude_ids or ())
    priors = load_priors(store)
    ref = db.now()
    idf = recall.tag_idf(store, recall.status_scope(q))
    dismissed = dismissal_penalty(store, q.project)
    out: list[Ranked] = []
    for c in cands:
        s, reasons = cut1(c, q, exclude, priors, ref, idf)
        if c.node.id in dismissed:
            s -= dismissed[c.node.id]
            reasons["dismissed"] = round(dismissed[c.node.id], 3)
        out.append(Ranked(c.node, s, s, None, reasons))
    out.sort(key=lambda r: (-r.score, -r.node.confidence, r.node.body_tokens))
    llm_used = False
    note = None
    survivors = [r for r in out if r.node.id not in exclude]
    judged = [r for r in survivors if r.node.type in recall.CURATED_TYPES][: recall.CURATED_ALL_MAX]
    judged_ids = {r.node.id for r in judged}
    judged += [r for r in survivors if r.node.id not in judged_ids][:top]
    if not use_llm:
        note = "llm relevance cut off"
    elif len(survivors) < LLM_MIN_SURVIVORS:
        note = f"llm relevance cut skipped ({len(survivors)} candidates, fewer than {LLM_MIN_SURVIVORS})"
    else:
        m = llm.get_llm("rank")
        if m is None:
            note = "llm relevance cut skipped (no rank model)"
        else:
            rel = llm_relevance(m, q.task, judged)
            if rel is None:
                note = "llm relevance cut skipped (no parsable answer)"
            else:
                llm_used = True
                for r in judged:
                    if r.node.id in rel:
                        r.relevance = rel[r.node.id]
                        r.score = r.cut1 + W_LLM * (r.relevance / 3.0)
                out.sort(key=lambda r: (-r.score, -r.node.confidence, r.node.body_tokens))
    return out, llm_used, note
