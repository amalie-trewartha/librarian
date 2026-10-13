"""Memory lifecycle: credit assignment, consolidation, decay.

Confirmation comes from outcomes, not opinions (spec, "Confirmation"). An
episode's outcome moves the confidence of every memory it cited; the
agent's own helpful rating is a tie-breaker only. Nothing is deleted:
nodes move to ``archived`` or ``superseded``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from . import db, gate, llm, model, queue

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
) -> CreditReport:
    """Record (or create) an episode with its outcome and run credit assignment."""
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
        for i in model.parse_ids(cited or []):
            rid = model.resolve_id(store, i)
            if rid and rid not in ids and rid != episode_id:
                ids.append(rid)
        for i in logged_ids(store, request_ids or []):
            if i not in ids and i != episode_id:
                ids.append(i)
        helpful_set = {model.resolve_id(store, h) or h for h in (helpful or [])}
        for nid in ids:
            src = "cite" if nid in (cited or []) else "log"
            ov = (overrides or {}).get(nid)
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
    n = len(cits)
    if n == 0:
        return report
    ts = db.now_iso()
    for c in cits:
        nid = c["node_id"]
        node = model.get_node(store, nid, with_edges=False)
        if node is None:
            continue
        effective = c["outcome_override"] or outcome
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


def decay(store: db.Store, dry_run: bool = False) -> dict:
    """Archive what fell below its floor; exit probation in both directions."""
    ref = db.now()
    archived: list[dict] = []
    exits: list[dict] = []

    def arch(nid: str, reason: str) -> None:
        archived.append({"id": nid, "reason": reason})
        if not dry_run:
            model.set_status(store, nid, "archived", reason=reason)

    with store.write():
        # Probation exits.
        for r in store.q("SELECT id, created, unknown_citations FROM nodes WHERE status = 'probationary' AND type NOT IN ('identity_core','identity_working','preference','episode')"):
            age = db.age_days(r["created"], ref) or 0.0
            if age >= PROBATION_DAYS or r["unknown_citations"] >= PROBATION_UNKNOWN_CITATIONS:
                exits.append({"id": r["id"], "reason": "unproven"})
                arch(r["id"], "unproven")
        # Skills.
        for r in store.q("SELECT id, created, last_confirmed, use_count FROM nodes WHERE type = 'skill' AND status = 'active'"):
            age = db.age_days(r["last_confirmed"] or r["created"], ref) or 0.0
            if age >= ARCHIVE_SKILL_DAYS and r["use_count"] == 0:
                arch(r["id"], "unused past two half-lives")
        # Decisions.
        for r in store.q("SELECT id, project, valid_to, created, last_confirmed FROM nodes WHERE type = 'decision' AND status = 'active'"):
            vt = db.parse_ts(r["valid_to"]) if r["valid_to"] else None
            if vt and vt < ref:
                arch(r["id"], "valid_to passed")
                continue
            if r["project"]:
                closed = store.q1("SELECT closed FROM projects WHERE project = ? AND closed IS NOT NULL", (r["project"],))
                if closed is not None:
                    newer = store.q1(
                        "SELECT 1 FROM edges e JOIN nodes n ON n.id = e.from_id WHERE e.to_id = ? AND n.type = 'decision' AND n.created > ? LIMIT 1",
                        (r["id"], r["created"]),
                    )
                    if newer is None:
                        arch(r["id"], "project closed, no later decision cites it")
        # Episodes.
        for r in store.q("SELECT id, created FROM nodes WHERE type = 'episode' AND status IN ('active','probationary')"):
            derived = store.q(
                "SELECT n.status FROM edges e JOIN nodes n ON n.id = e.from_id WHERE e.to_id = ? AND e.type = 'derived_from'",
                (r["id"],),
            )
            age = db.age_days(r["created"], ref) or 0.0
            if derived and all(d[0] == "active" for d in derived) and age >= ARCHIVE_EPISODE_DAYS:
                arch(r["id"], "every derived node is active")
    return {"archived": archived, "probation_exits": exits, "dry_run": dry_run}


# ── consolidation ────────────────────────────────────────────────────────────

STEPS = ("merge", "generalize", "disputes", "promote", "co_retrieved", "reembed")


def _log(store: db.Store, step: str, report: dict) -> None:
    store.ex("INSERT INTO consolidation_log(ts, step, report) VALUES (?,?,?)", (db.now_iso(), step, json.dumps(report)))


def _clusters(nodes: list[model.Node], threshold: float = NEAR_DUP) -> list[list[model.Node]]:
    toks = {n.id: set(model.tokenize(n.summary)) | set(n.tags) for n in nodes}
    parent = {n.id: n.id for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ids = [n.id for n in nodes]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if model.jaccard(toks[ids[i]], toks[ids[j]]) >= threshold:
                parent[find(ids[i])] = find(ids[j])
    groups: dict[str, list[model.Node]] = {}
    for n in nodes:
        groups.setdefault(find(n.id), []).append(n)
    return [g for g in groups.values() if len(g) >= 2]


def _draft(role_llm: Optional[llm.LLM], instruction: str, material: str) -> Optional[tuple[str, str]]:
    if role_llm is None:
        return None
    system = (
        "You write memory nodes for an autonomous research agent. Answer with one JSON object "
        '{"summary": "<= 60 tokens answering when would I want this", "body": "specifics: commands, versions, numbers, names"}.'
    )
    out = role_llm.complete(instruction + "\n\n" + material[:12000], system=system, max_tokens=900)
    parsed = llm.parse_json_lenient(out)
    if isinstance(parsed, dict) and parsed.get("summary") and parsed.get("body"):
        return str(parsed["summary"]).strip(), str(parsed["body"]).strip()
    return None


def _source_bodies(store: db.Store, members: list[model.Node]) -> str:
    """Bodies of the members' derived_from episodes (never the previous merged text), else member bodies."""
    parts: list[str] = []
    for m in members:
        for e in model.node_edges(store, m.id):
            if e["type"] == "derived_from":
                ep = model.get_node(store, e["to"], with_edges=False)
                if ep is not None and ep.body:
                    parts.append(f"[episode {ep.id}] {ep.body}")
    if not parts:
        parts = [f"[{m.type} {m.id}] {m.summary}\n{m.body}" for m in members]
    return "\n\n".join(parts)


def _merge(store: db.Store, use_llm: bool, dry_run: bool) -> dict:
    report: dict = {"clusters": 0, "merged": [], "duplicate_pairs": 0}
    drafter = llm.get_llm("draft", use_llm)
    for ntype in ("skill", "decision", "retrospective", "preference"):
        nodes = model.nodes_where(store, "type = ? AND status = 'active'", (ntype,))
        for cluster in _clusters(nodes):
            report["clusters"] += 1
            report["duplicate_pairs"] += len(cluster) * (len(cluster) - 1) // 2
            if dry_run:
                report["merged"].append({"members": [m.id for m in cluster], "dry_run": True})
                continue
            cluster.sort(key=lambda m: (-m.confidence, -m.use_count, m.created))
            survivor = cluster[0]
            drafted = _draft(drafter, f"Merge these {ntype} memories into one. Write the body from the source material, not from an earlier summary.", _source_bodies(store, cluster))
            tags = sorted({t for m in cluster for t in m.tags})
            episodes = sorted({e["to"] for m in cluster for e in model.node_edges(store, m.id) if e["type"] == "derived_from"})
            new = model.Node(
                id=db.ulid(),
                type=ntype,
                summary=drafted[0] if drafted else survivor.summary,
                body=drafted[1] if drafted else survivor.body,
                status="active",
                confidence=max(m.confidence for m in cluster),
                last_confirmed=max((m.last_confirmed or "" for m in cluster), default=None) or None,
                use_count=sum(m.use_count for m in cluster),
                success_count=sum(m.success_count for m in cluster),
                failure_count=sum(m.failure_count for m in cluster),
                provenance={
                    "author": "librarian",
                    "method": "consolidation",
                    "merged": [m.id for m in cluster],
                    "model": drafter.model if (drafter and drafted) else None,
                    "prompt_version": llm.PROMPT_VERSION,
                },
                project=survivor.project if all(m.project == survivor.project for m in cluster) else None,
                tags=tags,
            )
            model.insert_node(store, new)
            for ep in episodes:
                model.add_edge(store, new.id, ep, "derived_from", 1.0, {"by": "consolidation"})
            for m in cluster:
                model.supersede(store, new.id, m.id, {"reason": "merge", "by": "consolidation"})
            report["merged"].append({"id": new.id, "members": [m.id for m in cluster], "drafted": bool(drafted)})
    return report


def _generalize(store: db.Store, use_llm: bool, dry_run: bool) -> dict:
    report: dict = {"groups": [], "drafted": [], "skipped": None}
    skills = model.nodes_where(store, "type = 'skill' AND status = 'active'")
    general = [n for n in skills if "scope:general" in n.tags]
    pairs: dict[tuple[str, str], list[model.Node]] = {}
    for n in skills:
        if "scope:general" in n.tags:
            continue
        ts = sorted(t for t in n.tags if not t.startswith("project:") and not t.startswith("src:"))
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                pairs.setdefault((ts[i], ts[j]), []).append(n)
    drafter = llm.get_llm("draft", use_llm)
    for pair, members in sorted(pairs.items(), key=lambda kv: -len(kv[1])):
        if len(members) < GENERALIZE_MIN:
            continue
        if any(set(pair) <= set(g.tags) for g in general):
            continue
        report["groups"].append({"tags": list(pair), "members": [m.id for m in members]})
        if dry_run:
            continue
        if drafter is None:
            report["skipped"] = "skipped_no_model"
            continue
        drafted = _draft(
            drafter,
            "Write one general skill these specific skills are instances of; keep the specifics as examples.",
            "\n\n".join(f"[skill {m.id}] {m.summary}\n{m.body}" for m in members),
        )
        if not drafted:
            continue
        new = model.Node(
            id=db.ulid(),
            type="skill",
            summary=drafted[0],
            body=drafted[1],
            status="probationary",
            confidence=min(0.7, max(m.confidence for m in members)),
            provenance={
                "author": "librarian",
                "method": "consolidation",
                "generalized_from": [m.id for m in members],
                "model": drafter.model,
                "prompt_version": llm.PROMPT_VERSION,
            },
            tags=list(pair) + ["scope:general"],
        )
        model.insert_node(store, new)
        for m in members:
            model.add_edge(store, m.id, new.id, "part_of", 1.0, {"by": "consolidation"})
            for e in model.node_edges(store, m.id):
                if e["type"] == "derived_from":
                    model.add_edge(store, new.id, e["to"], "derived_from", 1.0, {"by": "consolidation"})
        general.append(new)
        report["drafted"].append(new.id)
    return report


def _disputes(store: db.Store, dry_run: bool) -> dict:
    report: dict = {"resolved": [], "queued": []}
    rows = store.q("SELECT from_id, to_id FROM edges WHERE type = 'contradicts'")
    seen = set()
    for r in rows:
        pair = tuple(sorted((r[0], r[1])))
        if pair in seen:
            continue
        seen.add(pair)
        a = model.get_node(store, pair[0], with_edges=False)
        b = model.get_node(store, pair[1], with_edges=False)
        if a is None or b is None or a.status not in model.LIVE_STATUSES or b.status not in model.LIVE_STATUSES:
            continue

        def dominates(x: model.Node, y: model.Node) -> bool:
            ge = x.created >= y.created and x.confidence >= y.confidence and x.use_count >= y.use_count
            gt = x.created > y.created or x.confidence > y.confidence or x.use_count > y.use_count
            return ge and gt

        winner = a if dominates(a, b) else b if dominates(b, a) else None
        if winner is None:
            qid = None
            if not dry_run:
                for n in (a, b):
                    if n.status != "disputed":
                        model.set_status(store, n.id, "disputed")
                qid = queue.enqueue(
                    store,
                    "dispute",
                    {"a": a.id, "b": b.id, "a_summary": a.summary, "b_summary": b.summary, "tags": sorted(set(a.tags) | set(b.tags))},
                    dedupe_key=f"dispute:{pair[0]}:{pair[1]}",
                )
            report["queued"].append({"pair": list(pair), "queue_id": qid})
            continue
        loser = b if winner is a else a
        if not dry_run:
            model.set_status(store, winner.id, "active")
            model.supersede(store, winner.id, loser.id, {"reason": "dispute", "by": "consolidation"})
        report["resolved"].append({"kept": winner.id, "superseded": loser.id})
    return report


def _confirming_projects(store: db.Store, node_id: str) -> set:
    rows = store.q(
        "SELECT DISTINCT n.project FROM credit_log c JOIN nodes n ON n.id = c.episode_id "
        "WHERE c.node_id = ? AND c.confirmed = 1 AND c.reversed_ts IS NULL AND n.project IS NOT NULL",
        (node_id,),
    )
    return {r[0] for r in rows}


def _promote(store: db.Store, dry_run: bool) -> dict:
    report: dict = {"preferences": [], "core_proposals": []}
    ref = db.now()
    # (a) retrospective confirmed in >= 2 other projects -> preference.
    for r in model.nodes_where(store, "type = 'retrospective' AND status = 'active'"):
        projects = _confirming_projects(store, r.id) - ({r.project} if r.project else set())
        if len(projects) < PROMOTE_PROJECTS:
            continue
        report["preferences"].append({"from": r.id, "projects": sorted(projects)})
        if dry_run:
            continue
        new = model.Node(
            id=db.ulid(),
            type="preference",
            summary=r.summary,
            body=r.body,
            status="probationary",
            confidence=r.confidence,
            provenance={"author": "librarian", "method": "promotion", "from": r.id, "projects": sorted(projects)},
            tags=[t for t in r.tags if not t.startswith("project:")] or ["team:observed"],
        )
        model.insert_node(store, new)
        model.add_edge(store, new.id, r.id, "derived_from", 1.0, {"by": "promotion"})
        model.add_edge(store, r.id, new.id, "informed", 1.0, {"by": "promotion"})
        model.set_status(store, r.id, "archived", reason=f"promoted:{new.id}")
        report["preferences"][-1]["id"] = new.id
    # (b) stable preference / (c) stable working identity -> core proposal.
    for n in model.nodes_where(store, "type IN ('preference','identity_working') AND status = 'active'"):
        age = db.age_days(n.created, ref) or 0.0
        if age < STABLE_DAYS:
            continue
        if store.q1("SELECT 1 FROM edges WHERE type = 'contradicts' AND (from_id = ? OR to_id = ?)", (n.id, n.id)):
            continue
        if n.type == "identity_working":
            if len(_confirming_projects(store, n.id)) < 3:
                continue
            if store.q1("SELECT 1 FROM identity_edits WHERE node_id = ? AND reverted_ts IS NOT NULL", (n.id,)):
                continue
        evidence = [r[0] for r in store.q("SELECT DISTINCT episode_id FROM credit_log WHERE node_id = ? AND confirmed = 1 AND reversed_ts IS NULL", (n.id,))]
        if dry_run:
            report["core_proposals"].append({"source": n.id})
            continue
        qid = queue.enqueue(
            store,
            "core_proposal",
            {"summary": n.summary, "body": n.body, "source": n.id, "source_type": n.type, "evidence": evidence, "tags": n.tags},
            dedupe_key=f"core:{n.id}",
        )
        if qid:
            report["core_proposals"].append({"source": n.id, "queue_id": qid})
    return report


def _co_retrieved(store: db.Store, dry_run: bool) -> dict:
    rows = store.q("SELECT episode_id, node_id FROM citations ORDER BY episode_id")
    by_ep: dict[str, list[str]] = {}
    for r in rows:
        by_ep.setdefault(r[0], []).append(r[1])
    counts: dict[tuple[str, str], int] = {}
    for ids in by_ep.values():
        ids = sorted(set(ids))
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                counts[(ids[i], ids[j])] = counts.get((ids[i], ids[j]), 0) + 1
    report = {"pairs": len(counts), "upserted": 0, "pruned": 0}
    if dry_run:
        return report
    keep = set()
    for (a, b), c in counts.items():
        w = 1 - 0.75**c
        if w < CO_RETRIEVED_FLOOR:
            continue
        keep.add((a, b))
        keep.add((b, a))
        model.add_edge(store, a, b, "co_retrieved", round(w, 3), {"by": "retrieval_log", "count": c})
        model.add_edge(store, b, a, "co_retrieved", round(w, 3), {"by": "retrieval_log", "count": c})
        report["upserted"] += 1
    for r in store.q("SELECT from_id, to_id, provenance FROM edges WHERE type = 'co_retrieved'"):
        prov = r["provenance"] or ""
        if '"retrieval_log"' in prov and (r["from_id"], r["to_id"]) not in keep:
            model.remove_edge(store, r["from_id"], r["to_id"], "co_retrieved")
            report["pruned"] += 1
    return report


def _reembed(store: db.Store, dry_run: bool) -> dict:
    provider = llm.embed_provider()
    rows = store.q(
        "SELECT n.id, n.summary FROM nodes n LEFT JOIN embeddings e ON e.node_id = n.id "
        "WHERE n.status IN ('active','probationary') AND (e.node_id IS NULL OR e.model != ?)",
        (provider.name,),
    )
    if provider.name == "none":
        return {"pending": len(rows), "skipped": "skipped_no_provider"}
    if dry_run:
        return {"pending": len(rows)}
    vectors = provider.embed([r[1] for r in rows]) or []
    done = 0
    for r, v in zip(rows, vectors):
        store.ex(
            "INSERT INTO embeddings(node_id, model, dim, vector, created) VALUES (?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET model = excluded.model, dim = excluded.dim, vector = excluded.vector, created = excluded.created",
            (r[0], provider.name, len(v) // 4, v, db.now_iso()),
        )
        done += 1
    return {"embedded": done}


def consolidate(store: db.Store, only: Optional[list[str]] = None, dry_run: bool = False, use_llm: bool = True) -> dict:
    steps = [s for s in STEPS if not only or s in only]
    out: dict = {"steps": {}, "dry_run": dry_run}
    for step in steps:
        with store.write():
            if step == "merge":
                rep = _merge(store, use_llm, dry_run)
            elif step == "generalize":
                rep = _generalize(store, use_llm, dry_run)
            elif step == "disputes":
                rep = _disputes(store, dry_run)
            elif step == "promote":
                rep = _promote(store, dry_run)
            elif step == "co_retrieved":
                rep = _co_retrieved(store, dry_run)
            else:
                rep = _reembed(store, dry_run)
            if not dry_run:
                _log(store, step, rep)
        out["steps"][step] = rep
    flagged = [r[0] for r in store.q("SELECT id FROM nodes WHERE review_flag IS NOT NULL AND status IN ('active','probationary','disputed')")]
    out["needs_review"] = flagged
    return out
