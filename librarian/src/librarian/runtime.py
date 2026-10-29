"""``runtime pre`` and ``runtime post``: the two composites the monolith step calls.

``pre`` runs before the model: maintenance keyed on the due ritual, the
context request, the pack, and the signal lines for this wake. ``post``
runs after: the deterministic outcome, the episode, credit, the progress
feed, resolved-failure capture, and the export mirrors. Neither trusts the
model's self-report as evidence of success.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import db, exchange, gate, identity, lifecycle, llm, model, outcome, pack, queue, triggers

REQUEST_FILE = "librarian_request.json"
SIGNALS_FILE = "librarian_signals"
NO_STORE_MARKER = ".no-store-noted"
CAPTURE_TTL_DAYS_DEFAULT = 3
DISPUTE_TTL_HOURS_DEFAULT = 48
REVIEW_WINDOW_DAYS_DEFAULT = 7
RECUR_WINDOW_DAYS_DEFAULT = 7
EXCLUDE_WAKES_DEFAULT = 1
TRANSFER_WAKES_DEFAULT = 3
# A closed brief's LESSON DUE signal shows on this many wakes at most.
BRIEF_LESSON_WAKES_DEFAULT = 3
# blind writes one line per review run here: the lessons named before the verdict existed.
BLIND_LEDGER = ".blind/lessons.jsonl"
RISKS_FILE = "risks.md"
LEDGER_VERDICT_MIN = 20
BRIEF_HEAD_CHARS = 1500
# Files a wake can change without doing project work: a wake that changed
# only these (and cited nothing) is a no-op, and its episode is never packed.
BOOKKEEPING_FILES = {"STATE", "librarian.md", "questions-summary.md"}
SIGNAL_LINES = ("- RITUAL DUE", "- FREE TIME", "- HUMAN ANSWER", "- DEFAULT DUE", "- STALL", "- DELIVERABLE", "- DEADLINE", "- FINAL STRETCH", "- GUARD", "- THE RUN HAS ENDED")


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    return int(v) if v.isdigit() else default


def identity_dir() -> Optional[Path]:
    v = os.environ.get("IDENTITY_DIR", "").strip()
    return Path(v) if v else None


def project_dir() -> Optional[Path]:
    v = os.environ.get("PROJECT_DIR", "").strip()
    if v:
        return Path(v)
    i = identity_dir()
    return (i / "workdir" / "project") if i else None


def pristine_dir() -> Optional[Path]:
    v = os.environ.get("PROJECT_PRISTINE_DIR", "").strip()
    if v:
        return Path(v)
    i = identity_dir()
    return (i / "project-pristine") if i else None


def run_dir() -> Optional[Path]:
    i = identity_dir()
    return (i / "run") if i else None


def _read(path: Optional[Path], limit: int = 200000) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(errors="replace")[:limit]
    except OSError:
        return ""


def _slug(text: str, n: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:n] or "project"


def project_id() -> Optional[str]:
    pp = pristine_dir()
    if pp is not None:
        pid = _read(pp / "project_id").strip()
        if pid:
            return pid
    pd = project_dir()
    if pd is None or not (pd / "charter.md").exists():
        return None
    spec = _read(pd / "spec.md")
    title = next((ln[2:].strip() for ln in spec.splitlines() if ln.startswith("# ")), "") or "project"
    started = _read((pp / "started_at") if pp else None).strip()
    day = db.dt.datetime.fromtimestamp(int(started), tz=db._UTC).strftime("%Y%m%d") if started.isdigit() else "0"
    return f"p-{day}-{_slug(title)}"


def _git(pd: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(pd), *args], capture_output=True, text=True, check=False, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def dirty_files(pd: Path) -> list[str]:
    out = []
    for line in _git(pd, "status", "--porcelain", "--untracked-files=all").splitlines():
        if len(line) > 3:
            out.append(line[3:].strip().strip('"'))
    return out


def _signal_lines(text: str) -> list[str]:
    keep = []
    for ln in (text or "").splitlines():
        if any(ln.startswith(s) for s in SIGNAL_LINES):
            keep.append(ln.strip()[:400])
    return keep


def _open_store() -> Optional[db.Store]:
    path = db.default_store_path()
    if path is None or not path.exists():
        rd = run_dir()
        marker = (path.parent / NO_STORE_MARKER) if path else None
        if marker is not None and not marker.exists() and rd is not None:
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(db.now_iso())
            except OSError:
                pass
            print("librarian: no store for this identity (librarian-project init creates one); packs disabled", file=sys.stderr)
        return None
    return db.Store.open(path)


# ── maintenance ──────────────────────────────────────────────────────────────


def _maint_done(store: db.Store, kind: str, key: str) -> bool:
    return store.q1("SELECT 1 FROM maintenance WHERE kind = ? AND key = ?", (kind, key)) is not None


def _maint_mark(store: db.Store, kind: str, key: str, report: dict) -> None:
    with store.write():
        store.ex(
            "INSERT INTO maintenance(kind, key, ts, report) VALUES (?,?,?,?) ON CONFLICT(kind, key) DO UPDATE SET ts = excluded.ts, report = excluded.report",
            (kind, key, db.now_iso(), json.dumps(report)[:20000]),
        )


def _late_outcomes(store: db.Store, pd: Optional[Path], project: Optional[str]) -> dict:
    """Weekly: upgrade or downgrade episodes inside the review window from exogenous evidence."""
    window_days = _env_int("LIBRARIAN_REVIEW_WINDOW_DAYS", REVIEW_WINDOW_DAYS_DEFAULT)
    recur_days = _env_int("LIBRARIAN_RECUR_WINDOW_DAYS", RECUR_WINDOW_DAYS_DEFAULT)
    ref = db.now()
    report: dict = {"amended": []}
    # Each human edit of deliverable.md corrects the mind's last write of it, so
    # only the episode that made that write is blamed, not every episode in the
    # window (between-wake commits are authored "human" even when they hold a
    # crashed wake's or a background job's output).
    corrected: set[str] = set()
    eps = model.nodes_where(store, "type = 'episode' AND project IS ? ORDER BY created", (project,))
    if pd is not None and (pd / ".git").exists():
        log = _git(pd, "log", "--format=%cI %an", "--", "deliverable.md")
        mind_ts: Optional[db.dt.datetime] = None
        for ln in reversed([ln.split(" ", 1) for ln in log.splitlines() if ln.strip()]):
            t = db.parse_ts(ln[0])
            if t is None:
                continue
            if len(ln) > 1 and ln[1].strip() == "human":
                if mind_ts is not None and t - mind_ts <= db.dt.timedelta(days=window_days):
                    last = None
                    for ep in eps:
                        c = db.parse_ts(ep.created)
                        if c is not None and c <= mind_ts:
                            last = ep
                    if last is not None:
                        corrected.add(last.id)
                mind_ts = None
            else:
                mind_ts = t
    recent_errors: dict[str, str] = {}  # signature -> last ts seen
    for r in store.q("SELECT errors, ts FROM progress_log WHERE project IS ? ORDER BY id", (project,)):
        try:
            for sig in json.loads(r["errors"] or "[]"):
                recent_errors[sig] = r["ts"]
        except ValueError:
            continue
    for ep in eps:
        age = db.age_days(ep.created, ref) or 0.0
        if age > window_days * 2:
            continue
        oc = (ep.outcome or {}).get("value")
        created = db.parse_ts(ep.created)
        # A human corrected the deliverable this episode wrote → failure.
        if oc in ("success", "partial") and created is not None and ep.id in corrected:
            rep = lifecycle.amend_outcome(store, ep.id, "failure", "human corrected deliverable")
            report["amended"].append({"episode": ep.id, "to": "failure", "reversed": rep.reversed})
        # Non-recurrence: a partial episode that cited a skill whose signature never came back.
        if oc == "partial" and age >= recur_days:
            cited = [r[0] for r in store.q("SELECT node_id FROM citations WHERE episode_id = ?", (ep.id,))]
            sigs = [r[0] for r in store.q("SELECT signature FROM pending_capture WHERE cleared_by IN (" + ",".join("?" for _ in cited) + ")", tuple(cited))] if cited else []
            body_sigs = [s for s in re.findall(r'error "(.*?)"', ep.body or "")]
            candidates = sigs or body_sigs
            if candidates and all((recent_errors.get(s) or "") <= ep.created for s in candidates):
                rep = lifecycle.amend_outcome(store, ep.id, "success", "failure did not recur")
                report["amended"].append({"episode": ep.id, "to": "success", "reversed": rep.reversed})
    return report


def _expire_disputes(store: db.Store) -> list[str]:
    """Daily: a dispute no human decided within the TTL is rejected (both memories kept, active again).

    The mind cannot decide a dispute, so an undecided one only lingers: in the
    2026-10 live run one waited seven days and kept surfacing in rest wakes.
    """
    ttl = _env_int("LIBRARIAN_DISPUTE_TTL_HOURS", DISPUTE_TTL_HOURS_DEFAULT)
    out = []
    for item in queue.list_items(store, "pending", "dispute"):
        if (db.age_days(item["created"]) or 0.0) * 24 < ttl:
            continue
        with store.write():
            identity.decide(store, item["id"], "reject", f"expired: no human decision within {ttl} h; both memories kept")
            for nid in ((item.get("payload") or {}).get("a"), (item.get("payload") or {}).get("b")):
                n = model.get_node(store, nid, with_edges=False) if nid else None
                if n is not None and n.status == "disputed":
                    model.set_status(store, nid, "active")
        out.append(item["id"])
    return out


def maintenance(store: db.Store, ritual: Optional[str], pd: Optional[Path], project: Optional[str], use_llm: bool) -> dict:
    out: dict = {}
    if not ritual:
        return out
    parts = ritual.split()
    kind = parts[0]
    key = parts[1] if len(parts) > 1 else "once"
    if kind == "daily" and not _maint_done(store, "daily", key):
        rep = {"consolidate": lifecycle.consolidate(store, use_llm=use_llm), "decay": lifecycle.decay(store), "expired_disputes": _expire_disputes(store)}
        _maint_mark(store, "daily", key, rep)
        out["daily"] = key
    elif kind == "weekly" and not _maint_done(store, "weekly", key):
        rep = {"late_outcomes": _late_outcomes(store, pd, project)}
        if key.isdigit() and int(key) % 4 == 0:
            probes_file = (pristine_dir() / "probes.md") if pristine_dir() else None
            text = _read(probes_file)
            if text:
                run = identity.run_probes(store, text, use_llm)
                cmp_ = identity.compare_probes(store, run["run_id"], use_llm=use_llm)
                reverted = identity.revert_drift(store, cmp_)
                rep["probes"] = {"run": run["run_id"], "mean_drift": cmp_.get("mean"), "reverted": reverted}
        _maint_mark(store, "weekly", key, rep)
        out["weekly"] = key
    return out


# ── pre ──────────────────────────────────────────────────────────────────────


def current_brief(spec: str) -> str:
    """The newest project brief in the spec: from its last top-level heading to the end."""
    heads = [m.start() for m in re.finditer(r"^# ", spec, flags=re.M)]
    return spec[heads[-1]:] if heads else spec


def _task_text(pd: Path, signals: list[str]) -> str:
    # The current brief's title, not the spec's first one: later briefs are
    # appended to the same spec, and recall should follow the work in hand.
    brief = current_brief(_read(pd / "spec.md", 200000))
    title = next((ln.strip("# ").strip() for ln in brief.splitlines() if ln.startswith("# ")), "")
    plan = "\n".join(_read(pd / "plan.md", 20000).splitlines()[:12])
    journal = _read(pd / "journal.md", 400000)
    blocks = re.split(r"^### ", journal, flags=re.M)
    last = ("### " + blocks[-1])[:1200] if len(blocks) > 1 else ""
    parts = [p for p in (title, plan, last, "\n".join(signals)) if p.strip()]
    return "\n\n".join(parts)


def _exclude_ids(store: db.Store, project: Optional[str], wakes: int) -> list[str]:
    reqs = store.q("SELECT request_id, ts FROM requests WHERE kind = 'pack' AND project IS ? ORDER BY ts DESC LIMIT ?", (project, wakes))
    if not reqs:
        return []
    ids: list[str] = []
    oldest = reqs[-1]["ts"]
    for r in reqs:
        for row in store.q("SELECT node_id FROM retrieval_log WHERE request_id = ? AND source = 'pack' AND section = 'task'", (r["request_id"],)):
            if row[0] not in ids:
                ids.append(row[0])
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    used = {r[0] for r in store.q(f"SELECT node_id FROM retrieval_log WHERE node_id IN ({marks}) AND source = 'fetch' AND ts >= ?", (*ids, oldest))}  # noqa: S608
    used |= {r[0] for r in store.q(f"SELECT c.node_id FROM citations c JOIN nodes n ON n.id = c.episode_id WHERE c.node_id IN ({marks}) AND n.created >= ?", (*ids, oldest))}  # noqa: S608
    return [i for i in ids if i not in used]


def _vocab_tags_in_text(store: db.Store, text: str) -> list[str]:
    words = set(model.tokenize(text))
    out = []
    for r in store.q("SELECT tag FROM tag_vocab WHERE status = 'active' AND namespace IN ('pkg','area','topic','data','method')"):
        free = model.tag_free(r[0])
        if free in words or free.replace("-", " ") in text.lower():
            out.append(r[0])
    return out[:10]


def _signals_out(store: db.Store, project: Optional[str], rd: Path, extra: Optional[list[str]] = None) -> list[str]:
    lines: list[str] = list(extra or [])
    with store.write():
        for row in store.q("SELECT * FROM pending_capture WHERE cleared IS NULL AND project IS ? ORDER BY created", (project,)):
            tags = json.loads(row["tags"] or "[]")
            span = json.loads(row["span"] or "[]") if row["span"] else []
            lines.append(
                f'- CAPTURE: you resolved "{row["signature"]}" (wake {row["created"]}, steps {" .. ".join(str(s)[:8] for s in span)}). '
                f"Write it down once: `librarian propose --type skill --summary \"<when would I want this?>\" --tags {' '.join(tags) or 'area:tooling'} --body-file <f>` "
                f"with symptom, cause, exact command, verified on. This signal stays until a skill with those tags is proposed; "
                f"if a memory already covers it, clear it instead: `librarian capture clear {row['id']} --covered-by <memory id>`."
            )
        for s in triggers.undelivered(store, project):
            mems = []
            for mid in s["memory_ids"]:
                n = model.get_node(store, mid, with_edges=False)
                if n:
                    mems.append(f'{mid} "{n.summary[:90]}"')
            lines.append(
                f"- LIBRARIAN SUGGESTION [{s['trigger'].replace('_', '-')}] ({s['id']}): {s['rationale']}. "
                + (f"Memories: {'; '.join(mems)}. Read them with `librarian fetch <id>`, then " if mems else "")
                + f"answer `librarian suggestion respond {s['id']} accept|defer|dismiss` this wake (unanswered counts as defer)."
            )
            triggers.mark_delivered(store, [s["id"]])
        for item in queue.list_items(store, "pending", "working_conflict"):
            payload = item.get("payload") or {}
            if payload.get("announced"):
                continue
            lines.append(f"- LIBRARIAN: your working-identity edit \"{str(payload.get('summary', ''))[:80]}\" was refused (it contradicts core node {payload.get('core_id')}); queued for a human as item {item['id']}.")
            payload["announced"] = True
            store.ex("UPDATE checkin_queue SET payload = ? WHERE id = ?", (json.dumps(payload), item["id"]))
        last_req = store.q1("SELECT ts FROM requests WHERE kind = 'pack' AND project IS ? ORDER BY ts DESC LIMIT 1", (project,))
        since = last_req[0] if last_req else "1970"
        for r in store.q("SELECT id, payload FROM checkin_queue WHERE kind = 'core_proposal' AND status = 'approved' AND decided >= ?", (since,)):
            try:
                summary = json.loads(r[1]).get("summary", "")
            except ValueError:
                summary = ""
            lines.append(f'- LIBRARIAN: a human approved core-identity change {r[0]} ("{summary[:80]}"); it is in your pack from this wake on.')
    path = rd / SIGNALS_FILE
    if lines:
        path.write_text("\n".join(lines) + "\n")
    elif path.exists():
        path.unlink()
    return lines


def pre(ritual: Optional[str], phase: str, budget: Optional[int], signals_text: str, use_llm: bool = True) -> int:
    store = _open_store()
    if store is None:
        return 0
    pd = project_dir()
    rd = run_dir()
    if pd is None or rd is None or not (pd / "charter.md").exists():
        return 0
    rd.mkdir(parents=True, exist_ok=True)
    project = project_id()
    signals = _signal_lines(signals_text)
    maint = maintenance(store, ritual, pd, project, use_llm)
    debugging = bool(triggers.undelivered(store, project) and any(s["trigger"] == "repeated_failure" for s in triggers.undelivered(store, project)))
    mapped = outcome.map_phase(phase, ritual, "\n".join(signals), debugging)
    task = _task_text(pd, signals)
    tags = [f"project:{project}"] if project else []
    tags.append(f"ctx:{mapped}")
    if ritual:
        kind = ritual.split()[0]
        if model.vocab_status(store, f"ctx:ritual-{kind}") == "active":
            tags.append(f"ctx:ritual-{kind}")
    tags += _vocab_tags_in_text(store, task)
    exclude = _exclude_ids(store, project, _env_int("LIBRARIAN_EXCLUDE_WAKES", EXCLUDE_WAKES_DEFAULT))
    # A project's first wakes also get earlier briefs' memories that match the brief.
    transfer_task = ""
    wakes = store.q1("SELECT COUNT(*) FROM requests WHERE kind = 'pack' AND project IS ?", (project,))[0]
    brief_start = wakes < _env_int("LIBRARIAN_TRANSFER_WAKES", TRANSFER_WAKES_DEFAULT)
    lessons_on = os.environ.get("LIBRARIAN_LESSONS", "1").strip() != "0"
    if lessons_on:
        _open_brief_lesson(store, project)
    if brief_start:
        others = store.q1("SELECT 1 FROM nodes WHERE project IS NOT ? AND type IN ('skill','fact','decision','retrospective') AND status IN ('active','probationary') LIMIT 1", (project,))
        if others is not None:
            transfer_task = current_brief(_read(pd / "spec.md", 200000))[:BRIEF_HEAD_CHARS]
    req = pack.PackRequest(
        task=task,
        tags=tags,
        project=project,
        phase=mapped,
        budget=int(budget or _env_int("LIBRARIAN_PACK_TOKENS", 5000)),
        exclude_ids=exclude,
        log=True,
        use_llm=use_llm,
        ritual=ritual,
        transfer_task=transfer_task,
        lessons=lessons_on,
        brief_start=brief_start,
    )
    pk = pack.build(store, req)
    settle_captures(store, [], project, use_llm)
    (rd / REQUEST_FILE).write_text(
        json.dumps(
            {
                "request_id": pk.request_id,
                "pack_ids": pk.ids(),
                "task_ids": pk.ids("task") + pk.ids("transfer") + pk.ids("lesson") + pk.ids("practice"),
                "ritual": ritual,
                "phase": mapped,
                "project": project,
                "tags": tags,
                "ts": db.now_iso(),
                "maintenance": maint,
            }
        )
    )
    extra = (_lesson_signals(store, project, pk.request_id, mapped) + _premortem_signal(pd, project, brief_start)) if lessons_on else []
    _signals_out(store, project, rd, extra)
    sys.stdout.write(pack.render_text(pk) + "\n")
    return 0


# ── lessons ──────────────────────────────────────────────────────────────────


def _lesson_proposed(store: db.Store, request_id: str) -> Optional[str]:
    """The id of a lesson proposed during the wake whose pack was ``request_id``."""
    for n in model.nodes_where(store, "type IN ('retrospective','skill','decision') AND json_extract(provenance, '$.run_id') = ?", (request_id,)):
        if pack.is_lesson(n):
            return n.id
    return None


def _open_brief_lesson(store: db.Store, project: Optional[str]) -> None:
    """On a project's first wake: if the brief before it left no retrospective, open a LESSON DUE."""
    if not project:
        return
    if store.q1("SELECT 1 FROM requests WHERE kind = 'pack' AND project IS ?", (project,)) is not None:
        return
    prev = store.q1("SELECT project FROM requests WHERE kind = 'pack' AND project IS NOT NULL AND project != ? ORDER BY ts DESC LIMIT 1", (project,))
    if prev is None:
        return
    prev = prev[0]
    has_retro = store.q1(
        "SELECT 1 FROM nodes n WHERE n.type = 'retrospective' AND n.status IN ('active','probationary') AND (n.project = ? OR EXISTS (SELECT 1 FROM tags t WHERE t.node_id = n.id AND t.tag = ?))",
        (prev, f"project:{prev}"),
    )
    if has_retro is not None or store.q1("SELECT 1 FROM pending_lesson WHERE kind = 'brief' AND ref = ?", (prev,)) is not None:
        return
    with store.write():
        store.ex("INSERT INTO pending_lesson(id, kind, ref, project, created) VALUES (?,?,?,?,?)", ("L" + db.ulid()[-8:], "brief", prev, project, db.now_iso()))


def record_claims(store: db.Store, project: Optional[str], verdicts: list[dict], reviews: dict[str, str]) -> dict[str, list[str]]:
    """Store the reviewer's claim verdicts, once per review file and claim; return, for each
    file that broke or weakened a claim, its failure classes (most frequent first)."""
    out: dict[str, list[str]] = {}
    ts = db.now_iso()
    broken_files = {v["file"] for v in verdicts if v["verdict"] == "BROKEN"}
    with store.write():
        for f, text in sorted(reviews.items()):
            claims = outcome.claim_verdicts(text)
            if not claims and f in broken_files:
                # No claim lines (an older review form): one row for the whole file.
                claims = [{"claim": "*", "verdict": "BROKEN", "class": c} for c in (outcome.failure_classes(text) or ["other"])][:1]
            for c in claims:
                store.ex(
                    "INSERT OR IGNORE INTO review_claim(file, claim, verdict, class, project, ts) VALUES (?,?,?,?,?,?)",
                    (f, c["claim"], c["verdict"], c["class"], project, ts),
                )
            if any(c["verdict"] in outcome.NOT_STANDING for c in claims):
                out[f] = outcome.failure_classes(text) or ["other"]
    return out


def _guarding_lessons(store: db.Store, classes: list[str]) -> dict[str, list[str]]:
    """For each failure class, the lessons already tagged as guarding against it."""
    out: dict[str, list[str]] = {}
    for c in classes:
        if c == "other":
            continue
        ids = [
            n.id
            for n in model.nodes_where(store, "status IN ('active','probationary') AND id IN (SELECT node_id FROM tags WHERE tag = ?)", (f"fail:{c}",))
            if pack.is_lesson(n)
        ]
        if ids:
            out[c] = ids
    return out


def _unblamed(store: db.Store, files: list[str], verdicts: list[dict]) -> list[str]:
    """Review files whose reviewer broke a claim but whose Memories lines name no BROKEN memory."""
    blamed = {v["file"] for v in verdicts if v["verdict"] == "BROKEN" and v.get("ids")}
    return [f for f in files if f not in blamed]


def _open_review_lesson(store: db.Store, project: Optional[str], verdicts: list[dict], classes: Optional[dict[str, list[str]]] = None) -> None:
    """A review that broke a claim may hold a lesson: one LESSON DUE for the next wake."""
    files = sorted({v["file"] for v in verdicts if v["verdict"] == "BROKEN"} | set(classes or {}))
    if not files:
        return
    # A review file is often edited again later (its Memories lines); it holds one lesson moment.
    # Review rows ignore the project: a lesson is about how the mind works, not one brief, and a
    # review's wake can start under one brief and end under the next (run D's trial).
    seen: set = set()
    for r in store.q("SELECT ref FROM pending_lesson WHERE kind = 'review'"):
        seen |= set(json.loads(r[0]))
    files = [f for f in files if f not in seen]
    if not files:
        return
    cls = sorted({c for f in files for c in (classes or {}).get(f, [])})
    unblamed = _unblamed(store, [f for f in files if f in (classes or {})], verdicts)
    # The guards are the lessons that existed when the review landed, not ones written after it
    # (run D's trial named a lesson written in answer to this very review).
    guarded = _guarding_lessons(store, cls)
    with store.write():
        row = store.q1("SELECT id, ref, detail FROM pending_lesson WHERE kind = 'review' AND cleared IS NULL AND delivered = 0")
        if row is not None:
            old = json.loads(row["detail"] or "{}")
            ref = sorted(set(json.loads(row["ref"])) | set(files))
            merged = {c: sorted(set(ids) | set(guarded.get(c, []))) for c, ids in old.get("guarded", {}).items()}
            merged.update({c: ids for c, ids in guarded.items() if c not in merged})
            detail = {
                "classes": sorted(set(cls) | set(old.get("classes", []))),
                "unblamed": sorted(set(unblamed) | set(old.get("unblamed", []))),
                "guarded": merged,
            }
            store.ex("UPDATE pending_lesson SET ref = ?, detail = ? WHERE id = ?", (json.dumps(ref), json.dumps(detail), row["id"]))
            return
        store.ex(
            "INSERT INTO pending_lesson(id, kind, ref, project, created, detail) VALUES (?,?,?,?,?,?)",
            ("L" + db.ulid()[-8:], "review", json.dumps(files), project, db.now_iso(), json.dumps({"classes": cls, "unblamed": unblamed, "guarded": guarded})),
        )


def _lesson_signals(store: db.Store, project: Optional[str], request_id: str, phase: str) -> list[str]:
    """LESSON DUE lines for this wake; marks each row delivered to this wake's pack."""
    lines: list[str] = []
    with store.write():
        for row in store.q("SELECT * FROM pending_lesson WHERE cleared IS NULL AND (project IS ? OR kind = 'review') ORDER BY created", (project,)):
            if row["kind"] == "brief":
                lines.append(
                    f"- LESSON DUE ({row['id']}): the previous brief ({row['ref']}) closed without a retrospective. Before this brief's work, write one: "
                    f'`librarian propose --type retrospective --summary "When starting a modeling brief: <what to do differently>" --tags area:process ctx:planning --body-file <f>`, '
                    "with what you would redo, what cost the most and what should carry to later briefs, each with its evidence (review files, commits). "
                    "It is shown in [LESSONS] on later briefs' first wakes."
                )
            else:
                files = ", ".join(json.loads(row["ref"]))
                detail = json.loads(row["detail"] or "{}")
                classes = [c for c in detail.get("classes", []) if c != "other"]
                fail_tags = " ".join(f"fail:{c}" for c in classes) or "fail:<class>"
                line = (
                    f"- LESSON DUE ({row['id']}): {files} found BROKEN claims"
                    + (f" (failure classes: {', '.join(classes)})" if classes else "")
                    + ". If a break shows a way of working you could have avoided (not just a wrong number), "
                    f'write one lesson: `librarian propose --type retrospective --summary "When <situation>: <what to do>" --tags area:process ctx:{phase} {fail_tags} --body-file <f>` naming the review as evidence. '
                )
                guarded = {c: ids for c, ids in detail["guarded"].items() if c in classes} if "guarded" in detail else _guarding_lessons(store, classes)
                if guarded:
                    named = "; ".join(f"{c}: {' '.join(ids)}" for c, ids in guarded.items())
                    line += (
                        f"This kind of mistake happened again although lessons guard against it ({named}). If you followed the lesson and it still broke, "
                        "sharpen it (`librarian propose --supersedes <id>`); if you did not follow it, say why in the journal. "
                    )
                if detail.get("unblamed"):
                    line += (
                        f"The reviewer broke claims in {', '.join(detail['unblamed'])}, but no `Memories BROKEN:` line there names a memory: "
                        "if a memory or episode held a broken value, add that line with its id. "
                    )
                lines.append(line + "If it was a one-off, write none. This signal shows once.")
            store.ex("UPDATE pending_lesson SET delivered = delivered + 1, last_request = ? WHERE id = ?", (request_id, row["id"]))
    return lines


def _settle_lessons(store: db.Store, request_id: str) -> list[dict]:
    """After a wake: clear the LESSON DUE rows it was shown, by the lesson it proposed or by expiry."""
    out = []
    limit = _env_int("LIBRARIAN_BRIEF_LESSON_WAKES", BRIEF_LESSON_WAKES_DEFAULT)
    proposed = _lesson_proposed(store, request_id)
    with store.write():
        for row in store.q("SELECT * FROM pending_lesson WHERE cleared IS NULL AND last_request = ?", (request_id,)):
            by = proposed or ("none" if row["kind"] == "review" else "expired" if row["delivered"] >= limit else None)
            if by is None:
                continue
            store.ex("UPDATE pending_lesson SET cleared = ?, cleared_by = ? WHERE id = ?", (db.now_iso(), by, row["id"]))
            out.append({"id": row["id"], "kind": row["kind"], "cleared_by": by})
    return out


def _premortem_signal(pd: Path, project: Optional[str], brief_start: bool) -> list[str]:
    """On a brief's first wakes, until project/risks.md has a section for this brief."""
    if not project or not brief_start:
        return []
    if re.search(rf"^#+\s.*{re.escape(project)}", _read(pd / RISKS_FILE), re.M):
        return []
    return [
        f"- PREMORTEM DUE: before this brief's first piece of work, append to project/{RISKS_FILE} a section headed `## {project}` with the three ways "
        "this brief is most likely to go wrong, each with its failure class (fail:<class>) and the lesson or practice id that guards against it, or `none`. "
        "Later reviews will show which ones happened."
    ]


def _ledger_lessons(pd: Path, review: str, review_text: str) -> list[str]:
    """Lessons blind recorded when it ran the review saved as ``review``: by its --out
    path, or by its verdict line when that is long enough to tell reviews apart."""
    out: list[str] = []
    for line in _read(pd / BLIND_LEDGER, 2_000_000).splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        v = str(row.get("verdict") or "").strip()
        dest = str(row.get("out") or "").strip()
        if (dest and (dest == review or dest.endswith("/" + review))) or (len(v) >= LEDGER_VERDICT_MIN and v in review_text):
            out += [i for i in row.get("lessons", []) if i not in out]
    return out


def _claims_path(review: str) -> str:
    """reviews/x-adversary.md → reviews/x-claims.md: the file the review was asked to judge."""
    return re.sub(r"-(adversary|review|verdicts?)\.md$", "", review) + "-claims.md"


def lesson_credit(store: db.Store, pd: Path, verdicts: list[dict], reviews: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Lessons a reviewed piece of work applied → that review's outcome.

    The lessons must have been named before the verdict was known: on a ``Lessons
    applied:`` line that blind recorded when it ran the review (its ledger, matched
    by the verdict line), or one already committed in the claims file, its
    ``-lessons.md`` sidecar or the review file as an earlier wake left it. A lesson
    named by several reviews this wake takes the worst outcome.

    The reviewer's claim verdicts decide: every claim survived → success; none stood →
    failure; mixed → failure only for a lesson tagged against (fail:) a class the review
    found, else nothing. Each review judges each lesson once.
    """
    by_file: dict[str, list[dict]] = {}
    for v in verdicts:
        by_file.setdefault(v["file"], []).append(v)
    out: dict[str, str] = {}
    judged: list[tuple[str, str, str]] = []
    for f, vs in by_file.items():
        text = (reviews or {}).get(f) or _read(pd / f)
        claims = outcome.claim_verdicts(text)
        oc = outcome.review_outcome(vs, claims)
        found = {c["class"] for c in claims if c["class"]}
        if oc is None and not found:
            continue
        claims = _claims_path(f)
        text = "\n".join(_git(pd, "show", f"HEAD:{x}") for x in (claims, claims.removesuffix("-claims.md") + "-lessons.md", f))
        named = outcome.applied_lessons(text)
        named += [i for i in _ledger_lessons(pd, f, _read(pd / f)) if i not in named]
        for i in named:
            n = model.get_node(store, i, with_edges=False)
            if n is None or not pack.is_lesson(n) or out.get(n.id) == "failure":
                continue
            if store.q1("SELECT 1 FROM lesson_judged WHERE file = ? AND node_id = ?", (f, n.id)) is not None:
                continue
            noc = oc if oc is not None else ("failure" if any(t.startswith("fail:") and t[5:] in found for t in n.tags) else None)
            if noc is None:
                continue
            out[n.id] = noc
            judged.append((f, n.id, noc))
    with store.write():
        for f, nid, oc in judged:
            store.ex("INSERT OR IGNORE INTO lesson_judged(file, node_id, outcome, ts) VALUES (?,?,?,?)", (f, nid, oc, db.now_iso()))
    return out


# ── post ─────────────────────────────────────────────────────────────────────


def _traj_steps(run_id: Optional[str]) -> list[dict]:
    if not run_id:
        return []
    tdir = os.environ.get("TRAJ_DIR", "").strip()
    tid = os.environ.get("TRAJ_ID", "").strip()
    if not tdir or not tid:
        return []
    root = Path(tdir)
    candidates = [root / tid / "trajectory.jsonl", root / f"{tid}.jsonl"]
    prefix = tid[:8]
    candidates += sorted(root.glob(f"**/{prefix}-*/trajectory.jsonl"))
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        return []
    steps: list[dict] = []
    try:
        with path.open(errors="replace") as fh:
            for line in fh:
                if run_id not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("run_id") == run_id or obj.get("step_id") == run_id:
                    steps.append(obj)
    except OSError:
        return []
    return steps


def _ritual_written(ritual: Optional[str], dirty: list[str], pd: Path) -> bool:
    if not ritual:
        return False
    parts = ritual.split()
    kind, arg = parts[0], (parts[1] if len(parts) > 1 else "")
    target = {
        "daily": f"daily/{arg}.md",
        "weekly": f"reports/week-{arg}.md",
        "final": "reports/final.md",
        "freetime": f"free-time/week-{arg}/report.md",
    }.get(kind)
    if not target:
        return False
    if target in dirty:
        return True
    if kind == "final":
        return (pd / target).exists() and target in dirty
    return False


def _added_lines(pd: Path, f: str) -> str:
    """The lines this wake added to ``f``: the + side of its diff, or the whole file when it is new."""
    diff = _git(pd, "diff", "--", f)
    if not diff.strip():
        return _read(pd / f, 60000)
    return "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))


def _review_texts(pd: Path, dirty: list[str]) -> dict[str, str]:
    out = {}
    for f in dirty:
        if f.startswith("reviews/") and f.endswith(".md"):
            out[f] = _read(pd / f, 60000)
    return out


def _capture(store: db.Store, steps: list[dict], project: Optional[str], run_id: Optional[str], tags: list[str], use_llm: bool) -> dict:
    """Open pending captures for resolved failures, then settle the open ones."""
    report: dict = {"opened": [], "cleared": [], "expired": []}
    base_tags = [t for t in tags if not t.startswith("ctx:")]
    with store.write():
        for rf in outcome.detect_resolved_failures(steps):
            if store.q1("SELECT 1 FROM pending_capture WHERE signature = ? AND project IS ? AND cleared IS NULL", (rf["signature"], project)):
                continue
            fam = rf.get("family") or ""
            ctags = list(base_tags) + ([f"pkg:{model.normalize_tag(fam)}"] if fam else []) + ["area:tooling"]
            cid = "C" + db.ulid()[-8:]
            store.ex(
                "INSERT INTO pending_capture(id, signature, tags, project, run_id, span, created) VALUES (?,?,?,?,?,?,?)",
                (cid, rf["signature"], json.dumps(ctags), project, run_id, json.dumps(rf["span"]), db.now_iso()),
            )
            report["opened"].append({"id": cid, "signature": rf["signature"]})
    settled = settle_captures(store, steps, project, use_llm)
    report["cleared"] = settled["cleared"]
    report["expired"] = settled["expired"]
    return report


def settle_captures(store: db.Store, steps: list[dict], project: Optional[str], use_llm: bool) -> dict:
    """Clear open captures a skill now covers; auto-draft or archive the expired ones.

    Runs in ``post`` and again in ``pre``, so a skill proposed during a wake
    clears its CAPTURE signal before the next prompt is built.
    """
    report: dict = {"cleared": [], "expired": []}
    ttl_days = _env_int("LIBRARIAN_CAPTURE_TTL_DAYS", CAPTURE_TTL_DAYS_DEFAULT)
    with store.write():
        for row in store.q("SELECT * FROM pending_capture WHERE cleared IS NULL AND project IS ?", (project,)):
            ctags = set(json.loads(row["tags"] or "[]"))
            sig_tokens = set(model.tokenize(row["signature"]))
            match = None
            for n in model.nodes_where(store, "type = 'skill' AND created >= ? AND status IN ('active','probationary')", (row["created"],)):
                if (ctags & set(n.tags)) and (sig_tokens & set(model.tokenize(n.summary + " " + n.body)) or row["signature"][:40] in n.body):
                    match = n
                    break
                if row["signature"][:40] in (n.body or ""):
                    match = n
                    break
            if match is not None:
                store.ex("UPDATE pending_capture SET cleared = ?, cleared_by = ? WHERE id = ?", (db.now_iso(), match.id, row["id"]))
                report["cleared"].append({"id": row["id"], "skill": match.id})
                continue
            if (db.age_days(row["created"]) or 0.0) >= ttl_days:
                drafter = llm.get_llm("draft", use_llm)
                drafted = None
                if drafter is not None:
                    span_text = "\n".join(
                        f"[{s.get('type')}] {(s.get('thought') or s.get('content') or '')[:600]}\n$ {(s.get('cmd') or '')[:400]}\n{(s.get('stderr') or s.get('stdout') or '')[:400]}"
                        for s in steps
                    )[:10000]
                    drafted = lifecycle._draft(drafter, f'Write the skill that resolved the error "{row["signature"]}": symptom, cause, exact fix command, verified on.', span_text)
                if drafted:
                    cand = gate.Candidate(
                        type="skill",
                        summary=drafted[0],
                        body=drafted[1],
                        tags=sorted(ctags),
                        provenance={"author": "librarian", "method": "auto-draft", "run_id": row["run_id"], "span": json.loads(row["span"] or "[]"), "model": drafter.model, "prompt_version": llm.PROMPT_VERSION},
                        project=project,
                        confidence=0.4,
                    )
                    res = gate.apply(store, cand)
                    if res.accepted and res.id:
                        store.ex("UPDATE pending_capture SET cleared = ?, cleared_by = ? WHERE id = ?", (db.now_iso(), res.id, row["id"]))
                        report["cleared"].append({"id": row["id"], "skill": res.id, "auto_draft": True})
                        continue
                store.ex("UPDATE pending_capture SET cleared = ?, cleared_by = 'undrafted' WHERE id = ?", (db.now_iso(), row["id"]))
                report["expired"].append(row["id"])
    return report


def post(rc: int, run_id: Optional[str], stderr_tail: str, final: str, use_llm: bool = True) -> int:
    rd = run_dir()
    pd = project_dir()
    if rd is None or pd is None or not (rd / REQUEST_FILE).exists():
        return 0
    try:
        req = json.loads((rd / REQUEST_FILE).read_text())
    except ValueError:
        (rd / REQUEST_FILE).unlink(missing_ok=True)
        return 0
    store = _open_store()
    if store is None:
        return 0
    project = req.get("project")
    phase = req.get("phase")
    ritual = req.get("ritual")
    dirty = dirty_files(pd) if (pd / ".git").exists() else []
    steps = _traj_steps(run_id)
    sigs = outcome.error_signatures(steps)
    tool_calls = sum(1 for s in steps if s.get("type") == "shell-output")
    if rc != 0 and tool_calls == 0 and not (final or "").strip():
        # The run never acted (e.g. the model API was down): no evidence about any memory, so no
        # episode and no credit. Blaming the pack here would punish memories for an outage.
        (rd / REQUEST_FILE).unlink(missing_ok=True)
        sys.stdout.write(json.dumps({"episode": None, "outcome": None, "criterion": f"run never acted (rc={rc})"}) + "\n")
        return 0
    # Cited ids: fetch log, ULIDs the mind wrote in this run's steps, FINAL and the lines this
    # wake added to the human records. The prompt (which carries the pack) and host feedback are
    # not the mind's writing, and old record lines were cited by the wakes that wrote them.
    text_blob = final + "\n" + "\n".join(
        str(s.get("thought") or "") + "\n" + str(s.get("content") or "") + "\n" + str(s.get("cmd") or "")
        for s in steps
        if s.get("type") not in ("prompt", "feedback")
    )
    for f in ("journal.md", "project-memory.md"):
        if f in dirty:
            text_blob += "\n" + _added_lines(pd, f)
    reviews = _review_texts(pd, dirty)
    for t in reviews.values():
        text_blob += "\n" + t
    cited = [
        i
        for i in outcome.find_ulids(text_blob)
        if model.get_node(store, i, with_edges=False) is not None and (i not in req.get("pack_ids", []) or i in req.get("task_ids", []))
    ]
    verdicts = outcome.review_verdicts(reviews)
    known_ids = set(req.get("pack_ids", [])) | set(cited)
    for v in verdicts:
        v["ids"] = [i for i in v["ids"] if i in known_ids or model.get_node(store, i, with_edges=False) is not None]
    recurred = []
    for sig in sigs:
        row = store.q1("SELECT cleared_by FROM pending_capture WHERE signature = ? AND project IS ? AND cleared_by IS NOT NULL AND cleared_by != 'undrafted'", (sig, project))
        if row is not None:
            recurred.append({"signature": sig, "skill_id": row[0]})
    ev = outcome.WakeEvidence(
        rc=rc,
        stderr_tail=stderr_tail or "",
        final=final or "",
        ritual=ritual,
        ritual_output_written=_ritual_written(ritual, dirty, pd),
        journal_dirty="journal.md" in dirty,
        dirty_files=dirty,
        review_verdicts=verdicts,
        recurred=recurred,
        cited_ids=cited,
    )
    oc, criterion, overrides = outcome.decide_outcome(ev)
    lessons = lesson_credit(store, pd, verdicts, reviews) if (pd / ".git").exists() else {}
    dismissed = [r[0] for r in store.q("SELECT DISTINCT node_id FROM dismissals WHERE request_id = ?", (req["request_id"],))]
    cited = [i for i in cited if i not in dismissed]
    body_parts = [f"FINAL: {final.strip()[:1500]}" if final.strip() else "FINAL: (none)"]
    if "journal.md" in dirty:
        body_parts.append("Journal diff:\n" + _git(pd, "diff", "--", "journal.md")[:2500])
    if sigs:
        body_parts.append("Errors:\n" + "\n".join(f'error "{s}"' for s in sigs[:10]))
    if cited:
        body_parts.append("Cited: " + " ".join(cited))
    body_parts.append(f"Outcome: {oc} ({criterion}); rc={rc}; tool calls={tool_calls}; dirty={' '.join(dirty[:20])}")
    summary = (final.strip().splitlines()[0][:200] if final.strip() else f"wake: {criterion}")
    try:
        report = lifecycle.close_episode(
            store,
            outcome=oc,
            criterion=criterion,
            summary=summary,
            body="\n\n".join(body_parts),
            tags=req.get("tags", []),
            project=project,
            phase=phase,
            cited=cited,
            request_ids=[req["request_id"]],
            overrides=overrides,
            provenance={"author": "runtime", "run_id": run_id, "request_id": req["request_id"], "ritual": ritual, "noop": not cited and set(dirty) <= BOOKKEEPING_FILES},
            dismissed=dismissed,
            lessons=lessons,
        )
    except ValueError as exc:
        print(f"librarian: episode not recorded: {exc}", file=sys.stderr)
        report = None
    if report is not None:
        # Memories proposed during this wake were derived from its episode, so
        # a hop from a lesson reaches the wake that learned it, and decay can
        # retire the episode once its lessons are active.
        with store.write():
            for r in store.q(
                "SELECT id FROM nodes WHERE type IN ('skill','fact','decision','retrospective') AND json_extract(provenance, '$.run_id') = ?",
                (req["request_id"],),
            ):
                model.add_edge(store, r[0], report.episode_id, "derived_from", 1.0, {"by": "runtime"})
    settled_lessons = _settle_lessons(store, req["request_id"])
    failures = record_claims(store, project, verdicts, reviews)
    if os.environ.get("LIBRARIAN_LESSONS", "1").strip() != "0":
        _open_review_lesson(store, project, verdicts, failures)
    prog = triggers.evaluate(
        store,
        triggers.Progress(status=final or criterion, tags=req.get("tags", []), phase=phase, project=project, tool_calls=tool_calls, errors=sigs, run_id=run_id),
        use_llm=use_llm,
    )
    cap = _capture(store, steps, project, run_id, req.get("tags", []), use_llm)
    ident = identity_dir()
    export_report = None
    if ident is not None:
        try:
            export_report = exchange.export_store(store, ident / "librarian" / "export", "md", pd, project)
        except OSError as exc:
            print(f"librarian: export failed: {exc}", file=sys.stderr)
    (rd / REQUEST_FILE).unlink(missing_ok=True)
    out = {
        "episode": report.to_dict() if report else None,
        "outcome": oc,
        "criterion": criterion,
        "cited": cited,
        "suggestion": prog.get("suggestion"),
        "capture": cap,
        "lessons": {"credited": lessons, "settled": settled_lessons},
        "failures": failures,
        "recurred": recurred,
        "export": export_report,
    }
    sys.stdout.write(json.dumps(out) + "\n")
    return 0
