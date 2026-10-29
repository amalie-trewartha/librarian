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
from librarian import db, gate, lifecycle, outcome, pack, runtime, triggers


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


# ── run D, second round: failure classes, the review-time ledger, practices, pre-mortem ──


class FailureClassParseTest(StoreCase):
    REVIEW = (
        "BROKEN: two of five claims do not stand\n"
        "Claim verdicts:\n"
        "- C1: BROKEN [basis] posted fare used where the elasticity needs paid fare\n"
        "- **C2**: SURVIVES\n"
        "| C3 | WEAKENED | [fail:robustness] |\n"
        "| C4 | BROKEN | stale |\n"
        "- C5: BROKEN\n"
        "Problems:\n- C1: BROKEN [calc] repeated in the list, the first line counts\n"
    )

    def test_claim_verdicts_from_lines_and_table_rows(self):
        got = {c["claim"]: (c["verdict"], c["class"]) for c in outcome.claim_verdicts(self.REVIEW)}
        self.assertEqual(got, {"C1": ("BROKEN", "basis"), "C2": ("SURVIVES", None), "C3": ("WEAKENED", "robustness"), "C4": ("BROKEN", "stale"), "C5": ("BROKEN", "other")})
        self.assertEqual(outcome.failure_classes(self.REVIEW)[:1], ["basis"])
        self.assertIsNone(outcome.review_outcome([], outcome.claim_verdicts(self.REVIEW)))
        self.assertEqual(outcome.review_outcome([], outcome.claim_verdicts("- C1: SURVIVES\n- C2: UNVERIFIABLE\n")), "success")
        self.assertEqual(outcome.review_outcome([], outcome.claim_verdicts("- C1: BROKEN [calc]\n- C2: WEAKENED [band]\n")), "failure")

    def test_reviewer_claims_beat_the_minds_lines(self):
        # Run B: 29 of 66 reviews that broke a claim carry only "Memories SURVIVES" lines.
        text = "- C1: BROKEN [stale] x\n- C2: SURVIVES\nMemories SURVIVES: 01JA0000000000000000000001\n"
        self.assertIsNone(outcome.review_outcome([{"verdict": "SURVIVES"}], outcome.claim_verdicts(text)))

    def test_older_failure_class_line(self):
        self.assertEqual(outcome.failure_classes("BROKEN: x\nFailure class: calc, stale\n"), ["calc", "stale"])
        self.assertEqual(outcome.failure_classes("**Failure class:** fail:basis; caveat (missing)"), ["basis", "caveat"])
        self.assertEqual(outcome.failure_classes("Failure classes: vibes"), ["other"])
        self.assertEqual(outcome.failure_classes("Failure class: none\nSURVIVES"), [])
        self.assertEqual(outcome.failure_classes("no such line"), [])

    def test_fail_tags_are_a_closed_list(self):
        ok_ = gate.check(self.store, gate.Candidate(type="retrospective", summary="When a rerun changes inputs: rescan the prose", body="Run B: 3 stale figures in `deliverable.md` after rerun 7.", tags=["area:process", "fail:stale"], provenance={"author": "main"}))
        bad = gate.check(self.store, gate.Candidate(type="retrospective", summary="When a rerun changes inputs: rescan the prose", body="Run B: 3 stale figures in `deliverable.md` after rerun 7.", tags=["area:process", "fail:vibes"], provenance={"author": "main"}))
        self.assertFalse(any("fail:" in r for r in ok_))
        self.assertTrue(any("closed fail: list" in r for r in bad))


class FailureClassRuntimeTest(LessonRuntimeCase):
    def setUp(self):
        super().setUp()
        self.project("p-2")

    def land(self, name: str, text: str) -> dict:
        self.pre()
        (self.pd / "reviews" / name).write_text(text)
        return self.post("Acted on the review.")

    def test_broken_review_records_its_claims_and_asks_for_a_tagged_lesson(self):
        res = self.land("x-adversary.md", "BROKEN: the 2030 fleet double counts PHEVs\n- C1: BROKEN [calc] double count\n- C2: WEAKENED [inference] causal reading\n- C3: SURVIVES\n")
        self.assertEqual(sorted(res["failures"]["reviews/x-adversary.md"]), ["calc", "inference"])
        rows = self.store.q("SELECT claim, verdict, class, project FROM review_claim ORDER BY claim")
        self.assertEqual([tuple(r) for r in rows], [("C1", "BROKEN", "calc", "p-2"), ("C2", "WEAKENED", "inference", "p-2"), ("C3", "SURVIVES", None, "p-2")])
        self.pre()
        sig = self.signals()
        self.assertIn("failure classes: calc, inference", sig)
        self.assertIn("fail:calc fail:inference", sig)
        self.assertIn("no `Memories BROKEN:` line there names a memory", sig)
        self.assertNotIn("happened again", sig)

    def test_a_named_broken_memory_needs_no_nudge(self):
        fact = self.add("fact", "When I need the city fleet size", ["area:fleet"], "42 vehicles, DMV 2024, https://dmv.example/2024, verified 2026-10-01.")
        self.land("x-adversary.md", f"BROKEN: x\n- C1: BROKEN [calc] y\nMemories BROKEN: {fact}\n")
        self.pre()
        self.assertNotIn("no `Memories BROKEN:` line", self.signals())

    def test_reviewer_breaks_without_the_word_in_mind_lines_still_asks(self):
        # Only SURVIVES on the mind's line, but the reviewer weakened a claim.
        self.land("w-adversary.md", "- C1: WEAKENED [robustness] floor claimed\n- C2: SURVIVES\nMemories SURVIVES: \n")
        self.pre()
        self.assertIn("LESSON DUE", self.signals())

    def test_recurring_class_names_the_lesson_that_should_have_caught_it(self):
        guard = self.retro("When converting energy units: carry units in column names", ["area:process", "fail:basis"], project="p-1")
        self.land("x-adversary.md", "BROKEN: kWh read as MWh\n- C1: BROKEN [basis] kWh read as MWh\n")
        self.pre()
        self.assertIn("happened again", self.signals())
        self.assertIn(guard, self.signals())

    def test_surviving_review_records_nothing(self):
        res = self.land("y-adversary.md", "SURVIVES: all numbers trace\n- C1: SURVIVES\n")
        self.assertEqual(res["failures"], {})
        self.assertEqual(self.store.q1("SELECT verdict FROM review_claim")[0], "SURVIVES")

    def test_lessons_against_frequent_mistakes_rank_first(self):
        others = [self.retro(f"When doing step {w}: lesson {w}", ["area:process"]) for w in ("alpha", "beta", "gamma")]
        guard = self.retro("When a rerun changes inputs: rescan prose numbers", ["area:process", "fail:stale"])
        with self.store.write():
            for o in others:
                self.store.ex("UPDATE nodes SET confidence = 0.8 WHERE id = ?", (o,))
            for f in ("a", "b"):
                self.store.ex("INSERT INTO review_claim(file, claim, verdict, class, project, ts) VALUES (?, 'C1', 'BROKEN', 'stale', 'p-1', ?)", (f"reviews/{f}.md", db.now_iso()))
        pk = pack.build(self.store, pack.PackRequest(task="x", tags=[], project="p-2", phase="building", budget=5000, log=False, use_llm=False, lessons=True))
        self.assertEqual(pk.ids("lesson")[0], guard)


class LedgerCreditTest(LessonRuntimeCase):
    def setUp(self):
        super().setUp()
        self.project("p-1", "# Project brief: mobility\n\nModel travel.\n")
        self.lesson = self.retro("When a report hand-cites outputs: key every number to its output", ["area:process"])
        (self.pd / ".blind").mkdir(exist_ok=True)

    def ledger(self, **row):
        with open(self.pd / ".blind" / "lessons.jsonl", "a") as f:
            f.write(json.dumps({"ts": "2026-10-01T00:00:00Z", "role": "adversary", "lessons": [self.lesson], **row}) + "\n")

    def land(self, name: str, text: str) -> dict:
        self.pre()
        (self.pd / "reviews" / name).write_text(text)
        return self.post("Acted on the review.")

    def test_lessons_blind_recorded_in_the_same_wake_count(self):
        # Claims written and reviewed in one wake: nothing committed yet, the ledger holds the lessons.
        self.ledger(out="project/reviews/p-adversary.md", verdict="SURVIVES: x")
        res = self.land("p-adversary.md", "SURVIVES: x\n")
        self.assertEqual(res["lessons"]["credited"], {self.lesson: "success"})

    def test_matched_by_verdict_line_without_out(self):
        self.ledger(out="", verdict="BROKEN: the bus speed ignores dwell time at stops")
        res = self.land("q-adversary.md", "BROKEN: the bus speed ignores dwell time at stops\nFailure class: base\n")
        self.assertEqual(res["lessons"]["credited"], {self.lesson: "failure"})

    def test_short_verdict_lines_do_not_match_other_reviews(self):
        self.ledger(out="", verdict="SURVIVES")
        res = self.land("r-adversary.md", "SURVIVES\n")
        self.assertEqual(res["lessons"]["credited"], {})

    def test_a_review_judges_a_lesson_once(self):
        self.ledger(out="project/reviews/p-adversary.md", verdict="SURVIVES: x")
        self.land("p-adversary.md", "SURVIVES: x\n")
        res = self.land("p-adversary.md", "SURVIVES: x\nMemories SURVIVES: (none)\n")
        self.assertEqual(res["lessons"]["credited"], {})
        self.assertAlmostEqual(self.node(self.lesson).confidence, 0.5 + lifecycle.STEP, places=3)

    def test_mixed_review_blames_only_lessons_against_the_class_it_found(self):
        guard = self.retro("When a rerun changes inputs: rescan prose numbers", ["area:process", "fail:stale"])
        other = self.retro("When quoting a band: cite the band's sources", ["area:process", "fail:band"])
        with open(self.pd / ".blind" / "lessons.jsonl", "a") as f:
            f.write(json.dumps({"out": "reviews/m-adversary.md", "verdict": "", "lessons": [guard, other, self.lesson]}) + "\n")
        res = self.land("m-adversary.md", "BROKEN: one figure is stale\n- C1: BROKEN [stale] 0.433 vs 0.441\n- C2: SURVIVES\n")
        self.assertEqual(res["lessons"]["credited"], {guard: "failure"})

    def test_a_committed_sidecar_counts(self):
        (self.pd / "reviews" / "s-lessons.md").write_text(f"Lessons applied: {self.lesson}\n")
        self.commit()
        res = self.land("s-adversary.md", "SURVIVES: x\n")
        self.assertEqual(res["lessons"]["credited"], {self.lesson: "success"})


class PracticeTest(StoreCase):
    def judge(self, nid: str, oc: str, project: str):
        self.episode("partial", [nid], project=project, overrides={nid: oc})

    def req(self) -> pack.PackRequest:
        return pack.PackRequest(task="x", tags=[], project="p-3", phase="building", budget=5000, log=True, use_llm=False, lessons=True)

    def test_confirmed_in_two_briefs_becomes_a_practice(self):
        lesson = self.retro("When starting a brief: build the crude end-to-end answer first", ["area:process", "ctx:planning"])
        self.judge(lesson, "success", "p-1")
        self.assertNotIn(lesson, pack.practice_ids(self.store))
        self.at("2026-10-03T00:00:00Z")
        self.judge(lesson, "success", "p-1")
        self.assertNotIn(lesson, pack.practice_ids(self.store))  # two wins in one brief are not two briefs
        self.at("2026-10-04T00:00:00Z")
        self.judge(lesson, "success", "p-2")
        pk = pack.build(self.store, self.req())
        self.assertEqual(pk.ids("practice"), [lesson])
        self.assertNotIn(lesson, pk.ids("lesson"))
        text = pack.render_text(pk)
        self.assertLess(text.index(pack.MARK_PRACTICES), text.index(pack.MARK_TASK))
        self.assertEqual(self.store.q1("SELECT section FROM retrieval_log WHERE node_id = ? AND request_id = ?", (lesson, pk.request_id))[0], "practice")

    def test_a_failure_demotes_it(self):
        lesson = self.retro("When starting a brief: build the crude end-to-end answer first", ["area:process"])
        self.judge(lesson, "success", "p-1")
        self.at("2026-10-03T00:00:00Z")
        self.judge(lesson, "success", "p-2")
        self.assertIn(lesson, pack.practice_ids(self.store))
        self.at("2026-10-05T00:00:00Z")
        self.judge(lesson, "failure", "p-3")
        self.assertNotIn(lesson, pack.practice_ids(self.store))
        self.assertIn(lesson, pack.build(self.store, self.req()).ids("lesson"))

    def test_only_lessons_become_practices(self):
        fact = self.add("fact", "When I need the US EV pack price in 2024", ["area:prices"], "123 $/kWh, BNEF 2024, https://about.bnef.com, verified 2026-10-01.")
        self.judge(fact, "success", "p-1")
        self.at("2026-10-03T00:00:00Z")
        self.judge(fact, "success", "p-2")
        self.assertEqual(pack.practice_ids(self.store), [])


class PremortemTest(LessonRuntimeCase):
    def test_first_wakes_of_a_brief_ask_for_risks_until_written(self):
        self.project("p-2")
        self.pre()
        self.assertIn("PREMORTEM DUE", self.signals())
        self.assertIn("## p-2", self.signals())
        self.post()
        (self.pd / "risks.md").write_text("## p-2 risks\n1. stale figures (fail:stale) - none\n")
        self.pre()
        self.assertNotIn("PREMORTEM DUE", self.signals())

    def test_not_after_the_brief_start(self):
        self.project("p-2")
        for _ in range(runtime.TRANSFER_WAKES_DEFAULT):
            self.pre()
            self.post()
        self.pre()
        self.assertNotIn("PREMORTEM DUE", self.signals())


class SignatureTest(StoreCase):
    def test_a_bare_number_is_not_an_error_signature(self):
        steps = [{"type": "shell-output", "exit": 1, "stderr": "", "stdout": "42\n"}, {"type": "shell-output", "exit": 1, "stderr": "KeyError: 'fleet_2030'"}]
        self.assertEqual(outcome.error_signatures(steps), [outcome.error_signatures(steps[1:])[0]])
        self.assertEqual(len(outcome.error_signatures(steps)), 1)


class TriggersOffTest(StoreCase):
    def test_decision_point_can_be_switched_off(self):
        os.environ["LIBRARIAN_TRIGGERS_OFF"] = "decision_point"
        try:
            self.assertIn("decision_point", triggers._off())
        finally:
            del os.environ["LIBRARIAN_TRIGGERS_OFF"]
        self.assertEqual(triggers._off(), set())


class MigrationV6Test(StoreCase):
    def test_v5_store_gains_failures_ledger_and_fail_tags(self):
        with self.store.write():
            self.store.ex("DROP TABLE review_claim")
            self.store.ex("DROP TABLE lesson_judged")
            self.store.ex("DROP TABLE pending_lesson")
            self.store.ex("CREATE TABLE pending_lesson (id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('review','brief')), ref TEXT NOT NULL, project TEXT, created TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0, last_request TEXT, cleared TEXT, cleared_by TEXT)")
            self.store.ex("DELETE FROM tag_vocab WHERE namespace = 'fail'")
            self.store.meta_set("schema_version", "5")
        self.store.close()
        self.store = db.Store.open()
        self.assertEqual(self.store.meta_get("schema_version"), "6")
        for t in ("review_claim", "lesson_judged"):
            self.assertIsNotNone(self.store.q1("SELECT name FROM sqlite_master WHERE name = ?", (t,)))
        self.assertIn("detail", {r[1] for r in self.store.q("PRAGMA table_info(pending_lesson)")})
        self.assertEqual(self.store.q1("SELECT status FROM tag_vocab WHERE tag = 'fail:calc'")[0], "active")


if __name__ == "__main__":
    unittest.main()
