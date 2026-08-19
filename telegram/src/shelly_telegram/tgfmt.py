"""Text conversion between the agent's markdown and Telegram.

Outbound targets Telegram's HTML parse mode (MarkdownV2's escaping rules
are a minefield). Deliberately minimal — common markdown the agent emits,
nothing close to full CommonMark.
"""

from __future__ import annotations

import html
import re

MAX_MESSAGE_CHARS = 3900  # Telegram hard limit is 4096; leave headroom
MAX_INBOUND_CHARS = 4000  # cap what one message can inject into the mind log

_CODE_SPLIT_RE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)


def _convert_prose(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)[*+]\s+", r"\1- ", text, flags=re.MULTILINE)
    return text


def _convert_code(span: str) -> str:
    if span.startswith("```"):
        body = span[3:-3]
        body = body.split("\n", 1)[1] if "\n" in body else body  # drop language tag
        return f"<pre>{html.escape(body, quote=False)}</pre>"
    return f"<code>{html.escape(span[1:-1], quote=False)}</code>"


def to_html(text: str) -> str:
    """Convert agent markdown to Telegram HTML, code spans preserved."""
    parts = _CODE_SPLIT_RE.split(text)
    return "".join(
        _convert_code(p) if p.startswith("`") else _convert_prose(p) for p in parts
    )


def strip_leaked_command(text: str) -> str:
    """Drop a leading 'chat reply <name>' the model echoed into its reply.

    Same bridge-side guard as the Slack bridge: a leak never reaches the
    phone even if an agent-typed reply slips through.
    """
    return re.sub(r"^\s*chat reply [A-Za-z0-9._-]+\s*", "", text, count=1)


def clean_inbound(text: str) -> str:
    """Normalize a Telegram message body for the mind log."""
    text = text.strip()
    if len(text) > MAX_INBOUND_CHARS:
        text = text[:MAX_INBOUND_CHARS] + " …(truncated by bridge)"
    return text


def sender_label(user: dict) -> str:
    """One-line display label for a Telegram user object.

    The parts are attacker-controlled strings headed for the admin's
    approval prompt and the mind-log header — collapse whitespace and cap
    the length so a hostile display name can't spread across lines.
    """
    name = " ".join(
        p for p in (user.get("first_name", ""), user.get("last_name", "")) if p
    )
    if user.get("username"):
        name = f"{name} (@{user['username']})" if name else f"@{user['username']}"
    name = re.sub(r"\s+", " ", name).strip()
    return name[:64] or str(user.get("id", "?"))


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
