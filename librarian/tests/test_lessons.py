"""Lessons, shared values and reviewer-confirmed facts: the v2 runtime.

Lessons live in a [LESSONS] section chosen by situation and are judged at a
brief's close by whether the failure class they guard against recurred (not by
claim-level verdicts, which in run D went 36 failures to 1 success because the
reviewer always finds something). Facts the reviewer marked SURVIVES are written
by the runtime. Shared quantities that disagree across briefs raise a
CONSISTENCY signal until reconciled.
"""

import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout

from helpers import StoreCase
from librarian import consistency, model, pack, runtime


def _git(pd, *args):
    subprocess.run(["git", "-C", str(pd), *args], check=True, capture_output=True)


class LessonPackTest(StoreCase):
    def req(self, **kw) -> pack.PackRequest:
        base = dict(task="battery second life retirements recycling", tags=["project:p-4"], project="p-4", phase="building", budget=3000, log=True, use_llm=False, lessons=True)
        base.update(kw)
        return pack.PackRequest(**base)

    def test_lesson_with_no_shared_words_reaches_a_new_brief(self):
        lesson = self.retro("When starting a modeling brief: one rerun script on day 1", ["area:process", "ctx:planning"], project="p-1")
        pk = pack.build(self.store, self.req(brief_start=True))
        self.assertIn(lesson, pk.ids("lesson"))
        text = pack.render_text(pk)
        self.assertLess(text.index(pack.MARK_LESSONS), text.index(pack.MARK_TASK))
        self.assertIn("shown 0", text)

    def test_situation_outranks_age(self):
        old_fit = self.retro("When starting a modeling brief: source the headline parameters first", ["area:process", "ctx:planning"], project="p-1")
        self.at("2026-10-05T00:00:00Z")
        for w in ("alpha", "beta", "gamma"):
            self.retro(f"When reviewing: lesson {w}", ["area:process", "ctx:reviewing"], project="p-2")
        pk = pack.build(self.store, self.req(brief_start=True, phase="planning"))
        self.assertEqual(pk.ids("lesson")[0], old_fit)

    def test_only_lessons_qualify_and_they_take_turns(self):
        self.skill("colcon eigen fix", ["pkg:colcon"], project="p-1")
        ids = [self.retro(f"When doing step {w}: lesson {w}", ["area:process"]) for w in ("alpha", "beta", "gamma", "delta", "ember")]
        first = pack.build(self.store, self.req()).ids("lesson")
        second = pack.build(self.store, self.req()).ids("lesson")
        self.assertEqual(len(first), pack.LESSONS_MAX)
        self.assertTrue(set(first) <= set(ids))
        self.assertTrue(set(ids) - set(first) <= set(second))

    def test_frequent_failure_class_of_this_brief_ranks_first(self):
        plain = self.retro("When building: lesson plain", ["area:process", "ctx:building"], project="p-1")
        guard = self.retro("When building: guard every hand-typed number", ["area:process", "ctx:building", "fail:stale"], project="p-1")
        with self.store.write():
            for i in range(2):
                self.store.ex("INSERT INTO review_claim(file, claim, verdict, class, project, ts) VALUES (?,?,?,?,?,?)", (f"reviews/r{i}.md", "C1", "BROKEN", "stale", "p-4", "2026-10-01T00:00:00Z"))
        pk = pack.build(self.store, self.req())
        self.assertEqual(pk.ids("lesson")[:2], [guard, plain])


class RuntimeCase(StoreCase):
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
        _git(self.pd, "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "--allow-empty", "-m", "wake")

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

    def propose_lesson(self, summary: str, tags=("area:process",)) -> str:
        body = "Brief 1 overran by 2 days: 4 of 9 reviews in reviews/ found the price basis BROKEN; fix it on day 1."
        return self.add("retrospective", summary, list(tags), body, provenance={"author": "main", "run_id": self.request_id()}, project=runtime.project_id())


class BriefCloseTest(RuntimeCase):
    def setUp(self):
        super().setUp()
        pack.build(self.store, pack.PackRequest(task="mobility", tags=[], project="p-1", budget=2000, log=True, use_llm=False))
        self.at("2026-10-02T00:00:00Z")
        self.project("p-2")

    def test_closed_brief_without_retrospective_asks_until_written(self):
        self.pre()
        self.assertIn("LESSON DUE", self.signals())
        self.assertIn("p-1", self.signals())
        self.post()
        self.pre()
        self.assertIn("LESSON DUE", self.signals())
        lesson = self.propose_lesson("When starting a modeling brief: build the rerun script on day 1")
        self.post()
        self.assertEqual(self.store.q1("SELECT cleared_by FROM pending_lesson")[0], lesson)
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

    def test_retrospective_answering_an_earlier_lesson_due_does_not_count_for_this_brief(self):
        # Brief 1 closed without a retrospective; the mind wrote it during brief 2. When brief 2
        # closes, that retrospective is brief 1's, so brief 2 still gets a LESSON DUE.
        self.pre()
        self.propose_lesson("When starting a modeling brief: brief 1's lesson")
        self.post()
        self.at("2026-10-03T00:00:00Z")
        pack.build(self.store, pack.PackRequest(task="x", tags=[], project="p-2", budget=2000, log=True, use_llm=False))
        self.project("p-3", "# Project brief 3: emissions\n\nCount them.\n")
        self.pre()
        self.assertIn("LESSON DUE", self.signals())
        self.assertIn("p-2", self.signals())

    def test_no_signal_when_the_brief_left_a_retrospective(self):
        self.retro("When closing brief 1: what I would redo", ["area:process"], project="p-1")
        self.pre()
        self.assertNotIn("LESSON DUE", self.signals())

    def test_premortem_until_risks_section_exists(self):
        self.pre()
        self.assertIn("PREMORTEM DUE", self.signals())
        (self.pd / "risks.md").write_text("## p-2\n- stale figures (fail:stale): guard script\n")
        self.post()
        self.pre()
        self.assertNotIn("PREMORTEM DUE", self.signals())

    def test_no_review_lesson_due(self):
        # Run D asked for a lesson after every broken review and got 19 footnotes in a day.
        self.pre()
        (self.pd / "reviews" / "x-claims.md").write_text("C1: the fare is 1.50 USD\n")
        (self.pd / "reviews" / "x-adversary.md").write_text("BROKEN posted fare\n\nClaim verdicts:\n- C1: BROKEN [basis] posted vs paid\n")
        self.post()
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM pending_lesson WHERE kind = 'review'")[0], 0)


class ClassRecurrenceTest(RuntimeCase):
    def claims(self, project, n_reviews, broken_stale):
        with self.store.write():
            for i in range(n_reviews):
                f = f"reviews/{project}-{i}.md"
                self.store.ex("INSERT INTO review_claim(file, claim, verdict, class, project, ts) VALUES (?,?,?,?,?,?)", (f, "C1", "SURVIVES", None, project, "2026-10-01T00:00:00Z"))
                if i < broken_stale:
                    self.store.ex("INSERT INTO review_claim(file, claim, verdict, class, project, ts) VALUES (?,?,?,?,?,?)", (f, "C2", "BROKEN", "stale", project, "2026-10-01T00:00:00Z"))

    def test_lesson_confirmed_when_its_class_falls_and_recurred_when_it_rises(self):
        guard = self.retro("When writing prose numbers: generate them from outputs", ["area:process", "fail:stale"], project="p-1")
        basis = self.retro("When setting a parameter: match the source's basis", ["area:process", "fail:basis"], project="p-1")
        self.claims("p-1", 4, 3)
        self.claims("p-2", 4, 1)
        out = runtime.judge_lessons(self.store, "p-2", "p-1")
        by = {o["lesson"]: o["outcome"] for o in out}
        self.assertEqual(by.get(guard), "confirmed")
        self.assertNotIn(basis, by)  # basis never appeared: no evidence either way
        self.assertEqual(self.node(guard).status, "active")
        self.assertEqual(pack.lesson_judgments(self.store, [guard])[guard], 1)
        self.claims("p-3", 4, 3)
        out = runtime.judge_lessons(self.store, "p-3", "p-2")
        self.assertEqual({o["lesson"]: o["outcome"] for o in out}.get(guard), "recurred")
        self.assertEqual(pack.lesson_judgments(self.store, [guard])[guard], 0)

    def test_too_few_reviews_judge_nothing(self):
        self.retro("When writing prose numbers: generate them", ["area:process", "fail:stale"], project="p-1")
        self.claims("p-1", 2, 2)
        self.claims("p-2", 2, 0)
        self.assertEqual(runtime.judge_lessons(self.store, "p-2", "p-1"), [])


class ConfirmedFactsTest(RuntimeCase):
    def setUp(self):
        super().setUp()
        self.project("p-1", "# Project brief 1: mobility\n\nBuild a model.\n")

    def test_survived_claims_become_active_facts_with_review_provenance(self):
        self.pre()
        (self.pd / "reviews" / "fare-claims.md").write_text("Claims for review.\n\nC1: The mean paid fare is 1.08 USD per linked trip (FY2024 audit, data/fare.txt).\nC2: Ridership fell 12% in 2020.\nC3: Buses are blue.\n")
        (self.pd / "reviews" / "fare-adversary.md").write_text("SURVIVES mostly\n\nClaim verdicts:\n- C1: SURVIVES\n- C2: WEAKENED [band] one year only\n- C3: SURVIVES\n")
        out = self.post("Reviewed fares.")
        self.assertEqual(len(out["facts"]), 1)  # C3 has no number
        fid = out["facts"][0]["id"]
        n = self.node(fid)
        self.assertEqual((n.type, n.status, n.project), ("fact", "active", "p-1"))
        self.assertIn("1.08 USD", n.summary)
        self.assertEqual(n.provenance["method"], "review")
        self.assertIn("area:review", n.tags)
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM review_claim")[0], 3)
        # The same review a second time writes nothing new.
        self.pre()
        out = self.post("Touched the review again.")
        self.assertEqual(out["facts"], [])

    def test_shared_tag_in_a_claim_carries_to_the_fact(self):
        self.pre()
        (self.pd / "reviews" / "b" ).mkdir()
        (self.pd / "reviews" / "b" / "claims.md").write_text("- C1 shared:fleet-2035 — the 2035 light-duty fleet is 61,200 vehicles (model/results.json).\n")
        (self.pd / "reviews" / "b" / "adversary.md").write_text("SURVIVES\n\nClaim verdicts:\n- C1: SURVIVES\n")
        out = self.post("Reviewed the fleet.")
        n = self.node(out["facts"][0]["id"])
        self.assertIn("shared:fleet-2035", n.tags)
        self.assertEqual(consistency.shared_facts(self.store)[0].quantity, "fleet-2035")
        self.assertTrue((self.pd / "shared-values.md").exists())


class SharedValuesTest(RuntimeCase):
    def setUp(self):
        super().setUp()
        self.project("p-2")

    def fact(self, summary, project, tags=("shared:fleet-2035", "area:modeling")):
        n = project[-1]
        checks = {"1": "cross-checked with the ACS B08201 vehicle counts and the county assessor file", "2": "taken as given from brief 1 and reconciled with the AFDC registration series for 2024"}
        return self.add("fact", summary, list(tags), f"Read from p{n}/model/results.json (run of 2026-10-0{n}); {checks.get(n, 'checked')}.", provenance={"author": "main", "source": "results.json"}, project=project)

    def test_conflict_signal_until_reconciled(self):
        a = self.fact("The 2035 light-duty fleet is 61,200 vehicles", "p-1")
        b = self.fact("The 2035 light-duty fleet is 58,900 vehicles", "p-2")
        self.assertEqual([c["quantity"] for c in consistency.conflicts(self.store)], ["fleet-2035"])
        self.pre()
        self.assertIn("CONSISTENCY", self.signals())
        self.assertIn("fleet-2035", self.signals())
        pk_text = self.pre()
        self.assertIn(pack.MARK_SHARED, pk_text)
        self.assertIn(a, pk_text)
        self.assertIn(b, pk_text)
        with self.store.write():
            model.set_status(self.store, b, "superseded")
        self.pre()
        self.assertNotIn("CONSISTENCY", self.signals())

    def test_agreeing_values_and_reconciled_tag_raise_nothing(self):
        self.fact("The 2035 light-duty fleet is 61,200 vehicles", "p-1")
        self.fact("The 2035 fleet is 61,400 light-duty vehicles", "p-2")
        self.assertEqual(consistency.conflicts(self.store), [])
        self.fact("Discount rate 3% real for public costs", "p-1", ("shared:discount-rate",))
        self.fact("Discount rate 7% real, the household view, differs from p1 on purpose", "p-2", ("shared:discount-rate", "scope:reconciled"))
        self.assertEqual(consistency.conflicts(self.store), [])
        ledger = consistency.render_ledger(self.store, "p-2")
        self.assertIn("discount-rate", ledger)
        self.assertIn("61,200", ledger)

    def test_shared_rows_only_when_the_wake_touches_the_quantity(self):
        a = self.fact("The 2035 light-duty fleet is 61,200 vehicles", "p-1")
        self.fact("Discount rate 3% real", "p-1", ("shared:discount-rate",))
        rows = consistency.pack_rows(self.store, "charging load from the fleet in 2035", brief_start=False)
        self.assertEqual([n.id for n in rows], [a])
        self.assertEqual(len(consistency.pack_rows(self.store, "anything", brief_start=True)), 2)
        self.assertEqual(consistency.pack_rows(self.store, "unrelated words", brief_start=False), [])


if __name__ == "__main__":
    unittest.main()
