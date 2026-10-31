import os
import unittest

from helpers import StoreCase
from librarian import model, pack, rank, recall


class RecallTest(StoreCase):
    def seed(self):
        self.a = self.skill("colcon picks the system Eigen: set Eigen3_DIR", ["pkg:colcon", "pkg:eigen", "area:build-system"], project="p-1")
        self.b = self.skill("ros2 launch files need the install setup sourced", ["pkg:ros2", "area:build-system"], project="p-1")
        self.c = self.skill("pandas groupby on a categorical needs observed=True", ["pkg:pandas", "area:data-pipeline"], project="p-2")
        self.d = self.decision("chose parquet over sqlite for episode logs", ["pkg:parquet", "area:data-pipeline"], project="p-2")
        self.pref_id = self.pref("Prefer small reviewable PRs over large branches.")
        self.core_id = self.core("I flag uncertainty explicitly.")

    def test_tag_specificity_prefers_rare_tag(self):
        self.seed()
        scope = recall.status_scope(recall.Query())
        idf = recall.tag_idf(self.store, scope)
        self.assertGreater(idf["pkg:colcon"], idf["area:build-system"])
        scores = recall.tag_match(self.store, recall.Query(tags=["pkg:colcon", "area:build-system"]), scope, idf)
        self.assertGreater(scores[self.a], scores[self.b])

    def test_text_match_fts_and_python_agree(self):
        self.seed()
        scope = recall.status_scope(recall.Query())
        fts = recall.text_match(self.store, "eigen link errors in colcon", scope)
        os.environ["LIBRARIAN_FTS"] = "python"
        self.store._fts_mode = None
        py = recall.text_match(self.store, "eigen link errors in colcon", scope)
        os.environ.pop("LIBRARIAN_FTS")
        self.store._fts_mode = None
        self.assertEqual(max(fts, key=fts.get), self.a)
        self.assertEqual(max(py, key=py.get), self.a)

    def test_graph_hop_reaches_neighbors_only_along_hop_edges(self):
        self.seed()
        with self.store.write():
            model.add_edge(self.store, self.a, self.c, "co_retrieved", 0.6)
            model.add_edge(self.store, self.a, self.d, "supersedes", 1.0)  # not a hop edge
        scope = recall.status_scope(recall.Query())
        hops = recall.graph_hop(self.store, [self.a], scope)
        self.assertIn(self.c, hops)
        self.assertNotIn(self.d, hops)
        self.assertIn(self.b, hops)  # via applies_to tag:area:build-system

    def test_recall_union_and_always_set(self):
        self.seed()
        always, cands = recall.recall(self.store, recall.Query(task="colcon eigen", tags=["pkg:colcon"]))
        ids = [c.node.id for c in cands]
        self.assertEqual(ids[0], self.a)
        self.assertNotIn(self.pref_id, ids)
        self.assertEqual({n.id for n in always}, {self.pref_id, self.core_id})

    def test_status_scope(self):
        self.seed()
        with self.store.write():
            model.set_status(self.store, self.a, "archived")
        _, cands = recall.recall(self.store, recall.Query(tags=["pkg:colcon"]))
        self.assertNotIn(self.a, [c.node.id for c in cands])
        _, cands = recall.recall(self.store, recall.Query(tags=["pkg:colcon"], include_history=True))
        self.assertIn(self.a, [c.node.id for c in cands])

    def test_cap(self):
        words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu amber birch cedar dune".split()
        for i, w in enumerate(words):
            self.skill(f"{w} widget needs the {w}-{i} calibration step", ["pkg:widget", "area:tooling"], body=f"Run `widget --cal {w}-{i} --mode {w}`; verified on {w}-rig 2026-09-{i % 28 + 1:02d}.")
        _, cands = recall.recall(self.store, recall.Query(tags=["pkg:widget"]), cap=10)
        self.assertEqual(len(cands), 10)


class RankTest(StoreCase):
    def test_phase_prior_reorders(self):
        s = self.skill("skill s", ["pkg:x"])
        d = self.decision("decision d", ["pkg:x"])
        r = self.retro("retro r", ["pkg:x"])
        _, cands = recall.recall(self.store, recall.Query(tags=["pkg:x"]))
        for phase, top in (("debugging", s), ("reviewing", d), ("planning", r)):
            ranked, used, _ = rank.rank(self.store, cands, recall.Query(tags=["pkg:x"], phase=phase))
            self.assertEqual(ranked[0].node.id, top, phase)
            self.assertFalse(used)

    def test_recency_decays_with_half_life(self):
        s = self.skill("fresh skill", ["pkg:x"])
        n = self.node(s)
        self.assertAlmostEqual(rank.recency(n), 1.0, places=3)
        self.at("2026-10-08T00:00:00Z")
        self.assertAlmostEqual(rank.recency(self.node(s)), 0.5, places=2)
        p = self.pref("a preference")
        self.assertEqual(rank.recency(self.node(p)), 1.0)

    def test_reuse_and_exclude_and_tiebreak(self):
        a = self.skill("skill a", ["pkg:x"], body="Run `a` v1; verified 2026-01-01.")
        b = self.skill("skill b", ["pkg:x"], body="Run `b` v1; verified 2026-01-01. " * 10, confidence=0.5)
        self.episode("success", [a])
        self.episode("success", [a])
        _, cands = recall.recall(self.store, recall.Query(tags=["pkg:x"]))
        ranked, _, _ = rank.rank(self.store, cands, recall.Query(tags=["pkg:x"]))
        self.assertEqual(ranked[0].node.id, a)
        ranked, _, _ = rank.rank(self.store, cands, recall.Query(tags=["pkg:x"]), exclude_ids={a})
        self.assertEqual(ranked[0].node.id, b)
        # Tie: same score → higher confidence then shorter body.
        c = self.skill("skill c", ["pkg:y"], confidence=0.7)
        d = self.skill("skill d", ["pkg:y"], confidence=0.7, body="Run `d` v1; verified 2026-01-01.  " * 20)
        _, cands = recall.recall(self.store, recall.Query(tags=["pkg:y"]))
        ranked, _, _ = rank.rank(self.store, cands, recall.Query(tags=["pkg:y"]))
        self.assertEqual(ranked[0].node.id, c)

    def test_fact_has_phase_prior(self):
        f = self.add("fact", "fare elasticity -0.40 (TRL593 Table 6.4)", ["area:transit"], body="Source: TRL593 Table 6.4, p. 112.")
        e = self.add("episode", "fare elasticity -0.40 (TRL593 Table 6.4)", ["area:transit"], body="Source: TRL593 Table 6.4, p. 112.")
        for phase in ("building", "reviewing"):
            self.assertGreater(rank.prior(rank.PRIORS, "fact", phase), rank.prior(rank.PRIORS, "episode", phase))
            _, cands = recall.recall(self.store, recall.Query(tags=["area:transit"], phase=phase))
            ranked, _, _ = rank.rank(self.store, cands, recall.Query(tags=["area:transit"], phase=phase))
            self.assertEqual([r.node.id for r in ranked[:2]], [f, e], phase)

    def test_priors_override_from_meta(self):
        with self.store.write():
            self.store.meta_set("rank.priors", '{"skill": {"planning": 5.0}}')
        pri = rank.load_priors(self.store)
        self.assertEqual(pri["skill"]["planning"], 5.0)
        self.assertEqual(pri["decision"]["reviewing"], rank.PRIORS["decision"]["reviewing"])


class PackTest(StoreCase):
    def setUp(self):
        super().setUp()
        self.c1 = self.core("I flag uncertainty explicitly.")
        self.c2 = self.core("I never write an Answer line.")
        self.w1 = self.working("I write the test scaffold first.")
        self.p1 = self.pref("Prefer small PRs.", ["team:robotics-sw", "area:review"])
        self.p2 = self.pref("Use boring tools.", ["team:robotics-sw", "area:tooling"])
        self.s1 = self.skill("eigen dir trick", ["pkg:colcon", "area:build-system"], project="p-1")
        self.s2 = self.skill("ros2 sourcing trick", ["pkg:ros2", "area:build-system"], project="p-1")

    def req(self, **kw) -> pack.PackRequest:
        base = dict(task="colcon eigen link errors", tags=["pkg:colcon", "area:build-system", "area:review"], project="p-1", phase="debugging", budget=4000, log=False, use_llm=False)
        base.update(kw)
        return pack.PackRequest(**base)

    def test_layout_markers_in_order_and_ids_on_entries(self):
        text = pack.render_text(pack.build(self.store, self.req()))
        pos = [text.index(m) for m in (pack.MARK_CORE, pack.MARK_PREFS, pack.MARK_TASK, pack.MARK_COVERAGE, pack.MARK_REQUEST)]
        self.assertEqual(pos, sorted(pos))
        for line in text[text.index(pack.MARK_TASK):text.index(pack.MARK_COVERAGE)].splitlines():
            if line.startswith("- "):
                self.assertRegex(line, r"^- [0-9A-HJKMNP-TV-Z]{26} · ")
        self.assertIn("PROBATIONARY", text)
        self.assertIn(self.p1, text)
        self.assertNotIn(self.p2, text)  # no tag overlap with the request

    def test_team_wide_preference_reaches_every_pack(self):
        p3 = self.pref("Cite primary sources.", ["team:robotics-sw"])
        pk = pack.build(self.store, self.req())
        ids = [e.node.id for e in pk.preferences]
        self.assertIn(p3, ids)
        self.assertNotIn(self.p2, ids)  # scoped to area:tooling, still filtered
        self.assertEqual(ids[0], self.p1)  # tag-matched first

    def test_identity_section_is_byte_stable(self):
        a = pack.build(self.store, self.req())
        self.at("2026-10-05T00:00:00Z")
        b = pack.build(self.store, self.req(task="something else entirely"))
        self.assertEqual([e.text for e in a.identity_core], [e.text for e in b.identity_core])

    def test_budget_never_exceeded_and_truncation_marker(self):
        long_body = ("Step: run `make` with FLAG=1 and check the output carefully. " * 40).strip()
        big = self.skill("a very long skill about colcon", ["pkg:colcon"], body=long_body + "\n\n" + long_body, project="p-1")
        pk = pack.build(self.store, self.req(budget=900))
        self.assertLessEqual(pk.used_tokens, 900)
        text = pack.render_text(pk)
        if big in pk.ids("task"):
            self.assertIn(f"[TRUNCATED: fetch {big}", text)
            self.assertIn(big, pk.truncated_ids)

    def test_exclude_and_coverage(self):
        pk = pack.build(self.store, self.req(exclude_ids=[self.s1]))
        self.assertNotIn(self.s1, pk.ids("task"))
        self.assertIn("pkg:colcon", pk.coverage)
        pk2 = pack.build(self.store, self.req())
        self.assertTrue(any(c.startswith("+") for c in pk2.coverage))

    def test_logging_rows(self):
        pk = pack.build(self.store, self.req(log=True))
        row = self.store.q1("SELECT kind, budget, llm_cut FROM requests WHERE request_id = ?", (pk.request_id,))
        self.assertEqual((row[0], row[1], row[2]), ("pack", 4000, 0))
        logged = {r[0] for r in self.store.q("SELECT node_id FROM retrieval_log WHERE request_id = ?", (pk.request_id,))}
        self.assertEqual(logged, set(pk.ids()))

    def test_reserved_slots_put_relevant_curated_memory_first(self):
        tags = ["pkg:colcon", "area:build-system"]
        for i in range(8):
            self.episode("partial", [], summary=f"Colcon eigen link step {'abcdefgh'[i]} done.", tags=tags)
        f = self.add("fact", "Eigen 3.4 is the colcon eigen link version that works", ["pkg:colcon"], "Source: https://eigen.tuxfamily.org release notes, verified 2026-09-01.", project="p-1")
        pk = pack.build(self.store, self.req(budget=8000))
        types = [e.node.type for e in pk.task_memories]
        self.assertIn(self.s1, pk.ids("task")[:3])
        self.assertIn(f, pk.ids("task")[:3])
        self.assertNotEqual(types[0], "episode")


class RunBRecallTest(StoreCase):
    def test_body_keywords_are_searchable(self):
        # Live run 2026-10: the index held summary and tags only, so a skill whose
        # body named the dataset and site was invisible to a search for them.
        from librarian import model
        a = self.skill("When I need a table without an API key", ["area:data-fetch"], body="Fetch from https://www2.census.gov/programs-surveys/acs/ with curl; ACS 5-year; verified 2026-10-18.")
        self.assertIn("census.gov", model.keywords(self.node(a).body))
        self.assertIn("acs", model.keywords(self.node(a).body))
        _, cands = recall.recall(self.store, recall.Query(task="download ACS census tables"))
        self.assertIn(a, [c.node.id for c in cands])

    def test_migration_to_schema_3_rebuilds_the_index(self):
        from librarian import db
        a = self.skill("When I need a table without an API key", ["area:data-fetch"], body="Fetch from https://www2.census.gov/ ACS; verified 2026-10-18.")
        with self.store.write():
            self.store.ex("DROP TABLE nodes_fts")
            self.store.ex("CREATE VIRTUAL TABLE nodes_fts USING fts5(node_id UNINDEXED, summary, tags, tokenize='porter unicode61')")
            self.store.ex("INSERT INTO nodes_fts(node_id, summary, tags) SELECT id, summary, '' FROM nodes")
            self.store.ex("ALTER TABLE requests DROP COLUMN llm_note")
            self.store.meta_set("schema_version", "2")
        path = self.store.path
        self.store.close()
        self.store = db.Store.open(path)
        self.assertEqual(self.store.meta_get("schema_version"), str(db.SCHEMA_VERSION))
        self.assertIsNotNone(self.store.q1("SELECT name FROM sqlite_master WHERE name = 'dismissals'"))
        self.assertIn("llm_note", {r[1] for r in self.store.q("PRAGMA table_info(requests)")})
        _, cands = recall.recall(self.store, recall.Query(task="census"))
        self.assertIn(a, [c.node.id for c in cands])


if __name__ == "__main__":
    unittest.main()
