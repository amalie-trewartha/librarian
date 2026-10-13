"""Path-safety guards for file-serving endpoints."""

import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException

BLOB_NAME_RE = re.compile(r"^[0-9a-f-]{36}-[0-9a-f]{6}\.(stdout|stderr)$")
LOG_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.log$")
MEMORY_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.md$")
# Underscores allowed: existing thinkers (inner_monologue, ...) use them even
# though `thinkers new` only scaffolds hyphenated names.
THINKER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# Same rule `identity new` enforces.
IDENTITY_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CHAT_FROM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ICON_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+\.png$")


def is_slack_permalink(value: str) -> bool:
    """Accept only Slack HTTPS archive links as chat source metadata."""
    if not value or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and (host == "slack.com" or host.endswith(".slack.com"))
        and parsed.path.startswith("/archives/")
    )


def contained_path(base: Path, *parts: str) -> Path:
    """Resolve base/parts and require the result to stay inside base."""
    resolved = (base / Path(*parts)).resolve()
    base_resolved = base.resolve()
    if resolved != base_resolved and not resolved.is_relative_to(base_resolved):
        raise HTTPException(status_code=404, detail="Not found")
    return resolved


def checked_name(name: str, pattern: re.Pattern[str]) -> str:
    if not pattern.match(name):
        raise HTTPException(status_code=404, detail="Not found")
    return name
