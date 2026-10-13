import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout

from helpers import StoreCase
from librarian import cli


class CliCase(StoreCase):
    def run_cli(self, *argv, text=False):
        out, err = io.StringIO(), io.StringIO()
        args = (["--text"] if text else []) + list(argv)
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(args)
        body = out.getvalue()
        if text:
            return rc, body, err.getvalue()
        try:
            return rc, json.loads(body) if body.strip() else None, err.getvalue()
        except json.JSONDecodeError:
            return rc, body, err.getvalue()

    def propose(self, summary="colcon picks the system Eigen: set Eigen3_DIR", **extra):
        argv = ["propose", "--type", "skill", "--summary", summary, "--body", "Fix: `cmake -DEigen3_DIR=/opt/eigen`; verified 2026-09-14.", "--tags", "pkg:colcon,area:build-system", "--source", "journal", "--project", "p-1"]
        for k, v in extra.items():
            argv += [f"--{k.replace('_', '-')}", v]
        return self.run_cli(*argv)


class ContractTest(CliCase):
    def test_no_store_exit_2(self):
        os.environ["LIBRARIAN_STORE"] = str(self.ident / "nope.sqlite")
        rc, out, err = self.run_cli("search", "--tags", "pkg:x")
        self.assertEqual(rc, 2)
        self.assertEqual(out["code"], 2)

    def test_propose_search_fetch_show(self):
        rc, out, _ = self.propose()
        self.assertEqual(rc, 0)
        self.assertEqual(out["action"], "stored")
        nid = out["id"]
        rc, rows, _ = self.run_cli("search", "--tags", "pkg:colcon", "--text", "eigen")
        self.assertEqual(rc, 0)
        self.assertEqual(rows[0]["id"], nid)
        self.assertNotIn("body", rows[0])
        rc, text, _ = self.run_cli("search", "--tags", "pkg:colcon", text=True)
        self.assertIn("PROBATIONARY", text)
        rc, rows, _ = self.run_cli("fetch", nid, "--budget", "5")
        self.assertEqual(rc, 0)
        self.assertTrue(rows[0]["truncated"])
        rc, rows, _ = self.run_cli("fetch", nid)
        self.assertIn("Eigen3_DIR", rows[0]["body"])
        rc, _, err = self.run_cli("fetch", nid, "01J00000000000000000000000")
        self.assertEqual(rc, 4)
        rc, d, _ = self.run_cli("show", nid[:8], "--history")
        self.assertEqual(rc, 0)
        self.assertEqual(d["id"], nid)
        self.assertIn("supersedes_chain", d)
        self.assertEqual(self.run_cli("show", "ZZZZZZZZ")[0], 4)

    def test_rejected_exit_3_and_dry_run(self):
        rc, out, _ = self.run_cli("propose", "--type", "skill", "--summary", "x", "--body", "lesson", "--tags", "free")
        self.assertEqual(rc, 3)
        self.assertEqual(out["action"], "rejected")
        rc, out, _ = self.propose(dry_run=None) if False else self.run_cli("propose", "--type", "skill", "--summary", "s", "--body", "Run `x` 1.", "--tags", "pkg:x", "--source", "j", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertEqual(out["action"], "dry-run")
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM nodes")[0], 0)

    def test_pack_text_and_request_contract(self):
        self.propose()
        rc, text, _ = self.run_cli("pack", "--task", "eigen errors", "--tags", "pkg:colcon", "--project", "p-1", "--phase", "debugging", "--budget", "2000", text=True)
        self.assertEqual(rc, 0)
        self.assertTrue(text.startswith("[IDENTITY: CORE]"))
        self.assertIn("[REQUEST] ", text)
        rc, d, _ = self.run_cli("pack", "--task", "eigen errors", "--tags", "pkg:colcon", "--budget", "2000", "--no-log")
        self.assertIn("request_id", d)
        self.assertEqual(self.store.q1("SELECT COUNT(*) FROM requests")[0], 1)

    def test_episode_close_credits_and_amend(self):
        _, out, _ = self.propose()
        nid = out["id"]
        _, pk, _ = self.run_cli("pack", "--task", "eigen", "--tags", "pkg:colcon", "--project", "p-1", "--budget", "2000")
        rc, rep, _ = self.run_cli("episode", "close", "--summary", "fixed", "--body", "FINAL: fixed", "--tags", "project:p-1", "--outcome", "success", "--criterion", "test", "--request", pk["request_id"], "--project", "p-1")
        self.assertEqual(rc, 0)
        self.assertEqual([c["id"] for c in rep["cited"]], [nid])
        self.assertEqual(rep["cited"][0]["status_after"], "active")
        rc, rep2, _ = self.run_cli("outcome", "amend", rep["episode_id"], "--outcome", "failure", "--criterion", "human corrected")
        self.assertEqual(rc, 0)
        self.assertEqual(rep2["reversed"], 1)
        self.assertEqual(self.node(nid).status, "probationary")
        rc, _, _ = self.run_cli("endorse", nid, "--by", "amalie")
        self.assertEqual(self.node(nid).status, "active")

    def test_fetch_logs_under_current_request_file(self):
        _, out, _ = self.propose()
        nid = out["id"]
        (self.ident / "run" / "librarian_request.json").write_text(json.dumps({"request_id": "01J9ZZZZZZZZZZZZZZZZZZZZZZ", "project": "p-1"}))
        self.run_cli("fetch", nid)
        row = self.store.q1("SELECT request_id, source FROM retrieval_log WHERE node_id = ? AND source = 'fetch'", (nid,))
        self.assertEqual(row[0], "01J9ZZZZZZZZZZZZZZZZZZZZZZ")
        self.assertIsNotNone(self.node(nid).last_used)

    def test_identity_queue_flow_exit_5(self):
        c = self.core("No unsourced number ever stands in for a sourced one; a placeholder is labeled as one.")
        ep = self.episode("success", []).episode_id
        rc, out, _ = self.run_cli("identity", "edit", "--summary", "I scaffold tests first.", "--body", "I scaffold tests first.", "--occasion", "weekly", "--occasion-key", "w1", "--reason", "r", "--episodes", ep, "--no-llm")
        self.assertEqual(rc, 0)
        rc, out, _ = self.run_cli("identity", "edit", "--summary", "I read the spec twice.", "--body", "I read the spec twice.", "--occasion", "weekly", "--occasion-key", "w1", "--reason", "r", "--episodes", ep, "--no-llm")
        self.assertEqual(rc, 5)
        self.assertIn("refused_reason=rate_limit", out["notes"])
        rc, out, _ = self.run_cli("identity", "edit", "--summary", "I never label a placeholder number; unsourced numbers are fine when sourced ones are slow.", "--body", "I never label a placeholder number; unsourced numbers are fine when sourced ones are slow.", "--occasion", "weekly", "--occasion-key", "w2", "--reason", "r", "--episodes", ep, "--no-llm")
        self.assertEqual(rc, 5)
        rc, items, _ = self.run_cli("queue", "list")
        self.assertEqual(items[0]["kind"], "working_conflict")
        rc, res, _ = self.run_cli("queue", "reject", items[0]["id"], "--note", "no")
        self.assertEqual(rc, 0)
        self.assertEqual(self.run_cli("queue", "list")[1], [])
        rc, d, _ = self.run_cli("identity", "list", "--working")
        self.assertEqual(d["working_count"], 1)
        rc, d, _ = self.run_cli("identity", "propose", "--summary", "I lead with the answer.", "--body", "I lead with the answer.")
        self.assertIsNotNone(d["queue_id"])
        rc, res, _ = self.run_cli("queue", "approve", d["queue_id"])
        self.assertTrue(res["effects"]["core"]["accepted"])
        self.assertEqual(self.run_cli("queue", "approve", "QNOPE")[0], 4)

    def test_progress_suggestion_respond(self):
        self.propose()
        sig = "ModuleNotFoundError: No module named 'pint'"
        for _ in range(3):
            rc, res, _ = self.run_cli("progress", "--status", "failed again", "--tags", "project:p-1,pkg:colcon", "--project", "p-1", "--error", sig, "--tool-calls", "3", "--no-llm")
        self.assertIsNotNone(res["suggestion"])
        sid = res["suggestion"]["id"]
        rc, out, _ = self.run_cli("suggestion", "respond", sid, "accept")
        self.assertEqual(rc, 0)
        rc, rows, _ = self.run_cli("suggestion", "list", "--project", "p-1")
        self.assertEqual(rows[0]["response"], "accept")
        self.assertEqual(self.run_cli("suggestion", "respond", "SNOPE", "accept")[0], 4)

    def test_consolidate_decay_tags_stats_export_import(self):
        self.propose()
        rc, d, _ = self.run_cli("consolidate", "--no-llm", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("steps", d)
        rc, d, _ = self.run_cli("decay", "--dry-run")
        self.assertEqual(rc, 0)
        rc, d, _ = self.run_cli("tags", "--namespace", "ctx")
        self.assertTrue(all(t["namespace"] == "ctx" for t in d["tags"]))
        rc, d, _ = self.run_cli("stats")
        self.assertEqual(d["nodes"]["total"], 1)
        pd = self.ident / "proj"
        rc, d, _ = self.run_cli("export", "--project-dir", str(pd), "--project", "p-1")
        self.assertEqual(rc, 0)
        self.assertTrue((pd / "librarian.md").exists())
        prefs = self.ident / "prefs.md"
        prefs.write_text("- Prefer boring, well-understood tools.\n")
        rc, d, _ = self.run_cli("import", "--preferences", str(prefs), "--tags", "team:x")
        self.assertEqual(d["counts"]["stored"], 1)
        rc, d, _ = self.run_cli("dispute", self.store.q1("SELECT id FROM nodes WHERE type = 'skill'")[0], "--reason", "stale")
        self.assertEqual(d["status"], "disputed")
        rc, d, _ = self.run_cli("project", "close", "p-1")
        self.assertEqual(rc, 0)

    def test_init_with_seeds(self):
        core = self.ident / "core.md"
        core.write_text("### a\nI flag uncertainty.\n")
        os.environ["LIBRARIAN_STORE"] = str(self.ident / "new.sqlite")
        rc, d, _ = self.run_cli("init", "--seed", str(core))
        self.assertEqual(rc, 0)
        self.assertEqual(d["core"][0]["action"], "stored")
        rc, d, _ = self.run_cli("identity", "list", "--core")
        self.assertEqual(len(d["nodes"]), 1)

    def test_help_and_usage(self):
        rc, _, _ = self.run_cli()
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
