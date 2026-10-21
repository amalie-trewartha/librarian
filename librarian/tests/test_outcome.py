import unittest

from librarian import outcome


def ev(**kw) -> outcome.WakeEvidence:
    return outcome.WakeEvidence(**kw)


class OutcomeRuleTest(unittest.TestCase):
    def test_table_in_order(self):
        self.assertEqual(outcome.decide_outcome(ev(ritual="daily 2026-10-01", ritual_output_written=True, rc=1))[:2], ("success", "ritual daily output written"))
        oc, crit, ov = outcome.decide_outcome(ev(review_verdicts=[{"file": "reviews/x.md", "verdict": "SURVIVES", "ids": ["A" * 26]}], final="done"))
        self.assertEqual((oc, crit), ("partial", "adversary review SURVIVES: reviews/x.md"))
        self.assertEqual(ov, {"A" * 26: "success"})
        oc, crit, ov = outcome.decide_outcome(ev(review_verdicts=[{"file": "reviews/y.md", "verdict": "BROKEN", "ids": ["B" * 26]}], final="done", journal_dirty=True))
        self.assertEqual((oc, crit), ("partial", "adversary review BROKEN: reviews/y.md"))
        self.assertEqual(ov, {"B" * 26: "failure"})
        self.assertEqual(outcome.decide_outcome(ev(stderr_tail="Max iterations (25) reached without final answer", rc=1))[:2], ("failure", "step cap reached without FINAL"))
        self.assertEqual(outcome.decide_outcome(ev(rc=2))[:2], ("failure", "run failed (rc=2)"))
        api = "shellm: error: llm failed (exit 1): llm: error: API error (HTTP 503): Bedrock is unable to process your request."
        self.assertEqual(outcome.decide_outcome(ev(rc=1, stderr_tail=api))[:2], ("partial", "run cut off by model API failure (rc=1)"))
        self.assertEqual(outcome.decide_outcome(ev(rc=1, stderr_tail="Traceback: API error (HTTP 404) from my script"))[:2], ("failure", "run failed (rc=1)"))
        oc, crit, ov = outcome.decide_outcome(ev(recurred=[{"signature": "boom", "skill_id": "C" * 26}], final="x"))
        self.assertEqual((oc, crit), ("failure", "failure recurred: boom"))
        self.assertEqual(ov, {"C" * 26: "failure"})
        self.assertEqual(outcome.decide_outcome(ev(journal_dirty=True, final="Did things"))[:2], ("partial", "journal entry + FINAL (unverified)"))
        self.assertEqual(outcome.decide_outcome(ev(final="Did things"))[:2], ("partial", "FINAL without journal entry"))
        self.assertEqual(outcome.decide_outcome(ev())[:2], ("unknown", "no measurable artifact"))

    def test_verdict_without_ids_is_not_success(self):
        oc, _, _ = outcome.decide_outcome(ev(review_verdicts=[{"file": "r.md", "verdict": "SURVIVES", "ids": []}], final="x", journal_dirty=True))
        self.assertEqual(oc, "partial")


class PhaseMapTest(unittest.TestCase):
    def test_map(self):
        self.assertEqual(outcome.map_phase("build", None, ""), "building")
        self.assertEqual(outcome.map_phase("harden", None, ""), "reviewing")
        self.assertEqual(outcome.map_phase("final", None, ""), "handoff")
        self.assertEqual(outcome.map_phase("ended", None, ""), "handoff")
        self.assertEqual(outcome.map_phase("open", None, ""), "building")
        self.assertEqual(outcome.map_phase("build", "daily 2026-10-01", ""), "reviewing")
        self.assertEqual(outcome.map_phase("build", "final final", ""), "handoff")
        self.assertEqual(outcome.map_phase("build", None, "- STALL: journal unchanged"), "planning")
        self.assertEqual(outcome.map_phase("build", None, "- DELIVERABLE MISSING"), "planning")
        self.assertEqual(outcome.map_phase("build", None, "", debugging=True), "debugging")


class TrajectoryTest(unittest.TestCase):
    def steps(self):
        return [
            {"type": "reasoning", "cmd": "python3 model.py", "run_id": "r"},
            {"type": "shell-output", "exit": 1, "stderr": "Traceback...\nModuleNotFoundError: No module named 'pint'", "run_id": "r", "step_id": "s1"},
            {"type": "reasoning", "cmd": "python3 model.py --fast", "run_id": "r"},
            {"type": "shell-output", "exit": 1, "stderr": "ModuleNotFoundError: No module named 'pint'", "run_id": "r", "step_id": "s2"},
            {"type": "reasoning", "cmd": "pip install --user pint", "run_id": "r"},
            {"type": "shell-output", "exit": 0, "stdout": "ok", "run_id": "r", "step_id": "s3"},
            {"type": "reasoning", "cmd": "python3 model.py", "run_id": "r"},
            {"type": "shell-output", "exit": 0, "stdout": "42", "run_id": "r", "step_id": "s4"},
            {"type": "observation", "content": "used memory 01J9W8K2M3N4P5Q6R7S8T9V0WX", "run_id": "r"},
        ]

    def test_error_signatures(self):
        sigs = outcome.error_signatures(self.steps())
        self.assertEqual(sigs, ["ModuleNotFoundError: No module named 'pint'"])

    def test_resolved_failures(self):
        res = outcome.detect_resolved_failures(self.steps())
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["family"], "python3")
        self.assertEqual(res[0]["span"], ["s1", "s4"])
        self.assertEqual(res[0]["count"], 2)

    def test_single_failure_not_resolved(self):
        steps = self.steps()[2:]
        self.assertEqual(outcome.detect_resolved_failures(steps), [])

    def test_mixed_review_credits_each_memory_by_its_own_verdict(self):
        good, bad, other = "01J9W8K2M3N4P5Q6R7S8T9V0WX", "01J9W8K2M3N4P5Q6R7S8T9V0WY", "01J9W8K2M3N4P5Q6R7S8T9V0WZ"
        text = f"BROKEN: claim 3 fails.\n(1) SURVIVES\n(3) BROKEN, see {other}\nMemories SURVIVES: {good}\nMemories BROKEN: {bad}\n"
        v = outcome.review_verdicts({"reviews/m.md": text})
        self.assertEqual([(x["verdict"], x["ids"]) for x in v], [("SURVIVES", [good]), ("BROKEN", [bad])])
        oc, crit, ov = outcome.decide_outcome(ev(review_verdicts=v, final="x", journal_dirty=True))
        self.assertEqual((oc, crit), ("partial", "adversary review mixed: reviews/m.md"))
        self.assertEqual(ov, {good: "success", bad: "failure"})

    def test_find_ulids_and_verdicts(self):
        self.assertEqual(outcome.find_ulids("see 01J9W8K2M3N4P5Q6R7S8T9V0WX and again 01J9W8K2M3N4P5Q6R7S8T9V0WX"), ["01J9W8K2M3N4P5Q6R7S8T9V0WX"])
        v = outcome.review_verdicts({"reviews/a.md": "Claim cites 01J9W8K2M3N4P5Q6R7S8T9V0WX.\nVerdict: SURVIVES", "reviews/b.md": "no verdict here", "reviews/c.md": "SURVIVES partly but BROKEN overall"})
        self.assertEqual(len(v), 2)
        self.assertEqual(v[0]["verdict"], "SURVIVES")
        self.assertEqual(v[0]["ids"], ["01J9W8K2M3N4P5Q6R7S8T9V0WX"])
        self.assertEqual(v[1]["verdict"], "BROKEN")

    def test_command_family(self):
        self.assertEqual(outcome.command_family("# comment\nsudo apt-get install x"), "apt-get")
        self.assertEqual(outcome.command_family("traj append ...\n/usr/bin/python3 x.py"), "python3")
        self.assertEqual(outcome.command_family(""), "")


if __name__ == "__main__":
    unittest.main()
