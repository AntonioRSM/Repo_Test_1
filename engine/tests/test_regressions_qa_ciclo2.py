"""Regression tests for FEEDBACK_QA.md ciclo 2 (Bug #1-#7, Miglioramento #1-#6).

The QA probes asserted each defect; these tests assert the fixed behaviour.
"""

import asyncio
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from vault_engine import ollama_hub, providers
from vault_engine.agent import tools as agent_tools
from vault_engine.config import ModelRef


def mock_httpx(module, monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)


def fake_ollama(tags, ps=None, pull_lines=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n, "size": 1} for n in tags]})
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": ps or []})
        if req.url.path == "/api/pull":
            return httpx.Response(200, text="\n".join(pull_lines or ['{"status":"success"}']))
        return httpx.Response(200, json={})

    return handler


# ---------------------------------------------------------------------- Bug #1


def test_ensure_loaded_tolerates_ollama_offline(monkeypatch):
    """With Ollama down, ensure_loaded must log-and-skip, not raise HubError."""

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    mock_httpx(providers, monkeypatch, handler)
    mock_httpx(ollama_hub, monkeypatch, handler)
    ref = ModelRef(provider="ollama", model="bge-m3")
    # Must not raise: the real embed/chat call will surface a clean 502 downstream.
    asyncio.run(providers.ensure_loaded({}, [(ref, "embedding")]))


def test_ensure_loaded_offline_does_not_attempt_pull(monkeypatch):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        raise httpx.ConnectError("refused")

    mock_httpx(providers, monkeypatch, handler)
    mock_httpx(ollama_hub, monkeypatch, handler)
    ref = ModelRef(provider="ollama", model="bge-m3")
    asyncio.run(providers.ensure_loaded({}, [(ref, "llm")], auto_pull=True))
    assert "/api/pull" not in calls


# ---------------------------------------------------------------------- Bug #2


def test_ensure_loaded_pull_failure_emits_error_event(monkeypatch):
    handler = fake_ollama([], pull_lines=['{"error":"file does not exist"}'])
    mock_httpx(providers, monkeypatch, handler)
    mock_httpx(ollama_hub, monkeypatch, handler)
    seen = []

    class Ev:
        def publish(self, e):
            seen.append(e)

    ref = ModelRef(provider="ollama", model="nonexistent-model")
    asyncio.run(providers.ensure_loaded({}, [(ref, "llm")], events=Ev()))
    statuses = [e["status"] for e in seen]
    assert "download_avviato" in statuses
    assert "errore" in statuses  # without it the Models page spun forever
    errors = [e for e in seen if e["status"] == "errore"]
    assert "file does not exist" in errors[0]["error"]


# ---------------------------------------------------------------------- Miglioramento #1


def test_ensure_loaded_notify_mode_raises_and_pulls_in_background(monkeypatch):
    handler = fake_ollama([])  # online, model missing
    mock_httpx(providers, monkeypatch, handler)
    mock_httpx(ollama_hub, monkeypatch, handler)
    started = []

    def fake_start_pull(endpoints, model, **kwargs):
        started.append(model)
        return True

    monkeypatch.setattr(ollama_hub, "start_pull", fake_start_pull)
    ref = ModelRef(provider="ollama", model="mancante")
    with pytest.raises(providers.ProviderError, match="download"):
        asyncio.run(providers.ensure_loaded({}, [(ref, "llm")], auto_pull=True, allow_download=False))
    assert started == ["mancante"]


# ---------------------------------------------------------------------- Bug #4


@pytest.fixture
def client(monkeypatch, tmp_path):
    from vault_engine import app as appmod
    from vault_engine.config import SettingsStore

    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    # Avoid the full lifespan (which would submit real sync jobs): the delete route
    # only needs state.settings for the Ollama endpoints.
    monkeypatch.setattr(appmod.state, "settings", SettingsStore(path=tmp_path / "settings.json"), raising=False)
    # Miglioramento #11 (ciclo 3): "testserver" is no longer an allowed Host; the
    # TestClient must present a loopback base URL instead.
    return TestClient(appmod.app, base_url="http://127.0.0.1")


def test_delete_route_accepts_namespaced_models(client, monkeypatch):
    called = []

    async def fake_unload(endpoints, name):
        called.append(("unload", name))

    async def fake_delete(endpoints, name):
        called.append(("delete", name))

    monkeypatch.setattr(ollama_hub, "unload", fake_unload)
    monkeypatch.setattr(ollama_hub, "delete", fake_delete)
    r = client.post("/ollama/delete", json={"model": "hf.co/bartowski/Qwen:Q4_K_M"})
    assert r.status_code == 200, r.text
    assert called == [("unload", "hf.co/bartowski/Qwen:Q4_K_M"), ("delete", "hf.co/bartowski/Qwen:Q4_K_M")]


def test_old_delete_route_is_gone(client, monkeypatch):
    async def fake(endpoints, name):  # must never be called
        raise AssertionError("unexpected call")

    monkeypatch.setattr(ollama_hub, "unload", fake)
    monkeypatch.setattr(ollama_hub, "delete", fake)
    r = client.delete("/ollama/models/hf.co%2Fbartowski%2FQwen:Q4_K_M")
    assert r.status_code == 404


# ---------------------------------------------------------------------- Bug #6


def test_trusted_host_middleware_installed_only_without_token():
    from vault_engine import app as appmod

    # Ciclo 3 (Bug #15): LocalhostOnlyMiddleware replaces TrustedHostMiddleware, which
    # misparsed IPv6 bracket hosts ([::1]:port) and rejected every request.
    installed = any(m.cls.__name__ == "LocalhostOnlyMiddleware" for m in appmod.app.user_middleware)
    assert installed == (not os.environ.get("WSOS_TOKEN"))


def test_health_rejects_foreign_host_header(client):
    if os.environ.get("WSOS_TOKEN"):
        pytest.skip("TrustedHostMiddleware only active without WSOS_TOKEN")
    assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------- Miglioramento #4


def test_scan_directory_visit_budget(monkeypatch, tmp_path):
    """A sparse pattern must stop after the visit budget, not crawl the whole disk."""
    monkeypatch.setattr(agent_tools, "SCAN_VISITED_LIMIT", 50)
    for i in range(100):
        (tmp_path / f"f{i:03}.txt").write_text("x", encoding="utf-8")
    out = agent_tools._scan_directory(tmp_path, "*.nessuno")
    assert out["entries"] == []
    assert out["truncated"] is True


def test_scan_directory_matches_dirs_and_nested_files(tmp_path):
    deep = tmp_path / "sub"
    deep.mkdir()
    (deep / "b.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "c.pdf").write_text("x", encoding="utf-8")
    names = {e["name"] for e in agent_tools._scan_directory(tmp_path, "**/*.txt")["entries"]}
    assert names == {"a.txt", "b.txt"}
    names = {e["name"] for e in agent_tools._scan_directory(tmp_path, "*")["entries"]}
    assert names == {"a.txt", "c.pdf", "sub"}
