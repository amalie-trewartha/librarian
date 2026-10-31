"""The quality gate every write passes before it is stored.

Rules (spec, "Capture"): a summary that answers "when would I want this?"
in ≤ 60 tokens and does not repeat the body's first sentence; at least one
namespaced tag; no near-duplicate (or the write becomes a supersession or a
``co_retrieved`` link instead); specifics in the body; provenance that
points somewhere real. New nodes enter ``probationary``. A fact (a sourced,
checkable finding) must also name where it came from: a URL, a DOI or a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import db, model

NEAR_DUP_SUMMARY = 0.6
NEAR_DUP_BODY = 0.8
SPECIFICS_TYPES = ("skill", "decision", "fact", "retrospective")

_DIGIT = re.compile(r"\d")
_PATH = re.compile(r"(?:^|\s|\()(?:~|\.{0,2})?/[\w.\-]+(?:/[\w.\-]+)*")
_BACKTICK = re.compile(r"`[^`\n]+`")
# A fact's source: a URL, a DOI, or a file path with an extension
# (sources/nhts2022.md, /data/x.csv), relative paths included.
_SOURCE = re.compile(
    r"https?://\S+|\bdoi:\s*10\.\d{4,}/\S+|\b10\.\d{4,}/\S+|(?:^|[\s(`'\"])(?:~|\.{1,2})?/?[\w.\-]+(?:/[\w.\-]+)*\.[A-Za-z0-9]{1,8}\b"
)
_COMMAND = re.compile(
    r"(?m)^\s*(?:\$ |(?:sudo |env |time )?(?:git|pip3?|uv|python3?|colcon|cmake|make|docker|npm|cargo|curl|grep|ls|cd|"
    r"pytest|bash|sh|jq|awk|sed|traj|mem|llm|shellm|blind|delegate|librarian|librarian-\w+)\b)"
)


@dataclass
class Candidate:
    type: str
    summary: str
    body: str = ""
    tags: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    confidence: float = 0.5
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    supersedes: Optional[str] = None
    project: Optional[str] = None
    untrusted: bool = False
    status: Optional[str] = None
    edges: list[dict] = field(default_factory=list)
    outcome: Optional[dict] = None
    id: Optional[str] = None  # fixed id for imports and eval fixtures; else a fresh ULID

    @property
    def author(self) -> str:
        return str(self.provenance.get("author") or "")


@dataclass
class GateResult:
    accepted: bool
    action: str  # stored | superseded | merged | rejected
    id: Optional[str] = None
    merge_target: Optional[str] = None
    linked: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    queued: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    status: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "action": self.action,
            "id": self.id,
            "merge_target": self.merge_target,
            "linked": self.linked,
            "children": self.children,
            "reasons": self.reasons,
            "queued": self.queued,
            "notes": self.notes,
            "status": self.status,
        }


def has_source(body: str) -> bool:
    return bool(_SOURCE.search(body or ""))


def has_specifics(body: str) -> bool:
    return bool(_DIGIT.search(body) or _PATH.search(body) or _BACKTICK.search(body) or _COMMAND.search(body))


def check(store: db.Store, cand: Candidate) -> list[str]:
    """Every rule violation, not just the first."""
    reasons: list[str] = []
    if cand.type not in model.NODE_TYPES:
        reasons.append(f"unknown type '{cand.type}'")
    summary = (cand.summary or "").strip()
    if not summary:
        reasons.append("summary is empty")
    elif model.estimate_tokens(summary) > model.SUMMARY_MAX_TOKENS:
        reasons.append(f"summary over {model.SUMMARY_MAX_TOKENS} tokens (about {model.estimate_tokens(summary)})")
    body = (cand.body or "").strip()
    # Identity, preference and episode nodes are the statement itself; only
    # the distilled types must write a summary that differs from the body.
    if summary and body and cand.type in SPECIFICS_TYPES:
        fs = model.first_sentence(body)
        if fs and model.jaccard(model.tokenize(summary), model.tokenize(fs)) >= 0.9:
            reasons.append("summary repeats the body's first sentence; write it to answer 'when would I want this?'")
    tags = model.parse_tags(cand.tags)
    namespaced = [t for t in tags if model.tag_namespace(t) in model.TAG_NAMESPACES]
    if not namespaced:
        reasons.append("at least one namespaced tag is required (pkg:, area:, ctx:, project:, team:, ...)")
    for t in tags:
        ns = model.tag_namespace(t)
        if ns == "ctx" and model.vocab_status(store, t) != "active":
            reasons.append(f"'{t}' is not in the closed ctx: list (librarian tags --namespace ctx)")
        if ns == "fail" and model.vocab_status(store, t) != "active":
            reasons.append(f"'{t}' is not in the closed fail: list (librarian tags --namespace fail)")
        if ns and ns not in model.TAG_NAMESPACES and ns not in ("tag",):
            # Unknown namespace: allowed as a free tag, but normalize so it does not drift.
            pass
    if cand.type in SPECIFICS_TYPES and not has_specifics(body):
        reasons.append("body needs specifics (a command, path, version, number or `backticked` name), not the lesson alone")
    if cand.type == "fact" and not has_source(body):
        reasons.append("a fact's body must name its source: a URL, a DOI, or the file it was read or computed from")
    if cand.type != "episode" and body and model.estimate_tokens(body) > model.BODY_MAX_TOKENS * 6:
        reasons.append(f"body is far over {model.BODY_MAX_TOKENS} tokens; split it into separate memories")
    author = cand.author
    if author not in model.AUTHORS:
        reasons.append("provenance.author must be one of main, librarian, human, runtime")
    elif author != "human" and cand.type != "episode":
        prov = cand.provenance
        ep = prov.get("episode")
        if ep:
            if model.get_node(store, str(ep), with_edges=False) is None:
                reasons.append(f"provenance.episode {ep} is not a stored episode")
        elif not (prov.get("source") or prov.get("run_id") or prov.get("span") or prov.get("method") in ("import", "auto-draft", "consolidation", "promotion")):
            reasons.append("provenance must name an episode, a source, a run_id or a span")
    if cand.supersedes:
        old = model.get_node(store, cand.supersedes, with_edges=False)
        if old is None:
            reasons.append(f"--supersedes {cand.supersedes}: no such node")
        elif old.type != cand.type and not (old.type in model.IDENTITY_TYPES and cand.type in model.IDENTITY_TYPES):
            reasons.append(f"--supersedes {cand.supersedes}: type {old.type} differs from {cand.type}")
    if cand.status and cand.status not in model.STATUSES:
        reasons.append(f"bad status '{cand.status}'")
    if not 0.0 <= float(cand.confidence) <= 1.0:
        reasons.append("confidence must be between 0 and 1")
    return reasons


def find_near_duplicates(store: db.Store, cand: Candidate, statuses=model.LIVE_STATUSES) -> list[tuple[str, float, float]]:
    """(id, summary_similarity, body_similarity) for same-type live nodes above the threshold, best first."""
    marks = ",".join("?" for _ in statuses)
    rows = store.q(
        f"SELECT id, summary, body FROM nodes WHERE type = ? AND status IN ({marks})",  # noqa: S608
        (cand.type, *statuses),
    )
    if not rows:
        return []
    tags_by = model.tags_for_nodes(store, [r["id"] for r in rows])
    ctoks = set(model.tokenize(cand.summary)) | set(model.parse_tags(cand.tags))
    cbody = set(model.tokenize(cand.body))
    out = []
    for r in rows:
        if cand.supersedes and r["id"] == cand.supersedes:
            continue
        ntoks = set(model.tokenize(r["summary"])) | set(tags_by.get(r["id"], []))
        s = model.jaccard(ctoks, ntoks)
        if s >= NEAR_DUP_SUMMARY:
            b = model.jaccard(cbody, model.tokenize(r["body"])) if (cbody or r["body"]) else 0.0
            out.append((r["id"], round(s, 3), round(b, 3)))
    out.sort(key=lambda x: (-x[1], -x[2]))
    return out


def split_body(body: str, max_tokens: int = model.CHUNK_MAX_TOKENS) -> list[str]:
    """Split a long body on paragraph boundaries into chunks under ``max_tokens``."""
    paras = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if cur and model.estimate_tokens(cur + "\n\n" + p) > max_tokens:
            chunks.append(cur)
            cur = p
        else:
            cur = p if not cur else cur + "\n\n" + p
        while model.estimate_tokens(cur) > max_tokens:
            cut = max_tokens * 4
            head, tail = cur[:cut], cur[cut:]
            sp = head.rfind(" ")
            if sp > cut // 2:
                head, tail = cur[:sp], cur[sp + 1 :]
            chunks.append(head)
            cur = tail
    if cur:
        chunks.append(cur)
    return chunks or [body]


# Tag hygiene (2026-10 live run: 36 curated tags, 24 used once; junk such as
# pkg:p and pkg:p2; near-duplicates such as area:data / area:data-fetch).
TAG_NAMESPACES_OPEN = ("pkg", "area", "topic", "data", "method")
TAG_ACTIVATE_USES = 2
_JUNK_PKG = re.compile(r"^(p\d*(-.*)?|project.*|brief.*|blind)$")


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def normalize_tags(store: db.Store, tags: list[str]) -> tuple[list[str], list[str]]:
    """Map a new tag to a close existing one in its namespace; drop junk pkg: values.

    Returns (tags, notes). Tags already in the vocabulary pass unchanged.
    """
    out: list[str] = []
    notes: list[str] = []
    for t in tags:
        ns, free = model.tag_namespace(t), model.tag_free(t)
        if ns not in TAG_NAMESPACES_OPEN or model.vocab_status(store, t) is not None:
            out.append(t)
            continue
        if ns == "pkg" and _JUNK_PKG.match(free):
            notes.append(f"dropped tag {t}: pkg: names a package or tool, not a project or brief")
            continue
        close = None
        if len(free) >= 5:
            for r in store.q("SELECT tag FROM tag_vocab WHERE namespace = ? AND status IN ('active','seen')", (ns,)):
                if _edit_distance(free, model.tag_free(r[0])) <= 2:
                    close = r[0]
                    break
        if close:
            notes.append(f"tag {t} written as the existing {close}")
            t = close
        if t not in out:
            out.append(t)
    return out, notes


def _activate_used_tags(store: db.Store, tags: list[str]) -> None:
    """A tag becomes active (usable in wake requests) once two curated memories carry it.

    Before, new tags waited for a human approval that never came: in the live run
    every tag the mind made stayed 'seen', so wakes never matched on them.
    """
    for t in tags:
        if model.tag_namespace(t) not in TAG_NAMESPACES_OPEN or model.vocab_status(store, t) == "active":
            continue
        n = store.q1(
            "SELECT COUNT(DISTINCT n.id) FROM tags g JOIN nodes n ON n.id = g.node_id WHERE g.tag = ? AND n.type IN ('skill','fact','decision','retrospective')",
            (t,),
        )[0]
        if n >= TAG_ACTIVATE_USES:
            store.ex("UPDATE tag_vocab SET status = 'active', note = ? WHERE tag = ?", (f"auto: used by {n} memories", t))


def _informed_edges(store: db.Store, node_id: str, body: str) -> int:
    """A memory whose body cites another memory's id was informed by it."""
    n = 0
    for nid in set(re.findall(r"\b[0-9A-HJKMNP-TV-Z]{26}\b", body or "")):
        if nid != node_id and model.get_node(store, nid, with_edges=False) is not None:
            model.add_edge(store, nid, node_id, "informed", 1.0, {"by": "gate", "cited_in_body": True})
            n += 1
    return n


def apply(store: db.Store, cand: Candidate) -> GateResult:
    """Run the checks, decide on duplicates, write. One write transaction."""
    reasons = check(store, cand)
    if reasons:
        return GateResult(False, "rejected", reasons=reasons)
    tags = model.parse_tags(cand.tags)
    tag_notes: list[str] = []
    if cand.type != "episode":
        tags, tag_notes = normalize_tags(store, tags)
    if cand.project and f"project:{cand.project}" not in tags:
        tags.append(f"project:{cand.project}")
    if cand.untrusted or str(cand.provenance.get("source_kind", "")) in ("web", "external"):
        if "src:untrusted" not in tags:
            tags.append("src:untrusted")
    result = GateResult(True, "stored")
    result.notes += tag_notes
    # Episodes are records of what happened, not claims awaiting confirmation.
    status = "active" if cand.type == "episode" else "probationary"
    if cand.status and cand.status != "probationary" and cand.type != "episode":
        if cand.author == "human" or cand.provenance.get("method") in ("consolidation", "promotion", "import"):
            status = cand.status
        else:
            result.notes.append(f"status '{cand.status}' ignored: only human-authored nodes enter active directly")
    with store.write():
        # Every wake is its own episode: episodes are never deduplicated.
        dups = find_near_duplicates(store, cand) if cand.type != "episode" else []
        if dups:
            best_id, s_sum, s_body = dups[0]
            if s_body >= NEAR_DUP_BODY:
                result.action = "merged"
                result.merge_target = best_id
                result.notes.append(f"near-duplicate of {best_id} (summary {s_sum}, body {s_body}); nothing written")
                return result
            best = model.get_node(store, best_id, with_edges=False)
            same_project = bool(best and cand.project and best.project == cand.project)
            if cand.supersedes is None and same_project:
                cand.supersedes = best_id
                result.notes.append(f"near-duplicate of {best_id} in the same project; written as a supersession")
            elif cand.supersedes is None:
                result.linked.append(best_id)
                result.notes.append(f"near-duplicate of {best_id} (summary {s_sum}); linked co_retrieved")
        # New tags are accepted as 'seen' and activate on their second use
        # (_activate_used_tags), without waiting on a human.
        body = (cand.body or "").strip()
        chunks = [body]
        if body and model.estimate_tokens(body) > model.BODY_MAX_TOKENS:
            chunks = split_body(body)
        node_id = db.ulid()
        if cand.id and db.is_ulid(cand.id.upper()) and model.get_node(store, cand.id.upper(), with_edges=False) is None:
            node_id = cand.id.upper()
        node = model.Node(
            id=node_id,
            type=cand.type,
            summary=cand.summary.strip(),
            body=chunks[0] if body else "",
            status=status,
            confidence=float(cand.confidence),
            provenance=dict(cand.provenance),
            project=cand.project,
            valid_from=cand.valid_from,
            valid_to=cand.valid_to,
            tags=tags,
            edges=list(cand.edges),
            outcome=cand.outcome,
        )
        if cand.type == "episode" and node.outcome is None:
            node.outcome = {"value": "unknown", "criterion": "not recorded", "recorded": db.now_iso()}
        model.insert_node(store, node)
        if cand.type != "episode":
            _activate_used_tags(store, tags)
            _informed_edges(store, node_id, body)
        if cand.supersedes:
            model.supersede(store, node_id, cand.supersedes, {"by": cand.author or "main", "reason": "proposal"})
            result.action = "superseded"
        for linked in result.linked:
            model.add_edge(store, node_id, linked, "co_retrieved", 0.6, {"by": "gate"})
            model.add_edge(store, linked, node_id, "co_retrieved", 0.6, {"by": "gate"})
        ep = cand.provenance.get("episode")
        if ep and cand.type != "episode":
            model.add_edge(store, node_id, str(ep), "derived_from", 1.0, {"by": "gate"})
        for t in tags:
            if model.tag_namespace(t) in ("pkg", "area") and cand.type in ("skill", "preference"):
                model.add_edge(store, node_id, f"tag:{t}", "applies_to", 1.0, {"by": "gate"})
        for i, chunk in enumerate(chunks[1:], start=2):
            child = model.Node(
                id=db.ulid(),
                type=cand.type,
                summary=f"{cand.summary.strip()} (part {i} of {len(chunks)})",
                body=chunk,
                status=status,
                confidence=float(cand.confidence),
                provenance={**cand.provenance, "part_of": node_id},
                project=cand.project,
                tags=tags,
            )
            model.insert_node(store, child)
            model.add_edge(store, child.id, node_id, "part_of", 1.0, {"by": "gate"})
            result.children.append(child.id)
        if result.children:
            result.notes.append(f"body split into {len(chunks)} chunks; children linked part_of")
    result.id = node_id
    result.status = status
    return result
