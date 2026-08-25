"""Thin httpx client for the Telegram Bot API.

Only the handful of methods the bridge needs. Every call returns the
`result` payload on ok=true and raises ApiError otherwise, except
get_updates, which lets a 409 (another poller holds the token — a
detection signal, see README security notes) surface as ApiError too.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Long-poll wait for getUpdates; the HTTP timeout must comfortably exceed it.
POLL_SECONDS = 50


class ApiError(RuntimeError):
    pass


class Bot:
    def __init__(self, token: str):
        self._base = f"https://api.telegram.org/bot{token}"
        self._client = httpx.Client(timeout=httpx.Timeout(30, read=POLL_SECONDS + 10))

    def _call(self, method: str, **params: Any) -> Any:
        response = self._client.post(f"{self._base}/{method}", json=params)
        # Anything that is not a well-formed Telegram envelope has to leave here
        # as ApiError. The poll loop retries on (ApiError, httpx.HTTPError) and
        # dies on everything else, so a 502 HTML page from an edge would
        # otherwise raise JSONDecodeError straight through it. The response text
        # is truncated and the URL left out because the URL carries the token.
        try:
            payload = response.json()
        except ValueError:
            raise ApiError(
                f"{method}: non-JSON response (HTTP {response.status_code}): "
                f"{response.text[:200]}"
            ) from None
        if not isinstance(payload, dict):
            raise ApiError(f"{method}: unexpected response shape {type(payload).__name__}")
        if not payload.get("ok"):
            raise ApiError(f"{method}: {payload.get('description', response.text)}")
        if "result" not in payload:
            raise ApiError(f"{method}: ok response carried no result")
        return payload["result"]

    def get_me(self) -> dict[str, Any]:
        return self._call("getMe")

    def get_updates(self, offset: int) -> list[dict[str, Any]]:
        return self._call(
            "getUpdates",
            offset=offset,
            timeout=POLL_SECONDS,
            allowed_updates=["message"],
        )

    def send_message(self, chat_id: int, text: str, html: bool = False) -> None:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if html:
            params["parse_mode"] = "HTML"
        self._call("sendMessage", **params)

    def leave_chat(self, chat_id: int) -> None:
        self._call("leaveChat", chat_id=chat_id)
