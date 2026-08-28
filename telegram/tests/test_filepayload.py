from headlong_telegram.filepayload import CAPTION_MAX, file_payload


def test_plain_text_is_not_a_file():
    assert file_payload({"type": "message", "content": "hello"}) is None


def test_filename_stamps_a_document():
    payload = file_payload({"filename": "note.txt", "content": "hi"})
    assert payload is not None
    assert payload["filename"] == "note.txt"
    assert payload["content"] == "hi"
    assert payload["as_photo"] is False
    assert payload["caption"] is None


def test_content_b64_roundtrips_png_bytes():
    import base64
    png = b"\x89PNG\r\n\x1a\n" + b"rest"
    payload = file_payload({
        "filename": "fig.png",
        "content_b64": base64.b64encode(png).decode("ascii"),
    })
    assert payload is not None
    assert payload["content"] == png
    assert payload["as_photo"] is True


def test_svg_without_filename_stays_text():
    assert file_payload({"content": "<svg xmlns='x'></svg>"}) is None


def test_path_is_reduced_to_basename():
    payload = file_payload({"filename": "/etc/passwd", "content": "x"})
    assert payload is not None
    assert payload["filename"] == "passwd"


def test_invalid_b64_is_not_a_file():
    assert file_payload({"filename": "a.bin", "content_b64": "!!!!"}) is None


def test_caption_is_truncated():
    payload = file_payload({
        "filename": "a.txt", "content": "x", "caption": "c" * 2000,
    })
    assert payload is not None
    assert payload["caption"] == "c" * CAPTION_MAX
