"""Framework env vars: SHELLY_* is canonical, SHELLM_* accepted as fallback.

The framework is being renamed shellm -> Shelly. Framework-level knobs read
through here so deployed boxes that still export the old SHELLM_* names keep
working. Tool-level vars (SHELLM_MODEL and friends, read by bin/shellm and
bin/llm) are NOT routed through this helper — they keep their SHELLM_ names.
"""

import os

__all__ = ["getenv"]


def getenv(name: str, default: str | None = None) -> str | None:
    """Read env var `name` (a SHELLY_* name); fall back to its SHELLM_* twin.

    An empty-but-set SHELLY_* value wins over the SHELLM_* fallback, matching
    plain os.environ.get semantics for each name in turn.
    """
    if name in os.environ:
        return os.environ[name]
    legacy = name.replace("SHELLY_", "SHELLM_", 1)
    if legacy != name and legacy in os.environ:
        return os.environ[legacy]
    return default
