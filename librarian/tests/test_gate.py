import unittest

from helpers import StoreCase
from headlong_librarian import gate, model, queue


def cand(**kw) -> gate.Candidate:
    base = dict(type="skill", summary="colcon picks the system Eigen: set Eigen3_DIR explicitly", body="Fix: `cmake -DEigen3_DIR=/opt/eigen` then colcon build; verified 2026-09-14.", tags=["pkg:colcon", "area:build-system"], provenance={"author": "main", "source": "journal"})
    base.update(kw)
    return gate.Candidate(**base)


class GateRules(StoreCase):
    def test_accepts_and_enters_probationary(self):
        res = gate.apply(self.store, cand())
        self.assertTrue(res.accepted)
        self.assertEqual(res.action, "stored")
        n = self.node(res.id)
        self.assertEqual(n.status, "probationary")
        self.assertEqual(n.known_from, n.created)
        self.assertIsNone(n.last_confirmed)
        self.assertEqual(n.use_count, 0)
        self.assertIn("applies_to", {e["type"] for e in n.edges})

    def test_collects_every_violation(self):
        res = gate.apply(self.store, cand(summary="", body="lesson only", tags=["free"], provenance={"author": "main"}))
        self.assertFalse(res.accepted)
        self.assertEqual(res.action, "rejected")
        joined = " ".join(res.reasons)
        for needle in ("summary is empty", "namespaced tag", "specifics", "provenance"):
            self.assertIn(needle, joined)

    def test_summary_token_bound(self):
        res = gate.apply(self.store, cand(summary="word " * 80))
        self.assertIn("over 60 tokens", " ".join(res.reasons))

    def test_summary_must_not_repeat_first_sentence(self):
        res = gate.apply(self.store, cand(summary="Run make fix with VERSION 1.2 first.", body="Run make fix with VERSION 1.2 first. Then rebuild."))
        self.assertIn("repeats the body", " ".join(res.reasons))

    def test_identity_and_preference_exempt_from_repeat_rule(self):
        res = gate.apply(self.store, cand(type="preference", summary="Prefer small PRs.", body="Prefer small PRs.", tags=["team:x"], provenance={"author": "human"}))
        self.assertTrue(res.accepted, res.reasons)

    def test_closed_ctx_namespace(self):
        self.assertFalse(gate.apply(self.store, cand(tags=["ctx:made-up"])).accepted)
        self.assertTrue(gate.apply(self.store, cand(tags=["ctx:debugging"])).accepted)

    def test_new_area_tag_accepted_and_queued(self):
        res = gate.apply(self.store, cand(tags=["area:novel-thing"]))
        self.assertTrue(res.accepted)
        self.assertEqual(len(res.queued), 1)
        items = queue.list_items(self.store, "pending", "new_area_tag")
        self.assertEqual(items[0]["payload"]["tag"], "area:novel-thing")
        # The same tag again does not queue twice.
        res2 = gate.apply(self.store, cand(summary="another thing about eigen on arm64", tags=["area:novel-thing"]))
        self.assertEqual(res2.queued, [])

    def test_specifics_required_only_for_distilled_types(self):
        self.assertFalse(gate.apply(self.store, cand(body="Always be careful.")).accepted)
        self.assertTrue(gate.apply(self.store, cand(type="episode", summary="day 1", body="did things", tags=["project:p-1"], provenance={"author": "runtime"})).accepted)
        for body in ("Set VERSION=2.", "Edit /etc/hosts first.", "Use `colcon` here.", "$ make test"):
            self.assertTrue(gate.has_specifics(body), body)

    def test_provenance_rules(self):
        self.assertFalse(gate.apply(self.store, cand(provenance={"author": "main"})).accepted)
        self.assertFalse(gate.apply(self.store, cand(provenance={"author": "bob", "source": "x"})).accepted)
        self.assertFalse(gate.apply(self.store, cand(provenance={"author": "main", "episode": "01J00000000000000000000000"})).accepted)
        ep = self.add("episode", "ep", ["project:p-1"], "x", provenance={"author": "runtime"})
        res = gate.apply(self.store, cand(provenance={"author": "main", "episode": ep}))
        self.assertTrue(res.accepted)
        self.assertIn(("derived_from", ep), {(e["type"], e["to"]) for e in self.node(res.id).edges})
        self.assertTrue(gate.apply(self.store, cand(summary="human note about eigen", provenance={"author": "human"})).accepted)

    def test_active_status_only_for_human(self):
        r1 = gate.apply(self.store, cand(status="active"))
        self.assertEqual(self.node(r1.id).status, "probationary")
        self.assertTrue(any("ignored" in n for n in r1.notes))
        r2 = gate.apply(self.store, cand(summary="human skill about eigen dirs", status="active", provenance={"author": "human"}))
        self.assertEqual(self.node(r2.id).status, "active")

    def test_untrusted_tag(self):
        res = gate.apply(self.store, cand(untrusted=True))
        self.assertTrue(self.node(res.id).untrusted)
        res2 = gate.apply(self.store, cand(summary="web-sourced eigen fix", provenance={"author": "main", "source": "web", "source_kind": "web"}))
        self.assertIn("src:untrusted", self.node(res2.id).tags)

    def test_project_tag_added(self):
        res = gate.apply(self.store, cand(project="p-9"))
        n = self.node(res.id)
        self.assertIn("project:p-9", n.tags)
        self.assertEqual(n.project, "p-9")


class GateDuplicates(StoreCase):
    def test_body_duplicate_is_merged_without_write(self):
        first = gate.apply(self.store, cand())
        res = gate.apply(self.store, cand())
        self.assertEqual(res.action, "merged")
        self.assertEqual(res.merge_target, first.id)
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM nodes")[0], 1)

    def test_same_project_near_duplicate_supersedes(self):
        first = gate.apply(self.store, cand(project="p-1"))
        res = gate.apply(self.store, cand(body="Fix: `cmake -DEigen3_DIR=/usr/share/eigen3` and pin CMake 3.22; verified 2026-10-01 on Jammy.", project="p-1"))
        self.assertEqual(res.action, "superseded")
        self.assertEqual(self.node(first.id).status, "superseded")
        self.assertIsNotNone(self.node(first.id).known_to)
        self.assertIn(("supersedes", first.id), {(e["type"], e["to"]) for e in self.node(res.id).edges})

    def test_other_project_near_duplicate_links(self):
        first = gate.apply(self.store, cand(project="p-1"))
        res = gate.apply(self.store, cand(body="Fix: `cmake -DEigen3_DIR=/usr/share/eigen3` and pin CMake 3.22; verified 2026-10-01 on Jammy.", project="p-2"))
        self.assertEqual(res.action, "stored")
        self.assertEqual(res.linked, [first.id])
        self.assertEqual(self.node(first.id).status, "probationary")
        self.assertIn(("co_retrieved", first.id), {(e["type"], e["to"]) for e in self.node(res.id).edges})

    def test_explicit_supersedes(self):
        first = gate.apply(self.store, cand())
        res = gate.apply(self.store, cand(summary="totally different wording for the eigen cmake dir trick", supersedes=first.id))
        self.assertEqual(res.action, "superseded")
        self.assertEqual(model.supersession_chain(self.store, res.id), [first.id])

    def test_supersedes_type_mismatch_rejected(self):
        first = gate.apply(self.store, cand())
        res = gate.apply(self.store, cand(type="decision", summary="decided x", body="Chose A over B; 3 cases.", supersedes=first.id))
        self.assertFalse(res.accepted)


class GateSplitting(StoreCase):
    def test_long_body_splits_into_part_of_children(self):
        para = ("Step: run `make` with FLAG=1. " * 60).strip()
        body = "\n\n".join([para] * 6)  # ~ 9000 chars, well over 1500 tokens
        res = gate.apply(self.store, cand(body=body))
        self.assertTrue(res.accepted)
        self.assertGreaterEqual(len(res.children), 1)
        for cid in res.children:
            child = self.node(cid)
            self.assertIn(("part_of", res.id), {(e["type"], e["to"]) for e in child.edges})
            self.assertLessEqual(child.body_tokens, model.CHUNK_MAX_TOKENS + 5)
        self.assertLessEqual(self.node(res.id).body_tokens, model.CHUNK_MAX_TOKENS + 5)

    def test_split_body_boundaries(self):
        chunks = gate.split_body("a\n\n" + "b" * 10000 + "\n\nc", max_tokens=1000)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertEqual(chunks[0], "a")


if __name__ == "__main__":
    unittest.main()
