"""Regression tests for FEEDBACK_QA.md ciclo 5 (Bug #19, Miglioramento #15).

Unlike the cycle 2 tests, these do not replace ollama_hub.delete: the real function
runs against httpx.MockTransport, so the HTTP request itself is checked.
"""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from vault_engine import ollama_hub

ENDPOINTS = {"ollama": "http://localhost:11434"}


def mock_httpx(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(ollama_hub.httpx, "AsyncClient", factory)


def recording_ollama(seen, delete_status=200):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, json.loads(req.content or b"{}")))
        if req.url.path == "/api/delete":
            if delete_status != 200:
                return httpx.Response(delete_status, json={"error": "model not found"})
            return httpx.Response(200)
        return httpx.Response(200, json={})

    return handler


# ---------------------------------------------------------------------- Bug #19


def test_hub_delete_sends_delete_with_json_body(monkeypatch):
    seen = []
    mock_httpx(monkeypatch, recording_ollama(seen))
    asyncio.run(ollama_hub.delete(ENDPOINTS, "hf.co/bartowski/Qwen:Q4_K_M"))
    assert seen == [("DELETE", "/api/delete", {"model": "hf.co/bartowski/Qwen:Q4_K_M"})]


def test_hub_delete_unknown_model_raises_huberror(monkeypatch):
    mock_httpx(monkeypatch, recording_ollama([], delete_status=404))
    with pytest.raises(ollama_hub.HubError, match="HTTP 404"):
        asyncio.run(ollama_hub.delete(ENDPOINTS, "x:latest"))


def test_hub_delete_offline_raises_huberror(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    mock_httpx(monkeypatch, handler)
    with pytest.raises(ollama_hub.HubError, match="non raggiungibile"):
        asyncio.run(ollama_hub.delete(ENDPOINTS, "x:latest"))


@pytest.fixture
def client(monkeypatch, tmp_path):
    from vault_engine import app as appmod
    from vault_engine.config import SettingsStore

    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    monkeypatch.setattr(appmod.state, "settings", SettingsStore(path=tmp_path / "settings.json"), raising=False)
    return TestClient(appmod.app, base_url="http://127.0.0.1")


def test_delete_route_unloads_then_deletes(client, monkeypatch):
    seen = []
    mock_httpx(monkeypatch, recording_ollama(seen))
    r = client.post("/ollama/delete", json={"model": "bge-m3:latest"})
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": "bge-m3:latest"}
    assert [(m, p) for m, p, _ in seen] == [("POST", "/api/generate"), ("DELETE", "/api/delete")]


def test_delete_route_unknown_model_answers_502(client, monkeypatch):
    mock_httpx(monkeypatch, recording_ollama([], delete_status=404))
    r = client.post("/ollama/delete", json={"model": "x:latest"})
    assert r.status_code == 502
    assert "HTTP 404" in r.json()["detail"]
