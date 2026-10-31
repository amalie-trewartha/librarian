"""Memory lifecycle: credit assignment, consolidation, decay.

Confirmation comes from outcomes, not opinions (spec, "Confirmation"). An
episode's outcome moves the confidence of every memory it cited; the
agent's own helpful rating is a tie-breaker only. Nothing is deleted:
nodes move to ``archived`` or ``superseded``.

A memory with a per-id outcome (a review verdict that names it, or a lesson
its work applied) is judged on its own, so it takes the full step split only
among the memories so judged; the rest of the wake's citations share the
wake's outcome. In run B (2026-10) a SURVIVES line moved a fact by 0.01,
split with the eight memories the pack logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from . import db, gate, model

STEP = 0.10
CONF_MIN, CONF_MAX = 0.01, 0.99
PROBATION_DAYS = 90
PROBATION_UNKNOWN_CITATIONS = 10
REVIEW_FAILURES = 2
NEAR_DUP = 0.6
GENERALIZE_MIN = 3
PROMOTE_PROJECTS = 2
STABLE_DAYS = 90
CO_RETRIEVED_FLOOR = 0.2

# Archival rules (days). Ranking half-lives live in rank.HALF_LIFE_DAYS.
ARCHIVE_SKILL_DAYS = 730
ARCHIVE_DECISION_DAYS = 180
ARCHIVE_EPISODE_DAYS = 30


@dataclass
class CreditReport:
    episode_id: str
    outcome: str
    criterion: str
    cited: list[dict] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    reversed: int = 0

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "outcome": self.outcome,
            "criterion": self.criterion,
            "cited": self.cited,
            "flagged": self.flagged,
            "reversed": self.reversed,
        }


# ── episodes and credit ──────────────────────────────────────────────────────


def logged_ids(store: db.Store, request_ids: list[str], sources=("pack", "fetch"), sections=("task",)) -> list[str]:
    """Node ids the retrieval log recorded for these requests (task-section pack rows and fetches)."""
    if not request_ids:
        return []
    marks = ",".join("?" for _ in request_ids)
    smarks = ",".join("?" for _ in sources)
    rows = store.q(
        f"SELECT node_id, source, section FROM retrieval_log WHERE request_id IN ({marks}) AND source IN ({smarks}) ORDER BY id",  # noqa: S608
        (*request_ids, *sources),
    )
    out: list[str] = []
    for r in rows:
        if r["source"] == "pack" and sections and r["section"] not in sections:
            continue
        if r["node_id"] not in out:
            out.append(r["node_id"])
    return out


def close_episode(
    store: db.Store,
    *,
    outcome: str,
    criterion: str = "",
    episode_id: Optional[str] = None,
    summary: str = "",
    body: str = "",
    tags: Optional[list[str]] = None,
    project: Optional[str] = None,
    phase: Optional[str] = None,
    cited: Optional[list[str]] = None,
    request_ids: Optional[list[str]] = None,
    helpful: Optional[list[str]] = None,
    overrides: Optional[dict[str, str]] = None,
    provenance: Optional[dict] = None,
    dismissed: Optional[list[str]] = None,
    lessons: Optional[dict[str, str]] = None,
) -> CreditReport:
    """Record (or create) an episode with its outcome and run credit assignment.

    Memories the mind dismissed this wake get no citation: it judged them not
    to apply, so the wake's outcome says nothing about them. ``lessons`` maps
    lessons a reviewed piece of work applied to that review's outcome; they are
    cited with source 'lesson'.
    """
    if outcome not in model.OUTCOMES:
        raise ValueError(f"bad outcome {outcome}")
    tags = model.parse_tags(tags or [])
    if project and f"project:{project}" not in tags:
        tags.append(f"project:{project}")
    if phase and f"ctx:{phase}" not in tags and model.vocab_status(store, f"ctx:{phase}") == "active":
        tags.append(f"ctx:{phase}")
    recorded = db.now_iso()
    with store.write():
        if episode_id is None:
            prov = dict(provenance or {})
            prov.setdefault("author", "runtime")
            cand = gate.Candidate(
                type="episode",
                summary=(summary or "episode")[:400],
                body=body or "",
                tags=tags or ["ctx:building"],
                provenance=prov,
                project=project,
                outcome={"value": outcome, "criterion": criterion, "recorded": recorded},
            )
            res = gate.apply(store, cand)
            if not res.accepted or res.id is None:
                raise ValueError("episode rejected by the gate: " + "; ".join(res.reasons))
            episode_id = res.id
        else:
            ep = model.get_node(store, episode_id, with_edges=False)
            if ep is None or ep.type != "episode":
                raise ValueError(f"{episode_id} is not an episode")
            store.ex(
                "UPDATE nodes SET outcome = ? WHERE id = ?",
                (json.dumps({"value": outcome, "criterion": criterion, "recorded": recorded}), episode_id),
            )
        ids: list[str] = []
        skip = set(dismissed or [])
        for i in model.parse_ids(cited or []):
            rid = model.resolve_id(store, i)
            if rid and rid not in ids and rid != episode_id and rid not in skip:
                ids.append(rid)
        for i in logged_ids(store, request_ids or []):
            if i not in ids and i != episode_id and i not in skip:
                ids.append(i)
        lessons = lessons or {}
        for i in lessons:
            if i not in ids and i != episode_id and i not in skip:
                ids.append(i)
        helpful_set = {model.resolve_id(store, h) or h for h in (helpful or [])}
        for nid in ids:
            src = "cite" if nid in (cited or []) else "lesson" if nid in lessons else "log"
            ov = (overrides or {}).get(nid) or lessons.get(nid)
            if ov and ov not in model.OUTCOMES:
                ov = None
            store.ex(
                """INSERT INTO citations(episode_id, node_id, source, request_id, helpful, outcome_override)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(episode_id, node_id) DO UPDATE SET
                     helpful = COALESCE(excluded.helpful, citations.helpful),
                     outcome_override = COALESCE(excluded.outcome_override, citations.outcome_override)""",
                (episode_id, nid, src, (request_ids or [None])[0], 1 if nid in helpful_set else None, ov),
            )
        if project:
            store.ex(
                "INSERT INTO projects(project, opened) VALUES (?, ?) ON CONFLICT(project) DO NOTHING",
                (project, recorded),
            )
        return assign_credit(store, episode_id)


def _clamp(c: float) -> float:
    return max(CONF_MIN, min(CONF_MAX, c))


def assign_credit(store: db.Store, episode_id: str) -> CreditReport:
    """Spec steps 2–5. Caller holds the write."""
    ep = model.get_node(store, episode_id, with_edges=False)
    if ep is None or ep.type != "episode":
        raise ValueError(f"{episode_id} is not an episode")
    outcome = (ep.outcome or {}).get("value", "unknown")
    criterion = (ep.outcome or {}).get("criterion", "")
    recorded = (ep.outcome or {}).get("recorded") or db.now_iso()
    cits = store.q("SELECT node_id, outcome_override FROM citations WHERE episode_id = ?", (episode_id,))
    report = CreditReport(episode_id, outcome, criterion)
    if not cits:
        return report
    judged = sum(1 for c in cits if c["outcome_override"])
    shares = {True: judged, False: len(cits) - judged}
    ts = db.now_iso()
    for c in cits:
        nid = c["node_id"]
        node = model.get_node(store, nid, with_edges=False)
        if node is None:
            continue
        effective = c["outcome_override"] or outcome
        n = shares[bool(c["outcome_override"])]
        before = node.status
        delta = 0.0
        confirmed = 0
        promoted = 0
        new_status = node.status
        use_count = node.use_count + 1
        succ, fail, fss, unk = node.success_count, node.failure_count, node.failures_since_success, node.unknown_citations
        last_confirmed = node.last_confirmed
        if effective == "success":
            delta = STEP / n
            confirmed = 1
            succ += 1
            fss = 0
            last_confirmed = recorded
            if node.status == "probationary":
                new_status = "active"
                promoted = 1
        elif effective == "failure":
            delta = -STEP / n
            fail += 1
            fss += 1
            model.add_edge(store, nid, episode_id, "failed_in", 1.0, {"criterion": criterion})
        elif effective == "unknown" and node.status == "probationary":
            unk += 1
        conf = _clamp(node.confidence + delta)
        # Log the change actually applied, so reversal is exact at the clamp (the
        # 2026-10 fix-19 repair had to replay credit for nodes floored at CONF_MIN).
        delta = conf - node.confidence
        review_flag = node.review_flag
        if fss >= REVIEW_FAILURES and effective == "failure":
            review_flag = "repeated_failure"
            report.flagged.append(nid)
        store.ex(
            """UPDATE nodes SET confidence = ?, use_count = ?, success_count = ?, failure_count = ?,
               failures_since_success = ?, unknown_citations = ?, last_used = ?, last_confirmed = ?, status = ?,
               known_to = CASE WHEN ? = 'active' THEN NULL ELSE known_to END, review_flag = ? WHERE id = ?""",
            (conf, use_count, succ, fail, fss, unk, ts, last_confirmed, new_status, new_status, review_flag, nid),
        )
        store.ex(
            """INSERT INTO credit_log(episode_id, node_id, outcome, delta_conf, confirmed, promoted, prev_last_confirmed,
               prev_status, ts) VALUES (?,?,?,?,?,?,?,?,?)""",
            (episode_id, nid, effective, delta, confirmed, promoted, node.last_confirmed, before, ts),
        )
        report.cited.append(
            {
                "id": nid,
                "outcome": effective,
                "delta": round(delta, 4),
                "confidence": round(conf, 4),
                "status_before": before,
                "status_after": new_status,
            }
        )
    return report


def reverse_credit(store: db.Store, episode_id: str) -> int:
    """Undo every un-reversed credit_log row for the episode. Caller holds the write."""
    rows = store.q(
        "SELECT * FROM credit_log WHERE episode_id = ? AND reversed_ts IS NULL ORDER BY id", (episode_id,)
    )
    ts = db.now_iso()
    count = 0
    for r in rows:
        node = model.get_node(store, r["node_id"], with_edges=False)
        if node is None:
            continue
        succ, fail, fss, unk = node.success_count, node.failure_count, node.failures_since_success, node.unknown_citations
        status = node.status
        last_confirmed = node.last_confirmed
        if r["outcome"] == "success":
            succ = max(0, succ - 1)
            other = store.q1(
                "SELECT 1 FROM credit_log WHERE node_id = ? AND confirmed = 1 AND reversed_ts IS NULL AND id != ?",
                (node.id, r["id"]),
            )
            if other is None:
                last_confirmed = r["prev_last_confirmed"]
                if r["promoted"] and status == "active":
                    status = "probationary"
        elif r["outcome"] == "failure":
            fail = max(0, fail - 1)
            fss = max(0, fss - 1)
            model.remove_edge(store, node.id, episode_id, "failed_in")
        elif r["outcome"] == "unknown":
            unk = max(0, unk - 1)
        review_flag = node.review_flag if fss >= REVIEW_FAILURES else None
        store.ex(
            """UPDATE nodes SET confidence = ?, use_count = ?, success_count = ?, failure_count = ?,
               failures_since_success = ?, unknown_citations = ?, last_confirmed = ?, status = ?, review_flag = ? WHERE id = ?""",
            (
                _clamp(node.confidence - r["delta_conf"]),
                max(0, node.use_count - 1),
                succ,
                fail,
                fss,
                unk,
                last_confirmed,
                status,
                review_flag,
                node.id,
            ),
        )
        store.ex("UPDATE credit_log SET reversed_ts = ? WHERE id = ?", (ts, r["id"]))
        count += 1
    return count


def amend_outcome(store: db.Store, episode_id: str, outcome: str, criterion: str = "") -> CreditReport:
    """Late outcome: reverse the earlier credit exactly, record history, re-run."""
    if outcome not in model.OUTCOMES:
        raise ValueError(f"bad outcome {outcome}")
    with store.write():
        ep = model.get_node(store, episode_id, with_edges=False)
        if ep is None or ep.type != "episode":
            raise ValueError(f"{episode_id} is not an episode")
        reversed_n = reverse_credit(store, episode_id)
        old = dict(ep.outcome or {})
        history = old.pop("history", [])
        history.append(old)
        new = {"value": outcome, "criterion": criterion or old.get("criterion", ""), "recorded": db.now_iso(), "history": history}
        store.ex("UPDATE nodes SET outcome = ? WHERE id = ?", (json.dumps(new), episode_id))
        report = assign_credit(store, episode_id)
        report.reversed = reversed_n
        return report


def endorse(store: db.Store, node_id: str, by: str = "human") -> dict:
    with store.write():
        node = model.get_node(store, node_id, with_edges=False)
        if node is None:
            raise ValueError(f"no node {node_id}")
        ts = db.now_iso()
        status = "active" if node.status in ("probationary", "disputed", "archived") else node.status
        prov = dict(node.provenance)
        prov.setdefault("endorsements", []).append({"by": by, "ts": ts})
        store.ex(
            "UPDATE nodes SET status = ?, known_to = NULL, last_confirmed = ?, confidence = ?, provenance = ?, archived_reason = NULL WHERE id = ?",
            (status, ts, _clamp(node.confidence + STEP), json.dumps(prov), node_id),
        )
        return {"id": node_id, "status": status, "last_confirmed": ts}


# ── decay and archival ───────────────────────────────────────────────────────
