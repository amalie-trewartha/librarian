"""Detect file-bearing mind-log steps for Telegram outbound.

`chat send-file` stamps `filename` on the message step. Binary files
travel in `content_b64` (standard base64) because JSON cannot hold raw
bytes; text may sit in `content`. Outbound uploads the decoded bytes
via sendPhoto/sendDocument rather than stuffing them into sendMessage.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Any

from .tgfmt import strip_leaked_command

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
CAPTION_MAX = 1024  # Telegram media-caption limit


def file_signature(filename: str, content: bytes | str) -> str:
    """Bounded RecentPosts key: basename plus a hash of the decoded bytes."""
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    return f"{filename}:{hashlib.sha256(raw).hexdigest()}"


class DecodeError(Exception):
    """File bytes could not be recovered from the step."""


def _content(step: dict[str, Any]) -> bytes | str | None:
    if "content_b64" in step:
        b64 = step.get("content_b64")
        if not isinstance(b64, str) or not b64:
            raise DecodeError("empty content_b64")
        try:
            raw = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise DecodeError(str(e)) from e
        if not raw:
            raise DecodeError("empty content_b64")
        return raw
    content = step.get("content")
    if content is None or content == "":
        return None
    if isinstance(content, str):
        return strip_leaked_command(content)
    # JSON can hold objects/arrays/numbers; file_signature and the
    # upload path only accept text or bytes. Anything else is a
    # decode error so outbound can notice-and-continue.
    raise DecodeError("non-string content")


def _as_photo(content: bytes | str | None) -> bool:
    if not isinstance(content, (bytes, bytearray)):
        return False
    raw = bytes(content)
    return raw.startswith(PNG_MAGIC) or raw.startswith(JPEG_MAGIC)


def file_payload(step: dict[str, Any]) -> dict[str, Any] | None:
    """Return upload kwargs, or None if this step is ordinary text.

    A file step is one with an explicit `filename` field. The `file`
    alias is not accepted: an ordinary message that happens to carry
    that key must stay a sendMessage. Content is leak-filtered so a
    stray `chat reply` in a caption cannot re-trigger the agent.

    If `content_b64` is present but not strict base64 (or decodes to
    empty), the returned dict has `content` None and `decode_error`
    True so outbound can fail loudly instead of falling through to
    sendMessage.
    """
    raw_name = step.get("filename")
    if not isinstance(raw_name, str) or not raw_name.strip():
        return None
    filename = Path(raw_name).name
    if not filename or filename in {".", ".."}:
        return None

    decode_error = False
    try:
        content = _content(step)
    except DecodeError:
        content = None
        decode_error = True
    if content is None and not decode_error:
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
        "decode_error": decode_error,
    }
