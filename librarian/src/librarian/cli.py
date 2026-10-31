"""The ``librarian`` command line.

JSON on stdout by default; ``--text`` renders for a model or a person.
Exit codes: 0 ok, 1 error, 2 usage or no store, 3 gate rejected, 4 not
found, 6 store busy.

What the mind uses: ``propose``, ``search``, ``fetch``, ``shared``,
``capture clear``, ``tags``. What the runtime uses: ``runtime pre|post``,
``export``. What humans use: ``init``, ``import``, ``stats``, ``show``,
``pack``, ``eval``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from . import __version__, consistency, db, exchange, gate, identity, model, pack, recall

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
    ident = db.identity_dir()
    return (ident / "run" / "librarian_request.json") if ident else None


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
    if "src:untrusted" in tags:
        m.append("UNTRUSTED")
    return m


def _r_search(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        marks = _marks(r["status"], r["tags"])
        brief = f"brief {r['project']} · " if r.get("project") else ""
        lines.append(f"{r['id']} · {r['type']} · " + (" · ".join(marks) + " · " if marks else "") + brief + " ".join(r["tags"]) + f" · {r['summary']}")
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
    if d["action"] == "dry-run":
        return "ok: " + "; ".join(d["notes"])
    return f"{d['action']} {d['id']} ({d['status']})" + ("\n- " + "\n- ".join(d["notes"]) if d["notes"] else "")


def _r_kv(d: dict) -> str:
    return "\n".join(f"{k}: {json.dumps(v) if isinstance(v, (dict, list)) else v}" for k, v in d.items())


def _r_json(d) -> str:
    return json.dumps(d, indent=2)


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
    prov = _provenance(args)
    if not any(prov.get(k) for k in ("episode", "source", "run_id", "span")):
        rid = _current_request().get("request_id")
        if rid:
            prov["run_id"] = rid
    cand = gate.Candidate(
        type=args.type,
        summary=args.summary,
        body=_read_body(args),
        tags=model.parse_tags(args.tags or []),
        provenance=prov,
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
        res = {"accepted": not reasons, "action": "dry-run", "reasons": reasons, "notes": [], "near_duplicates": [{"id": d[0], "summary": d[1], "body": d[2]} for d in dups[:3]]}
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
        rows.append({"id": n.id, "type": n.type, "status": n.status, "tags": n.tags, "summary": n.summary, "project": n.project, "score": round(c.tag_score + c.bm25_norm + 0.5 * c.hop, 3)})
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
        rows.append({"id": n.id, "type": n.type, "status": n.status, "tags": n.tags, "summary": n.summary, "body": body, "truncated": truncated, "tokens": model.estimate_tokens(body), "project": n.project, "edges": n.edges})
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
    out.emit(d, _r_json)
    return EXIT_OK


def cmd_shared(args, out: Out) -> int:
    store = _store(args)
    facts = consistency.shared_facts(store)
    confl = {c["quantity"]: c for c in consistency.conflicts(store)}
    rows = [
        {"quantity": f.quantity, "value": f.value_text, "project": f.node.project, "id": f.node.id, "source": f.source, "summary": f.node.summary, "conflict": f.quantity in confl}
        for f in facts
        if not args.quantity or f.quantity == args.quantity
    ]
    out.emit(rows, lambda rs: "\n".join(f"{r['quantity']}{' CONFLICT' if r['conflict'] else ''} · {r['value']} · brief {r['project']} · {r['id']} · {r['summary']}" for r in rs) or "(no shared values yet: tag a fact shared:<quantity>)")
    return EXIT_OK


def cmd_capture(args, out: Out) -> int:
    store = _store(args)
    proj = args.project or _current_request().get("project")
    if args.capture_cmd == "list":
        rows = [db.row_dict(r) for r in store.q("SELECT id, signature, tags, created FROM pending_capture WHERE cleared IS NULL AND project IS ? ORDER BY created", (proj,))]
        out.emit(rows, lambda rs: "\n".join(f"{r['id']} · {r['signature']}" for r in rs) or "(no open captures)")
        return EXIT_OK
    if args.capture_cmd != "clear":
        return out.error("capture: list | clear <id or signature> --covered-by <memory id>", EXIT_USAGE)
    nid = model.resolve_id(store, args.covered_by)
    if not nid or model.get_node(store, nid, with_edges=False) is None:
        return out.error(f"no memory {args.covered_by}", EXIT_NOTFOUND)
    row = store.q1("SELECT id FROM pending_capture WHERE cleared IS NULL AND (id = ? OR signature = ?) ORDER BY created LIMIT 1", (args.ref, args.ref))
    if row is None:
        return out.error(f"no open capture {args.ref}", EXIT_NOTFOUND)
    with store.write():
        store.ex("UPDATE pending_capture SET cleared = ?, cleared_by = ? WHERE id = ?", (db.now_iso(), nid, row[0]))
    out.emit({"id": row[0], "cleared_by": nid}, _r_kv)
    return EXIT_OK


def cmd_identity(args, out: Out) -> int:
    store = _store(args)
    if args.identity_cmd == "seed":
        rows = identity.seed_core(store, Path(args.file).read_text(), args.author or "human")
        out.emit(rows, _r_json)
        return EXIT_OK
    nodes = identity.list_identity(store, "core")
    out.emit([n.to_json() for n in nodes], lambda ns: "\n".join(f"- {n['id']} · {n['body'] or n['summary']}" for n in ns))
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
    ident = db.identity_dir()
    out_dir = Path(args.dir) if args.dir else (ident / "librarian" / "export" if ident else Path("librarian-export"))
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
    if args.namespace == "shared" or not args.namespace:
        for r in store.q("SELECT tag, COUNT(*) FROM tags WHERE tag LIKE 'shared:%' GROUP BY tag ORDER BY tag"):
            if not any(x["tag"] == r[0] for x in rows):
                rows.append({"tag": r[0], "namespace": "shared", "status": "seen", "count": r[1]})
    out.emit({"namespaces": list(model.TAG_NAMESPACES), "closed": ["ctx", "fail"], "tags": rows}, lambda d: "\n".join(f"{t['tag']} ({t['status']}, {t['count']})" for t in d["tags"]) or "(no tags yet)")
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
    p = argparse.ArgumentParser(prog="librarian", description="Librarian's memory store and context packer.")
    p.add_argument("--store", help="store path (default $LIBRARIAN_STORE or $IDENTITY_DIR/librarian/store.sqlite)")
    p.add_argument("--text", dest="text_mode", action="store_true", help="human/model-readable output instead of JSON")
    p.add_argument("--json", action="store_true", help="JSON output (default)")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="create the store (idempotent) and seed it")
    s.add_argument("--seed", action="append", help="identity-core markdown or a JSON node file (repeatable)")
    s.add_argument("--import-skills", help="a skills/ directory with project/ and generic/ subdirs")
    s.add_argument("--import-addenda", help="ignored (kept for older callers)")
    s.add_argument("--project")
    s.set_defaults(func=cmd_init)

    for name in ("propose", "add"):
        s = sub.add_parser(name, help="write a candidate node through the quality gate")
        s.add_argument("--type", required=True, choices=model.NODE_TYPES)
        s.add_argument("--summary", required=True)
        _add_body(s)
        s.add_argument("--tags", action="extend", nargs="+", help="tags, comma- or space-separated")
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
    s.add_argument("--tags", action="extend", nargs="+", help="tags, comma- or space-separated")
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
    s.add_argument("--task", default="")
    s.add_argument("--tags", action="extend", nargs="+")
    s.add_argument("--project")
    s.add_argument("--phase")
    s.add_argument("--budget", type=int, default=2000)
    s.add_argument("--exclude", action="append")
    s.add_argument("--no-log", action="store_true")
    s.add_argument("--no-llm", action="store_true")
    s.set_defaults(func=cmd_pack)

    s = sub.add_parser("show")
    s.add_argument("id")
    s.add_argument("--history", action="store_true")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("shared", help="the shared-values ledger: facts tagged shared:<quantity>, with conflicts")
    s.add_argument("--quantity")
    s.set_defaults(func=cmd_shared)

    s = sub.add_parser("capture", help="open CAPTURE signals; clear one a memory already covers")
    ss = s.add_subparsers(dest="capture_cmd")
    c = ss.add_parser("list")
    c.add_argument("--project")
    c = ss.add_parser("clear")
    c.add_argument("ref", help="capture id or its error signature")
    c.add_argument("--covered-by", required=True, help="the memory that already covers it")
    c.add_argument("--project")
    s.set_defaults(func=cmd_capture)

    s = sub.add_parser("identity")
    ss = s.add_subparsers(dest="identity_cmd")
    c = ss.add_parser("list")
    c.add_argument("--core", action="store_true")
    c = ss.add_parser("seed")
    c.add_argument("file")
    c.add_argument("--author", choices=model.AUTHORS)
    s.set_defaults(func=cmd_identity)

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
