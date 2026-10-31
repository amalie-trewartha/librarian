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

    def test_fetch_logs_under_current_request_file(self):
        _, out, _ = self.propose()
        nid = out["id"]
        (self.ident / "run" / "librarian_request.json").write_text(json.dumps({"request_id": "01J9ZZZZZZZZZZZZZZZZZZZZZZ", "project": "p-1"}))
        self.run_cli("fetch", nid)
        row = self.store.q1("SELECT request_id, source FROM retrieval_log WHERE node_id = ? AND source = 'fetch'", (nid,))
        self.assertEqual(row[0], "01J9ZZZZZZZZZZZZZZZZZZZZZZ")
        self.assertIsNotNone(self.node(nid).last_used)

    def test_tags_stats_export_import(self):
        self.propose()
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
        self.assertTrue((pd / "shared-values.md").exists())
        rc, rows, _ = self.run_cli("shared")
        self.assertEqual((rc, rows), (0, []))

    def test_init_with_seeds(self):
        core = self.ident / "core.md"
        core.write_text("### a\nI flag uncertainty.\n")
        os.environ["LIBRARIAN_STORE"] = str(self.ident / "new.sqlite")
        rc, d, _ = self.run_cli("init", "--seed", str(core))
        self.assertEqual(rc, 0)
        self.assertEqual(d["core"][0]["action"], "stored")
        rc, d, _ = self.run_cli("identity", "list", "--core")
        self.assertEqual(len(d), 1)

    def test_help_and_usage(self):
        rc, _, _ = self.run_cli()
        self.assertEqual(rc, 2)


class RunBTest(CliCase):
    def test_capture_clear_by_an_existing_memory(self):
        # Live trial 2026-10-20: a capture cleared only on a new propose, so an existing skill
        # drove ~25 re-fetches and a near-duplicate skill before the signal went away.
        sk = self.skill("absolute cd before each command", ["pkg:cd", "area:tooling"], project="p-1")
        with self.store.write():
            self.store.ex("INSERT INTO pending_capture(id, signature, tags, project, created) VALUES ('C1', 'cd exit 1', '[\"pkg:cd\"]', 'p-1', '2026-10-01T00:00:00Z')")
        rc, rows, _ = self.run_cli("capture", "list", "--project", "p-1")
        self.assertEqual((rc, [r["id"] for r in rows]), (0, ["C1"]))
        rc, res, _ = self.run_cli("capture", "clear", "cd exit 1", "--covered-by", sk)
        self.assertEqual((rc, res["cleared_by"]), (0, sk))
        rc, rows, _ = self.run_cli("capture", "list", "--project", "p-1")
        self.assertEqual(rows, [])
        rc, _, _ = self.run_cli("capture", "clear", "C1", "--covered-by", sk)
        self.assertEqual(rc, cli.EXIT_NOTFOUND)


if __name__ == "__main__":
    unittest.main()
