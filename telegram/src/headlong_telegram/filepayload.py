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

from .tgfmt import strip_leaked_command

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
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
    if isinstance(content, str):
        return strip_leaked_command(content)
    return content


def _as_photo(content: bytes | str | None) -> bool:
    if not isinstance(content, (bytes, bytearray)):
        return False
    raw = bytes(content)
    return raw.startswith(PNG_MAGIC) or raw.startswith(JPEG_MAGIC)


def file_payload(step: dict[str, Any]) -> dict[str, Any] | None:
    """Return upload kwargs, or None if this step is ordinary text.

    A file step is one with an explicit `filename` field. The `file`
    alias is not accepted: an ordinary message that happens to carry
    that key must stay a sendMessage. Content-sniffing without a name
    is not used either: a text reply that starts with `<svg` must
    stay a sendMessage.
    """
    raw_name = step.get("filename") or ""
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
        caption_out = strip_leaked_command(str(caption))[:CAPTION_MAX] or None

    return {
        "filename": filename,
        "content": content,
        "caption": caption_out,
        "as_photo": _as_photo(content),
    }
