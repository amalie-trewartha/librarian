"""Encode a Telegram conversation into a chat `from` name and back.

The name is the only routing metadata that survives the round trip through
the mind log (`from` on the inbound message step comes back as `to` on the
reply step), so it has to carry everything needed to deliver the reply:

    DM: telegram-5551234-5551234   (user id, chat id)

It must match the web API's CHAT_FROM_RE (^[A-Za-z0-9][A-Za-z0-9._-]*$).
The bridge is DM-only, where both ids are positive integers; group chat
ids are negative and their leading minus would break the `-` separator,
so encode() refuses them outright.
"""

from __future__ import annotations

from typing import NamedTuple

PREFIX = "telegram"


class Conversation(NamedTuple):
    user: int
    chat: int


def encode(user: int, chat: int) -> str:
    if user <= 0 or chat <= 0:
        raise ValueError(f"not a DM conversation: user={user} chat={chat}")
    return f"{PREFIX}-{user}-{chat}"


def decode(name: str) -> Conversation:
    parts = name.split("-")
    if len(parts) != 3 or parts[0] != PREFIX or not all(p.isdigit() for p in parts[1:]):
        raise ValueError(f"not a telegram conversation name: {name!r}")
    return Conversation(int(parts[1]), int(parts[2]))


def is_telegram_name(name: object) -> bool:
    if not isinstance(name, str):
        return False
    try:
        decode(name)
    except ValueError:
        return False
    return True
