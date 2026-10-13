"""Bridge to Librarian's ``llm`` CLI, with model tiers by role.

Every stage that calls a model is optional: when no model resolves, or the
call fails, the caller gets ``None`` and takes its deterministic path.

Roles and defaults (see design/librarian.md, "Model tiers by role"):

* ``rank``         fast model   - cut-2 relevance over summaries
* ``judge``        fast model   - probe drift, dispute pre-screen, deviation
* ``draft``        main model   - merged/generalized bodies, auto-drafted skills
* ``core-check``   escalation   - heuristic → fast → main → human queue
* ``probe-answer`` main model   - the probes measure the agent under its own model
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Optional, Protocol

ROLES = ("rank", "judge", "draft", "core-check", "probe-answer")
_FAST_ROLES = ("rank", "judge")
_MAIN_ROLES = ("draft", "probe-answer", "core-check")

PROMPT_VERSION = 1


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def main_model() -> Optional[str]:
    return _env("THINK_MODEL") or _env("SHELLM_MODEL") or _env("LLM_MODEL") or None


def fast_model() -> Optional[str]:
    return _env("SHELLM_FAST_MODEL") or None


def resolve_model(role: str) -> Optional[str]:
    """``LIBRARIAN_MODEL_<ROLE>`` → ``LIBRARIAN_MODEL`` → tier default → None."""
    if _env("LIBRARIAN_LLM") == "0":
        return None
    if role not in ROLES:
        raise ValueError(f"unknown librarian role {role}")
    specific = _env("LIBRARIAN_MODEL_" + role.upper().replace("-", "_"))
    if specific:
        return specific
    if role == "probe-answer":
        # Never the fast model: the probe measures the agent under its own model.
        return main_model()
    general = _env("LIBRARIAN_MODEL")
    if general:
        return general
    if role in _FAST_ROLES:
        return fast_model() or None
    return main_model() or fast_model() or None


def llm_bin() -> Optional[str]:
    explicit = _env("LIBRARIAN_LLM_BIN")
    if explicit:
        return explicit
    return shutil.which("llm")


class CallBudget:
    """Caps model calls per CLI invocation (``LIBRARIAN_LLM_MAX_CALLS``, default 4)."""

    def __init__(self, limit: Optional[int] = None):
        if limit is None:
            raw = _env("LIBRARIAN_LLM_MAX_CALLS")
            limit = int(raw) if raw.isdigit() else 4
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


class LLM:
    """One model, one role; ``complete`` never raises."""

    def __init__(self, model: str, role: str, budget: Optional[CallBudget] = None, timeout: int = 120):
        self.model = model
        self.role = role
        self.budget = budget or CallBudget()
        self.timeout = timeout
        self.calls = 0

    def complete(self, prompt: str, system: str = "", max_tokens: int = 800) -> Optional[str]:
        if not self.budget.take():
            print(f"librarian: llm call budget exhausted ({self.role})", file=sys.stderr)
            return None
        exe = llm_bin()
        if not exe:
            print("librarian: llm not found on PATH", file=sys.stderr)
            return None
        cmd = [exe, "-m", self.model, "-t", str(max_tokens), "--no-stream"]
        if system:
            cmd += ["-s", system]
        env = dict(os.environ)
        env["LLM_RUN_ID"] = f"librarian:{self.role}"
        env.pop("LLM_STOP_AFTER_CODE_BLOCK", None)
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"librarian: llm call failed ({self.role}): {exc}", file=sys.stderr)
            return None
        self.calls += 1
        if proc.returncode != 0 or not proc.stdout.strip():
            err = (proc.stderr or "").strip().splitlines()
            print(f"librarian: llm returned rc={proc.returncode} ({self.role}): {err[-1] if err else ''}", file=sys.stderr)
            return None
        return proc.stdout


_budget_singleton: Optional[CallBudget] = None


def shared_budget() -> CallBudget:
    global _budget_singleton
    if _budget_singleton is None:
        _budget_singleton = CallBudget()
    return _budget_singleton


def get_llm(role: str, allow: bool = True) -> Optional[LLM]:
    """An :class:`LLM` for the role, or None when the stage should be skipped."""
    if not allow:
        return None
    model = resolve_model(role)
    if not model:
        return None
    return LLM(model, role, shared_budget())


# ── lenient JSON ─────────────────────────────────────────────────────────────

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json_lenient(text: Optional[str]) -> Any:
    """Pull the first JSON object or array out of model prose; None on failure."""
    if not text:
        return None
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    for cand in candidates:
        cand = cand.strip()
        for opener, closer in (("{", "}"), ("[", "]")):
            start = cand.find(opener)
            if start < 0:
                continue
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(cand)):
                ch = cand[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cand[start : i + 1])
                        except ValueError:
                            break
    return None


# ── embeddings seam ──────────────────────────────────────────────────────────


class EmbedProvider(Protocol):
    name: str

    def embed(self, texts: list[str]) -> Optional[list[bytes]]: ...


class NullEmbedProvider:
    """No embeddings yet. The schema has the table; a real provider plugs in here."""

    name = "none"

    def embed(self, texts: list[str]) -> Optional[list[bytes]]:
        return None


def embed_provider() -> EmbedProvider:
    return NullEmbedProvider()
