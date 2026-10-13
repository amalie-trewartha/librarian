"""Framework env vars: HEADLONG_* is canonical, SHELLM_* accepted as fallback.

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
    """Read env var `name` (a HEADLONG_* name); fall back to its SHELLM_* twin.

    An empty-but-set HEADLONG_* value wins over the SHELLM_* fallback, matching
    plain os.environ.get semantics for each name in turn.
    """
    if name in os.environ:
        return os.environ[name]
    legacy = name.replace("HEADLONG_", "SHELLM_", 1)
    if legacy != name and legacy in os.environ:
        return os.environ[legacy]
    return default
