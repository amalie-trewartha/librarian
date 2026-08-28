"""Detect file-bearing mind-log steps for Telegram outbound.

`chat send-file` stamps `filename` on the message step and puts the file
bytes/text in `content`. Without this, outbound always used sendMessage
and a PNG/SVG landed as raw source in the chat.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FILE_TYPES = {"file", "image", "attachment"}


def file_payload(step: dict[str, Any]) -> dict[str, Any] | None:
    """Return upload kwargs, or None if this step is ordinary text."""
    filename = step.get("filename") or step.get("file") or ""
    content = step.get("content") or ""
    typed = str(step.get("type") or "") in FILE_TYPES

    if not filename:
        if isinstance(content, str) and content.lstrip().startswith("<svg"):
            filename = "figure.svg"
        elif isinstance(content, (bytes, bytearray)) and bytes(content[:8]) == PNG_MAGIC:
            filename = "figure.png"
        elif typed:
            filename = "attachment.bin"
        else:
            return None

    filename = Path(str(filename)).name or "attachment.bin"
    if isinstance(content, str):
        data = content.encode("utf-8")
    else:
        data = bytes(content)

    title = step.get("title") or filename
    comment = (step.get("caption") or step.get("comment") or "").strip()
    if len(comment) > 2000:
        comment = comment[:1990] + "…"
    return {
        "filename": filename,
        "content": data,
        "title": title,
        "initial_comment": comment or None,
    }
