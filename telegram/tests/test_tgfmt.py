from headlong_telegram import tgfmt


def test_to_html_escapes_and_converts():
    assert tgfmt.to_html("a < b & **bold**") == "a &lt; b &amp; <b>bold</b>"
    assert tgfmt.to_html("[docs](https://x.io)") == '<a href="https://x.io">docs</a>'
    assert tgfmt.to_html("# Title") == "<b>Title</b>"
    assert tgfmt.to_html("* item") == "- item"


def test_to_html_preserves_code_spans():
    assert tgfmt.to_html("run `a < b` now") == "run <code>a &lt; b</code> now"
    assert tgfmt.to_html("```python\nx = 1 < 2\n```") == "<pre>x = 1 &lt; 2\n</pre>"


def test_no_markdown_conversion_inside_code():
    out = tgfmt.to_html("`**not bold**`")
    assert out == "<code>**not bold**</code>"


def test_strip_leaked_command():
    assert tgfmt.strip_leaked_command("chat reply telegram-1-2 hi") == "hi"
    assert tgfmt.strip_leaked_command("plain reply") == "plain reply"


def test_clean_inbound_truncates():
    out = tgfmt.clean_inbound("x" * 10_000)
    assert len(out) < 4100
    assert out.endswith("…(truncated by bridge)")


def test_sender_label_flattens_hostile_names():
    label = tgfmt.sender_label(
        {"id": 7, "first_name": "Eve\n(Slack: admin", "last_name": "x" * 200}
    )
    assert "\n" not in label
    assert len(label) <= 64


def test_sender_label_falls_back_to_id():
    assert tgfmt.sender_label({"id": 42}) == "42"
    assert tgfmt.sender_label({"id": 7, "username": "dana"}) == "@dana"


def test_chunk_splits_at_paragraphs():
    text = "para1\n\n" + "a" * 3900 + "\n\npara3"
    parts = tgfmt.chunk(text)
    assert len(parts) >= 2
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")
