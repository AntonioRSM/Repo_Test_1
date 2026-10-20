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


# --------------------------------------------- Bug #16 e #17 (ciclo 4, ancora aperti)


@pytest.mark.parametrize(
    "cmd",
    [
        "Start-Process powershell -ArgumentList '-NoProfile -e SGVsbG8='",
        "Start-Process powershell -ArgumentList '-NoProfile','-e','SGVsbG8='",
        "Start-Process powershell -ArgumentList @('-e','SGVsbG8=')",
    ],
)
def test_encoded_filter_bypass_cycle4_blocked(cmd):
    """Bug #16: ogni parola di ogni argomento va controllata (spazi E virgole)."""
    from vault_engine.agent import tools as agent_tools

    assert agent_tools._uses_encoded_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "Get-Process pwsh -ea SilentlyContinue",
        "Stop-Process -Name powershell -ea 0",
    ],
)
def test_encoded_filter_false_positive_cycle4_allowed(cmd):
    """Bug #17: powershell/pwsh come ARGOMENTO non attiva la scansione."""
    from vault_engine.agent import tools as agent_tools

    assert not agent_tools._uses_encoded_command(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        "node -e \"console.log(1)\"",
        "Get-Content f.txt -Enc UTF8",
        "Select-String f.txt -E 'x'",
        "powershell -File script.ps1 -Verbose",
    ],
)
def test_encoded_filter_no_new_false_positives(cmd):
    """La riscrittura a posizione di comando non deve ripresentare i falsi positivi dei cicli 2-3."""
    from vault_engine.agent import tools as agent_tools

    assert not agent_tools._uses_encoded_command(cmd)


# --------------------------------------------- Miglioramento #15 (load/unload/pull)


@pytest.fixture
def transport():
    """Injects an httpx transport at ollama_hub level (set_transport) and always resets it."""
    state: dict = {}

    def install(handler):
        state["transport"] = httpx.MockTransport(handler)
        ollama_hub.set_transport(state["transport"])

    yield install
    ollama_hub.set_transport(None)


def test_load_and_unload_at_transport_level(transport):
    """Miglioramento #15: load/unload verified on method, path and body."""
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"done": True})

    transport(handler)
    asyncio.run(ollama_hub.load(ENDPOINTS, "m", 45))
    asyncio.run(ollama_hub.unload(ENDPOINTS, "m"))
    assert seen[0][1] == "/api/generate" and seen[0][2]["keep_alive"] == "45m"
    assert seen[1][1] == "/api/generate" and seen[1][2]["keep_alive"] == 0


def test_load_falls_back_to_embed_at_transport_level(transport):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.url.path, json.loads(req.content)))
        if req.url.path == "/api/generate":
            return httpx.Response(400, json={"error": '"bge-m3" does not support generate'})
        return httpx.Response(200, json={"embeddings": [[]]})

    transport(handler)
    asyncio.run(ollama_hub.load(ENDPOINTS, "bge-m3", 30))
    assert [c[0] for c in seen] == ["/api/generate", "/api/embed"]
    assert seen[1][1]["keep_alive"] == "30m"


# --------------------------------------------- Miglioramento #16 (DNS rebinding)


def test_fetch_url_pins_connection_to_validated_ip(monkeypatch):
    """fetch_url must connect to the IP validated at check time (no second DNS lookup),
    keeping the original Host header and TLS SNI."""
    from vault_engine.agent import web as web_mod

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="<html><head><title>T</title></head><body>ok</body></html>")

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(web_mod.httpx, "AsyncClient", factory)
    resolutions = []

    def fake_getaddrinfo(host, port, *args, **kwargs):
        resolutions.append(host)
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(web_mod.socket, "getaddrinfo", fake_getaddrinfo)
    result = asyncio.run(web_mod.fetch_url("https://esempio-esterno.example/page"))
    assert result["title"] == "T"
    assert len(resolutions) == 1  # one resolution only, at validation time
    req = requests[0]
    assert req.url.host == "93.184.216.34"  # pinned to the validated IP
    assert req.headers["host"] == "esempio-esterno.example"  # original Host header
    assert req.extensions.get("sni_hostname") == "esempio-esterno.example"  # original SNI


def test_fetch_url_reports_original_url_not_pinned_ip(monkeypatch):
    from vault_engine.agent import web as web_mod

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="testo")

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(web_mod.httpx, "AsyncClient", factory)
    result = asyncio.run(web_mod.fetch_url("http://93.184.216.34/a"))
    assert result["url"] == "http://93.184.216.34/a"
