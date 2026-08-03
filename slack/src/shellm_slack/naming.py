"""Encode a Slack conversation into a chat `from` name and back.

The name is the only routing metadata that survives the round trip through
the mind log (`from` on the inbound message step comes back as `to` on the
reply step), so it has to carry everything needed to deliver the reply:

    DM:              slack-U07AB12CD-D09XYZ123
    channel/thread:  slack-U07AB12CD-C09XYZ123-1722400000.123456

It must match the web API's CHAT_FROM_RE (^[A-Za-z0-9][A-Za-z0-9._-]*$).
Slack IDs are alphanumeric and thread timestamps are digits.digits, so `-`
is a safe separator.
"""

from __future__ import annotations

from typing import NamedTuple

PREFIX = "slack"


class Conversation(NamedTuple):
    user: str
    channel: str
    thread_ts: str | None  # None for DMs (top-level replies)


def encode(user: str, channel: str, thread_ts: str | None = None) -> str:
    parts = [PREFIX, user, channel]
    if thread_ts is not None:
        parts.append(thread_ts)
    return "-".join(parts)


def decode(name: str) -> Conversation:
    parts = name.split("-")
    if len(parts) not in (3, 4) or parts[0] != PREFIX or not all(parts):
        raise ValueError(f"not a slack conversation name: {name!r}")
    return Conversation(parts[1], parts[2], parts[3] if len(parts) == 4 else None)


def is_slack_name(name: object) -> bool:
    if not isinstance(name, str):
        return False
    try:
        decode(name)
    except ValueError:
        return False
    return True
