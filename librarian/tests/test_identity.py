import unittest

from helpers import StoreCase
from headlong_librarian import identity, model, queue, triggers


class WorkingEditTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.c1 = self.core("No unsourced number ever stands in for a sourced one; a placeholder is labeled as one.")
        self.c2 = self.core("I say plainly when I am blocked or done rather than reporting progress I did not make.")
        self.ep = self.episode("success", []).episode_id

    def edit(self, text, **kw):
        base = dict(occasion="weekly", occasion_key="w1", reason="it helped twice", episodes=[self.ep], use_llm=False)
        base.update(kw)
        return identity.edit_working(self.store, text, text, **base)

    def test_edit_stored_and_logged(self):
        res = self.edit("I write the integration test scaffold before the first feature commit.")
        self.assertTrue(res.accepted, res.reasons)
        n = self.node(res.id)
        self.assertEqual(n.type, "identity_working")
        self.assertEqual(n.status, "probationary")
        row = self.store.q1("SELECT occasion, occasion_key FROM identity_edits WHERE node_id = ?", (res.id,))
        self.assertEqual(tuple(row), ("weekly", "w1"))

    def test_rate_limit_per_occasion_key(self):
        self.assertTrue(self.edit("First habit about test scaffolds.").accepted)
        res = self.edit("Second habit about reading the spec twice.")
        self.assertEqual(res.action, "refused")
        self.assertEqual(res.status, "rate_limit")
        self.assertTrue(self.edit("Second habit about reading the spec twice.", occasion_key="w2").accepted)

    def test_failure_trigger_needs_accepted_suggestion_and_consumes_it(self):
        res = self.edit("After a repeated failure I check the skill store first.", occasion="failure-trigger")
        self.assertEqual(res.status, "rate_limit")
        with self.store.write():
            sid = triggers._suggest(self.store, "repeated_failure", [], "x", "p-1")["id"]
        res = self.edit("After a repeated failure I check the skill store first.", occasion="failure-trigger", trigger_id=sid)
        self.assertEqual(res.status, "rate_limit")  # not accepted yet
        triggers.respond(self.store, sid, "accept")
        res = self.edit("After a repeated failure I check the skill store first.", occasion="failure-trigger", trigger_id=sid)
        self.assertTrue(res.accepted, res.reasons)
        self.assertEqual(self.store.q1("SELECT consumed_by FROM suggestions WHERE id = ?", (sid,))[0], res.id)
        res2 = self.edit("Another habit after the same failure.", occasion="failure-trigger", trigger_id=sid)
        self.assertEqual(res2.status, "rate_limit")

    def test_bound_requires_supersede(self):
        rules = [
            "I begin every wake by rereading the plan file and choosing the single task that most improves the deliverable per token spent, ahead of any exploration or reading.",
            "I run the adversary reviewer on every quantitative claim before it enters project memory and I name its output file in the journal entry that records the claim.",
            "I keep the crude end-to-end model current with every new input and rerun it after each data source lands, writing the headline number into the deliverable each time.",
            "I close each work wake with a journal entry that names its evidence files and the next concrete step, so the following wake can resume without rereading the whole record.",
            "I spend the first steps of a project week reviewing every open question for defaults that matured and applying them, with their risk recorded, ahead of new work.",
            "I treat a subagent's result as a claim to audit against its cited lines, and I never copy a number from a helper into project memory without checking the citation.",
            "I size each wake's work to the step cap and record a handoff in FINAL when the harness warns me, instead of leaving half-finished edits for the next wake to discover.",
            "I read the cold-eyes review before planning the week and turn each finding I accept into a journal entry with a status, rather than answering it in prose only.",
        ]
        ids = []
        res = None
        for i, text in enumerate(rules):
            res = self.edit(text, occasion_key=f"k{i}")
            if res.accepted:
                ids.append(res.id)
            elif res.status == "over_bound":
                break
            else:
                self.fail(f"unexpected refusal: {res.status} {res.reasons}")
        self.assertGreaterEqual(len(ids), 4)
        self.assertEqual(res.status, "over_bound")
        self.assertTrue(any("current" in n for n in res.notes))
        res = self.edit("A short replacement rule about planning.", occasion_key="kfinal", supersedes=ids[0])
        self.assertTrue(res.accepted, res.reasons)
        self.assertEqual(self.node(ids[0]).status, "superseded")

    def test_core_contradiction_refused_and_queued(self):
        res = self.edit("I never label a placeholder number; unsourced numbers are fine when sourced ones are slow.")
        self.assertEqual(res.status, "contradicts_core")
        self.assertEqual(len(res.queued), 1)
        items = queue.list_items(self.store, "pending", "working_conflict")
        self.assertEqual(items[0]["payload"]["core_id"], self.c1)
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM nodes WHERE type = 'identity_working'")[0], 0)

    def test_heuristic_negative_and_positive_cases(self):
        self.assertFalse(triggers.heuristic_contradiction("I write tests first.", "I flag uncertainty explicitly."))
        self.assertTrue(triggers.heuristic_contradiction("I never flag uncertainty explicitly.", "I flag uncertainty explicitly."))
        self.assertTrue(triggers.heuristic_contradiction("I always ask before I proceed on a scope change.", "I proceed on scope changes and never ask first."))

    def test_llm_judge_overrides_heuristic(self):
        from headlong_librarian import llm as llmmod

        class Fake:
            model = "fake"

            def complete(self, prompt, system="", max_tokens=0):
                return '{"contradicts": false, "core_id": null}'

        orig = llmmod.get_llm
        llmmod.get_llm = lambda role, allow=True: Fake() if (allow and role == "judge") else None
        try:
            res = self.edit("I never label a placeholder number; unsourced numbers are fine when sourced ones are slow.", use_llm=True)
        finally:
            llmmod.get_llm = orig
        self.assertTrue(res.accepted, res.reasons)

    def test_held_behind_pending_core_proposal(self):
        identity.propose_core(self.store, "I write the test scaffold before the first feature commit", "I write the test scaffold before the first feature commit on multi-service work.", [], [])
        res = self.edit("I write the test scaffold before the first feature commit.")
        self.assertEqual(res.status, "held_pending_core")
        self.assertEqual(len(queue.list_items(self.store, "pending", "held_working_edit")), 1)

    def test_revert_restores_previous(self):
        a = self.edit("Rule version one about planning.", occasion_key="a")
        b = self.edit("Rule version two about planning.", occasion_key="b", supersedes=a.id)
        self.assertEqual(self.node(a.id).status, "superseded")
        rep = identity.revert(self.store, b.id, "probe drift")
        self.assertEqual(rep["restored"], a.id)
        self.assertEqual(self.node(a.id).status, "active")
        self.assertEqual(self.node(b.id).status, "superseded")
        self.assertIsNotNone(self.store.q1("SELECT reverted_ts FROM identity_edits WHERE node_id = ?", (b.id,))[0])
        self.assertEqual(len(queue.list_items(self.store, "pending", "reversion_note")), 1)

    def test_dry_run_writes_nothing(self):
        res = self.edit("A new habit about reading reviews first.", dry_run=True)
        self.assertEqual(res.action, "dry-run")
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM nodes WHERE type = 'identity_working'")[0], 0)


class QueueTest(StoreCase):
    def test_core_proposal_approve_inserts_core_and_supersedes_working(self):
        w = self.working("I write the test scaffold before the first feature commit.")
        with self.store.write():
            qid = queue.enqueue(self.store, "core_proposal", {"summary": "I write the test scaffold first", "body": "I write the test scaffold before the first feature commit.", "source": w, "source_type": "identity_working", "tags": ["scope:identity"], "evidence": []})
            held = queue.enqueue(self.store, "held_working_edit", {"summary": "x", "body": "x", "core_proposal": qid})
        res = identity.decide(self.store, qid, "approve", "ok")
        core = res["effects"]["core"]
        self.assertTrue(core["accepted"])
        self.assertEqual(self.node(core["id"]).type, "identity_core")
        self.assertEqual(self.node(core["id"]).status, "active")
        self.assertEqual(self.node(w).status, "superseded")
        self.assertEqual(queue.get_item(self.store, held)["status"], "rejected")
        self.assertEqual(identity.decide(self.store, qid, "approve")["note"], "already decided")

    def test_core_proposal_reject_lists_unblocked(self):
        with self.store.write():
            qid = queue.enqueue(self.store, "core_proposal", {"summary": "s", "body": "b"})
            held = queue.enqueue(self.store, "held_working_edit", {"summary": "x", "body": "x", "core_proposal": qid})
        res = identity.decide(self.store, qid, "reject")
        self.assertEqual(res["effects"]["unblocked_held"], [held])

    def test_working_conflict_approve_applies_edit(self):
        self.core("I flag uncertainty explicitly.")
        with self.store.write():
            qid = queue.enqueue(self.store, "working_conflict", {"summary": "I hedge uncertainty into prose when it reads better.", "body": "I hedge uncertainty into prose when it reads better.", "core_id": "x"})
        res = identity.decide(self.store, qid, "approve")
        self.assertTrue(res["effects"]["working"]["accepted"], res["effects"]["working"])

    def test_dispute_decision(self):
        a = self.skill("a", ["pkg:x"])
        b = self.skill("b", ["pkg:x"])
        with self.store.write():
            model.set_status(self.store, a, "disputed")
            model.set_status(self.store, b, "disputed")
            qid = queue.enqueue(self.store, "dispute", {"a": a, "b": b})
        with self.assertRaises(ValueError):
            identity.decide(self.store, qid, "approve")
        res = identity.decide(self.store, qid, "approve", a)
        self.assertEqual(res["effects"]["kept"], a)
        self.assertEqual(self.node(a).status, "active")
        self.assertEqual(self.node(b).status, "superseded")

    def test_new_area_tag_decisions(self):
        with self.store.write():
            model.upsert_vocab(self.store, "area:novel", "seen")
            q1 = queue.enqueue(self.store, "new_area_tag", {"tag": "area:novel"}, dedupe_key="area:area:novel")
        identity.decide(self.store, q1, "approve")
        self.assertEqual(model.vocab_status(self.store, "area:novel"), "active")
        with self.store.write():
            model.upsert_vocab(self.store, "area:bad", "seen")
            q2 = queue.enqueue(self.store, "new_area_tag", {"tag": "area:bad"})
        identity.decide(self.store, q2, "reject")
        self.assertEqual(model.vocab_status(self.store, "area:bad"), "rejected")

    def test_dedupe_and_counts(self):
        with self.store.write():
            a = queue.enqueue(self.store, "dispute", {"a": "1"}, dedupe_key="k")
            b = queue.enqueue(self.store, "dispute", {"a": "1"}, dedupe_key="k")
        self.assertIsNotNone(a)
        self.assertIsNone(b)
        self.assertEqual(queue.pending_count(self.store), 1)
        with self.assertRaises(KeyError):
            identity.decide(self.store, "nope", "approve")


class SeedAndProbeTest(StoreCase):
    def test_seed_core_from_blocks(self):
        text = "### a\nI flag uncertainty.\n\n### b\nI never write an Answer line.\n"
        rows = identity.seed_core(self.store, text)
        self.assertEqual([r["slug"] for r in rows], ["a", "b"])
        self.assertTrue(all(r["accepted"] for r in rows))
        self.assertEqual(len(identity.list_identity(self.store, "core")), 2)
        self.assertTrue(all(n.status == "active" for n in identity.list_identity(self.store, "core")))

    def test_core_candidate_rule(self):
        from headlong_librarian import lifecycle

        w = self.working("I write the scaffold first.")
        self.activate(w)
        for p in ("p-1", "p-2", "p-3"):
            self.episode("success", [w], project=p)
        self.at("2027-01-15T00:00:00Z")
        rep = lifecycle.consolidate(self.store, only=["promote"])
        self.assertEqual(rep["steps"]["promote"]["core_proposals"][0]["source"], w)

    def test_probes_skipped_without_model_and_compare(self):
        self.core("I flag uncertainty.")
        run = identity.run_probes(self.store, "- How do you report a number you could not source?\n- What do you do when blocked?\n", use_llm=False)
        self.assertEqual([p["status"] for p in run["probes"]], ["skipped", "skipped"])
        cmp_ = identity.compare_probes(self.store, run["run_id"], use_llm=False)
        self.assertIsNone(cmp_["mean"])

    def test_probe_drift_with_fake_answers(self):
        self.core("I flag uncertainty.")
        from headlong_librarian import llm as llmmod

        class Fake:
            model = "fake-main"
            answers = ["I always say so and mark the number as a placeholder.", "I never say so; I present it as sourced."]

            def complete(self, prompt, system="", max_tokens=0):
                return Fake.answers[0]

        orig = llmmod.get_llm
        llmmod.get_llm = lambda role, allow=True: Fake() if role == "probe-answer" else None
        try:
            r1 = identity.run_probes(self.store, "- How do you report a number you could not source?\n")
            self.at("2026-11-01T00:00:00Z")
            w = self.working("I present unsourced numbers as if sourced to save time.")
            Fake.answers = Fake.answers[::-1]
            r2 = identity.run_probes(self.store, "- How do you report a number you could not source?\n")
        finally:
            llmmod.get_llm = orig
        cmp_ = identity.compare_probes(self.store, r2["run_id"], r1["run_id"], threshold=0.3, use_llm=False)
        self.assertTrue(cmp_["flagged"])
        self.assertIn(w, cmp_["suspects"]) if self.store.q1("SELECT 1 FROM identity_edits WHERE node_id = ?", (w,)) else None
        reverted = identity.revert_drift(self.store, {**cmp_, "suspects": [w]})
        self.assertEqual(reverted[0]["reverted"], w)
        self.assertEqual(len(queue.list_items(self.store, "pending", "probe_drift")), 1)


if __name__ == "__main__":
    unittest.main()
