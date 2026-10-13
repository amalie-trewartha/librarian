"""Shared test scaffolding. unittest-style so both `python3 -m unittest` and pytest run it."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from headlong_librarian import db, gate, lifecycle, model  # noqa: E402

T0 = "2026-10-01T00:00:00Z"
CLEAR = ("PROJECT_NOW", "PROJECT_REAL_NOW", "PROJECT_TIME_SCALE", "PROJECT_STARTED_AT", "LIBRARIAN_MODEL", "SHELLM_FAST_MODEL", "SHELLM_MODEL", "THINK_MODEL", "LLM_MODEL", "LIBRARIAN_STORE", "LIBRARIAN_FTS", "TRAJ_DIR", "TRAJ_ID", "PROJECT_DIR")


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ident = Path(self.tmp.name) / "ident"
        (self.ident / "run").mkdir(parents=True)
        self._env = dict(os.environ)
        for k in CLEAR:
            os.environ.pop(k, None)
        os.environ.update({"IDENTITY_DIR": str(self.ident), "LIBRARIAN_LLM": "0", "LIBRARIAN_NOW": T0, "IDENTITY_NAME": "testid"})
        self.store = db.Store.open(create=True)
        with self.store.write():
            model.seed_vocab(self.store)

    def tearDown(self) -> None:
        self.store.close()
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    # ── clock ──
    def at(self, iso: str) -> None:
        os.environ["LIBRARIAN_NOW"] = iso

    # ── fixtures ──
    _WORDS = "amber birch cedar dune ember fjord grove heath iris jade kelp lotus maple nectar ocean pearl quartz reed slate thyme umber vale willow yarrow zephyr".split()

    def add(self, ntype: str, summary: str, tags, body: str = "", **kw) -> str:
        prov = kw.pop("provenance", {"author": "main", "source": "test"})
        # Distilled types get a unique trailer so terse fixtures do not trip the
        # near-duplicate gate (the gate's behaviour is right; the fixtures are terse).
        if ntype in ("skill", "decision", "retrospective") and body and not kw.pop("exact_body", False):
            n = self.__dict__.setdefault("_fixture_n", 0) + 1
            self._fixture_n = n
            w = self._WORDS[n % len(self._WORDS)]
            body = f"{body}\nCase {n}: verified on rig-{w}-{n} ({w} variant)."
        cand = gate.Candidate(type=ntype, summary=summary, body=body, tags=list(tags), provenance=prov, **kw)
        res = gate.apply(self.store, cand)
        assert res.accepted, res.reasons
        assert res.id, res
        return res.id

    def skill(self, summary: str, tags, body: str = "Fix: run `make fix` with VERSION=1.2; verified on 2026-09-01.", **kw) -> str:
        return self.add("skill", summary, tags, body, **kw)

    def decision(self, summary: str, tags, body: str = "Chose A over B because of 3 measured cases; revisit if latency > 50 ms.", **kw) -> str:
        return self.add("decision", summary, tags, body, **kw)

    def retro(self, summary: str, tags, body: str = "Project overran by 3 days; start integration tests by day 2.", **kw) -> str:
        return self.add("retrospective", summary, tags, body, **kw)

    def pref(self, text: str, tags=("team:robotics-sw",), **kw) -> str:
        kw.setdefault("provenance", {"author": "human", "method": "stated-value", "source": "values.md"})
        kw.setdefault("status", "active")
        return self.add("preference", text, tags, text, **kw)

    def core(self, text: str) -> str:
        return self.add("identity_core", text, ["scope:identity"], text, provenance={"author": "human", "method": "import"}, status="active", confidence=0.9)

    def working(self, text: str) -> str:
        return self.add("identity_working", text, ["scope:identity"], text, provenance={"author": "main", "source": "test"})

    def episode(self, outcome: str, cited: list[str], project: str = "p-1", **kw) -> lifecycle.CreditReport:
        return lifecycle.close_episode(self.store, outcome=outcome, criterion=kw.pop("criterion", "test"), summary=kw.pop("summary", f"episode {outcome}"), body=kw.pop("body", "FINAL: x"), tags=kw.pop("tags", []), project=project, cited=cited, **kw)

    def node(self, nid: str) -> model.Node:
        n = model.get_node(self.store, nid)
        assert n is not None, nid
        return n

    def activate(self, nid: str) -> None:
        with self.store.write():
            model.set_status(self.store, nid, "active")


def read_json(path: Path):
    return json.loads(Path(path).read_text())
