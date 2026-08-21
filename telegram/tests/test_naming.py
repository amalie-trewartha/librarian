import re

import pytest

from headlong_telegram import naming

# Mirrors CHAT_FROM_RE in web/src/headlong_web/safety.py — the web API rejects
# from_name values that don't match, so every encoded key must pass.
CHAT_FROM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def test_dm_round_trip():
    name = naming.encode(5551234, 5551234)
    assert name == "telegram-5551234-5551234"
    assert CHAT_FROM_RE.match(name)
    assert naming.decode(name) == (5551234, 5551234)


def test_encode_rejects_group_chats():
    # Group chat ids are negative; the leading minus would break both the
    # separator and CHAT_FROM_RE.
    with pytest.raises(ValueError):
        naming.encode(5551234, -1001234567890)
    with pytest.raises(ValueError):
        naming.encode(0, 5551234)


def test_is_telegram_name():
    assert naming.is_telegram_name("telegram-1-2")
    assert not naming.is_telegram_name("nick")
    assert not naming.is_telegram_name("telegram-1")
    assert not naming.is_telegram_name("telegram-1-2-3")
    assert not naming.is_telegram_name("telegram--1--2")
    assert not naming.is_telegram_name("slack-U1-D2")
    assert not naming.is_telegram_name(None)
    assert not naming.is_telegram_name(42)


def test_decode_rejects_garbage():
    with pytest.raises(ValueError):
        naming.decode("slack-U1-C2")
    with pytest.raises(ValueError):
        naming.decode("telegram-abc-def")
