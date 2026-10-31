"""The core identity: human-authored nodes seeded at init and shown verbatim every wake."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from . import db, gate, model

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
