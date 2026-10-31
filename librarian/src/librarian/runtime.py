"""``runtime pre`` and ``runtime post``: the two hooks the monolith step calls.

``pre`` runs before the model: the context request, the pack, and the signal
lines for this wake (CAPTURE, LESSON DUE, PREMORTEM DUE, CONSISTENCY).
``post`` runs after: the outcome from artifacts, the episode and its
citations, facts the reviewer confirmed, the claim verdicts, resolved
failures, and the lesson judgment at a brief's close. No model call in
either. The model's self-report is never evidence of success.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import consistency, db, exchange, gate, lifecycle, model, outcome, pack

REQUEST_FILE = "librarian_request.json"
SIGNALS_FILE = "librarian_signals"
NO_STORE_MARKER = ".no-store-noted"
CAPTURE_TTL_DAYS_DEFAULT = 3
EXCLUDE_WAKES_DEFAULT = 1
BRIEF_START_WAKES_DEFAULT = 3
# A closed brief's LESSON DUE signal shows on this many wakes at most.
BRIEF_LESSON_WAKES_DEFAULT = 3
RISKS_FILE = "risks.md"
# Files a wake can change without doing project work.
BOOKKEEPING_FILES = {"STATE", "librarian.md", "shared-values.md", "questions-summary.md"}
SIGNAL_LINES = ("- RITUAL DUE", "- FREE TIME", "- HUMAN ANSWER", "- DEFAULT DUE", "- STALL", "- DELIVERABLE", "- DEADLINE", "- FINAL STRETCH", "- GUARD", "- THE RUN HAS ENDED")
# A lesson is judged at a brief's close by whether the class it guards recurred:
# the brief's rate of that class per review against the brief before it.
LESSON_JUDGE_MIN_REVIEWS = 3


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
    return [ln.strip()[:400] for ln in (text or "").splitlines() if any(ln.startswith(s) for s in SIGNAL_LINES)]


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


# ── pre ──────────────────────────────────────────────────────────────────────


def current_brief(spec: str) -> str:
    """The newest project brief in the spec: from its last top-level heading to the end."""
    heads = [m.start() for m in re.finditer(r"^# ", spec, flags=re.M)]
    return spec[heads[-1]:] if heads else spec


def _task_text(pd: Path, signals: list[str]) -> str:
    brief = current_brief(_read(pd / "spec.md", 200000))
    title = next((ln.strip("# ").strip() for ln in brief.splitlines() if ln.startswith("# ")), "")
    plan = "\n".join(_read(pd / "plan.md", 20000).splitlines()[:12])
    journal = _read(pd / "journal.md", 400000)
    blocks = re.split(r"^### ", journal, flags=re.M)
    last = ("### " + blocks[-1])[:1200] if len(blocks) > 1 else ""
    parts = [p for p in (title, plan, last, "\n".join(signals)) if p.strip()]
    return "\n\n".join(parts)


def _exclude_ids(store: db.Store, project: Optional[str], wakes: int) -> list[str]:
    """Task rows the last ``wakes`` packs showed that the mind neither cited nor fetched."""
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


def _capture_signals(store: db.Store, project: Optional[str]) -> list[str]:
    lines = []
    for row in store.q("SELECT * FROM pending_capture WHERE cleared IS NULL AND project IS ? ORDER BY created", (project,)):
        tags = json.loads(row["tags"] or "[]")
        lines.append(
            f'- CAPTURE: you resolved "{row["signature"]}" after repeated failures (wake {row["created"][:16]}). Write the fix down once: '
            f"`librarian propose --type skill --summary \"<when would I want this?>\" --tags {' '.join(tags) or 'area:tooling'} --body-file <f>` "
            f"with symptom, cause, exact command, verified on. If a memory already covers it: `librarian capture clear {row['id']} --covered-by <id>`."
        )
    return lines


def _write_signals(rd: Path, lines: list[str]) -> None:
    path = rd / SIGNALS_FILE
    if lines:
        path.write_text("\n".join(lines) + "\n")
    elif path.exists():
        path.unlink()


def pre(ritual: Optional[str], phase: str, budget: Optional[int], signals_text: str, use_llm: bool = False) -> int:
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
    mapped = outcome.map_phase(phase, ritual, "\n".join(signals))
    task = _task_text(pd, signals)
    tags = [f"project:{project}"] if project else []
    tags.append(f"ctx:{mapped}")
    if ritual:
        kind = ritual.split()[0]
        if model.vocab_status(store, f"ctx:ritual-{kind}") == "active":
            tags.append(f"ctx:ritual-{kind}")
    tags += _vocab_tags_in_text(store, task)
    exclude = _exclude_ids(store, project, _env_int("LIBRARIAN_EXCLUDE_WAKES", EXCLUDE_WAKES_DEFAULT))
    wakes = store.q1("SELECT COUNT(*) FROM requests WHERE kind = 'pack' AND project IS ?", (project,))[0]
    brief_start = wakes < _env_int("LIBRARIAN_BRIEF_START_WAKES", BRIEF_START_WAKES_DEFAULT)
    lessons_on = os.environ.get("LIBRARIAN_LESSONS", "1").strip() != "0"
    if wakes == 0:
        close_previous_brief(store, project, pd, lessons_on)
    settle_captures(store, project)
    req = pack.PackRequest(
        task=task,
        tags=tags,
        project=project,
        phase=mapped,
        budget=int(budget or _env_int("LIBRARIAN_PACK_TOKENS", 2000)),
        exclude_ids=exclude,
        log=True,
        use_llm=use_llm,
        ritual=ritual,
        lessons=lessons_on,
        brief_start=brief_start,
        shared=os.environ.get("LIBRARIAN_SHARED", "1").strip() != "0",
    )
    pk = pack.build(store, req)
    (rd / REQUEST_FILE).write_text(
        json.dumps(
            {
                "request_id": pk.request_id,
                "pack_ids": pk.ids(),
                "task_ids": pk.ids("task") + pk.ids("lesson") + pk.ids("shared"),
                "ritual": ritual,
                "phase": mapped,
                "project": project,
                "tags": tags,
                "ts": db.now_iso(),
            }
        )
    )
    extra: list[str] = []
    if lessons_on:
        extra += _lesson_signals(store, project, pk.request_id)
        extra += _premortem_signal(pd, project, brief_start)
    if req.shared:
        extra += consistency.signals(store)
    extra += _capture_signals(store, project)
    _write_signals(rd, extra)
    sys.stdout.write(pack.render_text(pk) + "\n")
    return 0


# ── lessons: one moment per brief, judged by class recurrence ────────────────


def _class_rates(store: db.Store, project: Optional[str]) -> tuple[int, dict[str, float]]:
    """(reviews, {class: not-standing claims per review}) for a brief's reviews."""
    reviews = store.q1("SELECT COUNT(DISTINCT file) FROM review_claim WHERE project IS ?", (project,))[0]
    if not reviews:
        return 0, {}
    rates = {
        r[0]: r[1] / float(reviews)
        for r in store.q("SELECT class, COUNT(*) FROM review_claim WHERE project IS ? AND class IS NOT NULL AND verdict IN ('BROKEN','WEAKENED') GROUP BY class", (project,))
    }
    return reviews, rates


def judge_lessons(store: db.Store, closed: str, previous: Optional[str]) -> list[dict]:
    """At a brief's close: a lesson tagged fail:<class> written before the closed brief ended is
    confirmed when the class's not-standing rate fell against the brief before, and marked
    recurred when it rose. Needs at least LESSON_JUDGE_MIN_REVIEWS reviews on both sides."""
    if not previous:
        return []
    n_now, now = _class_rates(store, closed)
    n_prev, prev = _class_rates(store, previous)
    if n_now < LESSON_JUDGE_MIN_REVIEWS or n_prev < LESSON_JUDGE_MIN_REVIEWS:
        return []
    out = []
    ref = f"brief-close:{closed}"
    with store.write():
        for n in model.nodes_where(store, "type IN ('retrospective','skill','decision') AND status IN ('active','probationary') AND project IS NOT ?", (closed,)):
            if not pack.is_lesson(n):
                continue
            classes = [t[5:] for t in n.tags if t.startswith("fail:") and t[5:] != "other"]
            if not classes:
                continue
            deltas = [now.get(c, 0.0) - prev.get(c, 0.0) for c in classes]
            if all(d < 0 for d in deltas):
                oc = "confirmed"
            elif any(d > 0 for d in deltas):
                oc = "recurred"
            else:
                continue
            store.ex("INSERT OR IGNORE INTO lesson_judged(file, node_id, outcome, ts) VALUES (?,?,?,?)", (ref, n.id, oc, db.now_iso()))
            if oc == "confirmed" and n.status == "probationary":
                model.set_status(store, n.id, "active")
            out.append({"lesson": n.id, "outcome": oc, "classes": classes})
    return out


def close_previous_brief(store: db.Store, project: Optional[str], pd: Path, lessons_on: bool) -> dict:
    """On a brief's first wake: judge the lessons by the closed brief's reviews, open its
    LESSON DUE when it left no retrospective, and refresh the generated files."""
    report: dict = {}
    if not project:
        return report
    prev = store.q1("SELECT project FROM requests WHERE kind = 'pack' AND project IS NOT NULL AND project != ? ORDER BY ts DESC LIMIT 1", (project,))
    if prev is None:
        return report
    prev = prev[0]
    before = store.q1("SELECT project FROM requests WHERE kind = 'pack' AND project IS NOT NULL AND project NOT IN (?, ?) ORDER BY ts DESC LIMIT 1", (project, prev))
    report["judged"] = judge_lessons(store, prev, before[0] if before else None)
    if lessons_on:
        # A retrospective written during ``prev`` in answer to an earlier brief's LESSON DUE is
        # about that earlier brief, not about ``prev`` (the smoke trial of 2026-10-31 counted it).
        has_retro = store.q1(
            "SELECT 1 FROM nodes n WHERE n.type = 'retrospective' AND n.status IN ('active','probationary') AND n.project = ? "
            "AND n.id NOT IN (SELECT cleared_by FROM pending_lesson WHERE kind = 'brief' AND ref != ? AND cleared_by IS NOT NULL)",
            (prev, prev),
        )
        if has_retro is None and store.q1("SELECT 1 FROM pending_lesson WHERE kind = 'brief' AND ref = ?", (prev,)) is None:
            with store.write():
                store.ex("INSERT INTO pending_lesson(id, kind, ref, project, created) VALUES (?,?,?,?,?)", ("L" + db.ulid()[-8:], "brief", prev, project, db.now_iso()))
            report["lesson_due"] = prev
    try:
        exchange.export_project(store, pd, project)
    except OSError:
        pass
    return report


def _lesson_signals(store: db.Store, project: Optional[str], request_id: str) -> list[str]:
    lines: list[str] = []
    with store.write():
        for row in store.q("SELECT * FROM pending_lesson WHERE cleared IS NULL AND project IS ? AND kind = 'brief' ORDER BY created", (project,)):
            lines.append(
                f"- LESSON DUE ({row['id']}): the previous brief ({row['ref']}) closed without a retrospective. Before this brief's work, write one: "
                f'`librarian propose --type retrospective --summary "When starting a modeling brief: <what to do differently>" --tags area:process ctx:planning fail:<class> --body-file <f>`, '
                "with what you would redo, what cost the most, which shared values and methods carry to later briefs, and the failure classes its reviews found most, each with evidence (review files, commits)."
            )
            store.ex("UPDATE pending_lesson SET delivered = delivered + 1, last_request = ? WHERE id = ?", (request_id, row["id"]))
    return lines


def _settle_lessons(store: db.Store, request_id: str) -> list[dict]:
    out = []
    limit = _env_int("LIBRARIAN_BRIEF_LESSON_WAKES", BRIEF_LESSON_WAKES_DEFAULT)
    proposed = None
    for n in model.nodes_where(store, "type = 'retrospective' AND json_extract(provenance, '$.run_id') = ?", (request_id,)):
        proposed = n.id
        break
    with store.write():
        for row in store.q("SELECT * FROM pending_lesson WHERE cleared IS NULL AND last_request = ?", (request_id,)):
            by = proposed or ("expired" if row["delivered"] >= limit else None)
            if by is None:
                continue
            store.ex("UPDATE pending_lesson SET cleared = ?, cleared_by = ? WHERE id = ?", (db.now_iso(), by, row["id"]))
            out.append({"id": row["id"], "cleared_by": by})
    return out


def _premortem_signal(pd: Path, project: Optional[str], brief_start: bool) -> list[str]:
    if not project or not brief_start:
        return []
    if re.search(rf"^#+\s.*{re.escape(project)}", _read(pd / RISKS_FILE), re.M):
        return []
    return [
        f"- PREMORTEM DUE: before this brief's first piece of work, append to project/{RISKS_FILE} a section headed `## {project}` with the three ways "
        "this brief is most likely to go wrong, each with its failure class (fail:<class>) and the lesson or shared value that guards against it, or `none`."
    ]


# ── claims and facts ─────────────────────────────────────────────────────────


def record_claims(store: db.Store, project: Optional[str], reviews: dict[str, str]) -> dict[str, list[dict]]:
    """Store the reviewer's per-claim verdicts once per file; return them by file."""
    out: dict[str, list[dict]] = {}
    ts = db.now_iso()
    with store.write():
        for f, text in sorted(reviews.items()):
            claims = outcome.claim_verdicts(text)
            if not claims:
                continue
            for c in claims:
                store.ex(
                    "INSERT OR IGNORE INTO review_claim(file, claim, verdict, class, project, ts) VALUES (?,?,?,?,?,?)",
                    (f, c["claim"], c["verdict"], c["class"], project, ts),
                )
            out[f] = claims
    return out


def _claims_file_for(pd: Path, review: str) -> Optional[str]:
    """The claims file a review judged: <name>-claims.md next to <name>-adversary.md, or
    claims.md in the review's directory."""
    cands = [re.sub(r"-(adversary|review|verdicts?)\.md$", "-claims.md", review)]
    d = review.rsplit("/", 1)[0] if "/" in review else ""
    cands.append((d + "/" if d else "") + "claims.md")
    for c in cands:
        if c != review and (pd / c).exists():
            return c
    return None


def confirmed_facts(store: db.Store, pd: Path, project: Optional[str], claims_by_file: dict[str, list[dict]], tags: list[str], request_id: str) -> list[dict]:
    """Every claim the reviewer marked SURVIVES becomes a fact, written by the runtime with the
    review as provenance, so the mind spends no wake on proposing it. The fact's summary is
    the claim; its body names the claims file and the review."""
    out = []
    base_tags = [t for t in tags if not t.startswith("ctx:")]
    for review, claims in claims_by_file.items():
        cf = _claims_file_for(pd, review)
        if cf is None:
            continue
        texts = outcome.parse_claims(_read(pd / cf, 100000))
        for c in claims:
            if c["verdict"] != "SURVIVES":
                continue
            claim = texts.get(c["claim"])
            if not claim or not re.search(r"\d", claim):
                continue
            summary = claim if model.estimate_tokens(claim) <= model.SUMMARY_MAX_TOKENS else claim[: model.SUMMARY_MAX_TOKENS * 4 - 2].rsplit(" ", 1)[0] + " …"
            body = f"Claim {c['claim']} in {cf}: {claim}\n\nSurvived adversary review {review}."
            shared = re.findall(r"\bshared:[a-z0-9][a-z0-9-]*", claim)
            cand = gate.Candidate(
                type="fact",
                summary=summary,
                body=body,
                tags=base_tags + ["area:review"] + shared,
                provenance={"author": "runtime", "method": "review", "source": review, "run_id": request_id, "claim": c["claim"]},
                project=project,
                status="active",
            )
            res = gate.apply(store, cand)
            if res.accepted and res.id and res.action in ("stored", "superseded"):
                with store.write():
                    store.ex("UPDATE nodes SET status = 'active' WHERE id = ? AND status = 'probationary'", (res.id,))
                out.append({"id": res.id, "claim": c["claim"], "file": cf})
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
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        prefix = tid[:8]
        path = next(iter(sorted(root.glob(f"{prefix}-*/trajectory.jsonl"))), None)
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
    return bool(target) and target in dirty


def _added_lines(pd: Path, f: str) -> str:
    diff = _git(pd, "diff", "--", f)
    if not diff.strip():
        return _read(pd / f, 60000)
    return "\n".join(ln[1:] for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))


def _review_texts(pd: Path, dirty: list[str]) -> dict[str, str]:
    return {f: _read(pd / f, 60000) for f in dirty if f.startswith("reviews/") and f.endswith(".md")}


def settle_captures(store: db.Store, project: Optional[str]) -> dict:
    """Clear open captures a skill now covers; archive the expired ones (no auto-draft)."""
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
            elif (db.age_days(row["created"]) or 0.0) >= ttl_days:
                store.ex("UPDATE pending_capture SET cleared = ?, cleared_by = 'undrafted' WHERE id = ?", (db.now_iso(), row["id"]))
                report["expired"].append(row["id"])
    return report


def _capture(store: db.Store, steps: list[dict], project: Optional[str], run_id: Optional[str], tags: list[str]) -> dict:
    report: dict = {"opened": []}
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
    report.update(settle_captures(store, project))
    return report


def post(rc: int, run_id: Optional[str], stderr_tail: str, final: str, use_llm: bool = False) -> int:
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
    has_git = (pd / ".git").exists()
    dirty = dirty_files(pd) if has_git else []
    steps = _traj_steps(run_id)
    sigs = outcome.error_signatures(steps)
    tool_calls = sum(1 for s in steps if s.get("type") == "shell-output")
    if rc != 0 and tool_calls == 0 and not (final or "").strip():
        (rd / REQUEST_FILE).unlink(missing_ok=True)
        sys.stdout.write(json.dumps({"episode": None, "outcome": None, "criterion": f"run never acted (rc={rc})"}) + "\n")
        return 0
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
    ev = outcome.WakeEvidence(
        rc=rc,
        stderr_tail=stderr_tail or "",
        final=final or "",
        ritual=ritual,
        ritual_output_written=_ritual_written(ritual, dirty, pd),
        journal_dirty="journal.md" in dirty,
        dirty_files=dirty,
        review_verdicts=verdicts,
        cited_ids=cited,
    )
    oc, criterion, overrides = outcome.decide_outcome(ev)
    body_parts = [f"FINAL: {final.strip()[:1500]}" if final.strip() else "FINAL: (none)"]
    if sigs:
        body_parts.append("Errors:\n" + "\n".join(f'error "{s}"' for s in sigs[:10]))
    if cited:
        body_parts.append("Cited: " + " ".join(cited))
    body_parts.append(f"Outcome: {oc} ({criterion}); rc={rc}; tool calls={tool_calls}; dirty={' '.join(dirty[:20])}")
    summary = final.strip().splitlines()[0][:200] if final.strip() else f"wake: {criterion}"
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
        )
    except ValueError as exc:
        print(f"librarian: episode not recorded: {exc}", file=sys.stderr)
        report = None
    claims = record_claims(store, project, reviews)
    facts = confirmed_facts(store, pd, project, claims, req.get("tags", []), req["request_id"]) if has_git else []
    settled = _settle_lessons(store, req["request_id"])
    cap = _capture(store, steps, project, run_id, req.get("tags", []))
    export_report = None
    # Generated files: at rituals, when a shared fact or claim changed, or when the ledger is missing.
    shared_touched = any("shared:" in (t or "") for t in [text_blob]) or bool(facts) or not (pd / consistency.LEDGER_FILE).exists()
    if ritual or shared_touched or claims:
        try:
            export_report = exchange.export_project(store, pd, project)
            ident = identity_dir()
            if ritual and ident is not None:
                exchange.export_store(store, ident / "librarian" / "export", "md")
        except OSError as exc:
            print(f"librarian: export failed: {exc}", file=sys.stderr)
    (rd / REQUEST_FILE).unlink(missing_ok=True)
    out = {
        "episode": report.to_dict() if report else None,
        "outcome": oc,
        "criterion": criterion,
        "cited": cited,
        "claims": {f: len(c) for f, c in claims.items()},
        "facts": facts,
        "lessons": {"settled": settled},
        "capture": cap,
        "conflicts": [c["quantity"] for c in consistency.conflicts(store)],
        "export": export_report,
    }
    sys.stdout.write(json.dumps(out) + "\n")
    return 0
