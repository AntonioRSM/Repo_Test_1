"""Background folder watching with debounce; changes become ingest/remove jobs."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .pipeline import JobManager
from .vaults import VaultRegistry

log = logging.getLogger(__name__)

# Office apps save through temp files and several writes; wait for the burst to settle.
DEBOUNCE_SECONDS = 3.0


class _Handler(FileSystemEventHandler):
    def __init__(self, owner: "VaultWatcher", vault_id: str) -> None:
        self.owner = owner
        self.vault_id = vault_id

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed_no_write"):
            return
        paths = [event.src_path]
        if event.event_type == "moved":
            paths.append(getattr(event, "dest_path", ""))
        for path in filter(None, paths):
            self.owner.touch(self.vault_id, str(path))


class VaultWatcher:
    def __init__(self, registry: VaultRegistry, jobs: JobManager, loop: asyncio.AbstractEventLoop) -> None:
        self.registry = registry
        self.jobs = jobs
        self.loop = loop
        self._observer = Observer()
        self._watches: dict[str, list] = {}
        self._pending: dict[str, set[str]] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        self._observer.start()
        self.refresh()

    def stop(self) -> None:
        for timer in self._timers.values():
            timer.cancel()
        self._observer.stop()

    def watching(self, vault_id: str) -> bool:
        return bool(self._watches.get(vault_id))

    def refresh(self) -> None:
        """Re-reads every vault's sources and watch flag."""
        with self._lock:
            for handles in self._watches.values():
                for handle in handles:
                    self._observer.unschedule(handle)
            self._watches.clear()
            for vault in self.registry.list():
                if not vault.config.watch:
                    continue
                handles = []
                for source in vault.config.sources:
                    if Path(source).is_dir():
                        try:
                            handles.append(self._observer.schedule(_Handler(self, vault.config.id), source, recursive=True))
                        except OSError as exc:
                            log.warning("cannot watch %s: %s", source, exc)
                self._watches[vault.config.id] = handles

    def touch(self, vault_id: str, path: str) -> None:
        try:
            vault = self.registry.get(vault_id)
        except KeyError:
            return
        p = Path(path)
        # Deleted folders have no suffix; let them through so their files get removed.
        if p.exists() and p.is_file() and not vault.config.accepts(p):
            return
        if p.exists() and p.is_dir():
            return
        with self._lock:
            self._pending.setdefault(vault_id, set()).add(path)
            if timer := self._timers.get(vault_id):
                timer.cancel()
            timer = threading.Timer(DEBOUNCE_SECONDS, self._flush, args=(vault_id,))
            timer.daemon = True
            self._timers[vault_id] = timer
            timer.start()

    def _flush(self, vault_id: str) -> None:
        with self._lock:
            paths = sorted(self._pending.pop(vault_id, set()))
            self._timers.pop(vault_id, None)
        if not paths:
            return
        existing = [p for p in paths if Path(p).exists()]
        missing = [p for p in paths if not Path(p).exists()]

        def submit() -> None:
            if missing:
                self.jobs.submit(vault_id, "remove", missing)
            if existing:
                self.jobs.submit(vault_id, "ingest", existing)

        self.loop.call_soon_threadsafe(submit)
