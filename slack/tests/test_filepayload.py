from headlong_slack.filepayload import COMMENT_MAX, file_payload, file_signature


def test_plain_text_is_not_a_file():
    assert file_payload({"type": "message", "content": "hello"}) is None


def test_filename_stamps_a_document():
    payload = file_payload({"filename": "note.txt", "content": "hi"})
    assert payload is not None
    assert payload["filename"] == "note.txt"
    assert payload["content"] == "hi"
    assert payload["initial_comment"] is None
    assert payload["decode_error"] is False


def test_content_b64_roundtrips_png_bytes():
    import base64
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    payload = file_payload({
        "filename": "fig.png",
        "content_b64": base64.b64encode(png).decode("ascii"),
    })
    assert payload is not None
    assert payload["content"] == png


def test_svg_without_filename_stays_text():
    assert file_payload({"content": "<svg xmlns='x'></svg>"}) is None


def test_path_is_reduced_to_basename():
    payload = file_payload({"filename": "/etc/passwd", "content": "x"})
    assert payload is not None
    assert payload["filename"] == "passwd"


def test_invalid_b64_is_decode_error():
    payload = file_payload({
        "filename": "a.bin",
        "content_b64": "!!!!",
        "content": "[file: a.bin]",
    })
    assert payload is not None
    assert payload["content"] is None
    assert payload["decode_error"] is True


def test_empty_content_b64_is_decode_error():
    payload = file_payload({
        "filename": "note.txt",
        "content_b64": "",
        "content": "[file: note.txt]",
    })
    assert payload is not None
    assert payload["content"] is None
    assert payload["decode_error"] is True


def test_file_signature_is_filename_plus_content_hash():
    same = file_signature("note.txt", b"aaa")
    assert same == file_signature("note.txt", "aaa")
    assert same != file_signature("note.txt", b"bbb")
    assert same != file_signature("other.txt", b"aaa")


def test_non_string_content_is_decode_error():
    payload = file_payload({
        "filename": "bad.bin",
        "content": {"x": "y"},
    })
    assert payload is not None
    assert payload["content"] is None
    assert payload["decode_error"] is True


def test_file_alias_is_ignored():
    assert file_payload({"file": "note.txt", "content": "hi"}) is None
    payload = file_payload({"filename": "note.txt", "file": "other.bin", "content": "hi"})
    assert payload is not None
    assert payload["filename"] == "note.txt"


def test_caption_and_text_content_are_leak_filtered():
    payload = file_payload({
        "filename": "note.txt",
        "content": "chat reply slack-U1-C1 secret notes",
        "caption": "chat reply slack-U1-C1 look",
    })
    assert payload is not None
    assert payload["content"] == "secret notes"
    assert payload["initial_comment"] == "look"


def test_caption_is_truncated():
    payload = file_payload({
        "filename": "a.txt", "content": "x", "caption": "c" * (COMMENT_MAX + 50),
    })
    assert payload is not None
    assert payload["initial_comment"] == "c" * COMMENT_MAX
