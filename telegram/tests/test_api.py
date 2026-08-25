"""Bot._call's error contract: every failure arrives as ApiError.

The module docstring promises callers that a call either returns `result` or
raises ApiError. The poll loop leans on that promise -- it retries on
(ApiError, httpx.HTTPError) and dies on anything else -- so a failure shape
that escapes those two takes the bridge down.
"""

import httpx
import pytest

from headlong_telegram.api import ApiError, Bot


def bot_returning(response_factory):
    bot = Bot("t")
    bot._client = httpx.Client(
        transport=httpx.MockTransport(lambda request: response_factory(request))
    )
    return bot


def test_non_json_body_raises_api_error():
    """A 502 HTML page from an edge/proxy, not a Telegram JSON error."""
    bot = bot_returning(lambda r: httpx.Response(502, text="<html>502 Bad Gateway</html>"))
    with pytest.raises(ApiError):
        bot.get_updates(0)


def test_json_error_status_raises_api_error():
    """A 500 whose body is valid JSON but carries no ok/description."""
    bot = bot_returning(lambda r: httpx.Response(500, json={"oops": True}))
    with pytest.raises(ApiError):
        bot.get_updates(0)


def test_ok_false_still_raises_api_error_with_description():
    bot = bot_returning(
        lambda r: httpx.Response(200, json={"ok": False, "description": "Conflict"})
    )
    with pytest.raises(ApiError, match="Conflict"):
        bot.get_updates(0)


def test_ok_true_returns_result():
    bot = bot_returning(lambda r: httpx.Response(200, json={"ok": True, "result": [1, 2]}))
    assert bot.get_updates(0) == [1, 2]
