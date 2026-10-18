"""End-to-end vault sync with deterministic fake embeddings (no LLM server needed)."""

import asyncio
import os
import time
from pathlib import Path

import pytest

from vault_engine.config import ModelRef, SettingsStore
from vault_engine.events import EventBus
from vault_engine.pipeline import JobManager
from vault_engine.vaults import VaultConfig, VaultRegistry

from .conftest import fake_vector


@pytest.fixture
def env(tmp_path, monkeypatch, fake_embeddings):
    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


async def run_job(jobs: JobManager, vault_id: str, kind: str, paths=None):
    job = jobs.submit(vault_id, kind, paths)
    while job.status in ("queued", "running"):
        await asyncio.sleep(0.05)
    return job


def test_full_then_incremental_sync(env, docs: Path, fake_embeddings):
    async def scenario():
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        registry = VaultRegistry()
        jobs = JobManager(registry, SettingsStore(), events)
        vault = registry.create(
            VaultConfig(name="Test", sources=[str(docs)], embedding=ModelRef(provider="lmstudio", model="fake"))
        )

        first = await run_job(jobs, vault.config.id, "sync")
        assert first.status == "done", first.message
        assert first.failed == 0, [f.error for f in vault.files(status="error")]
        indexed = {Path(f.path).name for f in vault.files(status="indexed")}
        assert indexed == {
            "contratto.docx", "budget.xlsx", "roadmap.pptx", "manuale.pdf", "scansione.pdf",
            "foto.png", "note.md", "dati.csv", "config.json", "leggimi.txt",
        }
        assert vault.config.dimension == 64
        record = vault.file(str(docs / "contratto.docx"))
        assert record.author == "Mario Rossi" and len(record.sha256) == 64
        assert vault.file(str(docs / "scansione.pdf")).ocr_pages == 1

        # Nothing changed: nothing re-embedded.
        before = fake_embeddings["texts"]
        second = await run_job(jobs, vault.config.id, "sync")
        assert second.total == 0 and fake_embeddings["texts"] == before

        # Touch without content change: hash matches, skipped.
        txt = docs / "leggimi.txt"
        os.utime(txt, (time.time() + 5, time.time() + 5))
        third = await run_job(jobs, vault.config.id, "sync")
        assert third.skipped == 1 and third.done == 0

        # Edit, add, delete.
        txt.write_text("Contenuto aggiornato: progetto Borealis.", encoding="utf-8")
        (docs / "nuovo.md").write_text("# Nuovo\n\nDocumento aggiunto dopo.", encoding="utf-8")
        (docs / "dati.csv").unlink()
        fourth = await run_job(jobs, vault.config.id, "sync")
        assert (fourth.done, fourth.removed) == (2, 1)
        assert vault.file(str(docs / "dati.csv")) is None
        assert vault.count_chunks("file_name = 'dati.csv'") == 0

        hits = vault.search(fake_vector("progetto Borealis"), 3, "cosine")
        assert hits[0]["file_name"] == "leggimi.txt"
        assert set(hits[0]["scores"]) == {"cosine", "dot", "euclidean"}
        assert not any("Aurora" in h["text"] for h in hits if h["file_name"] == "leggimi.txt")

        projection = vault.projection()
        assert len(projection) == vault.count_chunks()

    asyncio.run(scenario())


def test_dimension_mismatch_is_reported(env, docs, monkeypatch):
    from vault_engine import providers

    async def scenario():
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        registry = VaultRegistry()
        jobs = JobManager(registry, SettingsStore(), events)
        vault = registry.create(VaultConfig(name="Dim", sources=[str(docs)], embedding=ModelRef(provider="lmstudio", model="fake")))
        await run_job(jobs, vault.config.id, "ingest", [str(docs / "note.md")])

        async def other_dim(self, ref, texts):
            return [[0.1] * 32 for _ in texts]

        monkeypatch.setattr(providers.ProviderClient, "embed", other_dim)
        job = await run_job(jobs, vault.config.id, "ingest", [str(docs / "leggimi.txt")])
        assert job.failed == 1
        assert "dimension" in vault.file(str(docs / "leggimi.txt")).error

    asyncio.run(scenario())
