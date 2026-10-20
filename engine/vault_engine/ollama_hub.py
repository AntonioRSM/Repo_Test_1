"""Ollama model hub: library search, download, load/unload and RAM/VRAM-aware management.

Model downloads and inference go through the local Ollama HTTP API. The only exception
is `library_search`, which sends the user's search query to ollama.com (the query
leaves the machine there — the Models page says so).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from html import unescape
from typing import Awaitable, Callable
from urllib.parse import quote

import httpx
from pydantic import BaseModel

log = logging.getLogger(__name__)

API_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
PULL_TIMEOUT = httpx.Timeout(600.0, connect=10.0)
LIBRARY_URL = "https://ollama.com/library"

ProgressFn = Callable[[dict], Awaitable[None]]

# Miglioramento #15: transport iniettabile per i test. I test di regressione
# intercettano le chiamate HTTP a livello di trasporto (httpx.MockTransport) invece
# di sostituire le funzioni del modulo: è così che il Bug #19 (delete con json= su
# httpx 0.28) è passato inosservato per tre cicli. In produzione resta None.
_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Pinna un transport httpx (es. MockTransport nei test) per TUTTE le chiamate
    all'API di Ollama di questo modulo. None ripristina il comportamento reale."""
    global _transport
    _transport = transport


def _client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    if _transport is not None:
        return httpx.AsyncClient(timeout=timeout, transport=_transport)
    return httpx.AsyncClient(timeout=timeout)


class HubError(RuntimeError):
    pass


class InstalledModel(BaseModel):
    name: str
    size: int
    digest: str | None = None


class RunningModel(BaseModel):
    name: str
    size: int
    size_vram: int
    expires_at: str | None = None


class LibraryModel(BaseModel):
    name: str
    label: str
    description: str = ""


def base_of(endpoints: dict[str, str]) -> str:
    return endpoints.get("ollama", "http://localhost:11434").rstrip("/")


# ---------------------------------------------------------------------- status


async def status(endpoints: dict[str, str]) -> dict:
    """Installed and in-memory models, for the Models page."""
    base = base_of(endpoints)
    async with _client(API_TIMEOUT) as client:
        try:
            tags = await client.get(f"{base}/api/tags")
            ps = await client.get(f"{base}/api/ps")
            online = tags.status_code == 200
        except httpx.HTTPError:
            return {"online": False, "installed": [], "running": []}
    installed = (
        [InstalledModel(name=m.get("name", ""), size=m.get("size", 0), digest=m.get("digest")) for m in tags.json().get("models", [])]
        if online
        else []
    )
    running = (
        [RunningModel(name=m.get("name", ""), size=m.get("size", 0), size_vram=m.get("size_vram", 0), expires_at=m.get("expires_at")) for m in ps.json().get("models", [])]
        if online and ps.status_code == 200
        else []
    )
    return {"online": online, "installed": installed, "running": running}


# ---------------------------------------------------------------------- library


_LIBRARY_LINK = re.compile(r'href="/library/([a-z0-9][a-z0-9._-]*?)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_CLEAN = re.compile(r"<[^>]+>")


async def library_search(query: str, limit: int = 24) -> list[LibraryModel]:
    """Searches the public Ollama model library (ollama.com) by scraping result cards."""
    url = LIBRARY_URL if not query.strip() else f"{LIBRARY_URL}?q={quote(query)}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), headers={"User-Agent": "RAG-Vault-Studio"}) as client:
        try:
            resp = await client.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise HubError(f"libreria non raggiungibile: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise HubError(f"libreria: HTTP {resp.status_code}")
    seen: dict[str, LibraryModel] = {}
    for name, inner in _LIBRARY_LINK.findall(resp.text):
        label = _TAG_CLEAN.sub("", inner)
        label = re.sub(r"\s+", " ", unescape(label)).strip()
        # Card text mixes name, description and stats ("tools 8b … Pulls 93 …"):
        # keep the name plus the first sentence of description.
        label = re.split(r"\s(?:tools|pulls|tags)\s|\sPulls\s", label, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        if name not in seen:
            seen[name] = LibraryModel(name=name, label=label or name)
        if len(seen) >= limit:
            break
    return list(seen.values())


# ---------------------------------------------------------------------- pull / load / unload / delete

# Seconds between progress events while a download streams (Miglioramento #3):
# Ollama emits one NDJSON line per block; forwarding them all floods the SSE bus and
# re-renders React per block. Terminal states always pass through immediately.
PROGRESS_THROTTLE_SECONDS = 0.3


def normalize_name(model: str) -> str:
    """Ollama treats a tagless name as :latest (llama3 == llama3:latest); the registry
    prefix (hf.co/…) may contain ':'-like text only in the last segment."""
    tail = model.rsplit("/", 1)[-1]
    return model if ":" in tail else f"{model}:latest"


async def pull(endpoints: dict[str, str], model: str, on_progress: ProgressFn | None = None) -> None:
    """Downloads a model, reporting NDJSON progress lines (completed/total bytes).

    Progress callbacks are throttled to one call every PROGRESS_THROTTLE_SECONDS;
    completion and error lines are always forwarded, and so is every phase change
    (Miglioramento #12: 'verifying sha256 digest', 'writing manifest'… would
    otherwise never reach the UI)."""
    base = base_of(endpoints)
    last_emit = 0.0
    last_status: str | None = None

    async def throttled(event: dict) -> None:
        nonlocal last_emit, last_status
        now = time.monotonic()
        status = event.get("status") or ""
        terminal = bool(event.get("error")) or status == "success"
        status_changed = bool(status) and status != last_status
        if terminal or status_changed or now - last_emit >= PROGRESS_THROTTLE_SECONDS:
            last_emit = now
            if status:
                last_status = status
            if on_progress is not None:
                await on_progress(event)

    async with _client(PULL_TIMEOUT) as client:
        try:
            async with client.stream("POST", f"{base}/api/pull", json={"model": model, "stream": True}) as resp:
                if resp.status_code != 200:
                    raise HubError(f"pull {model}: HTTP {resp.status_code}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("error"):
                        raise HubError(f"pull {model}: {event['error']}")
                    await throttled(
                        {
                            "status": event.get("status", ""),
                            "completed": event.get("completed"),
                            "total": event.get("total"),
                        }
                    )
        except httpx.HTTPError as exc:
            raise HubError(f"pull {model}: Ollama non raggiungibile ({type(exc).__name__})") from exc


async def installed_names(endpoints: dict[str, str]) -> set[str] | None:
    """Normalized (:latest-completed) names of installed models with a single /api/tags
    call; None when the server is offline. status() would cost a second call to /api/ps
    (Miglioramento #10)."""
    base = base_of(endpoints)
    async with _client(API_TIMEOUT) as client:
        try:
            resp = await client.get(f"{base}/api/tags")
        except httpx.HTTPError:
            return None
    if resp.status_code != 200:
        return None
    return {normalize_name(m.get("name", "")) for m in resp.json().get("models", [])}


async def is_installed(endpoints: dict[str, str], model: str) -> bool:
    """Exact match after :latest normalisation: llama3 is NOT satisfied by llama3:8b."""
    names = await installed_names(endpoints)
    return names is not None and normalize_name(model) in names


# ---------------------------------------------------------------------- deduplicated downloads (Miglioramento #2)

_pull_locks: dict[str, asyncio.Lock] = {}
_pull_users: dict[str, int] = {}
_background_pulls: dict[str, asyncio.Task] = {}


async def pull_dedup(endpoints: dict[str, str], model: str, on_progress: ProgressFn | None = None) -> None:
    """Downloads a model once even with concurrent callers: same-model requests
    serialize on a per-model lock and re-check the registry after waiting, so every
    caller after the first finds the model already installed."""
    # Miglioramento #9: llama3 and llama3:latest are the same model — the key must be
    # the normalized name, or the two spellings could download in parallel.
    key = normalize_name(model)
    lock = _pull_locks.setdefault(key, asyncio.Lock())
    _pull_users[key] = _pull_users.get(key, 0) + 1
    try:
        async with lock:
            if await is_installed(endpoints, model):
                return
            await pull(endpoints, model, on_progress)
    finally:
        # Bound the registry size: drop the lock once nobody holds or awaits it.
        _pull_users[key] -= 1
        if _pull_users[key] <= 0:
            _pull_users.pop(key, None)
            _pull_locks.pop(key, None)


def start_pull(
    endpoints: dict[str, str],
    model: str,
    on_progress: ProgressFn | None = None,
    on_finished: Callable[[], Awaitable[None]] | None = None,
    on_error: Callable[[Exception], Awaitable[None]] | None = None,
) -> bool:
    """Starts a background download unless one is already running for this model.
    Returns False when an existing download was joined instead."""
    key = normalize_name(model)
    task = _background_pulls.get(key)
    if task is not None and not task.done():
        return False

    async def run() -> None:
        try:
            await pull_dedup(endpoints, model, on_progress)
        except Exception as exc:  # noqa: BLE001 - reported to the UI via the error callback
            if on_error is not None:
                await on_error(exc)
            else:
                # Bug #9: without a callback the failure must at least hit the log,
                # not vanish silently.
                log.error("download in background di %s fallito: %s", model, exc)
        else:
            if on_finished is not None:
                await on_finished()
        finally:
            _background_pulls.pop(key, None)

    _background_pulls[key] = asyncio.create_task(run())
    return True


async def cancel_pulls() -> None:
    """Cancels in-flight background downloads (engine shutdown)."""
    tasks = [t for t in _background_pulls.values() if not t.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _keep_alive_body(model: str, keep_alive_minutes: int) -> dict:
    keep_alive: int | str = keep_alive_minutes if keep_alive_minutes == 0 else f"{keep_alive_minutes}m"
    return {"model": model, "keep_alive": keep_alive, "stream": False}


async def load(endpoints: dict[str, str], model: str, keep_alive_minutes: int) -> None:
    """Loads the model into memory (RAM or VRAM per the Ollama server defaults).

    Embedding-only models (b.g. bge-m3) reject /api/generate: warm them via /api/embed
    with the same keep_alive so the residency setting also applies to them.
    """
    base = base_of(endpoints)
    async with _client(httpx.Timeout(600.0, connect=5.0)) as client:
        try:
            resp = await client.post(f"{base}/api/generate", json=_keep_alive_body(model, keep_alive_minutes))
            if resp.status_code == 400 and "does not support generate" in resp.text:
                resp = await client.post(f"{base}/api/embed", json=_keep_alive_body(model, keep_alive_minutes) | {"input": ""})
        except httpx.HTTPError as exc:
            raise HubError(f"caricamento {model}: Ollama non raggiungibile ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        raise HubError(f"caricamento {model}: HTTP {resp.status_code}: {resp.text[:200]}")


async def unload(endpoints: dict[str, str], model: str) -> None:
    """Frees the model's RAM/VRAM immediately (keep_alive: 0)."""
    base = base_of(endpoints)
    async with _client(API_TIMEOUT) as client:
        try:
            resp = await client.post(f"{base}/api/generate", json=_keep_alive_body(model, 0))
            if resp.status_code == 400 and "does not support generate" in resp.text:
                resp = await client.post(f"{base}/api/embed", json={"model": model, "input": "", "keep_alive": 0})
        except httpx.HTTPError as exc:
            raise HubError(f"scarico {model}: Ollama non raggiungibile ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        raise HubError(f"scarico {model}: HTTP {resp.status_code}: {resp.text[:200]}")


async def delete(endpoints: dict[str, str], model: str) -> None:
    base = base_of(endpoints)
    async with _client(API_TIMEOUT) as client:
        try:
            # Bug #19: in httpx 0.28 AsyncClient.delete() NON accetta json= (TypeError
            # prima di qualunque richiesta); il verbo va scelto con request().
            resp = await client.request("DELETE", f"{base}/api/delete", json={"model": model})
        except httpx.HTTPError as exc:
            raise HubError(f"eliminazione {model}: Ollama non raggiungibile ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        raise HubError(f"eliminazione {model}: HTTP {resp.status_code}: {resp.text[:200]}")


__all__ = [
    "HubError",
    "InstalledModel",
    "LibraryModel",
    "RunningModel",
    "base_of",
    "cancel_pulls",
    "delete",
    "installed_names",
    "is_installed",
    "library_search",
    "load",
    "normalize_name",
    "pull",
    "pull_dedup",
    "set_transport",
    "start_pull",
    "status",
    "unload",
]
