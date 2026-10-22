"""Test di regressione della segnalazione del 21/10/2026 (Bug #32, Bug #33, Mgl #23).

Bug #32: il riassunto contestuale inviava 12.000 caratteri (~4.200 token) a un modello
Ollama con contesto predefinito di 4.096 token, e /v1/chat/completions non accetta
num_ctx. Ora per Ollama il riassunto passa dall'API nativa /api/chat con
options.num_ctx=8192 e, se il contesto resta troppo piccolo, riprova con metà testo.

Bug #33: un errore del riassunto (arricchimento facoltativo) mandava in `error` l'intero
documento cancellandone i chunk. Ora il documento viene indicizzato senza riassunto, con
un avviso nelle note.

Miglioramento #23: _ollama_status riporta il contesto effettivo del modello
(/api/ps → num_ctx del Modelfile → OLLAMA_CONTEXT_LENGTH → 4.096), così l'interfaccia
può avvisare sotto gli 8.192 token.
"""

import asyncio

import httpx
import pytest

from vault_engine import pipeline, providers
from vault_engine.config import ModelRef, SettingsStore
from vault_engine.events import EventBus
from vault_engine.providers import ProviderError
from vault_engine.vaults import VaultConfig, VaultRegistry


def _run_sync_with_chat(tmp_path, monkeypatch, fake_embeddings, chat, reps=50):
    """Vault con riassunto contestuale attivo e un LLM finto (chat iniettata)."""
    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    src = tmp_path / "src"
    src.mkdir()
    (src / "contratto.txt").write_text("Contratto di trust Wallace, emendamenti 1988. " * reps)
    monkeypatch.setattr(pipeline.ProviderClient, "chat", chat)

    async def scenario():
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        settings = SettingsStore()
        settings.update({"llm": {"provider": "ollama", "model": "qwen3:4b-instruct"}})
        registry = VaultRegistry()
        jobs = pipeline.JobManager(registry, settings, events)
        vault = registry.create(
            VaultConfig(
                name="T",
                sources=[str(src)],
                embedding=ModelRef(provider="lmstudio", model="fake"),
                contextual_summary=True,
            )
        )
        job = jobs.submit(vault.config.id, "sync")
        while job.status in ("queued", "running"):
            await asyncio.sleep(0.05)
        await jobs.shutdown()
        return vault, job

    return asyncio.run(scenario()), str(src / "contratto.txt")


def test_summary_failure_keeps_document_indexed(tmp_path, monkeypatch, fake_embeddings):
    """Bug #33 (sonda invertita): con chat che fallisce il documento resta indicizzato."""

    async def too_long(self, *a, **k):
        raise ProviderError("chat qwen3:4b-instruct: HTTP 400: request (4236 tokens) exceeds the available context size (4096 tokens)")

    (vault, job), key = _run_sync_with_chat(tmp_path, monkeypatch, fake_embeddings, too_long)
    rec = vault.file(key)
    assert job.status == "done"
    assert rec.status == "indexed"
    assert "indicizzato senza riassunto contestuale" in (rec.error or "")
    assert vault.count_chunks() > 0  # il documento resta ricercabile


def test_summary_retries_with_half_input_on_context_error(tmp_path, monkeypatch, fake_embeddings):
    """Bug #32: all'errore di contesto si riprova UNA volta con metà del testo."""
    calls = []

    async def flaky(self, ref, messages, **kwargs):
        calls.append(messages[0]["content"])
        if len(calls) == 1:
            raise ProviderError("HTTP 400: request (4236 tokens) exceeds the available context size (4096 tokens)")
        return "sintesi del documento"

    (vault, job), key = _run_sync_with_chat(tmp_path, monkeypatch, fake_embeddings, flaky, reps=400)
    rec = vault.file(key)
    assert job.status == "done" and rec.status == "indexed"
    assert rec.error is None  # retry riuscito: nessun avviso
    assert len(calls) == 2
    # documento più lungo di 12.000 caratteri: il primo tentativo è troncato a 12.000,
    # il secondo a metà (6.000 caratteri di testo)
    assert len(calls[0]) == len(pipeline.SUMMARY_PROMPT) + pipeline.SUMMARY_INPUT_CHARS
    assert len(calls[1]) == len(pipeline.SUMMARY_PROMPT) + pipeline.SUMMARY_INPUT_CHARS // 2


def test_summary_real_error_still_raises(tmp_path, monkeypatch, fake_embeddings):
    """Bug #32: un errore che NON è di contesto non scatena il retry, ma il documento
    resta comunque indicizzato (Bug #33)."""
    calls = []

    async def offline(self, *a, **k):
        calls.append(1)
        raise ProviderError("chat qwen3:4b-instruct: connection refused")

    (vault, job), key = _run_sync_with_chat(tmp_path, monkeypatch, fake_embeddings, offline)
    rec = vault.file(key)
    assert len(calls) == 1  # nessun retry su errori non di contesto
    assert rec.status == "indexed" and "indicizzato senza riassunto contestuale" in (rec.error or "")


# ------------------------------------------------------------- Bug #32: API nativa Ollama


def test_ollama_chat_with_num_ctx_uses_native_api(monkeypatch):
    """Bug #32: con num_ctx e provider Ollama la chat passa da /api/chat con options.num_ctx."""
    seen = {}

    async def fake_post(client, url, payload, what):
        seen["url"] = url
        seen["payload"] = payload
        return {"message": {"role": "assistant", "content": "sintesi"}, "done": True, "done_reason": "stop"}

    monkeypatch.setattr(providers, "post_json", fake_post)
    client = providers.ProviderClient({})
    out = asyncio.run(
        client.chat(ModelRef(provider="ollama", model="qwen3:4b-instruct"), [{"role": "user", "content": "testo"}], max_tokens=300, num_ctx=8192)
    )
    assert out == "sintesi"
    assert seen["url"].endswith("/api/chat")
    assert seen["payload"]["options"]["num_ctx"] == 8192
    assert seen["payload"]["options"]["num_predict"] == 300
    assert seen["payload"]["think"] is False
    assert seen["payload"]["stream"] is False


def test_ollama_chat_without_num_ctx_stays_on_openai_api(monkeypatch):
    """Nessuna regressione: senza num_ctx resta la /v1/chat/completions."""
    seen = {}

    async def fake_post(client, url, payload, what):
        seen["url"] = url
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(providers, "post_json", fake_post)
    client = providers.ProviderClient({})
    out = asyncio.run(client.chat(ModelRef(provider="ollama", model="qwen3:4b-instruct"), [{"role": "user", "content": "ciao"}]))
    assert out == "ok"
    assert seen["url"].endswith("/v1/chat/completions")


def test_lmstudio_chat_ignores_num_ctx(monkeypatch):
    """Per LM Studio il contesto si fissa al caricamento: niente /api/chat di Ollama."""
    seen = {}

    async def fake_post(client, url, payload, what):
        seen["url"] = url
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(providers, "post_json", fake_post)
    client = providers.ProviderClient({})
    out = asyncio.run(client.chat(ModelRef(provider="lmstudio", model="m"), [{"role": "user", "content": "ciao"}], num_ctx=8192))
    assert out == "ok"
    assert seen["url"].endswith("/v1/chat/completions")


# ----------------------------------------------- Miglioramento #23: contesto effettivo Ollama


def _ollama_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:11434")


def test_ollama_status_reports_effective_context(monkeypatch):
    """Mgl #23: context_length = /api/ps (se caricato) → num_ctx del Modelfile →
    OLLAMA_CONTEXT_LENGTH → 4.096."""
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    monkeypatch.setattr(providers, "_ollama_server_ctx", lambda: None)

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:4b-instruct", "size": 1}, {"name": "workspace-agent:latest", "size": 1}, {"name": "loaded:latest", "size": 1}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.12.0"})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "loaded:latest", "context_length": 32768}]})
        if request.url.path == "/api/show":
            model = request.read() and __import__("json").loads(request.read())["model"]
            params = "PARAMETER num_ctx 16384" if model == "workspace-agent:latest" else ""
            return httpx.Response(200, json={"capabilities": ["completion"], "parameters": params})
        return httpx.Response(404)

    async def scenario():
        async with _ollama_client(handler) as client:
            return await providers._ollama_status(client, "http://127.0.0.1:11434")

    status = asyncio.run(scenario())
    ctx = {m.id: m.context_length for m in status.models}
    assert ctx["loaded:latest"] == 32768  # contesto reale da /api/ps
    assert ctx["workspace-agent:latest"] == 16384  # num_ctx del Modelfile
    assert ctx["qwen3:4b-instruct"] == 4096  # predefinito di Ollama: l'avviso UI scatterà


def test_ollama_status_uses_server_env_context(monkeypatch):
    """Mgl #23: senza num_ctx nel Modelfile vale OLLAMA_CONTEXT_LENGTH (Bug #27)."""
    monkeypatch.setattr(providers, "_ollama_server_ctx", lambda: 8192)

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:4b-instruct", "size": 1}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.12.0"})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"], "parameters": ""})
        return httpx.Response(404)

    async def scenario():
        async with _ollama_client(handler) as client:
            return await providers._ollama_status(client, "http://127.0.0.1:11434")

    status = asyncio.run(scenario())
    assert status.models[0].context_length == 8192
