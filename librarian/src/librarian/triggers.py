"""The progress feed and proactive suggestions.

Each wake's FINAL and error signatures are a ``progress_update``. The
librarian checks a fixed trigger table and emits at most one suggestion
per update, under a global cooldown (project time or tool calls), and
raises a detector's threshold when its suggestions keep getting dismissed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from . import db, llm, model, recall

COOLDOWN_SECONDS = 900
COOLDOWN_TOOL_CALLS = 50
REPEAT_WINDOW_SECONDS = 2 * 3600
REPEAT_THRESHOLD = 3
DECISION_THRESHOLD = 2
ACCEPTANCE_FLOOR = 0.2
ACCEPTANCE_MIN_RESPONSES = 5
BUMP_MAX = 3

TRIGGERS = ("repeated_failure", "decision_point", "deviation", "phase_drift", "contradiction_found", "new_tag")

_DECISION_RE = re.compile(r"\b(either|or|versus|vs\.?|alternatives?|options?|trade-?offs?|choos(?:e|ing)|decid(?:e|ing)|whether)\b", re.I)
_NEGATION_RE = re.compile(r"\b(not|never|no|don't|dont|avoid|without|rather than|instead of|stop)\b", re.I)
_ANTONYMS = (
    ("always", "never"),
    ("before", "after"),
    ("ask", "proceed"),
    ("explicit", "implicit"),
    ("small", "large"),
    ("flag", "hide"),
    ("lead", "bury"),
    ("sourced", "unsourced"),
    ("verify", "assume"),
    ("label", "unlabeled"),
    ("cite", "uncited"),
    ("source", "unsourced"),
)


@dataclass
class Progress:
    status: str
    tags: list[str] = field(default_factory=list)
    phase: Optional[str] = None
    project: Optional[str] = None
    tool_calls: int = 0
    errors: list[str] = field(default_factory=list)
    run_id: Optional[str] = None


_SIG_NUM = re.compile(r"\b\d+(?:\.\d+)?\b")
_SIG_HEX = re.compile(r"\b(?:0x)?[0-9a-f]{6,}\b", re.I)
_SIG_PATH = re.compile(r"(?:/[\w.\-]+){2,}")
_SIG_WS = re.compile(r"\s+")


def normalize_signature(line: str) -> str:
    """First meaningful line of an error, with digits, hex and paths normalized."""
    first = ""
    for ln in (line or "").splitlines():
        if ln.strip():
            first = ln.strip()
            break
    first = _SIG_PATH.sub("<path>", first)
    first = _SIG_HEX.sub("<hex>", first)
    first = _SIG_NUM.sub("<n>", first)
    return _SIG_WS.sub(" ", first)[:200]


def record_progress(store: db.Store, p: Progress) -> int:
    cur = store.ex(
        "INSERT INTO progress_log(project, phase, status, tags, tool_calls, errors, run_id, ts) VALUES (?,?,?,?,?,?,?,?)",
        (p.project, p.phase, p.status[:4000], json.dumps(model.parse_tags(p.tags)), int(p.tool_calls), json.dumps(p.errors), p.run_id, db.now_iso()),
    )
    store.ex(
        """INSERT INTO trigger_state(project, trigger, tool_calls_total) VALUES (?, '*', ?)
           ON CONFLICT(project, trigger) DO UPDATE SET tool_calls_total = trigger_state.tool_calls_total + excluded.tool_calls_total""",
        (p.project or "", int(p.tool_calls)),
    )
    for t in model.parse_tags(p.tags):
        model.upsert_vocab(store, t, "seen")
    return int(cur.lastrowid)


def _state(store: db.Store, project: Optional[str], trigger: str = "*") -> dict:
    r = store.q1("SELECT * FROM trigger_state WHERE project = ? AND trigger = ?", (project or "", trigger))
    return db.row_dict(r) if r else {"project": project or "", "trigger": trigger, "last_fired": None, "tool_calls_at_fire": None, "tool_calls_total": 0, "threshold_bump": 0}


def cooldown_state(store: db.Store, project: Optional[str]) -> dict:
    s = _state(store, project)
    if not s.get("last_fired"):
        return {"ready": True, "until": None, "calls_remaining": 0}
    since = db.age_seconds(s["last_fired"]) or 0.0
    calls_since = int(s.get("tool_calls_total") or 0) - int(s.get("tool_calls_at_fire") or 0)
    ready = since >= COOLDOWN_SECONDS or calls_since >= COOLDOWN_TOOL_CALLS
    until = db.iso(db.parse_ts(s["last_fired"]) + db.dt.timedelta(seconds=COOLDOWN_SECONDS)) if not ready else None
    return {"ready": ready, "until": until, "calls_remaining": max(0, COOLDOWN_TOOL_CALLS - calls_since)}


def bump(store: db.Store, project: Optional[str], trigger: str) -> int:
    return int(_state(store, project, trigger).get("threshold_bump") or 0)


def _stem(tok: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(tok) > len(suf) + 3 and tok.endswith(suf):
            return tok[: -len(suf)]
    return tok


def heuristic_contradiction(a: str, b: str) -> bool:
    """Same topic (stemmed token Jaccard ≥ 0.25) and a flipped negation or an antonym pair across the two."""
    ta, tb = {_stem(t) for t in model.tokenize(a)}, {_stem(t) for t in model.tokenize(b)}
    if model.jaccard(ta, tb) < 0.25:
        return False
    na, nb = len(_NEGATION_RE.findall(a)) % 2, len(_NEGATION_RE.findall(b)) % 2
    if na != nb:
        return True
    la, lb = a.lower(), b.lower()
    for x, y in _ANTONYMS:
        if (re.search(rf"\b{x}\b", la) and re.search(rf"\b{y}\b", lb)) or (re.search(rf"\b{y}\b", la) and re.search(rf"\b{x}\b", lb)):
            return True
    return False


def _suggest(store: db.Store, trigger: str, memory_ids: list[str], rationale: str, project: Optional[str]) -> dict:
    sid = "S" + db.ulid()[-8:]
    ts = db.now_iso()
    store.ex(
        "INSERT INTO suggestions(id, trigger, memory_ids, rationale, project, ts) VALUES (?,?,?,?,?,?)",
        (sid, trigger, json.dumps(memory_ids), rationale, project, ts),
    )
    total = int(_state(store, project).get("tool_calls_total") or 0)
    store.ex(
        """INSERT INTO trigger_state(project, trigger, last_fired, tool_calls_at_fire, tool_calls_total) VALUES (?, '*', ?, ?, ?)
           ON CONFLICT(project, trigger) DO UPDATE SET last_fired = excluded.last_fired, tool_calls_at_fire = excluded.tool_calls_at_fire""",
        (project or "", ts, total, total),
    )
    store.ex(
        """INSERT INTO trigger_state(project, trigger, last_fired) VALUES (?, ?, ?)
           ON CONFLICT(project, trigger) DO UPDATE SET last_fired = excluded.last_fired""",
        (project or "", trigger, ts),
    )
    for mid in memory_ids:
        store.ex(
            "INSERT INTO retrieval_log(request_id, node_id, source, section, project, ts) VALUES (?,?,?,?,?,?)",
            (sid, mid, "suggestion", trigger, project, ts),
        )
    return {"id": sid, "trigger": trigger, "memory_ids": memory_ids, "rationale": rationale}


def _recent_progress(store: db.Store, project: Optional[str], seconds: int) -> list[dict]:
    rows = store.q("SELECT * FROM progress_log WHERE project IS ? ORDER BY id DESC LIMIT 50", (project,))
    out = []
    for r in rows:
        d = db.row_dict(r)
        age = db.age_seconds(d["ts"]) or 0.0
        if age <= seconds:
            try:
                d["errors"] = json.loads(d["errors"])
            except ValueError:
                d["errors"] = []
            out.append(d)
    return out


def detect_repeated_failure(store: db.Store, p: Progress) -> Optional[tuple[str, int]]:
    if not p.errors:
        return None
    recent = _recent_progress(store, p.project, REPEAT_WINDOW_SECONDS)
    threshold = REPEAT_THRESHOLD + bump(store, p.project, "repeated_failure")
    for sig in dict.fromkeys(p.errors):
        count = sum(1 for row in recent if sig in row["errors"])
        if count >= threshold:
            return sig, count
    return None


def detect_decision_point(store: db.Store, p: Progress) -> bool:
    hits = len(_DECISION_RE.findall(p.status or ""))
    return hits >= DECISION_THRESHOLD + bump(store, p.project, "decision_point")


def detect_deviation(store: db.Store, p: Progress, use_llm: bool) -> Optional[model.Node]:
    tags = set(model.parse_tags(p.tags))
    nodes = model.nodes_where(store, "type IN ('preference','identity_core','identity_working') AND status = 'active'")
    needed = 1 + bump(store, p.project, "deviation")
    for n in nodes:
        if n.type == "preference" and len(tags & set(n.tags)) < needed:
            continue
        if heuristic_contradiction(p.status, n.summary + " " + n.body):
            judge = llm.get_llm("judge", use_llm)
            if judge is not None:
                ans = judge.complete(
                    f"Does this status report describe an action that contradicts the standard?\nStandard: {n.summary}\nStatus: {p.status[:1500]}\nAnswer JSON {{\"contradicts\": true|false}}.",
                    system="Answer with one JSON object only.",
                    max_tokens=40,
                )
                parsed = llm.parse_json_lenient(ans)
                if isinstance(parsed, dict) and parsed.get("contradicts") is False:
                    continue
            return n
    return None


def detect_phase_drift(store: db.Store, p: Progress) -> Optional[tuple[model.Node, float, float]]:
    if not p.phase:
        return None
    first = store.q1(
        "SELECT ts FROM progress_log WHERE project IS ? AND phase = ? ORDER BY id DESC LIMIT 1 OFFSET 0", (p.project, p.phase)
    )
    rows = store.q("SELECT ts, phase FROM progress_log WHERE project IS ? ORDER BY id DESC LIMIT 200", (p.project,))
    start = None
    for r in rows:
        if r["phase"] != p.phase:
            break
        start = r["ts"]
    if start is None and first is None:
        return None
    elapsed_h = ((db.age_seconds(start) or 0.0) / 3600.0) if start else 0.0
    for n in model.nodes_where(store, "type = 'retrospective' AND status = 'active'"):
        for t in n.tags:
            m = re.match(rf"expect:{re.escape(p.phase)}:(\d+(?:\.\d+)?)$", t)
            if m and elapsed_h > float(m.group(1)) + bump(store, p.project, "phase_drift") * 4:
                return n, elapsed_h, float(m.group(1))
    return None


def detect_contradiction(store: db.Store, p: Progress) -> Optional[tuple[str, str]]:
    last = store.q1("SELECT request_id FROM requests WHERE kind = 'pack' AND project IS ? ORDER BY ts DESC LIMIT 1", (p.project,))
    if last is None:
        return None
    ids = [r[0] for r in store.q("SELECT node_id FROM retrieval_log WHERE request_id = ?", (last[0],))]
    if len(ids) < 2:
        return None
    marks = ",".join("?" for _ in ids)
    r = store.q1(
        f"SELECT from_id, to_id FROM edges WHERE type = 'contradicts' AND from_id IN ({marks}) AND to_id IN ({marks}) LIMIT 1",  # noqa: S608
        (*ids, *ids),
    )
    return (r[0], r[1]) if r else None


def new_tags(store: db.Store, p: Progress) -> list[str]:
    out = []
    for t in model.parse_tags(p.tags):
        st = model.vocab_status(store, t)
        if st is None:
            out.append(t)
    return out


def evaluate(store: db.Store, p: Progress, use_llm: bool = True) -> dict:
    """Record the update, run the detectors in priority order, emit at most one suggestion."""
    with store.write():
        fresh = new_tags(store, p)
        record_progress(store, p)
        cd = cooldown_state(store, p.project)
        result: dict = {"suggestion": None, "cooldown": cd, "new_tags": fresh}
        if not cd["ready"]:
            return result
        rf = detect_repeated_failure(store, p)
        if rf:
            sig, count = rf
            q = recall.Query(task=sig, tags=list(p.tags), project=p.project, phase=p.phase)
            _, cands = recall.recall(store, q, cap=50)
            ids = [c.node.id for c in cands if c.node.type in ("skill", "retrospective")][:3]
            if ids:
                result["suggestion"] = _suggest(store, "repeated_failure", ids, f'the error "{sig}" appeared in {count} wakes', p.project)
                return result
        if detect_decision_point(store, p):
            tags = set(model.parse_tags(p.tags))
            decisions = [n for n in model.nodes_where(store, "type = 'decision' AND status IN ('active','probationary','disputed')") if tags & set(n.tags)]
            if decisions:
                ids = [n.id for n in sorted(decisions, key=lambda n: -n.confidence)[:3]]
                result["suggestion"] = _suggest(store, "decision_point", ids, "you are weighing alternatives; prior decisions on these tags, with their outcomes", p.project)
                return result
        dev = detect_deviation(store, p, use_llm)
        if dev is not None:
            result["suggestion"] = _suggest(store, "deviation", [dev.id], f"this wake's report reads against {dev.type} {dev.id}: {dev.summary[:120]}", p.project)
            return result
        drift = detect_phase_drift(store, p)
        if drift is not None:
            n, elapsed, expected = drift
            result["suggestion"] = _suggest(store, "phase_drift", [n.id], f"{p.phase} has run {elapsed:.1f}h against an expectation of {expected:.0f}h", p.project)
            return result
        pair = detect_contradiction(store, p)
        if pair:
            a = model.get_node(store, pair[0], with_edges=False)
            b = model.get_node(store, pair[1], with_edges=False)
            newer = pair[1] if (a and b and b.created >= a.created) else pair[0]
            for nid in pair:
                n = model.get_node(store, nid, with_edges=False)
                if n and n.status == "active":
                    model.set_status(store, nid, "disputed")
            result["suggestion"] = _suggest(store, "contradiction_found", list(pair), f"two packed memories disagree; the newer is {newer}", p.project)
        return result


def respond(store: db.Store, sid: str, response: str) -> dict:
    if response not in ("accept", "defer", "dismiss"):
        raise ValueError("response must be accept, defer or dismiss")
    with store.write():
        r = store.q1("SELECT * FROM suggestions WHERE id = ?", (sid,))
        if r is None:
            raise KeyError(sid)
        store.ex("UPDATE suggestions SET response = ?, responded_ts = ? WHERE id = ?", (response, db.now_iso(), sid))
        update_bumps(store)
        return {"id": sid, "response": response, "trigger": r["trigger"]}


def acceptance(store: db.Store) -> dict:
    out: dict = {}
    for r in store.q("SELECT trigger, response, COUNT(*) AS c FROM suggestions GROUP BY trigger, response"):
        d = out.setdefault(r["trigger"], {"accept": 0, "defer": 0, "dismiss": 0, "pending": 0})
        d[r["response"] or "pending"] = r["c"]
    for t, d in out.items():
        denom = d["accept"] + d["dismiss"]
        d["rate"] = round(d["accept"] / denom, 3) if denom else None
    return out


def update_bumps(store: db.Store) -> dict:
    """Triggers below the acceptance floor over enough responses get a higher threshold."""
    bumps: dict = {}
    for trig, d in acceptance(store).items():
        responses = d["accept"] + d["dismiss"]
        if responses >= ACCEPTANCE_MIN_RESPONSES and d["rate"] is not None and d["rate"] < ACCEPTANCE_FLOOR:
            level = min(BUMP_MAX, 1 + int((ACCEPTANCE_FLOOR - d["rate"]) / 0.1))
        else:
            level = 0
        bumps[trig] = level
        for r in store.q("SELECT DISTINCT project FROM trigger_state"):
            store.ex(
                """INSERT INTO trigger_state(project, trigger, threshold_bump) VALUES (?, ?, ?)
                   ON CONFLICT(project, trigger) DO UPDATE SET threshold_bump = excluded.threshold_bump""",
                (r[0], trig, level),
            )
    return bumps


def list_suggestions(store: db.Store, project: Optional[str] = None, pending: bool = False) -> list[dict]:
    sql = "SELECT * FROM suggestions WHERE 1=1"
    params: list = []
    if project:
        sql += " AND project = ?"
        params.append(project)
    if pending:
        sql += " AND response IS NULL"
    sql += " ORDER BY ts DESC LIMIT 50"
    out = []
    for r in store.q(sql, tuple(params)):
        d = db.row_dict(r)
        d["memory_ids"] = json.loads(d["memory_ids"] or "[]")
        out.append(d)
    return out


def undelivered(store: db.Store, project: Optional[str]) -> list[dict]:
    rows = store.q("SELECT * FROM suggestions WHERE project IS ? AND delivered = 0 AND response IS NULL ORDER BY ts", (project,))
    out = []
    for r in rows:
        d = db.row_dict(r)
        d["memory_ids"] = json.loads(d["memory_ids"] or "[]")
        out.append(d)
    return out


def mark_delivered(store: db.Store, ids: list[str]) -> None:
    for sid in ids:
        store.ex("UPDATE suggestions SET delivered = 1 WHERE id = ?", (sid,))
