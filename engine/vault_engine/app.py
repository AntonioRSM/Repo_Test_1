"""HTTP API (localhost only) used by the desktop app and, later, by the agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .chunking import ChunkingSettings
from .config import ModelRef, OcrSettings, SettingsStore
from .events import EventBus
from .hardware import HardwareMonitor
from .parsers import SUPPORTED_EXTS
from .pipeline import JobManager
from .providers import ProviderClient, ProviderError, discover, ensure_loaded
from .vaults import Metric, VaultConfig, VaultRegistry, quote_sql
from .agent import api as agent_api
from .agent import mcp_api
from .agent.mcp import McpManager
from .agent.runner import AgentRunner
from .agent.store import AgentStore
from .watcher import VaultWatcher

log = logging.getLogger(__name__)

RERANK_PROMPT = (
    "Rate each passage independently for how useful it is to answer the query, from 0 "
    "(irrelevant) to 10 (directly answers it). The query may ask several things: a passage "
    "that answers any one part of it deserves a high score. "
    'Reply with JSON only: {{"scores": [n, n, ...]}} with one score per passage, in order.\n\n'
    "Query: {query}\n\n{passages}"
)
ANSWER_PROMPT = (
    "Answer the question using only the numbered sources below. Cite sources inline as [n]. "
    "If the sources do not contain the answer, say so. Answer in the question's language.\n\n"
    "{sources}\n\nQuestion: {question}"
)


class State:
    settings: SettingsStore
    registry: VaultRegistry
    events: EventBus
    jobs: JobManager
    hardware: HardwareMonitor
    watcher: VaultWatcher


state = State()


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    state.settings = SettingsStore()
    state.registry = VaultRegistry()
    state.events = EventBus()
    state.events.bind(loop)
    state.jobs = JobManager(state.registry, state.settings, state.events)
    state.hardware = HardwareMonitor()
    state.hardware.start()
    state.watcher = VaultWatcher(state.registry, state.jobs, loop)
    state.watcher.start()
    agent_store = AgentStore()
    mcp_manager = McpManager()
    await mcp_manager.start()
    mcp_api.init(mcp_manager)
    agent_api.init(AgentRunner(state.registry, state.settings, state.events, agent_store, mcp_manager), agent_store)
    # Catch up on changes made while the app was closed.
    for vault in state.registry.list():
        if vault.config.watch and vault.config.sources:
            state.jobs.submit(vault.config.id, "sync")
    yield
    state.watcher.stop()
    state.hardware.stop()
    await state.jobs.shutdown()
    await mcp_manager.shutdown()


app = FastAPI(title="RAG Vault Studio engine", version="0.1.0", lifespan=lifespan)


def _cors_origin_regex() -> str:
    """Origins allowed to read API responses.

    With the per-launch token (desktop mode) the renderer may be a file:// or null origin.
    Without a token (manual start on a known port) those origins would let any web page
    sandboxed in an iframe read the API: keep only explicit http localhost origins.
    """
    local = r"http://(localhost|127\.0\.0\.1)(:\d+)?"
    return rf"^({local}|file://.*|null)$" if os.environ.get("WSOS_TOKEN") else rf"^({local})$"


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_cors_origin_regex(),
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(request: Request) -> None:
    """When started by the desktop app, every call must carry its per-launch token."""
    expected = os.environ.get("WSOS_TOKEN")
    if not expected:
        return
    supplied = request.headers.get("x-wsos-token") or request.query_params.get("token")
    if supplied != expected:
        raise HTTPException(401, "invalid token")


api = Depends(require_token)
app.include_router(agent_api.router, dependencies=[api])
app.include_router(mcp_api.router, dependencies=[api])


def get_vault(vault_id: str):
    try:
        return state.registry.get(vault_id)
    except KeyError:
        raise HTTPException(404, f"vault {vault_id} not found") from None


# ------------------------------------------------------------------ system


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": app.version, "supported_extensions": sorted(SUPPORTED_EXTS)}


@app.get("/hardware", dependencies=[api])
def hardware():
    return state.hardware.latest()


@app.get("/events", dependencies=[api])
async def events(request: Request):
    queue = state.events.subscribe()

    async def stream():
        try:
            yield "event: hello\ndata: {}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            state.events.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ providers & settings


@app.get("/providers", dependencies=[api])
async def providers():
    return await discover(state.settings.get().endpoints)


@app.get("/settings", dependencies=[api])
def get_settings():
    return state.settings.get()


@app.patch("/settings", dependencies=[api])
def patch_settings(patch: dict):
    try:
        return state.settings.update(patch)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class EmbedTest(BaseModel):
    embedding: ModelRef
    text: str = "Prova di embedding / embedding test"


@app.post("/providers/test-embedding", dependencies=[api])
async def test_embedding(body: EmbedTest):
    client = ProviderClient(state.settings.get().endpoints)
    try:
        vector = (await client.embed(body.embedding, [body.text]))[0]
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"dimension": len(vector), "preview": vector[:8]}


# ------------------------------------------------------------------ vaults


class VaultCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    sources: list[str] = Field(default_factory=list)
    embedding: ModelRef
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    ocr: OcrSettings | None = None
    parser: str = "builtin"
    contextual_summary: bool = False
    watch: bool = True
    metric: Metric = "cosine"


def vault_view(vault) -> dict:
    return {
        **vault.config.model_dump(),
        "stats": vault.stats(),
        "busy": state.jobs.busy(vault.config.id),
        "watching": state.watcher.watching(vault.config.id),
    }


@app.get("/vaults", dependencies=[api])
def list_vaults():
    return [vault_view(v) for v in state.registry.list()]


@app.post("/vaults", dependencies=[api], status_code=201)
async def create_vault(body: VaultCreate):
    missing = [s for s in body.sources if not Path(s).is_dir()]
    if missing:
        raise HTTPException(422, f"cartelle inesistenti: {', '.join(missing)}")
    vault = state.registry.create(VaultConfig(**body.model_dump()))
    state.watcher.refresh()
    if vault.config.sources:
        state.jobs.submit(vault.config.id, "sync")
    return vault_view(vault)


@app.get("/vaults/{vault_id}", dependencies=[api])
def read_vault(vault_id: str):
    return vault_view(get_vault(vault_id))


@app.patch("/vaults/{vault_id}", dependencies=[api])
async def update_vault(vault_id: str, patch: dict):
    vault = get_vault(vault_id)
    rebuild_needed = "embedding" in patch and ModelRef.model_validate(patch["embedding"]) != vault.config.embedding
    for locked in ("id", "dimension", "created_at"):
        patch.pop(locked, None)
    try:
        updated = VaultConfig.model_validate(vault.config.model_dump() | patch)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    missing = [s for s in updated.sources if not Path(s).is_dir()]
    if missing:
        raise HTTPException(422, f"cartelle inesistenti: {', '.join(missing)}")
    sources_changed = updated.sources != vault.config.sources
    vault.config = updated
    vault.save_config()
    state.watcher.refresh()
    if rebuild_needed:
        state.jobs.submit(vault_id, "rebuild")
    elif sources_changed:
        state.jobs.submit(vault_id, "sync")
    return vault_view(vault)


@app.delete("/vaults/{vault_id}", dependencies=[api], status_code=204)
async def delete_vault(vault_id: str):
    get_vault(vault_id)
    state.registry.delete(vault_id)
    state.watcher.refresh()


class PathsBody(BaseModel):
    paths: list[str]


@app.post("/vaults/{vault_id}/sync", dependencies=[api])
async def sync_vault(vault_id: str, rebuild: bool = False):
    get_vault(vault_id)
    return state.jobs.submit(vault_id, "rebuild" if rebuild else "sync")


@app.post("/vaults/{vault_id}/ingest", dependencies=[api])
async def ingest_paths(vault_id: str, body: PathsBody):
    """Drag & drop: index files or folders even outside the vault's sources."""
    get_vault(vault_id)
    return state.jobs.submit(vault_id, "ingest", body.paths)


@app.get("/vaults/{vault_id}/files", dependencies=[api])
def vault_files(vault_id: str, status: str | None = None, q: str | None = None, offset: int = 0, limit: int = Query(200, le=2000)):
    return get_vault(vault_id).files(status=status, offset=offset, limit=limit, query=q)


@app.delete("/vaults/{vault_id}/files", dependencies=[api])
def remove_file(vault_id: str, path: str):
    """Drops a document from the index (the file on disk is untouched)."""
    get_vault(vault_id).remove_file(path)
    return {"removed": path}


@app.get("/vaults/{vault_id}/chunks", dependencies=[api])
def vault_chunks(vault_id: str, file: str | None = None, offset: int = 0, limit: int = Query(50, le=500)):
    vault = get_vault(vault_id)
    where = f"file_path = {quote_sql(file)}" if file else None
    return {"total": vault.count_chunks(where), "items": vault.list_chunks(offset, limit, file)}


@app.get("/vaults/{vault_id}/projection", dependencies=[api])
def vault_projection(vault_id: str, limit: int = Query(2000, le=10000)):
    return get_vault(vault_id).projection(limit)


@app.get("/jobs", dependencies=[api])
def list_jobs(vault_id: str | None = None):
    return state.jobs.list(vault_id)


@app.post("/jobs/{job_id}/cancel", dependencies=[api])
def cancel_job(job_id: str):
    state.jobs.cancel(job_id)
    return {"cancelled": job_id}


# ------------------------------------------------------------------ retrieval


class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(8, ge=1, le=100)
    metric: Metric | None = None
    rerank: bool = False
    file: str | None = None
    extensions: list[str] | None = None


RERANK_MAX_CANDIDATES = 24
RERANK_PASSAGE_CHARS = 800


async def retrieve(vault, body: SearchBody) -> tuple[list[dict], str | None]:
    """Vector search, optionally re-ranked by the LLM. Returns (rows, rerank error)."""
    settings = state.settings.get()
    client = ProviderClient(settings.endpoints)
    wanted = [(vault.config.embedding, "embedding")]
    if settings.llm is not None and (body.rerank or isinstance(body, AskBody)):
        wanted.append((settings.llm, "llm"))
    await ensure_loaded(settings.endpoints, wanted)
    try:
        vector = (await client.embed(vault.config.embedding, [body.query]))[0]
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    filters = []
    if body.file:
        filters.append(f"file_path = {quote_sql(body.file)}")
    if body.extensions:
        filters.append("ext IN (" + ", ".join(quote_sql(e.lower()) for e in body.extensions) + ")")
    # Every candidate lengthens the LLM prompt; on CPU-only machines prompt processing dominates.
    candidates = min(max(body.k * 2, body.k), RERANK_MAX_CANDIDATES) if body.rerank else body.k
    rows = await asyncio.to_thread(vault.search, vector, candidates, body.metric or vault.config.metric, " AND ".join(filters) or None)
    for row in rows:
        row.pop("vector", None)
    error = None
    if body.rerank and rows:
        if settings.llm is None:
            error = "nessun LLM configurato per il re-ranking"
        else:
            try:
                rows = await rerank(client, settings.llm, body.query, rows)
            except RerankError as exc:
                log.warning("rerank failed: %s", exc)
                error = str(exc)
    return rows[: body.k], error


class RerankError(Exception):
    pass


def parse_scores(reply: str, expected: int) -> list[float]:
    """Accepts {"scores": [...]}, optionally fenced in ```json, with numeric or numeric-string scores."""
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        raise RerankError(f"risposta del modello senza JSON: {reply[:200]!r}")
    try:
        raw = json.loads(match.group(0))["scores"]
        scores = [float(s) for s in raw]
    except (ValueError, KeyError, TypeError) as exc:
        raise RerankError(f"punteggi non validi: {reply[:200]!r}") from exc
    if len(scores) != expected:
        raise RerankError(f"attesi {expected} punteggi, ricevuti {len(scores)}")
    return scores


async def rerank(client: ProviderClient, llm: ModelRef, query: str, rows: list[dict]) -> list[dict]:
    passages = "\n\n".join(f"[{i + 1}] {r['text'][:RERANK_PASSAGE_CHARS]}" for i, r in enumerate(rows))
    try:
        reply = await client.chat(
            llm,
            [{"role": "user", "content": RERANK_PROMPT.format(query=query, passages=passages)}],
            max_tokens=64 + 8 * len(rows),
            temperature=0,
        )
    except ProviderError as exc:
        raise RerankError(str(exc)) from exc
    for row, score in zip(rows, parse_scores(reply, len(rows))):
        row["rerank_score"] = score
    # Stable sort: equal LLM scores keep their vector-similarity order.
    return sorted(rows, key=lambda r: r["rerank_score"], reverse=True)


@app.post("/vaults/{vault_id}/search", dependencies=[api])
async def search(vault_id: str, body: SearchBody):
    vault = get_vault(vault_id)
    rows, rerank_error = await retrieve(vault, body)
    return {"metric": body.metric or vault.config.metric, "results": rows, "rerank_error": rerank_error}


class AskBody(SearchBody):
    question: str | None = None


@app.post("/vaults/{vault_id}/ask", dependencies=[api])
async def ask(vault_id: str, body: AskBody):
    """Retrieval-augmented answer with numbered citations, entirely on local models."""
    vault = get_vault(vault_id)
    settings = state.settings.get()
    if settings.llm is None:
        raise HTTPException(422, "nessun LLM configurato nelle impostazioni")
    results, rerank_error = await retrieve(vault, body)
    if not results:
        return {"answer": "Nessun documento pertinente trovato in questo Vault.", "sources": [], "rerank_error": rerank_error}
    sources = "\n\n".join(
        f"[{i + 1}] {Path(r['file_path']).name}" + (f" p.{r['page_start']}" if r.get("page_start") else "") + f"\n{r['text']}"
        for i, r in enumerate(results)
    )
    client = ProviderClient(settings.endpoints)
    try:
        answer = await client.chat(
            settings.llm,
            [{"role": "user", "content": ANSWER_PROMPT.format(sources=sources, question=body.question or body.query)}],
            max_tokens=1200,
        )
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"answer": answer, "sources": results, "rerank_error": rerank_error}
