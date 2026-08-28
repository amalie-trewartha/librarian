"""Inbound reaction filter: only our messages (and DMs) land in the mind log."""

from headlong_slack.inbound import reaction_text, reaction_to_inbound

BOT = "U_BOT"


def _event(
    *,
    user="U_NICK",
    reaction="thumbsup",
    channel="C_CHAN",
    ts="111.222",
    item_user="U_BOT",
    item_type="message",
    bot_id=None,
):
    event = {
        "type": "reaction_added",
        "user": user,
        "reaction": reaction,
        "item_user": item_user,
        "item": {"type": item_type, "channel": channel, "ts": ts},
        "event_ts": "999.000",
    }
    if bot_id is not None:
        event["bot_id"] = bot_id
    return event


def test_channel_reaction_on_our_message():
    got = reaction_to_inbound(_event(), bot_user_id=BOT)
    assert got == ("U_NICK", "C_CHAN", "111.222", "thumbsup", True)


def test_channel_reaction_on_someone_else_dropped():
    assert (
        reaction_to_inbound(_event(item_user="U_OTHER"), bot_user_id=BOT) is None
    )


def test_dm_reaction_on_anyone():
    got = reaction_to_inbound(
        _event(channel="D_DM", item_user="U_OTHER"), bot_user_id=BOT
    )
    assert got == ("U_NICK", "D_DM", "111.222", "thumbsup", False)


def test_bot_reacting_dropped():
    assert reaction_to_inbound(_event(user=BOT), bot_user_id=BOT) is None


def test_non_message_item_dropped():
    assert reaction_to_inbound(_event(item_type="file"), bot_user_id=BOT) is None


def test_missing_reaction_dropped():
    event = _event()
    del event["reaction"]
    assert reaction_to_inbound(event, bot_user_id=BOT) is None


def test_bot_id_dropped():
    assert reaction_to_inbound(_event(bot_id="B123"), bot_user_id=BOT) is None


def test_plus_one_name_preserved():
    got = reaction_to_inbound(_event(reaction="+1"), bot_user_id=BOT)
    assert got[3] == "+1"


def test_reaction_text_same_item_is_just_emoji():
    assert reaction_text("thumbsup", "111.222", "111.222") == ":thumbsup:"
    assert reaction_text("+1", "111.222", None) == ":+1:"


def test_reaction_text_nested_item_keeps_line():
    assert (
        reaction_text("thumbsup", "111.333", "111.222")
        == ":thumbsup: (on 111.333)"
    )
