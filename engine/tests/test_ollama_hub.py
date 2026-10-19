"""Tests for the Ollama hub: status parsing, library search, pull progress, ensure_pulled."""

import asyncio
import json

import httpx
import pytest

from vault_engine import ollama_hub

ENDPOINTS = {"ollama": "http://localhost:11434"}


def mock_http(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(ollama_hub.httpx, "AsyncClient", factory)


def test_status_parses_installed_and_running(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "bge-m3:latest", "size": 1200, "digest": "abc"}]})
        return httpx.Response(200, json={"models": [{"name": "bge-m3:latest", "size": 1200, "size_vram": 800, "expires_at": "soon"}]})

    mock_http(monkeypatch, handler)
    info = asyncio.run(ollama_hub.status(ENDPOINTS))
    assert info["online"] is True
    assert [m.name for m in info["installed"]] == ["bge-m3:latest"]
    assert info["running"][0].size_vram == 800


def test_status_offline(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    mock_http(monkeypatch, handler)
    info = asyncio.run(ollama_hub.status(ENDPOINTS))
    assert info["online"] is False
    assert info["installed"] == [] and info["running"] == []


def test_library_search_parses_model_cards(monkeypatch):
    html = """
    <html><body>
      <a href="/library/llama3.2"><h2>llama3.2</h2></a>
      <a href="/library/llama3.1">llama3.1</a>
      <a href="/library/llama3.2">duplicate</a>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ollama.com"
        return httpx.Response(200, text=html)

    mock_http(monkeypatch, handler)
    models = asyncio.run(ollama_hub.library_search("llama"))
    names = [m.name for m in models]
    assert "llama3.2" in names and "llama3.1" in names
    assert names.count("llama3.2") == 1  # duplicates deduplicated


def test_pull_reports_progress(monkeypatch):
    lines = [
        json.dumps({"status": "downloading manifest", "completed": 5, "total": 10}),
        json.dumps({"status": "success"}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/pull"
        return httpx.Response(200, content="\n".join(lines))

    mock_http(monkeypatch, handler)
    seen = []

    async def on_progress(p: dict) -> None:
        seen.append(p)

    asyncio.run(ollama_hub.pull(ENDPOINTS, "m", on_progress))
    assert seen[0]["completed"] == 5 and seen[0]["total"] == 10


def test_pull_surfaces_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"error": "model not found"}))

    mock_http(monkeypatch, handler)
    with pytest.raises(ollama_hub.HubError, match="model not found"):
        asyncio.run(ollama_hub.pull(ENDPOINTS, "ghost"))


def test_ensure_pulled_skips_installed_models(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "bge-m3", "size": 1}]})
        return httpx.Response(200, json={"models": []})

    mock_http(monkeypatch, handler)
    assert asyncio.run(ollama_hub.ensure_pulled(ENDPOINTS, "bge-m3")) is True
    assert "/api/pull" not in requests


def test_ensure_pulled_downloads_missing(monkeypatch):
    pulled = []
    installed = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal installed
        if request.url.path == "/api/tags":
            models = [{"name": "nomic-embed-text", "size": 1}] if installed else []
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/pull":
            pulled.append(request.content)
            installed = True
            return httpx.Response(200, content=json.dumps({"status": "success"}))
        return httpx.Response(200, json={"models": []})

    mock_http(monkeypatch, handler)
    assert asyncio.run(ollama_hub.ensure_pulled(ENDPOINTS, "nomic-embed-text")) is True
    assert pulled and b"nomic-embed-text" in pulled[0]


def test_unload_uses_keep_alive_zero(monkeypatch):
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"done": True})

    mock_http(monkeypatch, handler)
    asyncio.run(ollama_hub.unload(ENDPOINTS, "m"))
    assert bodies[0]["keep_alive"] == 0
