"""Run D: lessons that compound across briefs.

Run B (2026-10) wrote six retrospectives, but the brief-1 "what I would redo"
lesson never reached a pack (transfer ranks by the brief's words), lessons were
written only at the daily ritual, and credit almost never moved them. These
tests pin the three changes: a [LESSONS] section chosen by situation, LESSON DUE
signals at the moments a lesson is learned, and review verdicts crediting the
lessons a piece of work named before it was reviewed.
"""

import io
import json
import os
import subprocess
import unittest
from contextlib import redirect_stdout

from helpers import StoreCase
from librarian import db, lifecycle, pack, runtime


def _git(pd, *args):
    subprocess.run(["git", "-C", str(pd), *args], check=True, capture_output=True)


class LessonPackTest(StoreCase):
    def req(self, **kw) -> pack.PackRequest:
        base = dict(task="battery second life retirements recycling", tags=["project:p-4"], project="p-4", phase="building", budget=5000, log=True, use_llm=False, lessons=True)
        base.update(kw)
        return pack.PackRequest(**base)

    def test_lesson_with_no_shared_words_reaches_a_new_brief(self):
        # The run-B case: a process lesson from brief 1 shares no words with brief 4.
        redo = self.retro("When starting a new modeling brief: bundle reviews, decide ownership early", ["area:process"], project="p-1")
        pk = pack.build(self.store, self.req(brief_start=True, transfer_task="EV battery retirements, second life and recycling for the city."))
        self.assertIn(redo, pk.ids("lesson"))
        self.assertNotIn(redo, pk.ids("transfer"))
        self.assertNotIn(redo, pk.ids("task"))
        text = pack.render_text(pk)
        self.assertLess(text.index(pack.MARK_LESSONS), text.index(pack.MARK_TASK))
        self.assertEqual(pack.build(self.store, self.req(lessons=False)).lessons, [])

    def test_brief_start_puts_starting_lessons_first(self):
        start = self.retro("When starting a modeling brief: fix the price basis on day 1", ["area:process", "ctx:planning"], project="p-2")
        newer = [self.retro(f"When doing step {w}: lesson {w}", ["area:process"], project="p-3") for w in ("alpha", "beta", "gamma")]
        self.assertEqual(pack.build(self.store, self.req(brief_start=True)).ids("lesson")[0], start)

    def test_only_lessons_qualify(self):
        tool = self.skill("When playwright screenshots fail on a headless box", ["pkg:playwright"])
        how = self.skill("When a background job writes tracked outputs: write atomically", ["area:process", "pkg:git"])
        fact = self.add("fact", "When I need the US EV pack price in 2024", ["area:prices"], "123 $/kWh, BNEF 2024, https://about.bnef.com, verified 2026-10-01.")
        ids = pack.build(self.store, self.req()).ids("lesson")
        self.assertIn(how, ids)
        self.assertNotIn(tool, ids)
        self.assertNotIn(fact, ids)

    def test_situation_outranks_confidence(self):
        fit = self.retro("When reviewing a report: check prose against outputs", ["area:process", "ctx:reviewing"])
        others = [self.retro(f"When doing step {w}: lesson {w}", ["area:process"]) for w in ("alpha", "beta", "gamma")]
        with self.store.write():
            for o in others:
                self.store.ex("UPDATE nodes SET confidence = 0.8 WHERE id = ?", (o,))
        self.assertEqual(pack.build(self.store, self.req(phase="reviewing")).ids("lesson")[0], fit)
        self.assertNotIn(fit, pack.build(self.store, self.req(phase="building")).ids("lesson"))

    def test_equal_lessons_take_turns(self):
        ids = [self.retro(f"When doing step {w}: lesson {w}", ["area:process"]) for w in ("alpha", "beta", "gamma", "delta", "ember")]
        first = pack.build(self.store, self.req()).ids("lesson")
        second = pack.build(self.store, self.req()).ids("lesson")
        self.assertEqual(len(first), pack.LESSONS_MAX)
        self.assertTrue(set(ids) - set(first) <= set(second))  # the two not shown come next


class LessonRuntimeCase(StoreCase):
    def project(self, pid: str, spec: str = "# Project brief 2: home energy\n\nModel heat pumps.\n"):
        pd = self.ident / "workdir" / "project"
        (pd / "reviews").mkdir(parents=True, exist_ok=True)
        (pd / "charter.md").write_text("charter")
        (pd / "spec.md").write_text(spec)
        pp = self.ident / "project-pristine"
        pp.mkdir(exist_ok=True)
        (pp / "project_id").write_text(pid)
        if not (pd / ".git").exists():
            _git(pd, "init", "-q")
            _git(pd, "-c", "user.name=t", "-c", "user.email=t@x", "add", "-A")
            _git(pd, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "init")
        self.pd = pd
        return pd

    def commit(self):
        _git(self.pd, "add", "-A")
        _git(self.pd, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-qm", "wake")

    def pre(self) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            runtime.pre(None, "building", None, "", use_llm=False)
        return buf.getvalue()

    def signals(self) -> str:
        p = self.ident / "run" / runtime.SIGNALS_FILE
        return p.read_text() if p.exists() else ""

    def request_id(self) -> str:
        return json.loads((self.ident / "run" / runtime.REQUEST_FILE).read_text())["request_id"]

    def post(self, final: str = "Did the work.") -> dict:
        with redirect_stdout(io.StringIO()) as out:
            runtime.post(0, None, "", final, use_llm=False)
        self.commit()
        return json.loads(out.getvalue())

    def propose_lesson(self, summary: str) -> str:
        body = "Brief 1 overran by 2 days: 4 of 9 reviews in reviews/ found the price basis BROKEN; fix it on day 1."
        return self.add("retrospective", summary, ["area:process"], body, provenance={"author": "main", "run_id": self.request_id()}, project=runtime.project_id())


class BriefLessonTest(LessonRuntimeCase):
    def setUp(self):
        super().setUp()
        pack.build(self.store, pack.PackRequest(task="mobility", tags=[], project="p-1", budget=2000, log=True, use_llm=False))
        self.at("2026-10-02T00:00:00Z")
        self.project("p-2")

    def test_closed_brief_without_retrospective_asks_for_one_until_written(self):
        self.pre()
        self.assertIn("LESSON DUE", self.signals())
        self.assertIn("p-1", self.signals())
        self.post()
        self.pre()
        self.assertIn("LESSON DUE", self.signals())  # still due: nothing proposed
        rid = self.propose_lesson("When starting a modeling brief: fix the price basis on day 1")
        res = self.post()
        self.assertEqual(res["lessons"]["settled"][0]["cleared_by"], rid)
        self.pre()
        self.assertNotIn("LESSON DUE", self.signals())

    def test_brief_signal_expires(self):
        for _ in range(runtime.BRIEF_LESSON_WAKES_DEFAULT):
            self.pre()
            self.assertIn("LESSON DUE", self.signals())
            self.post()
        self.pre()
        self.assertNotIn("LESSON DUE", self.signals())
        self.assertEqual(self.store.q1("SELECT cleared_by FROM pending_lesson")[0], "expired")

    def test_no_signal_when_the_brief_left_a_retrospective(self):
        self.retro("When starting a brief after mobility: what I would redo", ["area:process"], project="p-1")
        self.pre()
        self.assertNotIn("LESSON DUE", self.signals())

    def test_lessons_off(self):
        os.environ["LIBRARIAN_LESSONS"] = "0"
        out = self.pre()
        self.assertNotIn("LESSON DUE", self.signals())
        self.assertNotIn(pack.MARK_LESSONS, out)


class ReviewLessonTest(LessonRuntimeCase):
    def setUp(self):
        super().setUp()
        self.project("p-1", "# Project brief: mobility\n\nModel travel.\n")

    def land_review(self, name: str, verdict: str, extra: str = "") -> dict:
        self.pre()
        (self.pd / "reviews" / name).write_text(f"C1: {verdict}\n{extra}")
        return self.post("Acted on the review.")

    def test_broken_review_asks_once(self):
        self.land_review("x-adversary.md", "BROKEN")
        self.pre()
        self.assertIn("LESSON DUE", self.signals())
        self.assertIn("reviews/x-adversary.md", self.signals())
        res = self.post()
        self.assertEqual(res["lessons"]["settled"][0]["cleared_by"], "none")
        self.pre()
        self.assertNotIn("LESSON DUE", self.signals())

    def test_same_review_edited_again_does_not_ask_again(self):
        self.land_review("x-adversary.md", "BROKEN")
        self.pre()
        self.post()
        self.land_review("x-adversary.md", "BROKEN", "Memories BROKEN: (none)\n")
        self.pre()
        self.assertNotIn("LESSON DUE", self.signals())

    def test_surviving_review_asks_nothing(self):
        self.land_review("y-adversary.md", "SURVIVES")
        self.pre()
        self.assertNotIn("LESSON DUE", self.signals())


class LessonCreditTest(LessonRuntimeCase):
    def setUp(self):
        super().setUp()
        self.project("p-1", "# Project brief: mobility\n\nModel travel.\n")
        self.lesson = self.retro("When a report hand-cites outputs: key every number to its output", ["area:process"])

    def claims(self, name: str, ids: str, committed: bool = True):
        (self.pd / "reviews" / name).write_text(f"C1. The fleet is 42.\n\nLessons applied: {ids}\n")
        if committed:
            self.commit()

    def land(self, name: str, verdict: str) -> dict:
        self.pre()
        (self.pd / "reviews" / name).write_text(f"C1: {verdict}\n")
        return self.post("Acted on the review.")

    def test_surviving_review_confirms_the_lessons_its_work_applied(self):
        self.claims("p-claims.md", self.lesson)
        res = self.land("p-adversary.md", "SURVIVES")
        self.assertEqual(res["lessons"]["credited"], {self.lesson: "success"})
        n = self.node(self.lesson)
        self.assertEqual(n.status, "active")
        self.assertAlmostEqual(n.confidence, 0.5 + lifecycle.STEP, places=3)
        self.assertEqual(self.store.q1("SELECT source FROM citations WHERE node_id = ?", (self.lesson,))[0], "lesson")

    def test_broken_review_counts_against_them(self):
        self.claims("p-claims.md", self.lesson)
        self.land("p-adversary.md", "BROKEN")
        self.assertAlmostEqual(self.node(self.lesson).confidence, 0.5 - lifecycle.STEP, places=3)

    def test_lessons_named_after_the_verdict_earn_nothing(self):
        self.claims("p-claims.md", self.lesson, committed=False)
        res = self.land("p-adversary.md", "SURVIVES")
        self.assertEqual(res["lessons"]["credited"], {})
        self.assertAlmostEqual(self.node(self.lesson).confidence, 0.5, places=3)

    def test_mixed_review_and_non_lessons_earn_nothing(self):
        fact = self.add("fact", "When I need the city fleet size", ["area:fleet"], "42 vehicles, DMV 2024, https://dmv.example/2024, verified 2026-10-01.")
        self.claims("p-claims.md", f"{self.lesson} {fact}")
        self.pre()
        (self.pd / "reviews" / "p-adversary.md").write_text("Memories SURVIVES: \nMemories BROKEN: \nC1: SURVIVES\nC2: BROKEN\n")
        res = self.post()
        self.assertEqual(res["lessons"]["credited"], {})


class JudgedCreditTest(StoreCase):
    def test_a_verdict_judges_its_memory_at_full_weight(self):
        # Run B: a SURVIVES line moved its fact by 0.01, split with eight logged memories.
        judged = self.skill("judged", ["pkg:x"])
        logged = [self.skill(f"logged {w}", ["pkg:x"]) for w in ("a", "b", "c")]
        self.episode("partial", [judged, *logged], overrides={judged: "success"})
        self.assertAlmostEqual(self.node(judged).confidence, 0.5 + lifecycle.STEP, places=3)
        for nid in logged:
            self.assertAlmostEqual(self.node(nid).confidence, 0.5, places=3)


class MigrationTest(StoreCase):
    def test_v4_store_gains_pending_lesson(self):
        with self.store.write():
            self.store.ex("DROP TABLE pending_lesson")
            self.store.meta_set("schema_version", "4")
        self.store.close()
        self.store = db.Store.open()
        self.assertEqual(self.store.meta_get("schema_version"), str(db.SCHEMA_VERSION))
        self.assertIsNotNone(self.store.q1("SELECT name FROM sqlite_master WHERE name = 'pending_lesson'"))


if __name__ == "__main__":
    unittest.main()
