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


def test_is_installed_requires_exact_tag_after_normalization(monkeypatch):
    """Bug #3: llama3 means llama3:latest — llama3:8b alone must NOT satisfy it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3:8b", "size": 1}]})
        return httpx.Response(200, json={"models": []})

    mock_http(monkeypatch, handler)
    assert asyncio.run(ollama_hub.is_installed(ENDPOINTS, "llama3")) is False
    assert asyncio.run(ollama_hub.is_installed(ENDPOINTS, "llama3:8b")) is True
    assert asyncio.run(ollama_hub.is_installed(ENDPOINTS, "llama3:latest")) is False


def test_normalize_name_appends_latest_only_to_tagless_tail():
    assert ollama_hub.normalize_name("llama3") == "llama3:latest"
    assert ollama_hub.normalize_name("llama3:8b") == "llama3:8b"
    # Registry prefixes may contain ':' outside the model tag: untouched.
    assert ollama_hub.normalize_name("hf.co/bartowski/Qwen2") == "hf.co/bartowski/Qwen2:latest"
    assert ollama_hub.normalize_name("hf.co/bartowski/Qwen2:Q4_K_M") == "hf.co/bartowski/Qwen2:Q4_K_M"


def test_pull_dedup_skips_second_caller(monkeypatch):
    """Miglioramento #2: concurrent same-model downloads serialize and re-check."""
    installed = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal installed
        if request.url.path == "/api/tags":
            models = [{"name": "m:latest", "size": 1}] if installed else []
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/pull":
            installed = True  # ollama records the model once the pull completes
            return httpx.Response(200, content=json.dumps({"status": "success"}))
        return httpx.Response(200, json={"models": []})

    mock_http(monkeypatch, handler)

    async def scenario():
        # Both callers race; the lock + re-check must issue ONE pull.
        await asyncio.gather(ollama_hub.pull_dedup(ENDPOINTS, "m"), ollama_hub.pull_dedup(ENDPOINTS, "m"))

    pulls = []
    original = ollama_hub.pull

    async def counting_pull(endpoints, model, on_progress=None):
        pulls.append(model)
        await original(endpoints, model, on_progress)

    monkeypatch.setattr(ollama_hub, "pull", counting_pull)
    asyncio.run(scenario())
    assert pulls == ["m"]


def test_pull_throttles_progress_events(monkeypatch):
    """Miglioramento #3: 10k NDJSON lines must not produce 10k events."""
    lines = [json.dumps({"status": "pulling", "completed": i, "total": 10000}) for i in range(9999)]
    lines.append(json.dumps({"status": "success"}))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="\n".join(lines))

    mock_http(monkeypatch, handler)
    seen = []

    async def on_progress(p: dict) -> None:
        seen.append(p)

    asyncio.run(ollama_hub.pull(ENDPOINTS, "m", on_progress))
    assert len(seen) < 200, f"troppi eventi: {len(seen)}"
    assert seen[-1]["status"] == "success"  # terminal state always delivered


def test_unload_uses_keep_alive_zero(monkeypatch):
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"done": True})

    mock_http(monkeypatch, handler)
    asyncio.run(ollama_hub.unload(ENDPOINTS, "m"))
    assert bodies[0]["keep_alive"] == 0


def test_load_falls_back_to_embed_for_embedding_only_models(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path == "/api/generate":
            return httpx.Response(400, json={"error": '"bge-m3" does not support generate'})
        return httpx.Response(200, json={"embeddings": [[]]})

    mock_http(monkeypatch, handler)
    asyncio.run(ollama_hub.load(ENDPOINTS, "bge-m3", 30))
    assert [c[0] for c in calls] == ["/api/generate", "/api/embed"]
    assert calls[1][1]["model"] == "bge-m3"
    assert calls[0][1]["keep_alive"] == "30m"
    # Bug #7: the embed fallback must carry the same residency time (Bug #7 regression).
    assert calls[1][1]["keep_alive"] == "30m"


def test_unload_falls_back_to_embed_for_embedding_only_models(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path == "/api/generate":
            return httpx.Response(400, json={"error": '"bge-m3" does not support generate'})
        return httpx.Response(200, json={"embeddings": [[]]})

    mock_http(monkeypatch, handler)
    asyncio.run(ollama_hub.unload(ENDPOINTS, "bge-m3"))
    assert [c[0] for c in calls] == ["/api/generate", "/api/embed"]
    assert calls[1][1]["keep_alive"] == 0


def test_unload_real_error_is_not_masked_by_fallback(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'ghost' not found"})

    mock_http(monkeypatch, handler)
    with pytest.raises(ollama_hub.HubError, match="404"):
        asyncio.run(ollama_hub.unload(ENDPOINTS, "ghost"))
