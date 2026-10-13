"""The ``librarian`` command line.

JSON on stdout by default; ``--text`` renders for a model or a person.
Exit codes: 0 ok, 1 error, 2 usage or no store, 3 gate rejected, 4 not
found, 5 refused (rate limit, bound, core conflict, held), 6 store busy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from . import __version__, db, exchange, gate, identity, lifecycle, model, pack, queue, recall, triggers

EXIT_OK, EXIT_ERR, EXIT_USAGE, EXIT_REJECTED, EXIT_NOTFOUND, EXIT_REFUSED, EXIT_BUSY = 0, 1, 2, 3, 4, 5, 6


class Out:
    def __init__(self, text: bool, quiet: bool):
        self.text = text
        self.quiet = quiet

    def emit(self, obj: Any, render=None) -> None:
        if self.quiet:
            return
        if self.text and render is not None:
            sys.stdout.write(render(obj).rstrip("\n") + "\n")
        else:
            sys.stdout.write(json.dumps(obj, indent=None if self.text else 2) + "\n")

    def error(self, msg: str, code: int) -> int:
        print(f"librarian: {msg}", file=sys.stderr)
        if not self.text:
            sys.stdout.write(json.dumps({"error": msg, "code": code}) + "\n")
        return code


def _store(args, create: bool = False) -> db.Store:
    path = Path(args.store) if getattr(args, "store", None) else None
    return db.Store.open(path, create=create)


def _read_body(args) -> str:
    if getattr(args, "body_file", None):
        return Path(args.body_file).read_text()
    b = getattr(args, "body", None)
    if b == "-":
        return sys.stdin.read()
    return b or ""


def _provenance(args, default_author: str = "main") -> dict:
    prov: dict = {}
    raw = getattr(args, "provenance", None)
    if raw:
        prov = json.loads(raw)
    prov.setdefault("author", getattr(args, "author", None) or default_author)
    if getattr(args, "episode", None):
        prov["episode"] = args.episode
    if getattr(args, "source", None):
        prov["source"] = args.source
    return prov


def _parse_edges(raw: Optional[list[str]]) -> list[dict]:
    out = []
    for e in raw or []:
        parts = e.split(":")
        if len(parts) < 2:
            raise ValueError(f"bad --edge {e}; want TYPE:TO[:WEIGHT] or TYPE:tag:ns:free[:WEIGHT]")
        etype = parts[0]
        if parts[1] == "tag" and len(parts) >= 4:
            to = "tag:" + parts[2] + ":" + parts[3]
            w = float(parts[4]) if len(parts) > 4 else 1.0
        else:
            to = parts[1]
            w = float(parts[2]) if len(parts) > 2 else 1.0
        out.append({"type": etype, "to": to, "weight": w})
    return out


def _request_file() -> Optional[Path]:
    ident = os.environ.get("IDENTITY_DIR", "").strip()
    return (Path(ident) / "run" / "librarian_request.json") if ident else None


def _current_request() -> dict:
    p = _request_file()
    if p is None:
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _covered_by_pack(store: db.Store, project: Optional[str], tags: list[str]) -> Optional[int]:
    last = store.q1("SELECT coverage FROM requests WHERE kind = 'pack' AND project IS ? ORDER BY ts DESC LIMIT 1", (project,))
    if last is None or not tags:
        return None
    try:
        cov = {c.lstrip("+") for c in json.loads(last[0] or "[]")}
    except ValueError:
        return None
    return 1 if set(tags) <= cov else 0


# ── renderers ────────────────────────────────────────────────────────────────


def _marks(status: str, tags: list[str]) -> list[str]:
    m = []
    if status == "probationary":
        m.append("PROBATIONARY")
    elif status == "disputed":
        m.append("DISPUTED")
    if "src:untrusted" in tags:
        m.append("UNTRUSTED")
    return m


def _r_search(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        marks = _marks(r["status"], r["tags"])
        conf = f"conf {r['confidence']:.2f}" + (f", confirmed {r['last_confirmed'][:10]}" if r.get("last_confirmed") else "")
        lines.append(f"{r['id']} · {r['type']} · " + (" · ".join(marks) + " · " if marks else "") + " ".join(r["tags"]) + f" · {r['summary']} ({conf})")
    return "\n".join(lines) if lines else "(no matches)"


def _r_fetch(rows: list[dict]) -> str:
    out = []
    for r in rows:
        out.append(f"── {r['id']} · {r['type']} · {r['status']} · {' '.join(r['tags'])}\n{r['summary']}\n\n{r['body']}" + ("\n[TRUNCATED]" if r["truncated"] else ""))
    return "\n\n".join(out)


def _r_gate(d: dict) -> str:
    if d["action"] == "rejected":
        return "rejected:\n- " + "\n- ".join(d["reasons"])
    if d["action"] == "merged":
        return f"merged into {d['merge_target']}" + (f" ({'; '.join(d['notes'])})" if d["notes"] else "")
    if d["action"] == "refused":
        return "refused: " + "; ".join(d["reasons"])
    if d["action"] == "dry-run":
        return "ok: " + "; ".join(d["notes"])
    return f"{d['action']} {d['id']} ({d['status']})" + ("\n- " + "\n- ".join(d["notes"]) if d["notes"] else "")


def _r_kv(d: dict) -> str:
    return "\n".join(f"{k}: {json.dumps(v) if isinstance(v, (dict, list)) else v}" for k, v in d.items())


def _r_json(d) -> str:
    return json.dumps(d, indent=2)


def _r_identity(d: dict) -> str:
    lines = [f"working: {d['working_tokens']} tokens in {d['working_count']} nodes (limit {identity.WORKING_MAX_TOKENS}/{identity.WORKING_MAX_NODES})"]
    for n in d["nodes"]:
        lines.append(f"- {n['id']} · {n['type']} · {n['status']} · {n['body'] or n['summary']}")
    return "\n".join(lines)


def _r_queue(items: list[dict]) -> str:
    if not items:
        return "(queue empty)"
    out = []
    for i in items:
        p = i.get("payload") or {}
        what = str(p.get("summary") or p.get("tag") or p.get("a") or p.get("node_id") or "")[:100]
        out.append(f"{i['id']} · {i['kind']} · {i['status']} · {what}")
    return "\n".join(out)


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_init(args, out: Out) -> int:
    store = _store(args, create=True)
    with store.write():
        model.seed_vocab(store)
        store.meta_set("identity", os.environ.get("IDENTITY_NAME", ""))
    reports: dict = {"store": str(store.path), "fts_mode": store.fts_mode}
    for f in args.seed or []:
        p = Path(f)
        if p.suffix == ".json":
            reports.setdefault("imported", []).append(exchange.import_json(store, p, "human", None, False).to_dict())
        else:
            reports.setdefault("core", []).extend(identity.seed_core(store, p.read_text()))
    if args.import_skills:
        d = Path(args.import_skills)
        rep = exchange.ImportReport()
        for sub, generic in (("project", False), ("generic", True)):
            if (d / sub).is_dir():
                r = exchange.import_skills(store, d / sub, args.project, generic)
                rep.stored += r.stored
                rep.merged += r.merged
                rep.rejected += r.rejected
        reports["skills"] = rep.to_dict()
    if args.import_addenda:
        reports["addenda"] = exchange.import_addenda(store, Path(args.import_addenda), args.project).to_dict()
    out.emit(reports, lambda d: f"store ready at {d['store']} (text search: {d['fts_mode']})")
    return EXIT_OK


def cmd_propose(args, out: Out) -> int:
    store = _store(args)
    try:
        edges = _parse_edges(args.edge)
    except ValueError as exc:
        return out.error(str(exc), EXIT_USAGE)
    supersedes = None
    if args.supersedes:
        supersedes = model.resolve_id(store, args.supersedes)
        if supersedes is None:
            return out.error(f"no node matches {args.supersedes}", EXIT_NOTFOUND)
    cand = gate.Candidate(
        type=args.type,
        summary=args.summary,
        body=_read_body(args),
        tags=model.parse_tags(args.tags or []),
        provenance=_provenance(args),
        confidence=args.confidence,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
        supersedes=supersedes,
        project=args.project or _current_request().get("project"),
        untrusted=args.untrusted,
        status=args.status,
        edges=edges,
    )
    if args.dry_run:
        reasons = gate.check(store, cand)
        dups = gate.find_near_duplicates(store, cand)
        res = {"accepted": not reasons, "action": "dry-run", "reasons": reasons, "near_duplicates": [{"id": d[0], "summary": d[1], "body": d[2]} for d in dups[:3]]}
        out.emit(res, lambda d: ("ok" if d["accepted"] else "would reject:\n- " + "\n- ".join(d["reasons"])) + (f"\nnear duplicates: {', '.join(x['id'] for x in d['near_duplicates'])}" if d["near_duplicates"] else ""))
        return EXIT_OK if not reasons else EXIT_REJECTED
    res = gate.apply(store, cand)
    out.emit(res.to_dict(), _r_gate)
    return EXIT_OK if res.accepted else EXIT_REJECTED


def cmd_search(args, out: Out) -> int:
    store = _store(args)
    tags = model.parse_tags(args.tags or [])
    proj = args.project or _current_request().get("project")
    q = recall.Query(task=args.text or "", tags=tags, project=proj, type=args.type, include_probationary=not args.no_probationary, include_history=args.history)
    if not tags and not args.text:
        scope = recall.status_scope(q)
        where = "status IN (" + ",".join("?" for _ in scope) + ")"
        params: list = list(scope)
        if args.type:
            where += " AND type = ?"
            params.append(args.type)
        nodes = model.nodes_where(store, where + " ORDER BY created DESC", tuple(params))
        cands = [recall.Candidate(n) for n in nodes]
    else:
        _, cands = recall.recall(store, q, cap=max(args.limit * 5, 50))
    if args.project:
        cands = [c for c in cands if c.node.project in (args.project, None)]
    rows = []
    for c in cands[: args.limit]:
        n = c.node
        rows.append({"id": n.id, "type": n.type, "status": n.status, "tags": n.tags, "summary": n.summary, "confidence": round(n.confidence, 3), "last_confirmed": n.last_confirmed, "score": round(c.tag_score + c.bm25_norm + 0.5 * c.hop, 3)})
    if not args.no_log:
        rid = db.ulid()
        ts = db.now_iso()
        with store.write():
            store.ex(
                "INSERT INTO requests(request_id, kind, project, task, tags, covered_by_pack, ts) VALUES (?,?,?,?,?,?,?)",
                (rid, "search", proj, (args.text or "")[:2000], json.dumps(tags), _covered_by_pack(store, proj, tags), ts),
            )
            for i, r in enumerate(rows, start=1):
                store.ex("INSERT INTO retrieval_log(request_id, node_id, source, rank, score, project, ts) VALUES (?,?,?,?,?,?,?)", (rid, r["id"], "search", i, r["score"], proj, ts))
    out.emit(rows, _r_search)
    return EXIT_OK


def cmd_fetch(args, out: Out) -> int:
    store = _store(args)
    budget = args.budget
    rows = []
    missing = []
    used = 0
    for ref in args.ids:
        nid = model.resolve_id(store, ref)
        n = model.get_node(store, nid) if nid else None
        if n is None:
            missing.append(ref)
            continue
        body = n.body
        truncated = False
        if budget is not None:
            remaining = budget - used
            if remaining <= 0:
                body, truncated = "", True
            elif model.estimate_tokens(body) > remaining:
                body = pack.first_chunk(store, n, max(1, remaining - 10))
                truncated = True
        rows.append({"id": n.id, "type": n.type, "status": n.status, "tags": n.tags, "summary": n.summary, "body": body, "truncated": truncated, "tokens": model.estimate_tokens(body), "confidence": round(n.confidence, 3), "edges": n.edges})
        used += model.estimate_tokens(body)
    if not args.no_log and rows:
        cur = _current_request()
        rid = args.request or cur.get("request_id")
        proj = args.project or cur.get("project")
        ts = db.now_iso()
        with store.write():
            frid = db.ulid()
            ftags = sorted({t for r in rows for t in r["tags"] if not t.startswith("project:")})
            store.ex(
                "INSERT INTO requests(request_id, kind, project, tags, budget, used_tokens, covered_by_pack, ts) VALUES (?,?,?,?,?,?,?,?)",
                (frid, "fetch", proj, json.dumps(ftags), budget, used, _covered_by_pack(store, proj, ftags), ts),
            )
            for r in rows:
                store.ex("INSERT INTO retrieval_log(request_id, node_id, source, project, ts) VALUES (?,?,?,?,?)", (rid or frid, r["id"], "fetch", proj, ts))
                store.ex("UPDATE nodes SET last_used = ? WHERE id = ?", (ts, r["id"]))
    out.emit(rows, _r_fetch)
    if missing:
        print(f"librarian: not found: {', '.join(missing)}", file=sys.stderr)
        return EXIT_NOTFOUND
    return EXIT_OK


def cmd_pack(args, out: Out) -> int:
    store = _store(args)
    req = pack.PackRequest(task=args.task, tags=model.parse_tags(args.tags or []), project=args.project, phase=args.phase, budget=args.budget, exclude_ids=model.parse_ids(args.exclude or []), log=not args.no_log, use_llm=not args.no_llm)
    pk = pack.build(store, req)
    out.emit(pack.render_json(pk), lambda d: d["text"])
    return EXIT_OK


def cmd_show(args, out: Out) -> int:
    store = _store(args)
    nid = model.resolve_id(store, args.id)
    n = model.get_node(store, nid) if nid else None
    if n is None:
        return out.error(f"no node {args.id}", EXIT_NOTFOUND)
    d = n.to_json()
    if args.history:
        d["supersedes_chain"] = model.supersession_chain(store, n.id)
        d["superseded_by"] = [e["from"] for e in model.edges_to(store, n.id, ("supersedes",))]
    out.emit(d, lambda d: exchange.node_markdown(n))
    return EXIT_OK


def cmd_episode(args, out: Out) -> int:
    store = _store(args)
    if args.episode_cmd != "close":
        return out.error("episode: use `episode close`", EXIT_USAGE)
    try:
        rep = lifecycle.close_episode(
            store,
            outcome=args.outcome,
            criterion=args.criterion or "",
            episode_id=model.resolve_id(store, args.id) if args.id else None,
            summary=args.summary or "",
            body=_read_body(args),
            tags=model.parse_tags(args.tags or []),
            project=args.project,
            phase=args.phase,
            cited=model.parse_ids(args.cite or []),
            request_ids=model.parse_ids(args.request or []),
            helpful=model.parse_ids(args.helpful or []),
            provenance=_provenance(args, "runtime"),
        )
    except ValueError as exc:
        return out.error(str(exc), EXIT_USAGE)
    out.emit(rep.to_dict(), _r_kv)
    return EXIT_OK


def cmd_outcome(args, out: Out) -> int:
    store = _store(args)
    eid = model.resolve_id(store, args.episode)
    if eid is None:
        return out.error(f"no episode {args.episode}", EXIT_NOTFOUND)
    try:
        rep = lifecycle.amend_outcome(store, eid, args.outcome, args.criterion or "")
    except ValueError as exc:
        return out.error(str(exc), EXIT_USAGE)
    out.emit(rep.to_dict(), _r_kv)
    return EXIT_OK


def cmd_endorse(args, out: Out) -> int:
    store = _store(args)
    nid = model.resolve_id(store, args.id)
    if nid is None:
        return out.error(f"no node {args.id}", EXIT_NOTFOUND)
    out.emit(lifecycle.endorse(store, nid, args.by), _r_kv)
    return EXIT_OK


def cmd_dispute(args, out: Out) -> int:
    store = _store(args)
    nid = model.resolve_id(store, args.id)
    if nid is None:
        return out.error(f"no node {args.id}", EXIT_NOTFOUND)
    other = model.resolve_id(store, args.against) if args.against else None
    with store.write():
        model.set_status(store, nid, "disputed")
        n = model.get_node(store, nid, with_edges=False)
        qid = queue.enqueue(store, "dispute", {"a": nid, "b": other, "a_summary": n.summary if n else "", "reason": args.reason, "tags": n.tags if n else []}, dedupe_key=f"dispute:{nid}")
        if other:
            model.add_edge(store, nid, other, "contradicts", 1.0, {"by": "main", "reason": args.reason})
    out.emit({"id": nid, "status": "disputed", "queue_id": qid}, _r_kv)
    return EXIT_OK


def cmd_consolidate(args, out: Out) -> int:
    store = _store(args)
    only = [s.strip() for s in (args.only or "").split(",") if s.strip()] or None
    out.emit(lifecycle.consolidate(store, only, args.dry_run, not args.no_llm), _r_json)
    return EXIT_OK


def cmd_decay(args, out: Out) -> int:
    store = _store(args)
    out.emit(lifecycle.decay(store, args.dry_run), _r_json)
    return EXIT_OK


def cmd_progress(args, out: Out) -> int:
    store = _store(args)
    p = triggers.Progress(status=args.status, tags=model.parse_tags(args.tags or []), phase=args.phase, project=args.project, tool_calls=args.tool_calls, errors=[triggers.normalize_signature(e) for e in (args.error or [])])
    res = triggers.evaluate(store, p, not args.no_llm)

    def render(d: dict) -> str:
        s = d["suggestion"]
        text = f"suggestion {s['id']} [{s['trigger']}]: {s['rationale']} → {' '.join(s['memory_ids'])}" if s else ""
        if d["new_tags"]:
            text += ("\n" if text else "") + "new tags: " + " ".join(d["new_tags"])
        return text or "(nothing to suggest)"

    out.emit(res, render)
    return EXIT_OK


def cmd_suggestion(args, out: Out) -> int:
    store = _store(args)
    if args.suggestion_cmd == "list":
        out.emit(triggers.list_suggestions(store, args.project, args.pending), lambda rows: "\n".join(f"{r['id']} · {r['trigger']} · {r['response'] or 'pending'} · {r['rationale']}" for r in rows) or "(none)")
        return EXIT_OK
    if args.suggestion_cmd != "respond":
        return out.error("suggestion: list | respond", EXIT_USAGE)
    try:
        out.emit(triggers.respond(store, args.id, args.response), _r_kv)
    except KeyError:
        return out.error(f"no suggestion {args.id}", EXIT_NOTFOUND)
    except ValueError as exc:
        return out.error(str(exc), EXIT_USAGE)
    return EXIT_OK


def cmd_identity(args, out: Out) -> int:
    store = _store(args)
    sub = args.identity_cmd
    if sub == "list":
        nodes = identity.list_identity(store, args.tier, args.history)
        toks, count = identity.working_budget(store)
        d = {"working_tokens": toks, "working_count": count, "nodes": [{"id": n.id, "type": n.type, "status": n.status, "summary": n.summary, "body": n.body, "created": n.created} for n in nodes]}
        out.emit(d, _r_identity)
        return EXIT_OK
    if sub == "propose":
        qid = identity.propose_core(store, args.summary, _read_body(args), model.parse_tags(args.tags or []), model.parse_ids(args.evidence or []))
        out.emit({"queue_id": qid, "note": "core changes are applied only when a human approves the queue item"}, _r_kv)
        return EXIT_OK
    if sub == "edit":
        proj = args.project or _current_request().get("project") or "project"
        defaults = {"weekly": f"{proj}:week-{os.environ.get('LIBRARIAN_WEEK') or db.project_week()}", "project-close": proj, "failure-trigger": args.trigger_id or "", "human": "human"}
        key = args.occasion_key or defaults.get(args.occasion, "")
        res = identity.edit_working(
            store,
            args.summary,
            _read_body(args),
            occasion=args.occasion,
            occasion_key=key,
            reason=args.reason,
            episodes=model.parse_ids(args.episodes or []),
            tags=model.parse_tags(args.tags or []),
            project=args.project or _current_request().get("project"),
            trigger_id=args.trigger_id,
            supersedes=model.resolve_id(store, args.supersedes) if args.supersedes else None,
            use_llm=not args.no_llm,
            dry_run=args.dry_run,
        )
        out.emit(res.to_dict(), _r_gate)
        if res.action == "refused":
            return EXIT_REFUSED
        return EXIT_OK if res.accepted else EXIT_REJECTED
    if sub == "revert":
        nid = model.resolve_id(store, args.id)
        if nid is None:
            return out.error(f"no node {args.id}", EXIT_NOTFOUND)
        try:
            out.emit(identity.revert(store, nid, args.reason), _r_kv)
        except ValueError as exc:
            return out.error(str(exc), EXIT_USAGE)
        return EXIT_OK
    if sub == "seed":
        out.emit(identity.seed_core(store, Path(args.file).read_text(), args.author), lambda rows: "\n".join(f"{r['slug']}: {r['action']} {r.get('id') or ('; '.join(r['reasons']) if r['reasons'] else '')}" for r in rows))
        return EXIT_OK
    return out.error("identity: list | propose | edit | revert | seed", EXIT_USAGE)


def cmd_queue(args, out: Out) -> int:
    store = _store(args)
    if args.queue_cmd == "list":
        out.emit(queue.list_items(store, args.status, args.kind), _r_queue)
        return EXIT_OK
    if args.queue_cmd not in ("approve", "reject"):
        return out.error("queue: list | approve | reject", EXIT_USAGE)
    try:
        res = identity.decide(store, args.id, args.queue_cmd, args.note)
    except KeyError:
        return out.error(f"no queue item {args.id}", EXIT_NOTFOUND)
    except ValueError as exc:
        return out.error(str(exc), EXIT_USAGE)
    out.emit(res, _r_kv)
    return EXIT_OK


def cmd_probe(args, out: Out) -> int:
    store = _store(args)
    if args.probe_cmd == "run":
        res = identity.run_probes(store, Path(args.set).read_text(), not args.no_llm)
        if args.auto_revert:
            cmp_ = identity.compare_probes(store, res["run_id"], use_llm=not args.no_llm)
            res["compare"] = cmp_
            res["reverted"] = identity.revert_drift(store, cmp_)
        out.emit(res, _r_kv)
        return EXIT_OK
    if args.probe_cmd == "compare":
        out.emit(identity.compare_probes(store, args.run, args.against, args.threshold, not args.no_llm), _r_kv)
        return EXIT_OK
    return out.error("probe: run | compare", EXIT_USAGE)


def cmd_project(args, out: Out) -> int:
    store = _store(args)
    if args.project_cmd != "close":
        return out.error("project: close <project>", EXIT_USAGE)
    ts = db.now_iso()
    with store.write():
        store.ex("INSERT INTO projects(project, opened, closed) VALUES (?,?,?) ON CONFLICT(project) DO UPDATE SET closed = excluded.closed", (args.project, ts, ts))
    out.emit({"project": args.project, "closed": ts}, _r_kv)
    return EXIT_OK


def cmd_stats(args, out: Out) -> int:
    store = _store(args)
    out.emit(exchange.stats(store, args.since, args.project, args.week), _r_json)
    return EXIT_OK


def cmd_eval(args, out: Out) -> int:
    store = _store(args)
    rep = exchange.run_eval(store, Path(args.set), args.budget, args.llm)
    out.emit(rep, lambda d: "\n".join(f"{c['id']}: P={c['precision']} R={c['recall']}" + (f" missed {c['missed']}" if c["missed"] else "") for c in d["cases"]) + f"\nmacro P={d['macro_precision']} R={d['macro_recall']} over {d['n']}")
    if args.min_recall is not None and (rep["macro_recall"] or 0) < args.min_recall:
        return EXIT_ERR
    if args.min_precision is not None and (rep["macro_precision"] or 0) < args.min_precision:
        return EXIT_ERR
    return EXIT_OK


def cmd_export(args, out: Out) -> int:
    store = _store(args)
    ident = os.environ.get("IDENTITY_DIR", "").strip()
    out_dir = Path(args.dir) if args.dir else (Path(ident) / "librarian" / "export" if ident else Path("librarian-export"))
    pdir = Path(args.project_dir) if args.project_dir else None
    out.emit(exchange.export_store(store, out_dir, args.format, pdir, args.project), _r_kv)
    return EXIT_OK


def cmd_import(args, out: Out) -> int:
    store = _store(args)
    rep = exchange.ImportReport()

    def merge(r: exchange.ImportReport) -> None:
        rep.stored += r.stored
        rep.merged += r.merged
        rep.rejected += r.rejected

    for f in args.files or []:
        merge(exchange.import_json(store, Path(f), args.author, args.status, args.dry_run))
    if args.preferences:
        merge(exchange.import_preferences(store, Path(args.preferences), model.parse_tags(args.tags or []), args.author or "human", args.dry_run))
    if args.skills:
        d = Path(args.skills)
        found = False
        for sub, generic in (("project", False), ("generic", True)):
            if (d / sub).is_dir():
                found = True
                merge(exchange.import_skills(store, d / sub, args.project, generic, args.author or "main", args.dry_run))
        if not found:
            merge(exchange.import_skills(store, d, args.project, False, args.author or "main", args.dry_run))
    if args.identity_core:
        rows = identity.seed_core(store, Path(args.identity_core).read_text(), args.author or "human")
        rep.stored += [r["id"] for r in rows if r.get("id")]
        rep.rejected += [{"summary": r["slug"], "reasons": r["reasons"]} for r in rows if not r["accepted"]]
    if args.addenda:
        merge(exchange.import_addenda(store, Path(args.addenda), args.project, args.dry_run))
    out.emit(rep.to_dict(), lambda d: f"stored {d['counts']['stored']}, merged {d['counts']['merged']}, rejected {d['counts']['rejected']}" + ("\n" + "\n".join(f"- {r['summary']}: {'; '.join(r['reasons'])}" for r in d["rejected"]) if d["rejected"] else ""))
    return EXIT_OK


def cmd_tags(args, out: Out) -> int:
    store = _store(args)
    sql = "SELECT v.tag, v.namespace, v.status, (SELECT COUNT(*) FROM tags t WHERE t.tag = v.tag) AS n FROM tag_vocab v"
    params: tuple = ()
    if args.namespace:
        sql += " WHERE v.namespace = ?"
        params = (args.namespace,)
    sql += " ORDER BY v.namespace, v.tag"
    rows = [{"tag": r[0], "namespace": r[1], "status": r[2], "count": r[3]} for r in store.q(sql, params)]
    out.emit({"namespaces": list(model.TAG_NAMESPACES), "closed": ["ctx"], "review_on_new": ["area"], "tags": rows}, lambda d: "\n".join(f"{t['tag']} ({t['status']}, {t['count']})" for t in d["tags"]) or "(no tags yet)")
    return EXIT_OK


def cmd_runtime(args, out: Out) -> int:
    from . import runtime

    stdin_text = "" if sys.stdin.isatty() else sys.stdin.read()
    if args.runtime_cmd == "pre":
        return runtime.pre(args.ritual or None, args.phase or "", args.budget, stdin_text, not args.no_llm)
    if args.runtime_cmd == "post":
        return runtime.post(args.rc, args.run_id or None, args.stderr_tail or "", stdin_text, not args.no_llm)
    return out.error("runtime: pre | post", EXIT_USAGE)


# ── parser ───────────────────────────────────────────────────────────────────


def _add_body(p: argparse.ArgumentParser) -> None:
    p.add_argument("--body", help="text, or - for stdin")
    p.add_argument("--body-file")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="librarian", description="Headlong's memory store and context packer.")
    p.add_argument("--store", help="store path (default $LIBRARIAN_STORE or $IDENTITY_DIR/librarian/store.sqlite)")
    p.add_argument("--text", dest="text_mode", action="store_true", help="human/model-readable output instead of JSON")
    p.add_argument("--json", action="store_true", help="JSON output (default)")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="create the store (idempotent) and seed it")
    s.add_argument("--seed", action="append", help="identity-core markdown or a JSON node file (repeatable)")
    s.add_argument("--import-skills", help="a skills/ directory with project/ and generic/ subdirs")
    s.add_argument("--import-addenda", help="an existing addenda.md to convert to working identity")
    s.add_argument("--project")
    s.set_defaults(func=cmd_init)

    for name in ("propose", "add"):
        s = sub.add_parser(name, help="write a candidate node through the quality gate")
        s.add_argument("--type", required=True, choices=model.NODE_TYPES)
        s.add_argument("--summary", required=True)
        _add_body(s)
        s.add_argument("--tags", action="append")
        s.add_argument("--project")
        s.add_argument("--confidence", type=float, default=0.5)
        s.add_argument("--provenance", help="JSON object")
        s.add_argument("--episode")
        s.add_argument("--source")
        s.add_argument("--author", choices=model.AUTHORS)
        s.add_argument("--supersedes")
        s.add_argument("--valid-from")
        s.add_argument("--valid-to")
        s.add_argument("--untrusted", action="store_true")
        s.add_argument("--status", choices=model.STATUSES)
        s.add_argument("--edge", action="append", help="TYPE:TO[:WEIGHT]")
        s.add_argument("--dry-run", action="store_true")
        s.set_defaults(func=cmd_propose)

    s = sub.add_parser("search", help="summaries only")
    s.add_argument("--tags", action="append")
    s.add_argument("--text", dest="text", help="free text")
    s.add_argument("--type", choices=model.NODE_TYPES)
    s.add_argument("--project")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--no-probationary", action="store_true")
    s.add_argument("--history", action="store_true")
    s.add_argument("--no-log", action="store_true")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("fetch", help="full bodies")
    s.add_argument("ids", nargs="+")
    s.add_argument("--budget", type=int)
    s.add_argument("--request")
    s.add_argument("--project")
    s.add_argument("--no-log", action="store_true")
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("pack", help="build a context pack")
    s.add_argument("--task", required=True)
    s.add_argument("--tags", action="append")
    s.add_argument("--project")
    s.add_argument("--phase", choices=model.PHASES)
    s.add_argument("--budget", type=int, default=8000)
    s.add_argument("--exclude", action="append")
    s.add_argument("--no-llm", action="store_true")
    s.add_argument("--no-log", action="store_true")
    s.set_defaults(func=cmd_pack)

    s = sub.add_parser("show")
    s.add_argument("id")
    s.add_argument("--history", action="store_true")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("episode")
    ss = s.add_subparsers(dest="episode_cmd")
    c = ss.add_parser("close")
    c.add_argument("--id")
    c.add_argument("--summary")
    _add_body(c)
    c.add_argument("--tags", action="append")
    c.add_argument("--outcome", required=True, choices=model.OUTCOMES)
    c.add_argument("--criterion")
    c.add_argument("--cite", action="append")
    c.add_argument("--request", action="append")
    c.add_argument("--helpful", action="append")
    c.add_argument("--project")
    c.add_argument("--phase", choices=model.PHASES)
    c.add_argument("--provenance")
    c.add_argument("--author", choices=model.AUTHORS)
    c.add_argument("--episode")
    c.add_argument("--source")
    s.set_defaults(func=cmd_episode)

    s = sub.add_parser("outcome")
    ss = s.add_subparsers(dest="outcome_cmd")
    c = ss.add_parser("amend")
    c.add_argument("episode")
    c.add_argument("--outcome", required=True, choices=model.OUTCOMES)
    c.add_argument("--criterion")
    s.set_defaults(func=cmd_outcome)

    s = sub.add_parser("endorse")
    s.add_argument("id")
    s.add_argument("--by", default="human")
    s.set_defaults(func=cmd_endorse)

    s = sub.add_parser("dispute")
    s.add_argument("id")
    s.add_argument("--against")
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_dispute)

    s = sub.add_parser("consolidate")
    s.add_argument("--only")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--no-llm", action="store_true")
    s.set_defaults(func=cmd_consolidate)

    s = sub.add_parser("decay")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_decay)

    s = sub.add_parser("progress")
    s.add_argument("--status", required=True)
    s.add_argument("--tags", action="append")
    s.add_argument("--phase", choices=model.PHASES)
    s.add_argument("--project")
    s.add_argument("--tool-calls", type=int, default=0)
    s.add_argument("--error", action="append")
    s.add_argument("--no-llm", action="store_true")
    s.set_defaults(func=cmd_progress)

    s = sub.add_parser("suggestion")
    ss = s.add_subparsers(dest="suggestion_cmd")
    c = ss.add_parser("list")
    c.add_argument("--project")
    c.add_argument("--pending", action="store_true")
    c = ss.add_parser("respond")
    c.add_argument("id")
    c.add_argument("response", choices=("accept", "defer", "dismiss"))
    s.set_defaults(func=cmd_suggestion)

    s = sub.add_parser("identity")
    ss = s.add_subparsers(dest="identity_cmd")
    c = ss.add_parser("list")
    c.add_argument("--tier", choices=("core", "working"))
    c.add_argument("--core", dest="tier", action="store_const", const="core")
    c.add_argument("--working", dest="tier", action="store_const", const="working")
    c.add_argument("--history", action="store_true")
    c = ss.add_parser("propose")
    c.add_argument("--summary", required=True)
    _add_body(c)
    c.add_argument("--tags", action="append")
    c.add_argument("--evidence", action="append")
    c = ss.add_parser("edit")
    c.add_argument("--summary", required=True)
    _add_body(c)
    c.add_argument("--tags", action="append")
    c.add_argument("--occasion", required=True, choices=identity.OCCASIONS)
    c.add_argument("--occasion-key")
    c.add_argument("--trigger-id")
    c.add_argument("--supersedes")
    c.add_argument("--reason", required=True)
    c.add_argument("--episodes", action="append")
    c.add_argument("--because", dest="episodes", action="append")
    c.add_argument("--project")
    c.add_argument("--no-llm", action="store_true")
    c.add_argument("--dry-run", action="store_true")
    c = ss.add_parser("revert")
    c.add_argument("id")
    c.add_argument("--reason", required=True)
    c = ss.add_parser("seed")
    c.add_argument("file")
    c.add_argument("--author", default="human", choices=model.AUTHORS)
    s.set_defaults(func=cmd_identity)

    s = sub.add_parser("queue")
    ss = s.add_subparsers(dest="queue_cmd")
    c = ss.add_parser("list")
    c.add_argument("--status", default="pending")
    c.add_argument("--kind")
    for name in ("approve", "reject"):
        c = ss.add_parser(name)
        c.add_argument("id")
        c.add_argument("--note")
    s.set_defaults(func=cmd_queue)

    s = sub.add_parser("probe")
    ss = s.add_subparsers(dest="probe_cmd")
    c = ss.add_parser("run")
    c.add_argument("--set", required=True)
    c.add_argument("--auto-revert", action="store_true")
    c.add_argument("--no-llm", action="store_true")
    c = ss.add_parser("compare")
    c.add_argument("run", nargs="?")
    c.add_argument("--against")
    c.add_argument("--threshold", type=float, default=identity.PROBE_DRIFT_DEFAULT)
    c.add_argument("--no-llm", action="store_true")
    s.set_defaults(func=cmd_probe)

    s = sub.add_parser("project")
    ss = s.add_subparsers(dest="project_cmd")
    c = ss.add_parser("close")
    c.add_argument("project")
    s.set_defaults(func=cmd_project)

    s = sub.add_parser("stats")
    s.add_argument("--since")
    s.add_argument("--project")
    s.add_argument("--week")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("eval")
    s.add_argument("--set", required=True)
    s.add_argument("--budget", type=int)
    s.add_argument("--llm", action="store_true")
    s.add_argument("--min-recall", type=float)
    s.add_argument("--min-precision", type=float)
    s.set_defaults(func=cmd_eval)

    s = sub.add_parser("export")
    s.add_argument("--dir")
    s.add_argument("--format", choices=("md", "json"), default="md")
    s.add_argument("--project-dir")
    s.add_argument("--project")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("import")
    s.add_argument("files", nargs="*")
    s.add_argument("--author", choices=model.AUTHORS)
    s.add_argument("--status", choices=model.STATUSES)
    s.add_argument("--preferences")
    s.add_argument("--tags", action="append")
    s.add_argument("--skills")
    s.add_argument("--identity-core")
    s.add_argument("--addenda")
    s.add_argument("--project")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("tags")
    s.add_argument("--namespace")
    s.set_defaults(func=cmd_tags)

    s = sub.add_parser("runtime")
    ss = s.add_subparsers(dest="runtime_cmd")
    c = ss.add_parser("pre")
    c.add_argument("--ritual", default="")
    c.add_argument("--phase", default="")
    c.add_argument("--now")
    c.add_argument("--budget", type=int)
    c.add_argument("--no-llm", action="store_true")
    c = ss.add_parser("post")
    c.add_argument("--rc", type=int, default=0)
    c.add_argument("--run-id", default="")
    c.add_argument("--stderr-tail", default="")
    c.add_argument("--now")
    c.add_argument("--no-llm", action="store_true")
    s.set_defaults(func=cmd_runtime)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    if sys.version_info < (3, 10):
        print("librarian: python 3.10 or newer is required", file=sys.stderr)
        return EXIT_ERR
    parser = build_parser()
    args = parser.parse_args(argv)
    out = Out(text=bool(args.text_mode and not args.json), quiet=args.quiet)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return EXIT_USAGE
    if getattr(args, "now", None):
        os.environ["LIBRARIAN_NOW"] = str(args.now)
    try:
        return int(args.func(args, out))
    except db.NoStore as exc:
        return out.error(str(exc), EXIT_USAGE)
    except db.StoreBusy as exc:
        return out.error(str(exc), EXIT_BUSY)
    except db.StoreError as exc:
        return out.error(str(exc), EXIT_ERR)
    except KeyError as exc:
        return out.error(f"not found: {exc}", EXIT_NOTFOUND)
    except (ValueError, OSError) as exc:
        return out.error(str(exc), EXIT_ERR)
