import unittest

from helpers import StoreCase
from librarian import triggers


class SignatureTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(triggers.normalize_signature("\n  Error at /home/u/x/y.py line 42: code 0xdeadbeef1\n"), "Error at <path> line <n>: code <hex>")
        self.assertEqual(triggers.normalize_signature("ModuleNotFoundError: No module named 'pint'"), "ModuleNotFoundError: No module named 'pint'")


class ProgressTest(StoreCase):
    def prog(self, status="worked on the model", errors=(), tool_calls=5, **kw):
        base = dict(tags=["project:p-1", "pkg:pint"], phase="building", project="p-1")
        base.update(kw)
        return triggers.Progress(status=status, errors=list(errors), tool_calls=tool_calls, **base)

    def test_new_tags_noted_not_suggested(self):
        res = triggers.evaluate(self.store, self.prog(tags=["project:p-1", "pkg:brandnew"]))
        self.assertIsNone(res["suggestion"])
        self.assertIn("pkg:brandnew", res["new_tags"])
        res2 = triggers.evaluate(self.store, self.prog(tags=["project:p-1", "pkg:brandnew"]))
        self.assertEqual(res2["new_tags"], [])

    def test_repeated_failure_after_three_and_cooldown(self):
        s = self.skill("pint under the sandbox: pip install --user then PYTHONPATH", ["pkg:pint", "area:tooling"])
        sig = "ModuleNotFoundError: No module named 'pint'"
        for i in range(2):
            res = triggers.evaluate(self.store, self.prog(errors=[sig]))
            self.assertIsNone(res["suggestion"], i)
        res = triggers.evaluate(self.store, self.prog(errors=[sig]))
        self.assertIsNotNone(res["suggestion"])
        self.assertEqual(res["suggestion"]["trigger"], "repeated_failure")
        self.assertIn(s, res["suggestion"]["memory_ids"])
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM retrieval_log WHERE source = 'suggestion'")[0], 1)
        # Cooldown: another failure right away suggests nothing.
        res = triggers.evaluate(self.store, self.prog(errors=[sig], tool_calls=10))
        self.assertIsNone(res["suggestion"])
        self.assertFalse(res["cooldown"]["ready"])
        # 50 tool calls lift it.
        res = triggers.evaluate(self.store, self.prog(errors=[sig], tool_calls=45))
        self.assertIsNotNone(res["suggestion"])

    def test_cooldown_by_project_time(self):
        with self.store.write():
            triggers._suggest(self.store, "decision_point", [], "x", "p-1")
        self.assertFalse(triggers.cooldown_state(self.store, "p-1")["ready"])
        self.at("2026-10-01T00:16:00Z")
        self.assertTrue(triggers.cooldown_state(self.store, "p-1")["ready"])

    def test_decision_point(self):
        d = self.decision("chose parquet over sqlite for logs", ["pkg:parquet", "project:p-1"], project="p-1")
        res = triggers.evaluate(self.store, self.prog(status="Deciding whether to store logs in parquet or sqlite; weighing the alternatives.", tags=["project:p-1", "pkg:parquet"]))
        self.assertEqual(res["suggestion"]["trigger"], "decision_point")
        self.assertEqual(res["suggestion"]["memory_ids"], [d])

    def test_deviation(self):
        p = self.pref("Prefer small reviewable PRs over large feature branches.", ["team:x", "area:review"])
        res = triggers.evaluate(self.store, self.prog(status="Opened one large feature branch PR with everything; small reviewable PRs would never have fit.", tags=["project:p-1", "area:review"]))
        self.assertIsNotNone(res["suggestion"])
        self.assertEqual(res["suggestion"]["trigger"], "deviation")
        self.assertEqual(res["suggestion"]["memory_ids"], [p])

    def test_phase_drift(self):
        r = self.retro("building usually takes two hours here", ["expect:building:2", "area:process"])
        self.activate(r)
        triggers.evaluate(self.store, self.prog(status="started building"))
        self.at("2026-10-01T03:00:00Z")
        res = triggers.evaluate(self.store, self.prog(status="still building the model"))
        self.assertEqual(res["suggestion"]["trigger"], "phase_drift")
        self.assertEqual(res["suggestion"]["memory_ids"], [r])

    def test_contradiction_found_marks_disputed(self):
        from librarian import model, pack

        a = self.skill("eigen via Eigen3_DIR", ["pkg:colcon"], project="p-1", body="Set `Eigen3_DIR=/opt/eigen`; verified 2026-09-01.")
        b = self.skill("eigen via system package", ["pkg:colcon"], project="p-1", body="Run `apt install libeigen3-dev` 3.4; verified 2026-09-02.")
        for n in (a, b):
            self.activate(n)
        with self.store.write():
            model.add_edge(self.store, a, b, "contradicts")
        pack.build(self.store, pack.PackRequest(task="eigen", tags=["pkg:colcon"], project="p-1", budget=3000, use_llm=False))
        res = triggers.evaluate(self.store, self.prog(status="plain status"))
        self.assertEqual(res["suggestion"]["trigger"], "contradiction_found")
        self.assertEqual(self.node(a).status, "disputed")

    def test_respond_and_acceptance_bumps(self):
        sids = []
        for i in range(6):
            with self.store.write():
                sids.append(triggers._suggest(self.store, "decision_point", [], "x", "p-1")["id"])
        for sid in sids:
            triggers.respond(self.store, sid, "dismiss")
        acc = triggers.acceptance(self.store)["decision_point"]
        self.assertEqual(acc["dismiss"], 6)
        self.assertEqual(acc["rate"], 0.0)
        self.assertGreaterEqual(triggers.bump(self.store, "p-1", "decision_point"), 1)
        with self.assertRaises(ValueError):
            triggers.respond(self.store, sids[0], "maybe")
        with self.assertRaises(KeyError):
            triggers.respond(self.store, "nope", "accept")

    def test_undelivered_and_mark(self):
        with self.store.write():
            sid = triggers._suggest(self.store, "decision_point", [], "x", "p-1")["id"]
        self.assertEqual([s["id"] for s in triggers.undelivered(self.store, "p-1")], [sid])
        with self.store.write():
            triggers.mark_delivered(self.store, [sid])
        self.assertEqual(triggers.undelivered(self.store, "p-1"), [])


if __name__ == "__main__":
    unittest.main()
