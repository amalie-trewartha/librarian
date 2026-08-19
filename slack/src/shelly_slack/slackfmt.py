"""Text conversion between the agent's markdown and Slack.

Deliberately minimal — common markdown the agent emits, nothing close to
full CommonMark. Fenced and inline code are left untouched.
"""

from __future__ import annotations

import re

MAX_MESSAGE_CHARS = 3900  # Slack hard limit is ~4000; leave headroom

_CODE_SPLIT_RE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)
_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


def _convert_prose(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"<\2|\1>", text)  # [t](u) -> <u|t>
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)  # **bold** -> *bold*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)  # heading -> bold
    text = re.sub(r"^(\s*)[*+]\s+", r"\1- ", text, flags=re.MULTILINE)  # * item -> - item
    return text


def to_mrkdwn(text: str) -> str:
    """Convert agent markdown to Slack mrkdwn, skipping code spans."""
    parts = _CODE_SPLIT_RE.split(text)
    return "".join(p if p.startswith("`") else _convert_prose(p) for p in parts)


def strip_leaked_command(text: str) -> str:
    """Drop a leading 'chat reply <name>' the model echoed into its reply.

    The mind-log side also strips this; keeping a bridge-side guard means a
    leak never reaches Slack even if an agent-typed reply slips through.
    """
    return re.sub(r"^\s*chat reply [A-Za-z0-9._-]+\s*", "", text, count=1)


def clean_inbound(text: str, bot_user_id: str | None = None) -> str:
    """Normalize a Slack message body for the mind log."""
    if bot_user_id:
        text = text.replace(f"<@{bot_user_id}>", "")
    text = _MENTION_RE.sub(lambda m: m.group(0)[2:-1], text)  # other mentions -> bare id
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", text)  # <url|label>
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)  # <url>
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return text.strip()


def chunk(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split long text at paragraph (then line, then hard) boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip("\n"))
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks
