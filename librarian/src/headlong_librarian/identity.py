"""The two-tier identity, the human check-in queue decisions, and probes.

Core nodes change only through the queue (a human approves). Working nodes
are the agent's own to revise within bounds: a size cap, a rate limit per
occasion, no contradiction with core, reversible by status flip.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from . import db, gate, llm, model, queue, triggers

WORKING_MAX_TOKENS = 300
WORKING_MAX_NODES = 10
CORE_MAX_NODES = 10
HELD_OVERLAP = 0.4
OCCASIONS = ("weekly", "project-close", "failure-trigger", "human")
PROBE_DRIFT_DEFAULT = 0.3


def list_identity(store: db.Store, tier: Optional[str] = None, history: bool = False) -> list[model.Node]:
    types = {"core": ("identity_core",), "working": ("identity_working",)}.get(tier or "", model.IDENTITY_TYPES)
    statuses = model.STATUSES if history else model.LIVE_STATUSES
    tm = ",".join("?" for _ in types)
    sm = ",".join("?" for _ in statuses)
    return model.nodes_where(store, f"type IN ({tm}) AND status IN ({sm}) ORDER BY type, created", (*types, *statuses))


def working_budget(store: db.Store) -> tuple[int, int]:
    nodes = [n for n in list_identity(store, "working") if n.status != "superseded"]
    return sum(model.estimate_tokens(n.body or n.summary) for n in nodes), len(nodes)


def identity_hash(store: db.Store) -> str:
    text = "\n".join(f"{n.id}:{n.body or n.summary}" for n in list_identity(store))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── seeding and core proposals ───────────────────────────────────────────────


def parse_blocks(text: str) -> list[dict]:
    """``### slug`` blocks (body below) or ``- `` bullets, from a seed file."""
    blocks: list[dict] = []
    cur: Optional[dict] = None
    for line in text.splitlines():
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            if cur and cur["body"].strip():
                blocks.append(cur)
            cur = {"slug": m.group(1).strip(), "body": ""}
            continue
        if cur is not None:
            cur["body"] += line + "\n"
        elif line.startswith("- "):
            blocks.append({"slug": "", "body": line[2:].strip() + "\n"})
    if cur and cur["body"].strip():
        blocks.append(cur)
    return blocks


def seed_core(store: db.Store, text: str, author: str = "human", tags: Optional[list[str]] = None) -> list[dict]:
    results = []
    for b in parse_blocks(text):
        body = b["body"].strip()
        summary = model.first_sentence(body)[:240] or body[:240]
        cand = gate.Candidate(
            type="identity_core",
            summary=summary,
            body=body,
            tags=(tags or []) + ["scope:identity"],
            provenance={"author": author, "method": "import", "slug": b["slug"]},
            confidence=0.9,
            status="active" if author == "human" else None,
        )
        res = gate.apply(store, cand)
        results.append({"slug": b["slug"], **res.to_dict()})
    return results


def propose_core(store: db.Store, summary: str, body: str, tags: list[str], evidence: list[str], by: str = "main") -> Optional[str]:
    with store.write():
        return queue.enqueue(
            store,
            "core_proposal",
            {"summary": summary, "body": body, "tags": tags, "evidence": evidence, "proposed_by": by},
            dedupe_key="core:" + hashlib.sha1(summary.lower().encode()).hexdigest()[:12],
        )


# ── working-identity edits ───────────────────────────────────────────────────


def contradicts_core(store: db.Store, text: str, use_llm: bool = True) -> tuple[bool, Optional[str], str]:
    """Escalation: heuristic → fast judge → main model when unsure → (caller queues)."""
    core = list_identity(store, "core")
    heuristic_hit = None
    for n in core:
        if triggers.heuristic_contradiction(text, n.body or n.summary):
            heuristic_hit = n
            break
    for role in ("judge", "core-check"):
        m = llm.get_llm(role, use_llm)
        if m is None:
            continue
        listing = "\n".join(f"{n.id}: {n.body or n.summary}" for n in core)
        ans = m.complete(
            f"Core commitments:\n{listing}\n\nProposed working rule:\n{text}\n\n"
            'Does the proposed rule contradict any core commitment? Answer JSON {"contradicts": true|false|"unsure", "core_id": "<id or null>"}.',
            system="You check an agent's self-model for internal contradictions. Answer with one JSON object only.",
            max_tokens=60,
        )
        parsed = llm.parse_json_lenient(ans)
        if isinstance(parsed, dict) and parsed.get("contradicts") in (True, False):
            cid = parsed.get("core_id")
            if parsed["contradicts"]:
                return True, (str(cid) if cid else (heuristic_hit.id if heuristic_hit else None)), role
            return False, None, role
        # unsure or unparsable → escalate to the next role
    if heuristic_hit is not None:
        return True, heuristic_hit.id, "heuristic"
    return False, None, "heuristic"


def _refused(reason: str, detail: str, extra: Optional[dict] = None) -> gate.GateResult:
    r = gate.GateResult(False, "refused", reasons=[detail])
    r.notes.append(f"refused_reason={reason}")
    r.status = reason
    if extra:
        r.notes.append(json.dumps(extra))
    return r


def edit_working(
    store: db.Store,
    summary: str,
    body: str,
    *,
    occasion: str,
    occasion_key: str,
    reason: str,
    episodes: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    project: Optional[str] = None,
    trigger_id: Optional[str] = None,
    supersedes: Optional[str] = None,
    use_llm: bool = True,
    dry_run: bool = False,
) -> gate.GateResult:
    if occasion not in OCCASIONS:
        return _refused("bad_occasion", f"occasion must be one of {', '.join(OCCASIONS)}")
    text = (body or summary).strip()
    with store.write():
        # 1. rate limit
        if occasion != "human":
            if occasion == "failure-trigger":
                if not trigger_id:
                    return _refused("rate_limit", "a failure-trigger edit needs --trigger-id of an accepted repeated-failure suggestion")
                s = store.q1("SELECT * FROM suggestions WHERE id = ?", (trigger_id,))
                if s is None or s["trigger"] != "repeated_failure" or s["response"] != "accept" or s["consumed_by"]:
                    return _refused("rate_limit", f"suggestion {trigger_id} is not an accepted, unused repeated-failure suggestion")
                occasion_key = trigger_id
            prior = store.q1(
                "SELECT node_id FROM identity_edits WHERE occasion = ? AND occasion_key = ? AND reverted_ts IS NULL",
                (occasion, occasion_key),
            )
            if prior is not None:
                return _refused("rate_limit", f"one working-identity edit per {occasion} ({occasion_key}) already made: {prior[0]}")
        # 2. bound
        tokens, count = working_budget(store)
        old = model.get_node(store, supersedes, with_edges=False) if supersedes else None
        if supersedes and (old is None or old.type != "identity_working" or old.status not in model.LIVE_STATUSES):
            return _refused("bad_supersedes", f"--supersedes {supersedes} is not a live working-identity node")
        new_tokens = tokens + model.estimate_tokens(text) - (model.estimate_tokens(old.body or old.summary) if old else 0)
        new_count = count + (0 if old else 1)
        if new_tokens > WORKING_MAX_TOKENS or new_count > WORKING_MAX_NODES:
            current = [{"id": n.id, "summary": n.summary} for n in list_identity(store, "working")]
            return _refused(
                "over_bound",
                f"working identity would be {new_tokens} tokens in {new_count} nodes (limit {WORKING_MAX_TOKENS}/{WORKING_MAX_NODES}); supersede one with --supersedes",
                {"current": current},
            )
        # 3. core check
        hit, core_id, method = contradicts_core(store, text, use_llm)
        if hit:
            qid = queue.enqueue(
                store,
                "working_conflict",
                {"summary": summary, "body": body, "core_id": core_id, "method": method, "reason": reason, "project": project, "tags": tags or []},
                dedupe_key="wc:" + hashlib.sha1(text.lower().encode()).hexdigest()[:12],
            )
            r = _refused("contradicts_core", f"the edit contradicts core node {core_id} ({method}); queued for a human")
            if qid:
                r.queued.append(qid)
            return r
        # 4. held behind a pending core proposal
        for item in queue.list_items(store, "pending", "core_proposal"):
            ps = (item.get("payload") or {}).get("summary", "")
            if model.jaccard(model.tokenize(ps + " " + (item.get("payload") or {}).get("body", "")), model.tokenize(text)) >= HELD_OVERLAP:
                qid = queue.enqueue(
                    store,
                    "held_working_edit",
                    {"summary": summary, "body": body, "core_proposal": item["id"], "reason": reason, "project": project, "tags": tags or []},
                    dedupe_key="held:" + hashlib.sha1(text.lower().encode()).hexdigest()[:12],
                )
                r = _refused("held_pending_core", f"this behavior is under core review ({item['id']}); the edit is held")
                if qid:
                    r.queued.append(qid)
                return r
        if dry_run:
            return gate.GateResult(True, "dry-run", notes=["all checks passed"])
        # 5. the gate
        cand = gate.Candidate(
            type="identity_working",
            summary=summary,
            body=body,
            tags=(tags or []) + ["scope:identity"],
            provenance={"author": "main", "method": "identity-edit", "episodes": episodes or [], "reason": reason, "source": reason},
            confidence=0.6,
            supersedes=supersedes,
            project=project,
        )
        res = gate.apply(store, cand)
        if res.accepted and res.id:
            store.ex(
                "INSERT INTO identity_edits(node_id, occasion, project, occasion_key, trigger_id, superseded_id, ts, reason) VALUES (?,?,?,?,?,?,?,?)",
                (res.id, occasion, project, occasion_key, trigger_id, supersedes, db.now_iso(), reason),
            )
            if trigger_id:
                store.ex("UPDATE suggestions SET consumed_by = ? WHERE id = ?", (res.id, trigger_id))
        return res


def revert(store: db.Store, node_id: str, reason: str) -> dict:
    """Undo a working-identity edit: the node is superseded again, the one it replaced comes back."""
    with store.write():
        n = model.get_node(store, node_id)
        if n is None or n.type != "identity_working":
            raise ValueError(f"{node_id} is not a working-identity node")
        ts = db.now_iso()
        restored = None
        for e in n.edges:
            if e["type"] == "supersedes":
                restored = e["to"]
                store.ex("UPDATE nodes SET status = 'active', known_to = NULL WHERE id = ?", (restored,))
        store.ex("UPDATE nodes SET status = 'superseded', known_to = ? WHERE id = ?", (ts, node_id))
        store.ex("UPDATE identity_edits SET reverted_ts = ?, reason = COALESCE(reason, '') || ' | reverted: ' || ? WHERE node_id = ?", (ts, reason, node_id))
        qid = queue.enqueue(store, "reversion_note", {"node_id": node_id, "restored": restored, "reason": reason}, dedupe_key=f"rev:{node_id}")
        return {"reverted": node_id, "restored": restored, "queue_id": qid}


# ── queue decisions ──────────────────────────────────────────────────────────


def decide(store: db.Store, qid: str, decision: str, note: Optional[str] = None) -> dict:
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve or reject")
    with store.write():
        item = queue.get_item(store, qid)
        if item is None:
            raise KeyError(qid)
        if item["status"] != "pending":
            return {"id": qid, "status": item["status"], "note": "already decided"}
        payload = item["payload"] if isinstance(item["payload"], dict) else {}
        kind = item["kind"]
        effects: dict = {}
        if decision == "approve":
            if kind == "core_proposal":
                cand = gate.Candidate(
                    type="identity_core",
                    summary=payload.get("summary", ""),
                    body=payload.get("body", ""),
                    tags=[t for t in (payload.get("tags") or []) if not t.startswith("project:")] + ["scope:identity"],
                    provenance={"author": "human", "method": "core-approval", "queue": qid, "evidence": payload.get("evidence", []), "source": payload.get("source")},
                    confidence=0.9,
                    status="active",
                )
                res = gate.apply(store, cand)
                effects["core"] = res.to_dict()
                src = payload.get("source")
                if res.accepted and res.id and src and payload.get("source_type") == "identity_working":
                    model.supersede(store, res.id, src, {"reason": "promoted to core", "by": "human"})
                    effects["superseded_working"] = src
                for held in queue.list_items(store, "pending", "held_working_edit"):
                    if (held.get("payload") or {}).get("core_proposal") == qid:
                        queue.mark(store, held["id"], "rejected", "core proposal approved; the behavior is now core")
                        effects.setdefault("rejected_held", []).append(held["id"])
            elif kind in ("working_conflict", "held_working_edit"):
                res = edit_working(
                    store,
                    payload.get("summary", ""),
                    payload.get("body", ""),
                    occasion="human",
                    occasion_key=qid,
                    reason=f"approved by a human in queue item {qid}",
                    tags=payload.get("tags") or [],
                    project=payload.get("project"),
                    use_llm=False,
                )
                effects["working"] = res.to_dict()
            elif kind == "dispute":
                keep = (note or "").strip().upper() or payload.get("keep")
                a, b = payload.get("a"), payload.get("b")
                keep_id = model.resolve_id(store, keep) if keep else None
                if keep_id not in (a, b):
                    raise ValueError("approve a dispute with --note <id to keep>")
                loser = b if keep_id == a else a
                model.set_status(store, keep_id, "active")
                model.supersede(store, keep_id, loser, {"reason": "dispute decided by a human", "by": "human"})
                effects["kept"] = keep_id
                effects["superseded"] = loser
            elif kind == "new_area_tag":
                store.ex("UPDATE tag_vocab SET status = 'active' WHERE tag = ?", (payload.get("tag"),))
                effects["tag"] = payload.get("tag")
        else:
            if kind == "new_area_tag":
                store.ex("UPDATE tag_vocab SET status = 'rejected' WHERE tag = ?", (payload.get("tag"),))
            elif kind == "core_proposal":
                effects["unblocked_held"] = [
                    h["id"] for h in queue.list_items(store, "pending", "held_working_edit") if (h.get("payload") or {}).get("core_proposal") == qid
                ]
        queue.mark(store, qid, "approved" if decision == "approve" else "rejected", note)
        return {"id": qid, "kind": kind, "decision": decision, "effects": effects}


# ── probes ───────────────────────────────────────────────────────────────────


def parse_probes(text: str) -> list[dict]:
    out = []
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if s.startswith("- ") or re.match(r"^\d+[.)]\s", s):
            out.append({"id": f"p{len(out) + 1:02d}", "prompt": re.sub(r"^(- |\d+[.)]\s)", "", s)})
    return out


def run_probes(store: db.Store, text: str, use_llm: bool = True) -> dict:
    probes = parse_probes(text)
    ident = list_identity(store)
    system = "You are this agent. Your identity, verbatim:\n" + "\n".join(f"- {n.body or n.summary}" for n in ident) + "\nAnswer in two or three sentences, in the first person."
    run_id = "R" + db.ulid()[-8:]
    h = identity_hash(store)
    m = llm.get_llm("probe-answer", use_llm)
    results = []
    with store.write():
        for p in probes:
            answer = m.complete(p["prompt"], system=system, max_tokens=200) if m is not None else None
            store.ex(
                "INSERT INTO probes(run_id, probe_id, prompt, answer, identity_hash, model, ts) VALUES (?,?,?,?,?,?,?)",
                (run_id, p["id"], p["prompt"], answer, h, m.model if m else None, db.now_iso()),
            )
            results.append({"id": p["id"], "status": "answered" if answer else "skipped"})
    return {"run_id": run_id, "identity_hash": h, "probes": results, "model": m.model if m else None}


def compare_probes(store: db.Store, run_id: Optional[str] = None, against: Optional[str] = None, threshold: float = PROBE_DRIFT_DEFAULT, use_llm: bool = True) -> dict:
    runs = [r[0] for r in store.q("SELECT run_id FROM probes GROUP BY run_id ORDER BY MIN(ts) DESC")]
    if run_id is None and runs:
        run_id = runs[0]
    if against is None:
        later = [r for r in runs if r != run_id]
        against = later[0] if later else None
    if run_id is None or against is None:
        return {"run_id": run_id, "against": against, "drift": [], "mean": None, "note": "need two probe runs"}
    cur = {r["probe_id"]: db.row_dict(r) for r in store.q("SELECT * FROM probes WHERE run_id = ?", (run_id,))}
    prev = {r["probe_id"]: db.row_dict(r) for r in store.q("SELECT * FROM probes WHERE run_id = ?", (against,))}
    judge = llm.get_llm("judge", use_llm)
    drift = []
    for pid, c in cur.items():
        p = prev.get(pid)
        if not p or not c["answer"] or not p["answer"]:
            continue
        score = 1.0 - model.jaccard(model.tokenize(c["answer"]), model.tokenize(p["answer"]))
        if judge is not None:
            ans = judge.complete(
                f"Question: {c['prompt']}\nEarlier answer: {p['answer']}\nLater answer: {c['answer']}\nRate how much the stance changed, JSON {{\"drift\": 0-3}} (0 same stance, 3 reversed).",
                system="Answer with one JSON object only.",
                max_tokens=30,
            )
            parsed = llm.parse_json_lenient(ans)
            if isinstance(parsed, dict) and str(parsed.get("drift", "")).strip().isdigit():
                score = int(parsed["drift"]) / 3.0
        drift.append({"probe": pid, "drift": round(score, 3), "flag": score > threshold})
    mean = round(sum(d["drift"] for d in drift) / len(drift), 3) if drift else None
    suspects = []
    if drift and prev and cur:
        t0 = min(p["ts"] for p in prev.values())
        t1 = max(c["ts"] for c in cur.values())
        suspects = [r[0] for r in store.q("SELECT node_id FROM identity_edits WHERE ts > ? AND ts <= ? AND reverted_ts IS NULL", (t0, t1))]
    return {"run_id": run_id, "against": against, "drift": drift, "mean": mean, "threshold": threshold, "suspects": suspects, "flagged": any(d["flag"] for d in drift)}


def revert_drift(store: db.Store, report: dict) -> list[dict]:
    out = []
    if not report.get("flagged"):
        return out
    for nid in report.get("suspects", []):
        try:
            out.append(revert(store, nid, f"probe drift {report.get('mean')} in run {report.get('run_id')}"))
        except ValueError:
            continue
    with store.write():
        queue.enqueue(store, "probe_drift", {"run_id": report.get("run_id"), "mean": report.get("mean"), "reverted": [o["reverted"] for o in out]}, dedupe_key=f"drift:{report.get('run_id')}")
    return out
