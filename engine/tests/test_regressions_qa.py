"""Regression tests for the issues found in FEEDBACK_QA.md (Bug #1-#6)."""

import asyncio
import threading

import pytest

from vault_engine.agent.tools import _list_directory, _uses_encoded_command
from vault_engine.config import ModelRef


# ---------------------------------------------------------------------- Bug #1


@pytest.mark.parametrize(
    "command",
    [
        "powershell -e SGVsbG8=",
        "powershell -ec SGVsbG8=",
        "powershell -enc SGVsbG8=",
        "powershell -ENCO SGVsbG8=",
        "powershell -encodedCommand SGVsbG8=",
        "Get-ChildItem C:\\; -e SGVsbG8=",
    ],
)
def test_encoded_command_abbreviations_are_rejected(command):
    assert _uses_encoded_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "Get-ChildItem C:\\Users",
        'Write-Host "100% -e di sconto"',
        "git -C repo log --oneline",
        "Get-Content file.txt -Encoding utf8",
        "Remove-Item -Recurse -Force C:\\temp\\old",
    ],
)
def test_ordinary_commands_are_not_flagged(command):
    assert not _uses_encoded_command(command)


# ---------------------------------------------------------------------- Bug #4


def test_list_directory_limits_without_full_scan(tmp_path):
    for i in range(350):
        (tmp_path / f"f{i:03}.txt").write_text("x", encoding="utf-8")
    result = asyncio.run(_list_directory(None, {"path": str(tmp_path)}))
    assert len(result["entries"]) == 300
    assert result["truncated"] is True


def test_list_directory_recursive_pattern_is_bounded(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    for i in range(200):
        (tmp_path / f"root{i:03}.txt").write_text("x", encoding="utf-8")
    for i in range(150):
        (deep / f"deep{i:03}.txt").write_text("x", encoding="utf-8")
    result = asyncio.run(_list_directory(None, {"path": str(tmp_path), "pattern": "**/*.txt"}))
    assert len(result["entries"]) == 300
    assert result["truncated"] is True


# ---------------------------------------------------------------------- Bug #5


def test_files_query_matches_like_wildcards_literally(tmp_path):
    from vault_engine.vaults import FileRecord, Vault, VaultConfig

    vault = Vault(tmp_path / "v", VaultConfig(name="t", embedding=ModelRef(provider="lmstudio", model="x")))
    for name in ("contratto_100%.pdf", "contratto_100x.pdf", "altro.txt"):
        vault.upsert_file(FileRecord(path=name, source=None, sha256=None, size=1, mtime=0.0, status="indexed"))

    assert [f.path for f in vault.files(query="100%")] == ["contratto_100%.pdf"]
    # "_" must not act as a single-character wildcard.
    assert vault.files(query="contratto_100_") == []
    assert len(vault.files(query="contratto_100")) == 2


# ---------------------------------------------------------------------- Bug #3


def test_cors_allows_null_origin_only_with_token(monkeypatch):
    from vault_engine.app import _cors_origin_regex

    monkeypatch.delenv("WSOS_TOKEN", raising=False)
    assert "null" not in _cors_origin_regex()
    assert "file://" not in _cors_origin_regex()

    monkeypatch.setenv("WSOS_TOKEN", "abc")
    assert "null" in _cors_origin_regex()


# ---------------------------------------------------------------------- Bug #2


def test_worker_picks_up_jobs_submitted_while_running(tmp_path, monkeypatch):
    """A job queued while the worker is busy must run (no lost wakeup)."""
    from vault_engine.config import SettingsStore
    from vault_engine.events import EventBus
    from vault_engine.pipeline import JobManager
    from vault_engine.vaults import VaultConfig, VaultRegistry

    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))

    async def scenario():
        registry = VaultRegistry()
        vault = registry.create(VaultConfig(name="t", embedding=ModelRef(provider="lmstudio", model="x")))
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        jobs = JobManager(registry, SettingsStore(path=tmp_path / "settings.json"), events)

        # Hold the first job inside its processing until the second has been submitted:
        # with the old `while not queue.empty()` loop this timing could strand the job.
        inside_first = threading.Event()
        release = threading.Event()

        def slow_walk(v):
            inside_first.set()
            release.wait(5)
            return {}

        monkeypatch.setattr("vault_engine.pipeline.walk_sources", slow_walk)

        first = jobs.submit(vault.config.id, "sync")
        await asyncio.to_thread(inside_first.wait, 5)
        second = jobs.submit(vault.config.id, "remove", [])
        release.set()

        for job in (first, second):
            for _ in range(200):
                if jobs.jobs[job.id].status == "done":
                    break
                await asyncio.sleep(0.01)
            assert jobs.jobs[job.id].status == "done", f"job {job.id} stuck in {job.status}"

        # The worker stays alive after the queue drains and is cancelled only at shutdown.
        assert not jobs._workers[vault.config.id].done()
        await jobs.shutdown()

    asyncio.run(scenario())
