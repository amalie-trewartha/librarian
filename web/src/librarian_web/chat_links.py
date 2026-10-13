"""Resolve source links shared by the chat and mind log views."""

from typing import Any


def resolve_source_url(
    message: dict[str, Any], known: dict[str, str]
) -> str | None:
    """Return a message's own source URL or the URL of the message it answers."""
    source_url = message.get("source_url")
    reply_to = message.get("reply_to")
    if (not isinstance(source_url, str) or not source_url) and isinstance(
        reply_to, str
    ):
        source_url = known.get(reply_to)
    if not isinstance(source_url, str) or not source_url:
        return None
    step_id = message.get("step_id")
    if isinstance(step_id, str) and step_id:
        known[step_id] = source_url
    return source_url
