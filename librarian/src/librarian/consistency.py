"""Shared values: the quantities more than one brief depends on, and whether the briefs agree.

A fact tagged ``shared:<quantity>`` (for example ``shared:fleet-2035``,
``shared:discount-rate``) is a value later work may reuse. The librarian keeps
``project/shared-values.md`` as a generated ledger of those facts, shows the
ones a wake touches in a [SHARED VALUES] pack section, and raises a
CONSISTENCY signal when two briefs carry different values for one quantity
until the mind reconciles them: supersede the wrong one, or tag a fact
``scope:reconciled`` with the documented reason both stand.

Everything here is derived from the store on demand; no state of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import db, model

SHARED_NS = "shared:"
RECONCILED_TAG = "scope:reconciled"
# Two values of one quantity within this relative gap agree.
AGREE_REL = 0.01
PACK_MAX = 8
LEDGER_FILE = "shared-values.md"

_NUM = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\s*%|\s*[eE][-+]?\d+)?")
_PATH = re.compile(r"(?:^|[\s(`'\"])((?:~|\.{1,2})?/?[\w.\-]+(?:/[\w.\-]+)+\.[A-Za-z0-9]{1,8})\b")


@dataclass
class SharedFact:
    node: model.Node
    quantity: str
    value: Optional[float]
    value_text: str
    source: str


def quantity_of(node: model.Node) -> Optional[str]:
    for t in node.tags:
        if t.startswith(SHARED_NS) and len(t) > len(SHARED_NS):
            return t[len(SHARED_NS):]
    return None


def _year_like(raw: str) -> bool:
    s = raw.strip()
    return s.isdigit() and len(s) == 4 and 1900 <= int(s) <= 2100


def first_number(text: str) -> tuple[Optional[float], str]:
    """The quantity's number in a summary: the first number that is not a bare year
    (2035 in "the 2035 fleet is 61,200 vehicles"), else the first number."""
    raws = [m.group(0) for m in _NUM.finditer(text or "")]
    if not raws:
        return None, ""
    non_year = [r for r in raws if not _year_like(r)]
    raw = (non_year or raws)[0]
    s = raw.replace(",", "").replace(" ", "")
    pct = s.endswith("%")
    s = s.rstrip("%")
    try:
        v = float(s)
    except ValueError:
        return None, raw.strip()
    return (v / 100.0 if pct else v), raw.strip()


def source_of(body: str) -> str:
    m = _PATH.search(body or "")
    if m:
        return m.group(1)
    u = re.search(r"https?://\S+", body or "")
    return u.group(0)[:80] if u else ""


def shared_facts(store: db.Store, statuses=("active", "probationary")) -> list[SharedFact]:
    marks = ",".join("?" for _ in statuses)
    nodes = model.nodes_where(
        store,
        f"type = 'fact' AND status IN ({marks}) AND id IN (SELECT node_id FROM tags WHERE tag LIKE 'shared:%') ORDER BY created",  # noqa: S608
        tuple(statuses),
    )
    out = []
    for n in nodes:
        q = quantity_of(n)
        if not q:
            continue
        v, vt = first_number(n.summary)
        out.append(SharedFact(n, q, v, vt, source_of(n.body)))
    return out


def by_quantity(facts: list[SharedFact]) -> dict[str, list[SharedFact]]:
    out: dict[str, list[SharedFact]] = {}
    for f in facts:
        out.setdefault(f.quantity, []).append(f)
    return out


def _agree(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a == b
    if a == b:
        return True
    return abs(a - b) <= AGREE_REL * max(abs(a), abs(b))


def conflicts(store: db.Store) -> list[dict]:
    """Quantities whose live facts from different briefs disagree and are not marked reconciled."""
    out = []
    for q, fs in sorted(by_quantity(shared_facts(store)).items()):
        if len(fs) < 2 or any(RECONCILED_TAG in f.node.tags for f in fs):
            continue
        projects = {f.node.project for f in fs}
        if len(projects) < 2:
            continue
        base = fs[0]
        if all(_agree(base.value, f.value) for f in fs[1:]):
            continue
        out.append(
            {
                "quantity": q,
                "facts": [{"id": f.node.id, "project": f.node.project, "value": f.value_text or "(no number)", "summary": f.node.summary[:120]} for f in fs],
            }
        )
    return out


def signals(store: db.Store) -> list[str]:
    lines = []
    for c in conflicts(store):
        vals = "; ".join(f"{f['id']} ({f['project'] or 'no brief'}): {f['value']}" for f in c["facts"])
        lines.append(
            f"- CONSISTENCY: shared quantity `{c['quantity']}` has different values in different briefs: {vals}. "
            "Before other work, settle it: `librarian propose --type fact --supersedes <wrong id> ...` with the value every brief should use "
            "(and fix the files that read the old one), or, when both are right for a documented reason, re-propose one with the tag "
            f"`{RECONCILED_TAG}` and the reason in its body. Record the call in project-memory.md."
        )
    return lines


def render_ledger(store: db.Store, project: Optional[str]) -> str:
    facts = shared_facts(store)
    confl = {c["quantity"] for c in conflicts(store)}
    out = [
        "# Shared values",
        "",
        "Generated by the librarian from facts tagged `shared:<quantity>`. One row per fact; a quantity with",
        "rows from different briefs that disagree is marked CONFLICT until it is reconciled. Set a shared",
        "quantity in a new brief only after reading its row here; reuse the value or record why not.",
        "",
        "| Quantity | Value | Brief | Id | Source | Summary |",
        "|---|---|---|---|---|---|",
    ]
    for q, fs in sorted(by_quantity(facts).items()):
        for f in fs:
            flag = " **CONFLICT**" if q in confl else ""
            out.append(f"| {q}{flag} | {f.value_text or ''} | {f.node.project or ''} | {f.node.id} | {f.source} | {f.node.summary[:100].replace('|', '/')} |")
    if len(out) == 8:
        out.append("| (none yet) | | | | | |")
    out.append("")
    return "\n".join(out)


def pack_rows(store: db.Store, task_text: str, brief_start: bool, max_rows: int = PACK_MAX) -> list[model.Node]:
    """Shared facts to show this wake: at a brief's start all of them; otherwise those whose
    quantity words occur in the task text. Conflicting quantities come first."""
    facts = shared_facts(store)
    if not facts:
        return []
    confl = {c["quantity"] for c in conflicts(store)}
    words = set(model.tokenize(task_text))
    text = (task_text or "").lower()
    chosen: list[SharedFact] = []
    for f in facts:
        q_words = [w for w in f.quantity.replace("-", " ").split() if len(w) >= 3]
        hit = brief_start or f.quantity in confl or (q_words and all(w in words or w in text for w in q_words))
        if hit:
            chosen.append(f)
    chosen.sort(key=lambda f: (f.quantity not in confl, f.quantity, f.node.created))
    return [f.node for f in chosen[:max_rows]]
