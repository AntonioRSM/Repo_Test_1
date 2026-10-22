"""Coverage tests for modules that had none (web, watcher, events, hardware, __main__)
plus regressions for the improvements in FEEDBACK_QA.md (Miglioramento #1-#8)."""

import asyncio
import json

import httpx
import pytest

from vault_engine import events as events_mod
from vault_engine.agent import web as web_mod
from vault_engine.agent.runner import _fit_result
from vault_engine.config import ModelRef


def mock_http(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(web_mod.httpx, "AsyncClient", factory)


# ---------------------------------------------------------------------- events.py


def test_events_deliver_to_subscriber_in_same_loop():
    bus = events_mod.EventBus()

    async def scenario():
        bus.bind(asyncio.get_running_loop())
        queue = bus.subscribe()
        bus.publish({"type": "x", "n": 1})
        payload = await asyncio.wait_for(queue.get(), timeout=1)
        assert json.loads(payload) == {"type": "x", "n": 1}
        bus.unsubscribe(queue)
        bus.publish({"type": "y"})
        assert queue.empty()

    asyncio.run(scenario())


def test_events_publish_without_bound_loop_is_safe_noop():
    bus = events_mod.EventBus()  # no bind(): nothing must explode
    bus.publish({"type": "x"})


def test_events_drop_for_slow_client():
    bus = events_mod.EventBus()

    async def scenario():
        bus.bind(asyncio.get_running_loop())
        queue = bus.subscribe()
        for i in range(1001):
            bus.publish({"i": i})
        # The 1002nd event exceeds the 1000-queue cap and is dropped for this client.
        bus.publish({"i": 1001})
        assert queue.qsize() == 1001
        first = json.loads(await queue.get())
        last = None
        while not queue.empty():
            last = json.loads(await queue.get())
        assert first == {"i": 0}
        assert last == {"i": 1000}  # 1001 was dropped

    asyncio.run(scenario())


# ---------------------------------------------------------------------- web.py


def test_html_to_text_extracts_title_and_body():
    html = "<html><head><title>  Ciao &amp; mondo </title></head><body><script>var x=1;</script><p>Testo   importante</p></body></html>"
    title, text = web_mod.html_to_text(html)
    assert title == "Ciao & mondo"
    assert "var x" not in text
    assert "Testo importante" in text


def test_fetch_url_rejects_non_http():
    with pytest.raises(web_mod.WebError, match="http"):
        asyncio.run(web_mod.fetch_url("file:///etc/passwd"))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://192.168.1.10/router",
        "http://10.0.0.5/x",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata
        "http://[::1]/x",
        "http://172.16.0.1/x",
        "http://100.64.0.1/x",
    ],
)
def test_fetch_url_blocks_private_and_loopback_destinations(url):
    # Literal IPs: the guard must reject them before any DNS or connection.
    with pytest.raises(web_mod.WebError, match="non consentita"):
        asyncio.run(web_mod.fetch_url(url))


def test_fetch_url_blocks_redirect_to_private_ip(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="segreto")

    mock_http(monkeypatch, handler)
    with pytest.raises(web_mod.WebError, match="non consentita"):
        asyncio.run(web_mod.fetch_url("http://93.184.216.34/start"))


def test_fetch_url_blocks_unresolvable_host(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="x")

    mock_http(monkeypatch, handler)

    async def scenario():
        real_getaddrinfo = web_mod.socket.getaddrinfo

        def failing(*args, **kwargs):
            raise web_mod.socket.gaierror("no such host")

        web_mod.socket.getaddrinfo = failing
        try:
            with pytest.raises(web_mod.WebError, match="non risolvibile"):
                await web_mod.fetch_url("http://esempio-inesistente-xyz.example/start")
        finally:
            web_mod.socket.getaddrinfo = real_getaddrinfo

    asyncio.run(scenario())


def test_fetch_url_follows_safe_redirect_and_reads_html(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        if request.url.path == "/b":
            return httpx.Response(200, text="<html><head><title>T</title></head><body><p>corpo</p></body></html>")
        return httpx.Response(404)

    mock_http(monkeypatch, handler)
    # 93.184.216.34 is a globally routable literal: with Bug #12 the guard also blocks
    # documentation ranges via is_private, so TEST-NET-3 (203.0.113.0/24) no longer
    # works as a stand-in for a public host.
    result = asyncio.run(web_mod.fetch_url("http://93.184.216.34/a"))
    assert result["url"].endswith("/b")
    assert result["title"] == "T"
    assert "corpo" in result["text"]


def test_fetch_url_gives_up_after_redirect_loop(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/loop"})

    mock_http(monkeypatch, handler)
    with pytest.raises(web_mod.WebError, match="redirect"):
        asyncio.run(web_mod.fetch_url("http://93.184.216.34/loop"))


# ---------------------------------------------------------------------- watcher.py


class _FakeJobs:
    def __init__(self):
        self.submitted = []

    def submit(self, vault_id, kind, paths=None):
        self.submitted.append((vault_id, kind, paths))


class _FakeLoop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, fn):
        self.calls.append(fn)
        fn()


def _make_watcher(tmp_path, monkeypatch):
    from vault_engine.vaults import VaultConfig, VaultRegistry
    from vault_engine.watcher import VaultWatcher

    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    registry = VaultRegistry()
    vault = registry.create(VaultConfig(name="t", embedding=ModelRef(provider="lmstudio", model="x")))
    return VaultWatcher(registry, _FakeJobs(), _FakeLoop()), vault


def test_watcher_touch_ignores_unaccepted_files_and_dirs(tmp_path, monkeypatch):
    watcher, vault = _make_watcher(tmp_path, monkeypatch)
    src = tmp_path / "src"
    src.mkdir()
    vault.config.sources = [str(src)]
    (src / "doc.exe").write_text("x", encoding="utf-8")
    (src / "doc.txt").write_text("x", encoding="utf-8")

    watcher.touch(vault.config.id, str(src / "doc.exe"))  # extension not indexed
    watcher.touch(vault.config.id, str(src))  # a directory
    assert watcher._pending == {}

    watcher.touch(vault.config.id, str(src / "doc.txt"))
    assert watcher._pending[vault.config.id] == {str(src / "doc.txt")}


def test_watcher_flush_splits_existing_and_missing(tmp_path, monkeypatch):
    watcher, vault = _make_watcher(tmp_path, monkeypatch)
    src = tmp_path / "src"
    src.mkdir()
    vault.config.sources = [str(src)]
    existing = src / "a.txt"
    existing.write_text("x", encoding="utf-8")
    missing = src / "gone.txt"

    watcher.touch(vault.config.id, str(existing))
    watcher.touch(vault.config.id, str(missing))
    watcher._flush(vault.config.id)

    jobs = watcher.jobs.submitted
    assert (vault.config.id, "remove", [str(missing)]) in jobs
    assert (vault.config.id, "ingest", [str(existing)]) in jobs
    assert watcher._pending == {} and watcher._timers == {}


def test_watcher_touch_unknown_vault_is_ignored(tmp_path, monkeypatch):
    watcher, _vault = _make_watcher(tmp_path, monkeypatch)
    watcher.touch("no-such-vault", str(tmp_path / "x.txt"))
    assert watcher._pending == {}


# ---------------------------------------------------------------------- hardware.py


def test_luid_parsing():
    assert web_mod is not None  # keep imports used
    from vault_engine.hardware import _luid

    instance = "pid_123_luid_0x0_0x1234_phys_0_eng_0_engtype_3D"
    assert _luid(instance) == "0x0_0x1234"
    assert _luid("something_without_luid") == "something_without_luid"


def test_hardware_latest_returns_sample_before_start():
    from vault_engine.hardware import HardwareMonitor, HardwareSample

    monitor = HardwareMonitor(interval=60)
    sample = monitor.latest()
    assert isinstance(sample, HardwareSample)
    assert sample.ram_total_mb > 0
    assert sample.cpu_count >= 1
    # never started: no background thread was spun up
    assert not monitor._thread.is_alive()


# ---------------------------------------------------------------------- __main__.py


def test_main_announces_bound_port_from_uvicorn_socket(monkeypatch, capsys):
    import uvicorn
    import vault_engine.__main__ as main_mod

    captured = {}

    class FakeSocket:
        def getsockname(self):
            return ("127.0.0.1", 43210)

    class FakeHTTPServer:
        sockets = [FakeSocket()]

    class FakeServer:
        def __init__(self, config):
            captured["server"] = self
            self.started = False
            self.servers = []

        async def serve(self):
            self.started = True
            self.servers = [FakeHTTPServer()]
            await asyncio.sleep(60)

    class FakeConfig:
        def __init__(self, *args, **kwargs):
            captured["config_kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.setattr(main_mod, "exit_with_parent", lambda: None)
    monkeypatch.setattr(
        "sys.argv", ["vault_engine", "--port", "0", "--host", "127.0.0.1", "--log-level", "warning"]
    )

    async def scenario():
        task = asyncio.create_task(main_mod._serve(main_mod.argparse.Namespace(host="127.0.0.1", port=0, log_level="warning")))
        announced = False
        for _ in range(200):
            # readouterr() clears the buffer: keep the result instead of re-reading at the end.
            if "VAULT_ENGINE_PORT=43210" in capsys.readouterr().out:
                announced = True
                break
            await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return announced

    assert asyncio.run(scenario())
    assert captured["config_kwargs"]["port"] == 0  # single bind delegated to uvicorn
    assert captured["config_kwargs"]["host"] == "127.0.0.1"


def test_main_warns_when_binding_outside_loopback(monkeypatch, caplog):
    import vault_engine.__main__ as main_mod

    monkeypatch.setattr(main_mod, "exit_with_parent", lambda: None)

    def fake_run(coro, *a, **k):
        coro.close()  # avoid 'never awaited' warnings

    monkeypatch.setattr(main_mod.asyncio, "run", fake_run)
    monkeypatch.setattr("sys.argv", ["vault_engine", "--host", "0.0.0.0"])
    with caplog.at_level("WARNING"):
        main_mod.main()
    assert any("0.0.0.0" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------- Miglioramento #1 (vaults.matching_paths)


def test_matching_paths_exact_prefix_and_like_escaping(tmp_path):
    from vault_engine.vaults import FileRecord, Vault, VaultConfig

    vault = Vault(tmp_path / "v", VaultConfig(name="t", embedding=ModelRef(provider="lmstudio", model="x")))
    sep = __import__("os").sep
    paths = [
        f"C:{sep}docs{sep}a.txt",
        f"C:{sep}docs{sep}sub{sep}b.txt",
        f"C:{sep}docs2{sep}c.txt",
        f"C:{sep}docs{sep}100%{sep}d.txt",
    ]
    for p in paths:
        vault.upsert_file(FileRecord(path=p, source=None, sha256=None, size=1, mtime=0.0, status="indexed"))

    root = f"C:{sep}docs"
    result = vault.matching_paths(root)
    assert f"C:{sep}docs{sep}a.txt" in result
    assert f"C:{sep}docs{sep}sub{sep}b.txt" in result
    assert f"C:{sep}docs2{sep}c.txt" not in result  # sibling must not match
    # A folder name containing a LIKE wildcard must still match literally:
    assert f"C:{sep}docs{sep}100%{sep}d.txt" in result
    # Exact file match, and nothing else.
    assert vault.matching_paths(f"C:{sep}docs{sep}a.txt") == [f"C:{sep}docs{sep}a.txt"]
    assert vault.matching_paths(f"C:{sep}nope") == []


# ---------------------------------------------------------------------- Miglioramento #2 (runner._fit_result)


def test_fit_result_keeps_json_valid_and_within_budget():
    big = {"rows": [{"text": "x" * 500, "n": i} for i in range(50)], "note": "y" * 300}
    fitted = _fit_result(big, 2000)
    text = json.dumps(fitted, ensure_ascii=False)
    assert len(text) <= 2000
    assert json.loads(text)  # still parseable


def test_fit_result_leaves_small_payload_untouched():
    small = {"a": [1, 2, 3], "b": "short"}
    assert _fit_result(small, 8000) == small


def test_fit_result_truncates_long_string():
    fitted = _fit_result("z" * 10000, 100)
    assert len(fitted) <= 100
    assert fitted.endswith("…[troncato]")


# ---------------------------------------------------------------------- Miglioramento #4 (token handling)


def test_query_token_rejected_on_regular_routes(monkeypatch):
    from fastapi import HTTPException
    from vault_engine.app import require_token

    monkeypatch.setenv("WSOS_TOKEN", "segreto")
    request = _FakeRequest(headers={}, query={"token": "segreto"})
    with pytest.raises(HTTPException) as exc_info:
        require_token(request)
    assert exc_info.value.status_code == 401
    # header token still works
    require_token(_FakeRequest(headers={"x-wsos-token": "segreto"}, query={}))


def test_query_token_accepted_only_on_events_route(monkeypatch):
    from vault_engine.app import require_token_events

    monkeypatch.setenv("WSOS_TOKEN", "segreto")
    monkeypatch.setattr("vault_engine.app._query_token_warned", False)
    require_token_events(_FakeRequest(headers={}, query={"token": "segreto"}))  # must not raise
    with pytest.raises(Exception):
        require_token_events(_FakeRequest(headers={}, query={"token": "sbagliato"}))


class _FakeRequest:
    def __init__(self, headers, query):
        self.headers = headers
        self.query_params = query


# ---------------------------------------------------------------------- change detection (sync vs rebuild)


def test_rebuild_catches_files_with_preserved_timestamps(tmp_path, monkeypatch):
    """A file whose content changed but size+mtime were preserved (robocopy /COPY:T,
    zip extraction) is caught by an explicit REBUILD (full content check). A routine
    sync trusts size+mtime instead (Miglioramento #7, ciclo 3): re-hashing the whole
    archive at every app start is what that improvement removed."""
    from vault_engine.config import SettingsStore
    from vault_engine.events import EventBus
    from vault_engine.parsers import Block, ParsedDocument
    from vault_engine.pipeline import JobManager, sha256_file
    from vault_engine.vaults import FileRecord, VaultConfig, VaultRegistry

    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    src = tmp_path / "src"
    src.mkdir()

    registry = VaultRegistry()
    vault = registry.create(VaultConfig(name="t", embedding=ModelRef(provider="lmstudio", model="x")))
    vault.config.sources = [str(src)]
    vault.save_config()

    changed = src / "changed.txt"
    changed.write_text("AAAA", encoding="utf-8")
    stable = src / "stable.txt"
    stable.write_text("BBBB", encoding="utf-8")

    # Record both files as indexed with their CURRENT hash/stat...
    for path in (changed, stable):
        stat = path.stat()
        vault.upsert_file(
            FileRecord(
                path=str(path), source=str(src), sha256=sha256_file(path),
                size=stat.st_size, mtime=stat.st_mtime, status="indexed", chunks=1,
            )
        )
    # ...then alter `changed.txt` WITHOUT touching size or mtime.
    changed.write_text("ZZZZ", encoding="utf-8")
    stat = changed.stat()
    import os

    os.utime(changed, (stat.st_atime, vault.file(str(changed)).mtime))

    fake_doc = ParsedDocument(blocks=[Block(text="testo finto")])

    async def run_job(jobs, vault_id, kind):
        job = jobs.submit(vault_id, kind)
        for _ in range(500):
            if jobs.jobs[job.id].status in ("done", "failed"):
                break
            await asyncio.sleep(0.01)
        finished = jobs.jobs[job.id]
        assert finished.status == "done", finished.message
        return finished

    async def scenario():
        monkeypatch.setattr("vault_engine.pipeline.parse_file", lambda *a, **k: fake_doc)
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        jobs = JobManager(registry, SettingsStore(path=tmp_path / "settings.json"), events)

        # Routine sync: nothing to re-read, the tampered file included.
        sync = await run_job(jobs, vault.config.id, "sync")
        assert sync.total == 0
        # Explicit rebuild: every file is re-processed, tampering included.
        rebuild = await run_job(jobs, vault.config.id, "rebuild")
        assert rebuild.total == 2
        await jobs.shutdown()

    asyncio.run(scenario())
