"""The bot token never reaches the log.

Every Bot API URL embeds the token. httpx logs the URL of each request at
INFO and quotes it in its exception messages, so before configure_logging the
bridge wrote the token to journald on every poll.
"""

import io
import logging

from headlong_telegram.cli import RedactingFormatter, configure_logging, redact

TOKEN_URL = "https://api.telegram.org/bot123456789:FAKE-token-for-tests_not-a-real-one/getUpdates"


def test_redact_strips_the_token_from_a_url():
    assert redact(f"POST {TOKEN_URL} 200") == "POST https://api.telegram.org/bot<redacted>/getUpdates 200"


def test_redact_leaves_other_text_alone():
    assert redact("robot 12:30 bottle") == "robot 12:30 bottle"


def _formatted(record_fn):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(name)s %(levelname)s %(message)s"))
    log = logging.getLogger("test.redaction")
    log.propagate = False
    log.setLevel(logging.DEBUG)
    log.handlers = [handler]
    record_fn(log)
    return stream.getvalue()


def test_formatter_redacts_the_message_and_its_args():
    out = _formatted(lambda log: log.info('HTTP Request: %s %s "%s"', "POST", TOKEN_URL, "HTTP/1.1 200 OK"))
    assert "FAKE-token-for-tests_not-a-real-one" not in out
    assert "bot<redacted>/getUpdates" in out


def test_formatter_redacts_exception_text():
    def go(log):
        try:
            raise RuntimeError(f"Connect failed for url '{TOKEN_URL}'")
        except RuntimeError:
            log.exception("poll failed")

    out = _formatted(go)
    assert "FAKE-token-for-tests_not-a-real-one" not in out
    assert "poll failed" in out and "Traceback" in out


def test_configure_logging_silences_httpx_request_lines_and_redacts_root():
    saved = (logging.getLogger().handlers[:], logging.getLogger().level,
             logging.getLogger("httpx").level, logging.getLogger("httpcore").level)
    try:
        configure_logging(verbose=False)
        assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("httpcore").getEffectiveLevel() == logging.WARNING
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, RedactingFormatter)
        configure_logging(verbose=True)
        assert logging.getLogger("httpx").getEffectiveLevel() == logging.DEBUG
        assert len(logging.getLogger().handlers) == 1
    finally:
        root = logging.getLogger()
        root.handlers = saved[0]
        root.setLevel(saved[1])
        logging.getLogger("httpx").setLevel(saved[2])
        logging.getLogger("httpcore").setLevel(saved[3])
