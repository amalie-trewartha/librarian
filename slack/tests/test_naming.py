import re

import pytest

from headlong_slack import naming

# Mirrors CHAT_FROM_RE in web/src/headlong_web/safety.py — the web API rejects
# from_name values that don't match, so every encoded key must pass.
CHAT_FROM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def test_dm_round_trip():
    name = naming.encode("U07AB12CD", "D09XYZ123")
    assert name == "slack-U07AB12CD-D09XYZ123"
    assert CHAT_FROM_RE.match(name)
    assert naming.decode(name) == ("U07AB12CD", "D09XYZ123", None)


def test_thread_round_trip():
    name = naming.encode("U07AB12CD", "C09XYZ123", "1722400000.123456")
    assert name == "slack-U07AB12CD-C09XYZ123-1722400000.123456"
    assert CHAT_FROM_RE.match(name)
    assert naming.decode(name) == ("U07AB12CD", "C09XYZ123", "1722400000.123456")


def test_is_slack_name():
    assert naming.is_slack_name("slack-U1-C2-3.4")
    assert naming.is_slack_name("slack-U1-D2")
    assert not naming.is_slack_name("nick")
    assert not naming.is_slack_name("slack-U1")
    assert not naming.is_slack_name("slack--C2-3.4")
    assert not naming.is_slack_name(None)
    assert not naming.is_slack_name(42)


def test_decode_rejects_garbage():
    with pytest.raises(ValueError):
        naming.decode("telegram-U1-C2")
    with pytest.raises(ValueError):
        naming.decode("slack-U1-C2-3.4-extra")
