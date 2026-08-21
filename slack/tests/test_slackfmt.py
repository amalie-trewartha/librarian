from headlong_slack.slackfmt import chunk, clean_inbound, strip_leaked_command, to_mrkdwn


def test_strip_leaked_command():
    leaked = "chat reply slack-U0BNK8YBF7A-C0BMUKCR44C-1785790643.112419 Right where Max left them"
    assert strip_leaked_command(leaked) == "Right where Max left them"
    assert strip_leaked_command("no leak here") == "no leak here"
    assert strip_leaked_command("mid-text chat reply foo stays") == "mid-text chat reply foo stays"


def test_bold_and_links():
    assert to_mrkdwn("**hi** [docs](https://x.io/a)") == "*hi* <https://x.io/a|docs>"


def test_headings_and_bullets():
    assert to_mrkdwn("# Title\n* one\n+ two\n- three") == "*Title*\n- one\n- two\n- three"


def test_code_untouched():
    text = "use **x**\n```\n**not bold** [a](b)\n```\nand `**inline**`"
    out = to_mrkdwn(text)
    assert "*x*" in out
    assert "**not bold** [a](b)" in out
    assert "`**inline**`" in out


def test_clean_inbound_strips_bot_mention():
    assert clean_inbound("<@U0BOT> hello", "U0BOT") == "hello"


def test_clean_inbound_entities_and_links():
    assert clean_inbound("a &lt;b&gt; &amp; c") == "a <b> & c"
    assert clean_inbound("<https://x.io|the site>") == "the site (https://x.io)"
    assert clean_inbound("<https://x.io>") == "https://x.io"
    assert clean_inbound("ask <@U0OTHER>") == "ask U0OTHER"


def test_chunk_short_passthrough():
    assert chunk("hello") == ["hello"]


def test_chunk_prefers_paragraphs():
    text = "a" * 3000 + "\n\n" + "b" * 3000
    parts = chunk(text, limit=3900)
    assert parts == ["a" * 3000, "b" * 3000]


def test_chunk_hard_split_when_no_boundary():
    text = "x" * 9000
    parts = chunk(text, limit=3900)
    assert "".join(parts) == text
    assert all(len(p) <= 3900 for p in parts)


def test_recent_posts_dedupe():
    from headlong_slack.outbound import RecentPosts

    recent = RecentPosts(window=300)
    assert not recent.is_duplicate("slack-U1-C2-3.4", "hello", now=1000)
    assert recent.is_duplicate("slack-U1-C2-3.4", "hello", now=1010)
    assert not recent.is_duplicate("slack-U1-C2-3.4", "different", now=1020)
    assert not recent.is_duplicate("slack-U1-D9", "hello", now=1030)
    recent2 = RecentPosts(window=300)
    assert not recent2.is_duplicate("slack-U1-C2-3.4", "hello", now=1000)
    assert not recent2.is_duplicate("slack-U1-C2-3.4", "hello", now=1400)  # outside window
