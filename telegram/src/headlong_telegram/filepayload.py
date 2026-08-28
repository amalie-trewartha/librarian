"""Detect file-bearing mind-log steps for Telegram outbound.

`chat send-file` stamps `filename` on the message step. Binary files
travel in `content_b64` (standard base64) because JSON cannot hold raw
bytes; text may sit in `content`. Outbound uploads the decoded bytes
via sendPhoto/sendDocument rather than stuffing them into sendMessage.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CAPTION_MAX = 1024  # Telegram media-caption limit


def _content(step: dict[str, Any]) -> bytes | str | None:
    b64 = step.get("content_b64")
    if isinstance(b64, str) and b64:
        try:
            return base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            return None
    content = step.get("content")
    if content is None or content == "":
        return None
    return content


def file_payload(step: dict[str, Any]) -> dict[str, Any] | None:
    """Return upload kwargs, or None if this step is ordinary text.

    A file step is one with a `filename` (or `file`) field. Content-sniffing
    without a name is not used: a text reply that happens to start with
    `<svg` must stay a sendMessage.
    """
    raw_name = step.get("filename") or step.get("file") or ""
    if not isinstance(raw_name, str) or not raw_name.strip():
        return None
    filename = Path(raw_name).name
    if not filename or filename in {".", ".."}:
        return None

    content = _content(step)
    if content is None:
        return None

    caption = step.get("caption")
    if caption is None or caption == "":
        caption_out = None
    else:
        caption_out = str(caption)[:CAPTION_MAX]

    raw = content if isinstance(content, (bytes, bytearray)) else None
    as_photo = bool(raw and bytes(raw).startswith(PNG_MAGIC))

    return {
        "filename": filename,
        "content": content,
        "caption": caption_out,
        "as_photo": as_photo,
    }
