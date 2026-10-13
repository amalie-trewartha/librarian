import unittest

from helpers import StoreCase
from headlong_librarian import lifecycle, model, queue


class CreditTest(StoreCase):
    def test_success_splits_credit_and_promotes(self):
        a = self.skill("a", ["pkg:x"])
        b = self.skill("b", ["pkg:x"])
        rep = self.episode("success", [a, b])
        self.assertEqual(len(rep.cited), 2)
        for nid in (a, b):
            n = self.node(nid)
            self.assertEqual(n.status, "active")
            self.assertAlmostEqual(n.confidence, 0.55, places=3)
            self.assertEqual(n.use_count, 1)
            self.assertEqual(n.success_count, 1)
            self.assertIsNotNone(n.last_confirmed)
        single = self.skill("c", ["pkg:y"])
        self.episode("success", [single])
        self.assertAlmostEqual(self.node(single).confidence, 0.60, places=3)

    def test_failure_lowers_and_flags_after_two(self):
        a = self.skill("a", ["pkg:x"])
        self.episode("failure", [a])
        n = self.node(a)
        self.assertEqual(n.status, "probationary")
        self.assertAlmostEqual(n.confidence, 0.40, places=3)
        self.assertIn("failed_in", {e["type"] for e in n.edges})
        self.assertIsNone(n.review_flag)
        rep = self.episode("failure", [a])
        self.assertEqual(rep.flagged, [a])
        self.assertEqual(self.node(a).review_flag, "repeated_failure")

    def test_partial_and_unknown_move_nothing_but_counters(self):
        a = self.skill("a", ["pkg:x"])
        self.episode("partial", [a])
        n = self.node(a)
        self.assertEqual((n.status, n.confidence, n.use_count), ("probationary", 0.5, 1))
        self.episode("unknown", [a])
        self.assertEqual(self.node(a).unknown_citations, 1)
        self.assertEqual(self.node(a).confidence, 0.5)

    def test_cited_from_request_log_task_rows_and_fetch_only(self):
        from headlong_librarian import pack

        a = self.skill("eigen trick", ["pkg:colcon"], project="p-1")
        c = self.core("core line")
        pk = pack.build(self.store, pack.PackRequest(task="eigen", tags=["pkg:colcon"], project="p-1", phase="debugging", budget=3000, log=True, use_llm=False))
        with self.store.write():
            self.store.ex("INSERT INTO retrieval_log(request_id, node_id, source, ts) VALUES (?,?,?,?)", (pk.request_id, c, "search", "2026-10-01T00:00:00Z"))
        rep = lifecycle.close_episode(self.store, outcome="success", summary="s", body="b", tags=["project:p-1"], project="p-1", request_ids=[pk.request_id])
        cited = {c["id"] for c in rep.cited}
        self.assertIn(a, cited)
        self.assertNotIn(c, cited)  # identity rows and search rows are never auto-credited

    def test_helpful_is_recorded_not_credited(self):
        a = self.skill("a", ["pkg:x"])
        self.episode("unknown", [a], helpful=[a])
        self.assertEqual(self.store.q1("SELECT helpful FROM citations WHERE node_id = ?", (a,))[0], 1)
        self.assertEqual(self.node(a).confidence, 0.5)

    def test_per_id_override(self):
        a = self.skill("a", ["pkg:x"])
        b = self.skill("b", ["pkg:x"])
        rep = self.episode("partial", [a, b], overrides={a: "success"})
        self.assertEqual(self.node(a).status, "active")
        self.assertEqual(self.node(b).status, "probationary")
        self.assertEqual({c["id"]: c["outcome"] for c in rep.cited}, {a: "success", b: "partial"})

    def test_late_amend_reverses_exactly(self):
        a = self.skill("a", ["pkg:x"])
        rep = self.episode("success", [a])
        self.assertEqual(self.node(a).status, "active")
        rep2 = lifecycle.amend_outcome(self.store, rep.episode_id, "failure", "human corrected deliverable")
        self.assertEqual(rep2.reversed, 1)
        n = self.node(a)
        self.assertEqual(n.status, "probationary")
        self.assertIsNone(n.last_confirmed)
        self.assertAlmostEqual(n.confidence, 0.40, places=3)
        self.assertEqual(n.success_count, 0)
        self.assertEqual(n.failure_count, 1)
        self.assertEqual(n.use_count, 1)
        ep = self.node(rep.episode_id)
        self.assertEqual(ep.outcome["value"], "failure")
        self.assertEqual(ep.outcome["history"][0]["value"], "success")

    def test_amend_keeps_active_when_another_success_exists(self):
        a = self.skill("a", ["pkg:x"])
        r1 = self.episode("success", [a])
        self.episode("success", [a])
        lifecycle.amend_outcome(self.store, r1.episode_id, "failure")
        n = self.node(a)
        self.assertEqual(n.status, "active")
        self.assertIsNotNone(n.last_confirmed)

    def test_endorse(self):
        a = self.skill("a", ["pkg:x"])
        lifecycle.endorse(self.store, a, "amalie")
        n = self.node(a)
        self.assertEqual(n.status, "active")
        self.assertAlmostEqual(n.confidence, 0.6, places=3)
        self.assertEqual(n.provenance["endorsements"][0]["by"], "amalie")


class DecayTest(StoreCase):
    def test_probation_exits(self):
        old = self.skill("old", ["pkg:x"])
        unk = self.skill("unk", ["pkg:y"])
        for _ in range(10):
            self.episode("unknown", [unk])
        self.at("2026-12-31T00:00:00Z")
        rep = lifecycle.decay(self.store)
        ids = {e["id"] for e in rep["probation_exits"]}
        self.assertEqual(ids, {old, unk})
        self.assertEqual(self.node(old).status, "archived")
        self.assertEqual(self.node(old).archived_reason, "unproven")

    def test_dry_run_changes_nothing(self):
        old = self.skill("old", ["pkg:x"])
        self.at("2027-06-01T00:00:00Z")
        rep = lifecycle.decay(self.store, dry_run=True)
        self.assertTrue(rep["archived"])
        self.assertEqual(self.node(old).status, "probationary")

    def test_skill_archival_two_half_lives_unused(self):
        a = self.skill("a", ["pkg:x"])
        self.activate(a)
        self.at("2028-10-02T00:00:00Z")
        lifecycle.decay(self.store)
        self.assertEqual(self.node(a).status, "archived")
        b = self.skill("b", ["pkg:x"])
        self.episode("success", [b])  # used, confirmed now
        lifecycle.decay(self.store)
        self.assertEqual(self.node(b).status, "active")

    def test_decision_archival_rules(self):
        d = self.decision("d", ["pkg:x"], valid_to="2026-10-05T00:00:00Z")
        self.activate(d)
        self.at("2026-10-06T00:00:00Z")
        lifecycle.decay(self.store)
        self.assertEqual(self.node(d).archived_reason, "valid_to passed")
        e = self.decision("e", ["pkg:x"], project="p-1")
        self.activate(e)
        lifecycle.decay(self.store)
        self.assertEqual(self.node(e).status, "active")
        with self.store.write():
            self.store.ex("INSERT INTO projects(project, opened, closed) VALUES ('p-1', 'x', 'y')")
        lifecycle.decay(self.store)
        self.assertEqual(self.node(e).status, "archived")

    def test_episode_archival_once_derived_active(self):
        rep = self.episode("success", [])
        ep = rep.episode_id
        s = self.skill("derived", ["pkg:x"], provenance={"author": "main", "episode": ep})
        self.at("2026-11-15T00:00:00Z")
        lifecycle.decay(self.store)
        self.assertNotEqual(self.node(ep).status, "archived")  # derived node still probationary
        self.activate(s)
        lifecycle.decay(self.store)
        self.assertEqual(self.node(ep).status, "archived")


class ConsolidateTest(StoreCase):
    def test_merge_without_model_keeps_best_and_supersedes(self):
        a = self.skill("colcon eigen dir trick for humble", ["pkg:colcon", "pkg:eigen"], confidence=0.6)
        b = self.skill("colcon eigen dir trick for humble builds", ["pkg:colcon", "pkg:eigen"], body="Fix: set `Eigen3_DIR=/opt/x`; verified 2026-09-02.", confidence=0.8, project="p-2")
        for n in (a, b):
            self.activate(n)
        rep = lifecycle.consolidate(self.store, only=["merge"], use_llm=False)
        merged = rep["steps"]["merge"]["merged"]
        self.assertEqual(len(merged), 1)
        new = self.node(merged[0]["id"])
        self.assertEqual(new.status, "active")
        self.assertAlmostEqual(new.confidence, 0.8)
        self.assertEqual(new.summary, self.node(b).summary)
        self.assertEqual(self.node(a).status, "superseded")
        self.assertEqual(self.node(b).status, "superseded")
        self.assertEqual(rep["steps"]["merge"]["duplicate_pairs"], 1)
        # Idempotent: a second pass finds nothing.
        rep2 = lifecycle.consolidate(self.store, only=["merge"], use_llm=False)
        self.assertEqual(rep2["steps"]["merge"]["merged"], [])

    def test_merge_with_fake_model_writes_from_sources(self):
        ep = self.episode("success", []).episode_id
        a = self.skill("widget calibration via cal-tool", ["pkg:widget"], provenance={"author": "main", "episode": ep})
        b = self.skill("widget calibration via the cal-tool flag", ["pkg:widget"], body="Run `cal-tool --fast`; verified 2026-09-03.", provenance={"author": "main", "episode": ep})
        for n in (a, b):
            self.activate(n)
        from headlong_librarian import llm as llmmod

        class Fake:
            model = "fake-main"

            def complete(self, prompt, system="", max_tokens=0):
                assert "[episode" in prompt
                return '{"summary": "widget calibration: use cal-tool --fast", "body": "Run `cal-tool --fast`; verified 2026-09-03 on rev 2."}'

        orig = llmmod.get_llm
        llmmod.get_llm = lambda role, allow=True: Fake() if role == "draft" else None
        try:
            rep = lifecycle.consolidate(self.store, only=["merge"], use_llm=True)
        finally:
            llmmod.get_llm = orig
        new = self.node(rep["steps"]["merge"]["merged"][0]["id"])
        self.assertTrue(rep["steps"]["merge"]["merged"][0]["drafted"])
        self.assertEqual(new.summary, "widget calibration: use cal-tool --fast")
        self.assertEqual(new.provenance["model"], "fake-main")
        self.assertIn(("derived_from", ep), {(e["type"], e["to"]) for e in new.edges})

    def test_generalize_skipped_without_model_and_drafted_with(self):
        ids = [self.skill(f"gadget-{i} needs the PORT env set", ["pkg:gadget", "area:tooling"], body=f"Run `gadget-{i} --port 80{i}`; verified 2026-09-0{i + 1}.") for i in range(3)]
        for n in ids:
            self.activate(n)
        rep = lifecycle.consolidate(self.store, only=["generalize"], use_llm=False)
        self.assertEqual(rep["steps"]["generalize"]["skipped"], "skipped_no_model")
        self.assertEqual(len(rep["steps"]["generalize"]["groups"]), 1)
        from headlong_librarian import llm as llmmod

        class Fake:
            model = "fake-main"

            def complete(self, prompt, system="", max_tokens=0):
                return '{"summary": "gadgets need PORT set before start", "body": "Set `PORT` for any gadget-N; examples: gadget-0 --port 800."}'

        orig = llmmod.get_llm
        llmmod.get_llm = lambda role, allow=True: Fake() if role == "draft" else None
        try:
            rep = lifecycle.consolidate(self.store, only=["generalize"], use_llm=True)
        finally:
            llmmod.get_llm = orig
        gen = self.node(rep["steps"]["generalize"]["drafted"][0])
        self.assertIn("scope:general", gen.tags)
        self.assertEqual(gen.status, "probationary")
        for n in ids:
            self.assertIn(("part_of", gen.id), {(e["type"], e["to"]) for e in self.node(n).edges})

    def test_disputes_dominance_and_queue(self):
        a = self.skill("a", ["pkg:x"], confidence=0.9)
        self.at("2026-10-02T00:00:00Z")
        b = self.skill("b", ["pkg:x"], confidence=0.5)
        for n in (a, b):
            self.activate(n)
        with self.store.write():
            model.add_edge(self.store, a, b, "contradicts")
        rep = lifecycle.consolidate(self.store, only=["disputes"])
        # Neither dominates: a is more confident, b newer → queued and both disputed.
        self.assertEqual(len(rep["steps"]["disputes"]["queued"]), 1)
        self.assertEqual(self.node(a).status, "disputed")
        self.assertEqual(len(queue.list_items(self.store, "pending", "dispute")), 1)
        c = self.skill("c", ["pkg:z"], confidence=0.9)
        self.at("2026-10-03T00:00:00Z")
        d = self.skill("d", ["pkg:z"], confidence=0.95)
        for n in (c, d):
            self.activate(n)
        with self.store.write():
            model.add_edge(self.store, c, d, "contradicts")
        rep = lifecycle.consolidate(self.store, only=["disputes"])
        self.assertEqual(rep["steps"]["disputes"]["resolved"][0]["kept"], d)
        self.assertEqual(self.node(c).status, "superseded")

    def test_promote_retrospective_to_preference(self):
        r = self.retro("start integration tests by day 2", ["area:process", "project:p-0"], project="p-0")
        self.activate(r)
        self.episode("success", [r], project="p-1")
        self.episode("success", [r], project="p-2")
        rep = lifecycle.consolidate(self.store, only=["promote"])
        promoted = rep["steps"]["promote"]["preferences"]
        self.assertEqual(len(promoted), 1)
        new = self.node(promoted[0]["id"])
        self.assertEqual(new.type, "preference")
        self.assertNotIn("project:p-0", new.tags)
        self.assertEqual(self.node(r).status, "archived")

    def test_promote_stable_preference_to_core_proposal_once(self):
        p = self.pref("Safety-relevant uncertainty is reported, not smoothed over.")
        self.at("2027-01-15T00:00:00Z")
        rep = lifecycle.consolidate(self.store, only=["promote"])
        self.assertEqual(rep["steps"]["promote"]["core_proposals"][0]["source"], p)
        rep2 = lifecycle.consolidate(self.store, only=["promote"])
        self.assertEqual(rep2["steps"]["promote"]["core_proposals"], [])
        items = queue.list_items(self.store, "pending", "core_proposal")
        self.assertEqual(len(items), 1)

    def test_co_retrieved_recompute_and_prune(self):
        a = self.skill("a", ["pkg:x"])
        b = self.skill("b", ["pkg:x"])
        c = self.skill("c", ["pkg:x"])
        for _ in range(3):
            self.episode("partial", [a, b])
        self.episode("partial", [a, c])
        rep = lifecycle.consolidate(self.store, only=["co_retrieved"])
        w_ab = self.store.q1("SELECT weight FROM edges WHERE from_id = ? AND to_id = ? AND type = 'co_retrieved'", (a, b))[0]
        self.assertAlmostEqual(w_ab, 1 - 0.75**3, places=3)
        w_ac = self.store.q1("SELECT weight FROM edges WHERE from_id = ? AND to_id = ? AND type = 'co_retrieved'", (a, c))[0]
        self.assertAlmostEqual(w_ac, 0.25, places=3)
        self.assertGreaterEqual(rep["steps"]["co_retrieved"]["upserted"], 2)

    def test_reembed_skipped_without_provider(self):
        self.skill("a", ["pkg:x"])
        rep = lifecycle.consolidate(self.store, only=["reembed"])
        self.assertEqual(rep["steps"]["reembed"]["skipped"], "skipped_no_provider")

    def test_consolidation_logged_and_flags_listed(self):
        a = self.skill("a", ["pkg:x"])
        self.episode("failure", [a])
        self.episode("failure", [a])
        rep = lifecycle.consolidate(self.store)
        self.assertEqual(rep["needs_review"], [a])
        self.assertGreaterEqual(self.store.q1("SELECT COUNT(*) FROM consolidation_log")[0], 6)


if __name__ == "__main__":
    unittest.main()
