from headlong_telegram.filepayload import file_payload

PNG = b"\x89PNG\r\n\x1a\n" + b"rest"


def test_plain_text_is_none():
    assert file_payload({"type": "message", "content": "hello"}) is None


def test_filename_field():
    p = file_payload({"content": "<svg xmlns", "filename": "walk.svg", "caption": "a figure"})
    assert p["filename"] == "walk.svg"
    assert p["content"] == b"<svg xmlns"
    assert p["initial_comment"] == "a figure"
    assert p["title"] == "walk.svg"


def test_svg_sniff_without_filename():
    p = file_payload({"content": "  <svg xmlns=\"http://www.w3.org/2000/svg\">"})
    assert p["filename"] == "figure.svg"
    assert p["content"].lstrip().startswith(b"<svg")


def test_png_sniff_without_filename():
    p = file_payload({"content": PNG})
    assert p["filename"] == "figure.png"
    assert p["content"].startswith(b"\x89PNG")


def test_typed_attachment_without_name():
    p = file_payload({"type": "file", "content": b"abc"})
    assert p["filename"] == "attachment.bin"
    assert p["content"] == b"abc"


def test_path_is_basename():
    p = file_payload({"filename": "/tmp/secret/fig.png", "content": "x"})
    assert p["filename"] == "fig.png"
