"""Framework env vars: LIBRARIAN_* is canonical; HEADLONG_* (the name until 2026-10) and SHELLM_* accepted as fallbacks.

Framework-level knobs read through here because the deployed box's parked
shellm-named machinery (/opt/shellm, the root .env, operator drop-ins) still
exports SHELLM_* names; the fallback retires when those paths are renamed.
Tool-level vars (SHELLM_MODEL and friends, read by bin/shellm and bin/llm)
are NOT routed through this helper — shellm is the RLM tool's own name and
its vars keep the SHELLM_ prefix on purpose.
"""

import os

__all__ = ["getenv"]


def getenv(name: str, default: str | None = None) -> str | None:
    """Read env var `name` (a LIBRARIAN_* name); fall back to its SHELLM_* twin.

    An empty-but-set LIBRARIAN_* value wins over the SHELLM_* fallback, matching
    plain os.environ.get semantics for each name in turn.
    """
    if name in os.environ:
        return os.environ[name]
    # Headlong era (until 2026-10): HEADLONG_X, with two renamed exceptions.
    special = {"LIBRARIAN_MEMORY": "HEADLONG_LIBRARIAN", "LIBRARIAN_SRC": "HEADLONG_LIBRARIAN_SRC"}
    headlong = special.get(name) or name.replace("LIBRARIAN_", "HEADLONG_", 1)
    if headlong != name and headlong in os.environ:
        return os.environ[headlong]
    legacy = name.replace("LIBRARIAN_", "SHELLM_", 1)
    if legacy != name and legacy in os.environ:
        return os.environ[legacy]
    return default
