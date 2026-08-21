"""OpenRouter model catalog for the config screen.

Proxies OpenRouter's model list so the dash can show which models this
deployment's key can actually use. With an OPENROUTER_API_KEY (process env
first, then the serve-root .env — the same precedence the tools use) it
calls /api/v1/models/user, which filters by the key's org settings
(model/provider allowlists, ZDR, spend caps). Without a key, or if that
call fails, it falls back to the public catalog. The key never leaves the
server; the response carries only model metadata.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from headlong_web import envfile

_USER_URL = "https://openrouter.ai/api/v1/models/user"
_PUBLIC_URL = "https://openrouter.ai/api/v1/models"
_TIMEOUT_S = 15
# Model catalogs change slowly; errors retry sooner so a transient outage
# doesn't stick for the full TTL.
_CACHE_TTL_S = 600
_ERROR_TTL_S = 60

_cache: dict = {"ts": 0.0, "key_fp": None, "payload": None}


def _api_key(root: Path) -> str:
    """Process env beats .env, matching the loaders' merge semantics."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    for name, value in envfile.parse_env_file(root / ".env"):
        if name == "OPENROUTER_API_KEY":
            key = value.strip()
    return key


def _per_million(raw: object) -> float | None:
    """OpenRouter pricing strings are USD per token; report USD per 1M."""
    try:
        return round(float(raw) * 1_000_000, 3)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fetch(url: str, key: str | None) -> dict:
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        return json.load(response)


def _trim(raw_models: list) -> list[dict]:
    models = []
    for model in raw_models:
        if not isinstance(model, dict) or not model.get("id"):
            continue
        pricing = model.get("pricing") or {}
        models.append(
            {
                "id": str(model["id"]),
                "name": model.get("name"),
                "context_length": model.get("context_length"),
                "prompt_usd_per_m": _per_million(pricing.get("prompt")),
                "completion_usd_per_m": _per_million(pricing.get("completion")),
            }
        )
    models.sort(key=lambda m: m["id"])
    return models


def available_models(root: Path) -> dict:
    key = _api_key(root)
    key_fp = hashlib.sha256(key.encode()).hexdigest()[:12] if key else ""
    now = time.time()
    cached = _cache["payload"]
    if cached is not None and _cache["key_fp"] == key_fp:
        ttl = _ERROR_TTL_S if cached.get("error") else _CACHE_TTL_S
        if now - _cache["ts"] < ttl:
            return cached

    source = None
    error = None
    data = None
    if key:
        try:
            data = _fetch(_USER_URL, key)
            source = "key"
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            error = f"models/user failed: {exc}"
    if data is None:
        try:
            data = _fetch(_PUBLIC_URL, None)
            source = "public"
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            error = f"{error + '; ' if error else ''}public catalog failed: {exc}"
            data = {}

    models = _trim(data.get("data") or [])
    payload = {
        # "key": filtered to what this org's key can use; "public": whole catalog
        "source": source,
        "has_key": bool(key),
        "count": len(models),
        "models": models,
        "error": error,
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _cache.update(ts=now, key_fp=key_fp, payload=payload)
    return payload
