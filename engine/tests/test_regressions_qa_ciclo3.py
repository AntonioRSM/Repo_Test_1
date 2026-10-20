"""Regression tests for FEEDBACK_QA.md ciclo 3 (Bug #8-#15, Miglioramento #7-#12).

The QA probes asserted each defect; these tests assert the fixed behaviour.
"""

import asyncio
import json
import logging
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from vault_engine import ollama_hub, providers
from vault_engine.agent import tools as agent_tools
from vault_engine.agent import web
from vault_engine.config import ModelRef

ENDPOINTS = {"ollama": "http://localhost:11434"}


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


def patch_all_transports(monkeypatch, handler):
    """Patches httpx.AsyncClient globally (the pull route's background task included)."""
    orig = httpx.AsyncClient.__init__

    def init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        orig(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)


# ---------------------------------------------------------------------- Bug #8


def test_ollama_pull_route_reports_progress_and_completes(monkeypatch, tmp_path):
    """/ollama/pull must await an async on_progress: the old sync lambda returned
    publish()'s None and every download died with 'object NoneType can't be used in
    await expression' on the first progress line. End-to-end: start_pull is NOT stubbed."""
    from vault_engine import app as appmod

    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    patch_all_transports(monkeypatch, fake_ollama([], pull_lines=['{"status":"pulling manifest"}', '{"status":"success"}']))
    seen = []
    with TestClient(appmod.app, base_url="http://127.0.0.1") as client:
        monkeypatch.setattr(appmod.state.events, "publish", lambda e: seen.append(e))
        assert client.post("/ollama/pull", json={"model": "bge-m3"}).status_code == 202

        async def wait():
            for _ in range(200):
                if any(e.get("status") in ("errore", "download_completato") for e in seen):
                    return
                await asyncio.sleep(0.02)
            raise AssertionError(f"nessun evento finale: {seen}")

        client.portal.call(wait)
    final = [e for e in seen if e.get("status") in ("errore", "download_completato")]
    assert final and final[-1]["status"] == "download_completato"


# ---------------------------------------------------------------------- Bug #9


def test_background_pull_from_search_reports_error(monkeypatch):
    """409 path (allow_download=False): the background download must publish its
    outcome, or the Models page stays stuck on the last percentage without ✓/Riprova."""
    handler = fake_ollama([], pull_lines=['{"error":"file does not exist"}'])
    mock_httpx(providers, monkeypatch, handler)
    mock_httpx(ollama_hub, monkeypatch, handler)
    seen = []

    class Ev:
        def publish(self, e):
            seen.append(e)

    ref = ModelRef(provider="ollama", model="modello-inesistente")

    async def run():
        with pytest.raises(providers.ProviderError):
            await providers.ensure_loaded({}, [(ref, "embedding")], events=Ev(), allow_download=False)
        for _ in range(100):
            if any(e.get("status") in ("errore", "download_completato") for e in seen):
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"nessun evento finale: {seen}")

    asyncio.run(run())
    errors = [e for e in seen if e.get("status") == "errore"]
    assert errors and "file does not exist" in errors[0]["error"]


def test_background_pull_from_search_reports_completion(monkeypatch):
    handler = fake_ollama([], pull_lines=['{"status":"success"}'])
    mock_httpx(providers, monkeypatch, handler)
    mock_httpx(ollama_hub, monkeypatch, handler)
    seen = []

    class Ev:
        def publish(self, e):
            seen.append(e)

    ref = ModelRef(provider="ollama", model="nuovo-modello")

    async def run():
        with pytest.raises(providers.ProviderError):
            await providers.ensure_loaded({}, [(ref, "llm")], events=Ev(), allow_download=False)
        for _ in range(100):
            if any(e.get("status") == "download_completato" for e in seen):
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"nessun evento finale: {seen}")

    asyncio.run(run())


def test_start_pull_logs_error_when_no_callback(monkeypatch, caplog):
    """A background failure without on_error must hit the log, not vanish."""
    handler = fake_ollama([], pull_lines=['{"error":"boom"}'])
    mock_httpx(ollama_hub, monkeypatch, handler)

    async def run():
        assert ollama_hub.start_pull(ENDPOINTS, "modello-senza-callback") is True
        for _ in range(100):
            if "modello-senza-callback:latest" not in ollama_hub._background_pulls:
                return
            await asyncio.sleep(0.02)
        raise AssertionError("download in background mai concluso")

    with caplog.at_level(logging.ERROR, logger="vault_engine.ollama_hub"):
        asyncio.run(run())
    assert any("boom" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------- Bug #11


@pytest.mark.parametrize(
    "command",
    [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -e SGVsbG8=",  # full path
        r'& "C:\Program Files\PowerShell\7\pwsh.exe" -enc SGVsbG8=',  # &-call, quoted path
        'cmd /c "powershell -e SGVsbG8="',  # nested command inside one quoted token
        "Start-Process powershell -ArgumentList '-e SGVsbG8='",  # switch inside a quoted arg
    ],
)
def test_encoded_filter_bypass_cycle3_blocked(command):
    assert agent_tools._uses_encoded_command(command)


@pytest.mark.parametrize(
    "command",
    [
        # Merely naming the executable is not an invocation with encoded payloads.
        'Test-Path "C:\\Program Files\\PowerShell\\7\\pwsh.exe"',
        "Get-Item C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe | Select-Object Length",
    ],
)
def test_encoded_filter_cycle3_no_new_false_positives(command):
    assert not agent_tools._uses_encoded_command(command)


# ---------------------------------------------------------------------- Bug #12


def test_ssrf_ipv4_mapped_ipv6_blocked():
    """::ffff:a.b.c.d reaches the same local services on dual-stack hosts."""
    for url in (
        "http://[::ffff:127.0.0.1]:11434/api/tags",
        "http://[::ffff:192.168.1.10]/",
        "http://[::ffff:10.1.2.3]/",
    ):
        with pytest.raises(web.WebError):
            asyncio.run(web._validate_url(url))


def test_ssrf_nat64_and_benchmark_ranges_blocked():
    for url in ("http://[64:ff9b::7f00:1]/", "http://198.18.0.1/"):
        with pytest.raises(web.WebError):
            asyncio.run(web._validate_url(url))


def test_ssrf_public_literal_still_allowed():
    # Literal IPs skip DNS resolution: no network access needed by this test.
    asyncio.run(web._validate_url("http://93.184.216.34/"))


# ---------------------------------------------------------------------- Bug #13


def test_scan_star_does_not_walk_subtree(tmp_path, monkeypatch):
    """`*` can only match the top level: a huge subfolder must neither be traversed
    nor mark the listing truncated."""
    monkeypatch.setattr(agent_tools, "SCAN_VISITED_LIMIT", 50)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    deep = tmp_path / "archivio"
    deep.mkdir()
    for i in range(100):
        (deep / f"f{i:03}.txt").write_text("x", encoding="utf-8")
    out = agent_tools._scan_directory(tmp_path, "*")
    assert {e["name"] for e in out["entries"]} == {"a.txt", "archivio"}
    assert out["truncated"] is False  # the requested level IS complete


def test_scan_prunes_only_beyond_pattern_depth(tmp_path, monkeypatch):
    """A two-segment pattern still descends one level and the visit budget applies
    to the entries it can actually reach."""
    monkeypatch.setattr(agent_tools, "SCAN_VISITED_LIMIT", 50)
    deep = tmp_path / "archivio"
    deep.mkdir()
    for i in range(100):
        (deep / f"f{i:03}.txt").write_text("x", encoding="utf-8")
    out = agent_tools._scan_directory(tmp_path, "archivio/*.txt")
    assert len(out["entries"]) > 0
    assert out["truncated"] is True  # budget hit INSIDE the reachable level


# ---------------------------------------------------------------------- Bug #14


def test_scan_matches_case_insensitively_on_windows(tmp_path):
    """Path.glob (used up to ciclo 2) was case-insensitive on Windows: keep it."""
    (tmp_path / "Contratto.PDF").write_text("x", encoding="utf-8")
    out = agent_tools._scan_directory(tmp_path, "*.pdf")
    if os.name == "nt":
        assert [e["name"] for e in out["entries"]] == ["Contratto.PDF"]
    else:
        assert out["entries"] == []


# ---------------------------------------------------------------------- Bug #15


def test_localhost_only_middleware_accepts_ipv6_loopback(monkeypatch):
    """TrustedHostMiddleware split the Host header on ':' and turned '[::1]:8765'
    into '[': every request got a 400. The custom middleware parses brackets."""
    from vault_engine import app as appmod

    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    if not any(m.cls.__name__ == "LocalhostOnlyMiddleware" for m in appmod.app.user_middleware):
        pytest.skip("il middleware è attivo solo senza WSOS_TOKEN")
    client = TestClient(appmod.app, base_url="http://127.0.0.1")
    assert client.get("/health", headers={"Host": "[::1]:8765"}).status_code == 200
    assert client.get("/health", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400
    # Miglioramento #11: the TestClient default host is no longer allowed; tests
    # configure base_url="http://127.0.0.1" instead.
    assert client.get("/health", headers={"Host": "testserver"}).status_code == 400
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------- Miglioramento #7


def test_unchanged_sync_does_not_rehash(tmp_path, monkeypatch, fake_embeddings):
    """A sync with no changes must not re-read/re-hash the archive nor rewrite the
    manifest. Full content verification happens on an explicit rebuild."""
    from vault_engine import pipeline
    from vault_engine.config import SettingsStore
    from vault_engine.events import EventBus
    from vault_engine.vaults import VaultConfig, VaultRegistry

    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    src = tmp_path / "src"
    src.mkdir()
    for i in range(40):
        (src / f"nota{i}.txt").write_text(f"contenuto {i}", encoding="utf-8")
    calls = []
    orig = pipeline.sha256_file
    monkeypatch.setattr(pipeline, "sha256_file", lambda p: calls.append(p) or orig(p))

    async def scenario():
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        registry = VaultRegistry()
        jobs = pipeline.JobManager(registry, SettingsStore(path=tmp_path / "settings.json"), events)
        vault = registry.create(VaultConfig(name="T", sources=[str(src)], embedding=ModelRef(provider="lmstudio", model="fake")))

        async def run():
            job = jobs.submit(vault.config.id, "sync")
            while job.status in ("queued", "running"):
                await asyncio.sleep(0.05)
            assert job.status == "done", job.message
            return job

        first = await run()
        assert first.total == 40
        calls.clear()
        second = await run()
        await jobs.shutdown()
        return second

    second = asyncio.run(scenario())
    assert second.total == 0
    assert calls == []  # no file re-hashed (was 40 SHA-256 computations)


# ---------------------------------------------------------------------- Miglioramento #9


def test_pull_dedup_normalizes_keys_and_releases_lock(monkeypatch):
    """llama3 and llama3:latest are the same model: one lock, one download — and the
    lock registry must not grow without bound."""
    installed = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal installed
        if request.url.path == "/api/tags":
            models = [{"name": "llama3:latest", "size": 1}] if installed else []
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/pull":
            installed = True
            return httpx.Response(200, content=json.dumps({"status": "success"}))
        return httpx.Response(200, json={"models": []})

    mock_httpx(ollama_hub, monkeypatch, handler)
    pulls = []
    original = ollama_hub.pull

    async def counting_pull(endpoints, model, on_progress=None):
        pulls.append(model)
        await original(endpoints, model, on_progress)

    monkeypatch.setattr(ollama_hub, "pull", counting_pull)

    async def scenario():
        await asyncio.gather(
            ollama_hub.pull_dedup(ENDPOINTS, "llama3"),
            ollama_hub.pull_dedup(ENDPOINTS, "llama3:latest"),
        )

    asyncio.run(scenario())
    assert len(pulls) == 1  # the second spelling joined the first download
    assert "llama3:latest" not in ollama_hub._pull_locks  # lock released once unused


def test_start_pull_joins_normalized_duplicate(monkeypatch):
    started = []

    async def fake_pull_dedup(endpoints, model, on_progress=None):
        started.append(model)
        await asyncio.sleep(0.2)

    monkeypatch.setattr(ollama_hub, "pull_dedup", fake_pull_dedup)

    async def scenario():
        assert ollama_hub.start_pull(ENDPOINTS, "llama3") is True
        await asyncio.sleep(0)
        assert ollama_hub.start_pull(ENDPOINTS, "llama3:latest") is False  # same model
        await asyncio.sleep(0.3)

    asyncio.run(scenario())
    assert started == ["llama3"]


# ---------------------------------------------------------------------- Miglioramento #10


def test_ensure_loaded_uses_single_tags_call(monkeypatch):
    """The online check and the installed-model lookup share ONE /api/tags fetch per
    ensure_loaded call (status()+is_installed() used to cost 4 requests per model)."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "bge-m3:latest", "size": 1}]})
        return httpx.Response(200, json={})

    mock_httpx(providers, monkeypatch, handler)
    mock_httpx(ollama_hub, monkeypatch, handler)
    ref = ModelRef(provider="ollama", model="bge-m3")
    asyncio.run(providers.ensure_loaded({}, [(ref, "embedding")]))
    assert calls.count("/api/tags") == 1
    assert "/api/ps" not in calls
    assert "/api/pull" not in calls  # already installed


# ---------------------------------------------------------------------- Miglioramento #12


def test_pull_emits_phase_changes_despite_throttle(monkeypatch):
    """Throttling is time-based, but a phase change (verifying sha256 digest, writing
    manifest…) must be delivered immediately, or it may never appear in the UI."""
    lines = [json.dumps({"status": "pulling abc", "completed": i, "total": 10_000}) for i in range(200)]
    lines.append(json.dumps({"status": "verifying sha256 digest"}))
    lines.extend(json.dumps({"status": "pulling abc", "completed": 200 + i, "total": 10_000}) for i in range(200))
    lines.append(json.dumps({"status": "writing manifest"}))
    lines.append(json.dumps({"status": "success"}))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="\n".join(lines))

    mock_httpx(ollama_hub, monkeypatch, handler)
    seen = []

    async def on_progress(p: dict) -> None:
        seen.append(p)

    asyncio.run(ollama_hub.pull(ENDPOINTS, "m", on_progress))
    statuses = [e["status"] for e in seen]
    assert "verifying sha256 digest" in statuses
    assert "writing manifest" in statuses
    assert statuses[-1] == "success"
    assert len(seen) < 50  # still throttled: no flood between phase changes
