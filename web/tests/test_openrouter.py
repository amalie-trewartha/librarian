"""OpenRouter catalog proxy: key resolution, trimming, fallback, caching."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from headlong_web import openrouter
from headlong_web.server import create_app

RAW = {
    "data": [
        {
            "id": "openai/gpt-oss-120b",
            "name": "GPT-OSS 120B",
            "context_length": 131072,
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
        },
        {
            "id": "anthropic/claude-sonnet-4.5",
            "name": "Claude Sonnet 4.5",
            "context_length": 200000,
            "pricing": {"prompt": "not-a-number", "completion": None},
        },
        {"name": "no id — dropped"},
    ]
}


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(
        openrouter, "_cache", {"ts": 0.0, "key_fp": None, "payload": None}
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def test_key_from_root_env_hits_user_endpoint(tmp_path: Path, monkeypatch):
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sk-or-test\n")
    seen = {}

    def fake_fetch(url, key):
        seen["url"], seen["key"] = url, key
        return RAW

    monkeypatch.setattr(openrouter, "_fetch", fake_fetch)
    payload = openrouter.available_models(tmp_path)

    assert seen == {"url": openrouter._USER_URL, "key": "sk-or-test"}
    assert payload["source"] == "key"
    assert payload["has_key"] is True
    assert payload["count"] == 2  # id-less entry dropped
    by_id = {m["id"]: m for m in payload["models"]}
    assert by_id["openai/gpt-oss-120b"]["prompt_usd_per_m"] == 0.15
    assert by_id["openai/gpt-oss-120b"]["completion_usd_per_m"] == 0.6
    assert by_id["anthropic/claude-sonnet-4.5"]["prompt_usd_per_m"] is None
    # sorted by id
    assert [m["id"] for m in payload["models"]] == sorted(by_id)


def test_no_key_falls_back_to_public(tmp_path: Path, monkeypatch):
    def fake_fetch(url, key):
        assert key is None
        assert url == openrouter._PUBLIC_URL
        return RAW

    monkeypatch.setattr(openrouter, "_fetch", fake_fetch)
    payload = openrouter.available_models(tmp_path)
    assert payload["source"] == "public"
    assert payload["has_key"] is False


def test_user_endpoint_failure_falls_back_to_public(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")

    def fake_fetch(url, key):
        if url == openrouter._USER_URL:
            raise TimeoutError("timed out")
        return RAW

    monkeypatch.setattr(openrouter, "_fetch", fake_fetch)
    payload = openrouter.available_models(tmp_path)
    assert payload["source"] == "public"
    assert "models/user failed" in payload["error"]


def test_cache_and_key_rotation_invalidates(tmp_path: Path, monkeypatch):
    calls = []

    def fake_fetch(url, key):
        calls.append(url)
        return RAW

    monkeypatch.setattr(openrouter, "_fetch", fake_fetch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-one")
    openrouter.available_models(tmp_path)
    openrouter.available_models(tmp_path)
    assert len(calls) == 1  # second call served from cache

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-two")
    openrouter.available_models(tmp_path)
    assert len(calls) == 2  # rotated key bypasses the cache


def test_endpoint(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(openrouter, "_fetch", lambda url, key: RAW)
    client = TestClient(create_app(tmp_path))
    body = client.get("/api/openrouter/models").json()
    assert body["source"] == "public"
    assert body["count"] == 2
