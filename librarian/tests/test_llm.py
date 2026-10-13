import os
import subprocess
import unittest

from librarian import llm


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        for k in ("LIBRARIAN_LLM", "LIBRARIAN_MODEL", "SHELLM_FAST_MODEL", "SHELLM_MODEL", "THINK_MODEL", "LLM_MODEL", "LIBRARIAN_MODEL_DRAFT", "LIBRARIAN_MODEL_RANK", "LIBRARIAN_MODEL_PROBE_ANSWER", "LIBRARIAN_LLM_MAX_CALLS"):
            os.environ.pop(k, None)
        llm._budget_singleton = None

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        llm._budget_singleton = None

    def test_nothing_set_means_skip(self):
        for role in llm.ROLES:
            self.assertIsNone(llm.resolve_model(role))
            self.assertIsNone(llm.get_llm(role))

    def test_tier_defaults(self):
        os.environ["SHELLM_FAST_MODEL"] = "haiku"
        os.environ["SHELLM_MODEL"] = "opus"
        self.assertEqual(llm.resolve_model("rank"), "haiku")
        self.assertEqual(llm.resolve_model("judge"), "haiku")
        self.assertEqual(llm.resolve_model("draft"), "opus")
        self.assertEqual(llm.resolve_model("core-check"), "opus")
        self.assertEqual(llm.resolve_model("probe-answer"), "opus")

    def test_precedence(self):
        os.environ["SHELLM_FAST_MODEL"] = "haiku"
        os.environ["SHELLM_MODEL"] = "opus"
        os.environ["LIBRARIAN_MODEL"] = "sonnet"
        self.assertEqual(llm.resolve_model("rank"), "sonnet")
        self.assertEqual(llm.resolve_model("draft"), "sonnet")
        os.environ["LIBRARIAN_MODEL_DRAFT"] = "special"
        self.assertEqual(llm.resolve_model("draft"), "special")
        # probe-answer ignores LIBRARIAN_MODEL and the fast model: it must be the agent's own model.
        self.assertEqual(llm.resolve_model("probe-answer"), "opus")
        os.environ["LIBRARIAN_MODEL_PROBE_ANSWER"] = "forced"
        self.assertEqual(llm.resolve_model("probe-answer"), "forced")

    def test_disable_switch(self):
        os.environ["SHELLM_FAST_MODEL"] = "haiku"
        os.environ["LIBRARIAN_LLM"] = "0"
        self.assertIsNone(llm.resolve_model("rank"))

    def test_unknown_role(self):
        with self.assertRaises(ValueError):
            llm.resolve_model("nope")


class CallTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._run = subprocess.run
        llm._budget_singleton = None

    def tearDown(self):
        subprocess.run = self._run
        os.environ.clear()
        os.environ.update(self._env)
        llm._budget_singleton = None

    def test_subprocess_contract_and_run_id(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            seen["env"] = kw["env"]
            seen["input"] = kw["input"]

            class P:
                returncode = 0
                stdout = "answer"
                stderr = ""

            return P()

        subprocess.run = fake_run
        os.environ["LIBRARIAN_LLM_BIN"] = "/fake/llm"
        m = llm.LLM("haiku", "rank")
        out = m.complete("the prompt", system="sys", max_tokens=123)
        self.assertEqual(out, "answer")
        self.assertEqual(seen["cmd"][:7], ["/fake/llm", "-m", "haiku", "-t", "123", "--no-stream", "-s"])
        self.assertEqual(seen["env"]["LLM_RUN_ID"], "librarian:rank")
        self.assertEqual(seen["input"], "the prompt")

    def test_failure_paths_return_none(self):
        def fail_run(cmd, **kw):
            class P:
                returncode = 1
                stdout = ""
                stderr = "boom"

            return P()

        subprocess.run = fail_run
        os.environ["LIBRARIAN_LLM_BIN"] = "/fake/llm"
        self.assertIsNone(llm.LLM("x", "judge").complete("p"))

        def raise_run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1)

        subprocess.run = raise_run
        self.assertIsNone(llm.LLM("x", "judge").complete("p"))

    def test_call_budget(self):
        os.environ["LIBRARIAN_LLM_MAX_CALLS"] = "2"
        os.environ["LIBRARIAN_LLM_BIN"] = "/fake/llm"

        def ok_run(cmd, **kw):
            class P:
                returncode = 0
                stdout = "y"
                stderr = ""

            return P()

        subprocess.run = ok_run
        b = llm.CallBudget()
        m = llm.LLM("x", "draft", b)
        self.assertEqual(m.complete("a"), "y")
        self.assertEqual(m.complete("b"), "y")
        self.assertIsNone(m.complete("c"))


class ParseTest(unittest.TestCase):
    def test_lenient_json(self):
        self.assertEqual(llm.parse_json_lenient('Sure: {"a": 1}'), {"a": 1})
        self.assertEqual(llm.parse_json_lenient('```json\n{"a": [1, 2]}\n```'), {"a": [1, 2]})
        self.assertEqual(llm.parse_json_lenient('text [1, "x"] more'), [1, "x"])
        self.assertEqual(llm.parse_json_lenient('{"s": "a } b", "n": 2}'), {"s": "a } b", "n": 2})
        self.assertIsNone(llm.parse_json_lenient("no json"))
        self.assertIsNone(llm.parse_json_lenient(None))
        self.assertIsNone(llm.parse_json_lenient("{broken"))

    def test_null_embed_provider(self):
        p = llm.embed_provider()
        self.assertEqual(p.name, "none")
        self.assertIsNone(p.embed(["x"]))


if __name__ == "__main__":
    unittest.main()
