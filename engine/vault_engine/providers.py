"""LM Studio and Ollama access through their OpenAI-compatible endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Literal

import httpx
from pydantic import BaseModel

from .config import DEFAULT_ENDPOINTS, ModelRef, ProviderKind

ModelKind = Literal["embedding", "llm", "vision"]
log = logging.getLogger(__name__)

DISCOVERY_TIMEOUT = httpx.Timeout(2.0)
EMBED_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
CHAT_TIMEOUT = httpx.Timeout(600.0, connect=5.0)


class ProviderError(RuntimeError):
    pass


class ModelInfo(BaseModel):
    id: str
    kinds: list[ModelKind]
    loaded: bool | None = None
    size_bytes: int | None = None
    context_length: int | None = None
    # Trained for function calling (LM Studio reports it); None = unknown.
    tool_use: bool | None = None


class ProviderStatus(BaseModel):
    provider: ProviderKind
    base_url: str
    online: bool
    version: str | None = None
    models: list[ModelInfo] = []
    error: str | None = None


def _guess_kinds(model_id: str) -> list[ModelKind]:
    name = model_id.lower()
    if "embed" in name or name.startswith(("bge", "e5-", "gte-")):
        return ["embedding"]
    kinds: list[ModelKind] = ["llm"]
    if any(tag in name for tag in ("llava", "-vl", "vision", "qwen2-vl", "qwen2.5-vl", "gemma-3", "gemma-4", "minicpm-v", "moondream")):
        kinds.append("vision")
    return kinds


async def _lmstudio_status(client: httpx.AsyncClient, base: str) -> ProviderStatus:
    # LM Studio 0.4+: /api/v1/models (capabilities, loaded instances). 0.3: /api/v0/models.
    # Older builds only have the OpenAI-compatible /v1/models.
    try:
        resp = await client.get(f"{base}/api/v1/models")
        resp.raise_for_status()
        models = []
        for m in resp.json()["models"]:
            caps = m.get("capabilities") or {}
            kinds: list[ModelKind] = ["embedding"] if m.get("type") == "embedding" else ["llm"] + (["vision"] if caps.get("vision") else [])
            models.append(
                ModelInfo(
                    id=m["key"],
                    kinds=kinds,
                    loaded=bool(m.get("loaded_instances")),
                    size_bytes=m.get("size_bytes"),
                    context_length=m.get("max_context_length"),
                    tool_use=caps.get("trained_for_tool_use") if m.get("type") != "embedding" else None,
                )
            )
        return ProviderStatus(provider="lmstudio", base_url=base, online=True, models=models)
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        pass
    try:
        resp = await client.get(f"{base}/api/v0/models")
        resp.raise_for_status()
        models = []
        for m in resp.json().get("data", []):
            kind = m.get("type")
            kinds: list[ModelKind] = (
                ["embedding"] if kind == "embeddings" else ["llm", "vision"] if kind == "vlm" else ["llm"]
            )
            models.append(
                ModelInfo(
                    id=m["id"],
                    kinds=kinds,
                    loaded=m.get("state") == "loaded",
                    context_length=m.get("max_context_length"),
                )
            )
        return ProviderStatus(provider="lmstudio", base_url=base, online=True, models=models)
    except (httpx.HTTPError, KeyError, ValueError):
        resp = await client.get(f"{base}/v1/models")
        resp.raise_for_status()
        models = [ModelInfo(id=m["id"], kinds=_guess_kinds(m["id"])) for m in resp.json().get("data", [])]
        return ProviderStatus(provider="lmstudio", base_url=base, online=True, models=models)


async def _ollama_status(client: httpx.AsyncClient, base: str) -> ProviderStatus:
    resp = await client.get(f"{base}/api/tags")
    resp.raise_for_status()
    version = None
    try:
        version = (await client.get(f"{base}/api/version")).json().get("version")
    except (httpx.HTTPError, ValueError):
        pass
    loaded = set()
    try:
        loaded = {m["name"] for m in (await client.get(f"{base}/api/ps")).json().get("models", [])}
    except (httpx.HTTPError, ValueError, KeyError):
        pass

    async def describe(m: dict) -> ModelInfo:
        name = m["name"]
        kinds = _guess_kinds(name)
        try:
            show = (await client.post(f"{base}/api/show", json={"model": name})).json()
            caps = show.get("capabilities") or []
            if caps:
                kinds = []
                if "embedding" in caps:
                    kinds.append("embedding")
                if "completion" in caps:
                    kinds.append("llm")
                if "vision" in caps:
                    kinds.append("vision")
        except (httpx.HTTPError, ValueError):
            pass
        return ModelInfo(id=name, kinds=kinds or ["llm"], loaded=name in loaded, size_bytes=m.get("size"))

    models = await asyncio.gather(*(describe(m) for m in resp.json().get("models", [])))
    return ProviderStatus(provider="ollama", base_url=base, online=True, version=version, models=list(models))


async def discover(endpoints: dict[str, str] | None = None) -> list[ProviderStatus]:
    """Probes every configured endpoint (plus the defaults) and lists available models."""
    targets = dict(DEFAULT_ENDPOINTS) | (endpoints or {})
    async with httpx.AsyncClient(timeout=DISCOVERY_TIMEOUT) as client:

        async def probe(provider: ProviderKind, base: str) -> ProviderStatus:
            base = base.rstrip("/")
            try:
                if provider == "lmstudio":
                    return await _lmstudio_status(client, base)
                return await _ollama_status(client, base)
            except (httpx.HTTPError, ValueError) as exc:
                return ProviderStatus(provider=provider, base_url=base, online=False, error=type(exc).__name__)

        return list(await asyncio.gather(*(probe(p, b) for p, b in targets.items())))  # type: ignore[arg-type]


class ProviderClient:
    """Calls embeddings and chat on one provider via the OpenAI-compatible /v1 API."""

    def __init__(self, endpoints: dict[str, str]) -> None:
        self.endpoints = dict(DEFAULT_ENDPOINTS) | endpoints

    def _base(self, ref: ModelRef) -> str:
        return self.endpoints[ref.provider].rstrip("/")

    async def embed(self, ref: ModelRef, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
            body = await post_json(
                client, f"{self._base(ref)}/v1/embeddings", {"model": ref.model, "input": texts}, f"embedding {ref.model}"
            )
        data = sorted(body["data"], key=lambda d: d["index"])
        if len(data) != len(texts):
            raise ProviderError(f"expected {len(texts)} embeddings, got {len(data)}")
        return [d["embedding"] for d in data]

    async def chat(
        self,
        ref: ModelRef,
        messages: list[dict],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        reasoning: bool = False,
    ) -> str:
        payload = chat_payload(ref, messages, temperature, max_tokens, reasoning)
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
            body = await post_json(client, f"{self._base(ref)}/v1/chat/completions", payload, f"chat {ref.model}")
        return chat_content(ref, body)


async def ensure_loaded(endpoints: dict[str, str], refs: list[tuple[ModelRef, ModelKind]]) -> None:
    """Loads the given models explicitly so they stay resident together.

    LM Studio's just-in-time loading keeps a single model: alternating the chat model and
    the embedding model (every agent step, every ingestion wave) would reload one of them
    each time. Explicitly loaded models are not evicted. Ollama gets a long keep_alive.
    Best effort: older servers without these APIs fall back to on-demand loading."""
    targets = dict(DEFAULT_ENDPOINTS) | endpoints
    unique = {(r.provider, r.model): (r, kind) for r, kind in refs}
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=3.0)) as client:
        lms_loaded: set[str] | None = None
        for (provider, model), (ref, kind) in unique.items():
            base = targets[provider].rstrip("/")
            try:
                if provider == "lmstudio":
                    if lms_loaded is None:
                        listing = (await client.get(f"{base}/api/v1/models")).json()["models"]
                        lms_loaded = {m["key"] for m in listing if m.get("loaded_instances")}
                    if model not in lms_loaded:
                        resp = await client.post(f"{base}/api/v1/models/load", json={"model": model})
                        resp.raise_for_status()
                        lms_loaded.add(model)
                else:
                    route, body = ("/api/embed", {"input": ""}) if kind == "embedding" else ("/api/generate", {})
                    await client.post(f"{base}{route}", json={"model": model, "keep_alive": "30m"} | body)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                log.info("could not preload %s/%s: %s", provider, model, exc)


class StreamResult(BaseModel):
    content: str
    tool_calls: list[dict]  # [{"id", "name", "arguments"}]
    finish_reason: str | None
    usage: dict | None = None


async def chat_stream(
    endpoints: dict[str, str],
    ref: ModelRef,
    messages: list[dict],
    *,
    tools: list[dict] | None,
    max_tokens: int,
    temperature: float = 0.2,
    reasoning: bool = False,
    on_text=None,
) -> StreamResult:
    """Streams one completion, forwarding text deltas and assembling tool-call fragments."""
    base = (dict(DEFAULT_ENDPOINTS) | endpoints)[ref.provider].rstrip("/")
    payload = chat_payload(ref, messages, temperature, max_tokens, reasoning) | {"stream": True}
    payload["stream_options"] = {"include_usage": True}
    if tools:
        payload["tools"] = tools
    async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                async with client.stream("POST", f"{base}/v1/chat/completions", json=payload) as resp:
                    if not resp.is_success:
                        await resp.aread()
                        decision = _retry_decision(resp, payload)
                        if decision == "drop-reasoning":
                            payload.pop("reasoning_effort")
                            continue
                        if decision == "retry" and attempt < len(RETRY_DELAYS):
                            await asyncio.sleep(RETRY_DELAYS[attempt])
                            continue
                        raise ProviderError(f"chat {ref.model}: HTTP {resp.status_code}: {error_detail(resp)}")
                    return await _read_stream(resp, on_text)
            except httpx.ConnectError as exc:
                raise ProviderError(f"chat {ref.model}: server non raggiungibile ({base})") from exc
    raise ProviderError(f"chat {ref.model}: nessuna risposta valida")


async def _read_stream(resp: httpx.Response, on_text) -> StreamResult:
    content, finish, usage = "", None, None
    calls: dict[int, dict] = {}
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        usage = chunk.get("usage") or usage
        if not chunk.get("choices"):
            continue
        choice = chunk["choices"][0]
        finish = choice.get("finish_reason") or finish
        delta = choice.get("delta") or {}
        if text := delta.get("content"):
            content += text
            if on_text is not None:
                await on_text(text)
        for fragment in delta.get("tool_calls") or []:
            slot = calls.setdefault(fragment.get("index", len(calls)), {"id": "", "name": "", "arguments": ""})
            slot["id"] = fragment.get("id") or slot["id"]
            fn = fragment.get("function") or {}
            slot["name"] += fn.get("name") or ""
            slot["arguments"] += fn.get("arguments") or ""
    tool_calls = []
    for index in sorted(calls):
        call = calls[index]
        if call["name"]:
            call["id"] = call["id"] or f"call_{uuid.uuid4().hex[:10]}"
            tool_calls.append(call)
    return StreamResult(content=strip_reasoning(content), tool_calls=tool_calls, finish_reason=finish, usage=usage)


# A server that keeps one model in memory answers with these while it swaps models.
TRANSIENT_MARKERS = ("failed to load model", "operation canceled", "operation cancelled", "loading model", "model is loading", "unloaded")
RETRY_DELAYS = (3.0, 10.0, 20.0)


def error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        error = body.get("error", body)
        return str(error.get("message", error) if isinstance(error, dict) else error)[:500]
    except ValueError:
        return resp.text[:500]


def _retry_decision(resp: httpx.Response, payload: dict) -> str:
    """'ok', 'drop-reasoning', 'retry' or 'fail'."""
    if resp.is_success:
        return "ok"
    detail = error_detail(resp).lower()
    if resp.status_code in (400, 422) and "reasoning_effort" in payload and "reasoning" in detail:
        return "drop-reasoning"  # server predates the field: fall back to the model's default
    if resp.status_code in (429, 500, 502, 503, 504) or any(m in detail for m in TRANSIENT_MARKERS):
        return "retry"
    return "fail"


async def post_json(client: httpx.AsyncClient, url: str, payload: dict, what: str) -> dict:
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            resp = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise ProviderError(f"{what}: server non raggiungibile ({url})") from exc
        except httpx.TransportError as exc:
            if attempt == len(RETRY_DELAYS):
                raise ProviderError(f"{what}: {type(exc).__name__}") from exc
            await asyncio.sleep(RETRY_DELAYS[attempt])
            continue
        decision = _retry_decision(resp, payload)
        if decision == "ok":
            return resp.json()
        if decision == "drop-reasoning":
            payload.pop("reasoning_effort")
            continue
        if decision == "retry" and attempt < len(RETRY_DELAYS):
            await asyncio.sleep(RETRY_DELAYS[attempt])
            continue
        raise ProviderError(f"{what}: HTTP {resp.status_code}: {error_detail(resp)}")
    raise ProviderError(f"{what}: nessuna risposta valida")


def post_json_sync(url: str, payload: dict, what: str, timeout: httpx.Timeout) -> dict:
    """Blocking twin of post_json for code running in worker threads (OCR)."""
    import time  # noqa: PLC0415

    with httpx.Client(timeout=timeout) as client:
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                resp = client.post(url, json=payload)
            except httpx.ConnectError as exc:
                raise ProviderError(f"{what}: server non raggiungibile ({url})") from exc
            except httpx.TransportError as exc:
                if attempt == len(RETRY_DELAYS):
                    raise ProviderError(f"{what}: {type(exc).__name__}") from exc
                time.sleep(RETRY_DELAYS[attempt])
                continue
            decision = _retry_decision(resp, payload)
            if decision == "ok":
                return resp.json()
            if decision == "drop-reasoning":
                payload.pop("reasoning_effort")
                continue
            if decision == "retry" and attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise ProviderError(f"{what}: HTTP {resp.status_code}: {error_detail(resp)}")
    raise ProviderError(f"{what}: nessuna risposta valida")


def chat_payload(ref: ModelRef, messages: list[dict], temperature: float, max_tokens: int, reasoning: bool) -> dict:
    payload = {
        "model": ref.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if not reasoning and ref.provider == "lmstudio":
        # Reasoning models (Gemma 4, Qwen 3, DeepSeek-R1…) otherwise spend most of the token
        # budget thinking: 5x slower on CPU, and the answer can be cut off entirely.
        payload["reasoning_effort"] = "none"
    if not reasoning and ref.provider == "ollama":
        payload["think"] = False
    return payload


def chat_content(ref: ModelRef, data: dict) -> str:
    choice = data["choices"][0]
    content = strip_reasoning(choice["message"].get("content") or "")
    if not content and choice.get("finish_reason") == "length":
        raise ProviderError(
            f"{ref.model} used its whole token budget before answering (reasoning model?); "
            "raise max_tokens or choose a non-reasoning model"
        )
    return content


def strip_reasoning(text: str) -> str:
    """Drops <think>…</think> blocks emitted by reasoning models such as DeepSeek-R1 distills."""
    while "<think>" in text and "</think>" in text:
        start = text.index("<think>")
        end = text.index("</think>", start) + len("</think>")
        text = text[:start] + text[end:]
    return text.strip()
