"""Ingestion jobs: incremental sync, per-file processing and progress events."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .chunking import chunk_document, detect_language
from .config import SettingsStore
from .events import EventBus
from .ocr import build_engine
from .parsers import ParsedDocument, parse_file
from .providers import ProviderClient, ensure_loaded
from .vaults import FileRecord, Vault, VaultRegistry, quote_sql

log = logging.getLogger(__name__)

JobKind = Literal["sync", "ingest", "remove", "rebuild"]
JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]

SUMMARY_PROMPT = (
    "Summarise this document in at most three sentences, in the document's own language. "
    "Name its type, subject, parties, dates and key figures so that any excerpt can be "
    "understood in context. Output only the summary.\n\n"
)
SUMMARY_INPUT_CHARS = 12000
# Files parsed before their embeddings are computed; bounds memory held by parsed text.
WAVE_SIZE = 24


class Job(BaseModel):
    id: str
    vault_id: str
    kind: JobKind
    status: JobStatus = "queued"
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    removed: int = 0
    current: str | None = None
    message: str | None = None
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def walk_sources(vault: Vault) -> dict[str, tuple[str, os.stat_result]]:
    """path -> (source root, stat) for every accepted file under the vault's sources."""
    found: dict[str, tuple[str, os.stat_result]] = {}
    for source in vault.config.sources:
        root = Path(source)
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune excluded directories in place.
            dirnames[:] = [d for d in dirnames if not _excluded(vault, d)]
            for name in filenames:
                path = Path(dirpath) / name
                if not vault.config.accepts(path):
                    continue
                try:
                    found[str(path)] = (source, path.stat())
                except OSError:
                    continue
    return found


def _excluded(vault: Vault, dirname: str) -> bool:
    import fnmatch  # noqa: PLC0415

    return any(fnmatch.fnmatch(dirname, pattern) for pattern in vault.config.exclude_patterns)


class JobManager:
    """One worker per vault processes queued jobs in order; files inside a job run concurrently."""

    def __init__(self, registry: VaultRegistry, settings: SettingsStore, events: EventBus) -> None:
        self.registry = registry
        self.settings = settings
        self.events = events
        self.jobs: dict[str, Job] = {}
        self._queues: dict[str, asyncio.Queue[tuple[Job, list[str]]]] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._cancel: set[str] = set()

    # ------------------------------------------------------------------ API

    def submit(self, vault_id: str, kind: JobKind, paths: list[str] | None = None) -> Job:
        self.registry.get(vault_id)
        job = Job(id=uuid.uuid4().hex[:12], vault_id=vault_id, kind=kind, created_at=time.time())
        self.jobs[job.id] = job
        queue = self._queues.setdefault(vault_id, asyncio.Queue())
        queue.put_nowait((job, paths or []))
        if vault_id not in self._workers or self._workers[vault_id].done():
            self._workers[vault_id] = asyncio.create_task(self._worker(vault_id), name=f"vault-{vault_id}")
        self._publish(job)
        return job

    def cancel(self, job_id: str) -> None:
        self._cancel.add(job_id)

    def list(self, vault_id: str | None = None) -> list[Job]:
        jobs = [j for j in self.jobs.values() if vault_id is None or j.vault_id == vault_id]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:100]

    def busy(self, vault_id: str) -> bool:
        return any(j.vault_id == vault_id and j.status in ("queued", "running") for j in self.jobs.values())

    async def shutdown(self) -> None:
        for task in self._workers.values():
            task.cancel()

    # ------------------------------------------------------------------ worker

    async def _worker(self, vault_id: str) -> None:
        queue = self._queues[vault_id]
        # Loop on queue.get(): checking queue.empty() before get() is racy — a job submitted
        # in the window between the check and the task ending would wait for another submit.
        # The task lives until shutdown() cancels it; a crashed task is replaced by submit().
        while True:
            job, paths = await queue.get()
            if job.id in self._cancel:
                job.status = "cancelled"
                self._publish(job)
                continue
            job.status, job.started_at = "running", time.time()
            self._publish(job)
            try:
                vault = self.registry.get(vault_id)
                if job.kind != "remove":
                    settings = self.settings.get()
                    await ensure_loaded(
                        settings.endpoints,
                        self._models_for(vault),
                        events=self.events,
                        auto_pull=settings.ollama_auto_pull,
                        keep_alive_minutes=settings.ollama_keep_alive_minutes,
                    )
                if job.kind == "rebuild":
                    vault.reset_vectors()
                    await self._sync(job, vault, force=True)
                elif job.kind == "sync":
                    await self._sync(job, vault, force=False)
                elif job.kind == "ingest":
                    await self._ingest_paths(job, vault, paths)
                elif job.kind == "remove":
                    for path in paths:
                        self._remove(job, vault, path)
                job.status = "cancelled" if job.id in self._cancel else "done"
            except KeyError:
                job.status, job.message = "failed", "vault no longer exists"
            except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
                log.exception("job %s failed", job.id)
                job.status, job.message = "failed", str(exc)
            job.current, job.finished_at = None, time.time()
            self._publish(job)

    async def _sync(self, job: Job, vault: Vault, force: bool) -> None:
        found = await asyncio.to_thread(walk_sources, vault)
        known = vault.known_paths()
        for path in set(known) - set(found):
            self._remove(job, vault, path)
        # Miglioramento #7: size+mtime is the routine change check. Hash-verifying every
        # file on every sync re-read whole archives (a 100 GB NAS share at each app
        # start); the full content check runs on an explicit `rebuild` instead. Files
        # whose mtime changed fall into `todo` and are hash-checked one by one in
        # prepare_file, so a mere touch stays cheap.
        todo = []
        for path, (_source, stat) in found.items():
            record = known.get(path)
            unchanged = (
                record is not None
                and record.status in ("indexed", "skipped")
                and record.size == stat.st_size
                and abs(record.mtime - stat.st_mtime) < 1e-3
            )
            if force or not unchanged:
                todo.append(path)
        job.total = len(todo)
        job.message = f"{len(found)} file nelle sorgenti, {len(todo)} da elaborare"
        self._publish(job)
        await self._run_files(job, vault, todo)

    async def _ingest_paths(self, job: Job, vault: Vault, paths: list[str]) -> None:
        files: list[str] = []
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                for dirpath, _, names in os.walk(path):
                    files.extend(str(Path(dirpath) / n) for n in names if vault.config.accepts(Path(dirpath) / n))
            elif path.exists() and vault.config.accepts(path):
                files.append(str(path))
            elif not path.exists() and vault.file(str(path)):
                self._remove(job, vault, str(path))
        job.total = len(files)
        self._publish(job)
        await self._run_files(job, vault, files)

    async def _run_files(self, job: Job, vault: Vault, files: list[str]) -> None:
        """Processes files in waves: parse/OCR the whole wave, then embed the whole wave.

        A local server that keeps one model in memory (LM Studio JIT, small-RAM Ollama)
        otherwise swaps the vision/LLM model and the embedding model for every file, and
        concurrent swaps cancel each other's loads."""
        settings = self.settings.get()
        semaphore = asyncio.Semaphore(max(1, settings.ingest_workers))

        def count(outcome: str) -> None:
            if outcome == "indexed":
                job.done += 1
            elif outcome == "skipped":
                job.skipped += 1
            else:
                job.failed += 1
            self._publish(job, throttle=True)

        async def prepare(path: str) -> "Prepared | None":
            async with semaphore:
                if job.id in self._cancel:
                    return None
                job.current = path
                self._publish(job, throttle=True)
                result = await self.prepare_file(vault, Path(path))
                if isinstance(result, str):
                    count(result)
                    return None
                return result

        async def index(prepared: Prepared) -> None:
            async with semaphore:
                if job.id in self._cancel:
                    return
                job.current = str(prepared.path)
                count(await self.index_file(vault, prepared))

        for start in range(0, len(files), WAVE_SIZE):
            wave = await asyncio.gather(*(prepare(p) for p in files[start : start + WAVE_SIZE]))
            await asyncio.gather(*(index(p) for p in wave if p is not None))

    def _models_for(self, vault: Vault) -> list:
        settings = self.settings.get()
        ocr = vault.config.ocr or settings.ocr
        models = [(vault.config.embedding, "embedding")]
        if ocr.engine == "vision" and ocr.vision is not None:
            models.append((ocr.vision, "vision"))
        if vault.config.contextual_summary and settings.llm is not None:
            models.append((settings.llm, "llm"))
        return models

    def _remove(self, job: Job, vault: Vault, path: str) -> None:
        # Removing a folder removes every file recorded under it (SQL prefix match).
        for target in vault.matching_paths(path):
            vault.remove_file(target)
            job.removed += 1
            self.events.publish({"type": "file", "vault_id": vault.config.id, "path": target, "status": "removed"})

    # ------------------------------------------------------------------ one file

    async def process_file(self, vault: Vault, path: Path) -> str:
        prepared = await self.prepare_file(vault, path)
        return prepared if isinstance(prepared, str) else await self.index_file(vault, prepared)

    async def prepare_file(self, vault: Vault, path: Path) -> "Prepared | str":
        """Phase 1: hash, change detection, parsing/OCR and optional LLM summary.

        Returns an outcome string when the file needs no phase 2."""
        settings = self.settings.get()
        config = vault.config
        key = str(path)
        try:
            stat = path.stat()
            sha = await asyncio.to_thread(sha256_file, path)
        except OSError as exc:
            return self._record_error(vault, key, None, 0, 0.0, f"lettura file: {exc}")

        previous = vault.file(key)
        base = FileRecord(
            path=key,
            source=config.source_of(path),
            sha256=sha,
            size=stat.st_size,
            mtime=stat.st_mtime,
            status="pending",
        )
        if previous and previous.sha256 == sha and previous.status == "indexed" and vault.count_chunks(f"file_path = {quote_sql(key)}"):
            # Content unchanged (touched or copied back): refresh stat only.
            vault.upsert_file(previous.model_copy(update={"size": stat.st_size, "mtime": stat.st_mtime}))
            return "skipped"

        self.events.publish({"type": "file", "vault_id": config.id, "path": key, "status": "processing"})
        ocr_settings = config.ocr or settings.ocr
        try:
            ocr = build_engine(ocr_settings, settings.endpoints)
            parsed = await asyncio.to_thread(
                parse_file, path, ocr, min_text_chars_per_page=ocr_settings.min_text_chars_per_page, parser=config.parser
            )
        except Exception as exc:  # noqa: BLE001 - corrupt or locked documents, OCR model errors
            return self._record_error(vault, key, sha, stat.st_size, stat.st_mtime, f"parsing: {exc}", base)

        if not parsed.text.strip():
            vault.delete_chunks(key)
            record = base.model_copy(update=_doc_fields(parsed) | {"status": "skipped", "error": "nessun testo estraibile"})
            vault.upsert_file(record)
            self._file_event(vault, record)
            return "skipped"

        summary = None
        if config.contextual_summary and settings.llm is not None:
            try:
                summary = await ProviderClient(settings.endpoints).chat(
                    settings.llm,
                    [{"role": "user", "content": SUMMARY_PROMPT + parsed.text[:SUMMARY_INPUT_CHARS]}],
                    max_tokens=300,
                )
            except Exception as exc:  # noqa: BLE001 - LLM offline
                return self._record_error(vault, key, sha, stat.st_size, stat.st_mtime, f"riassunto contestuale: {exc}", base)
        return Prepared(path=path, stat=stat, sha=sha, base=base, parsed=parsed, summary=summary)

    async def index_file(self, vault: Vault, prepared: "Prepared") -> str:
        """Phase 2: chunking, embeddings and the vector-store write."""
        settings = self.settings.get()
        config = vault.config
        path, stat, sha, base, parsed, summary = (
            prepared.path, prepared.stat, prepared.sha, prepared.base, prepared.parsed, prepared.summary
        )
        key = str(path)
        provider = ProviderClient(settings.endpoints)
        try:

            async def embed(texts: list[str]) -> list[list[float]]:
                vectors: list[list[float]] = []
                for start in range(0, len(texts), settings.embed_batch_size):
                    vectors.extend(await provider.embed(config.embedding, texts[start : start + settings.embed_batch_size]))
                return vectors

            chunks = await chunk_document(parsed.blocks, config.chunking, embed)
            if not chunks:
                vault.delete_chunks(key)
                record = base.model_copy(update=_doc_fields(parsed) | {"status": "skipped", "error": "nessun testo estraibile"})
                vault.upsert_file(record)
                self._file_event(vault, record)
                return "skipped"
            title = parsed.title or path.stem
            vectors = await embed([c.embedding_text(title, summary) for c in chunks])
        except Exception as exc:  # noqa: BLE001 - provider offline, model unloaded…
            return self._record_error(vault, key, sha, stat.st_size, stat.st_mtime, f"embedding: {exc}", base)

        language = detect_language(parsed.text)
        now = datetime.now(timezone.utc).isoformat()
        created = parsed.created or datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat()
        modified = parsed.modified or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        rows = [
            {
                "id": hashlib.sha1(f"{key}#{c.index}".encode()).hexdigest(),
                "vector": [float(x) for x in vector],
                "text": c.text,
                "file_path": key,
                "file_name": path.name,
                "ext": path.suffix.lower(),
                "file_sha256": sha,
                "chunk_index": c.index,
                "heading": " > ".join(c.heading_path),
                "page_start": c.page_start,
                "page_end": c.page_end,
                "title": title,
                "author": parsed.author,
                "created": created,
                "modified": modified,
                "language": language,
                "ocr": parsed.ocr_pages > 0,
                "ingested_at": now,
            }
            for c, vector in zip(chunks, vectors)
        ]
        try:
            await asyncio.to_thread(vault.replace_chunks, key, rows)
        except Exception as exc:  # noqa: BLE001 - dimension mismatch, disk full…
            return self._record_error(vault, key, sha, stat.st_size, stat.st_mtime, f"vector store: {exc}", base)

        record = base.model_copy(
            update=_doc_fields(parsed)
            | {
                "status": "indexed",
                "chunks": len(rows),
                "language": language,
                "created": created,
                "modified": modified,
                "title": title,
                "error": "; ".join(parsed.warnings) or None,
            }
        )
        vault.upsert_file(record)
        self._file_event(vault, record)
        return "indexed"

    def _record_error(self, vault, key, sha, size, mtime, message, base: FileRecord | None = None) -> str:
        record = (base or FileRecord(path=key, source=vault.config.source_of(Path(key)), sha256=sha, size=size, mtime=mtime, status="error")).model_copy(
            update={"status": "error", "error": message[:1000], "chunks": 0}
        )
        vault.delete_chunks(key)
        vault.upsert_file(record)
        self._file_event(vault, record)
        log.warning("%s: %s", key, message)
        return "error"

    def _file_event(self, vault: Vault, record: FileRecord) -> None:
        self.events.publish({"type": "file", "vault_id": vault.config.id, "path": record.path, "status": record.status, "chunks": record.chunks, "error": record.error})

    _last_publish: dict[str, float] = {}

    def _publish(self, job: Job, throttle: bool = False) -> None:
        now = time.monotonic()
        if throttle and now - self._last_publish.get(job.id, 0.0) < 0.25:
            return
        self._last_publish[job.id] = now
        self.events.publish({"type": "job", "job": job.model_dump()})


@dataclass
class Prepared:
    path: Path
    stat: os.stat_result
    sha: str
    base: FileRecord
    parsed: ParsedDocument
    summary: str | None


def _doc_fields(parsed) -> dict:
    return {
        "title": parsed.title,
        "author": parsed.author,
        "created": parsed.created,
        "modified": parsed.modified,
        "pages": parsed.pages,
        "ocr_pages": parsed.ocr_pages,
        "ocr_engine": parsed.ocr_engine,
    }
