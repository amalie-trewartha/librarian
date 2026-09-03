from headlong_web.chat_links import resolve_source_url


def test_source_url_is_recorded_and_inherited():
    known = {}
    source_url = "https://laudesters.slack.com/archives/C1/p1788451200123456"

    assert resolve_source_url(
        {"step_id": "m1", "source_url": source_url}, known
    ) == source_url
    assert resolve_source_url(
        {"step_id": "m2", "reply_to": "m1"}, known
    ) == source_url
    assert known == {"m1": source_url, "m2": source_url}


def test_own_source_url_takes_precedence_over_replied_message():
    old_url = "https://old.slack.com/archives/C1/p1"
    new_url = "https://new.slack.com/archives/C1/p2"
    known = {"m1": old_url}

    assert resolve_source_url(
        {"step_id": "m2", "reply_to": "m1", "source_url": new_url}, known
    ) == new_url
    assert known["m2"] == new_url


def test_missing_source_url_stays_none():
    assert resolve_source_url({"step_id": "m1"}, {}) is None
