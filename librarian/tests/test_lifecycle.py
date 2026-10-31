import os
import unittest

from helpers import StoreCase
from librarian import lifecycle, model


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
        from librarian import pack

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


if __name__ == "__main__":
    unittest.main()
