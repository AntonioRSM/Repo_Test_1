"""MCP client manager: server configuration, long-lived connections and agent tool adapters."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import sys
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import data_dir, write_json_atomic

log = logging.getLogger(__name__)

Transport = Literal["stdio", "http"]
Status = Literal["disabled", "connecting", "connected", "error"]
SECRET_MASK = "••••••••"
CONNECT_TIMEOUT = 60.0
MAX_RESULT_CHARS = 8000


# ---------------------------------------------------------------------- secrets


def protect(value: str) -> str:
    """Encrypts with Windows DPAPI (current user); other platforms keep the value as is."""
    if sys.platform != "win32" or not value:
        return value
    import win32crypt  # noqa: PLC0415

    blob = win32crypt.CryptProtectData(value.encode("utf-8"), "WorkspaceOS MCP", None, None, None, 0)
    return "dpapi:" + base64.b64encode(blob).decode("ascii")


def unprotect(value: str) -> str:
    if not value.startswith("dpapi:"):
        return value
    import win32crypt  # noqa: PLC0415

    _, data = win32crypt.CryptUnprotectData(base64.b64decode(value[6:]), None, None, None, 0)
    return data.decode("utf-8")


# ---------------------------------------------------------------------- config


class McpServerConfig(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = Field(min_length=1, max_length=40)
    transport: Transport = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    url: str = ""
    # Values are stored DPAPI-encrypted; the API only ever returns masks.
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: int = Field(120, ge=5, le=1800)

    def public(self) -> dict:
        data = self.model_dump()
        data["env"] = {k: SECRET_MASK for k in self.env}
        data["headers"] = {k: SECRET_MASK for k in self.headers}
        return data


class McpToolInfo(BaseModel):
    name: str  # name exposed to the model
    server_id: str
    original_name: str
    description: str
    input_schema: dict
    read_only: bool | None = None


def agent_tool_name(server: str, tool: str) -> str:
    """OpenAI function names allow [a-zA-Z0-9_-]{1,64}."""
    slug = lambda s: re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_") or "x"  # noqa: E731
    return f"mcp__{slug(server)[:20]}__{slug(tool)}"[:64]


# ---------------------------------------------------------------------- connection


class McpConnection:
    """Owns one server session inside a dedicated task (the SDK's context managers must be
    entered and exited by the same task); other tasks call tools through the session."""

    def __init__(self, config: McpServerConfig, log_dir: Path) -> None:
        self.config = config
        self.log_path = log_dir / f"mcp-{config.id}.log"
        self.status: Status = "disabled" if not config.enabled else "connecting"
        self.error: str | None = None
        self.tools: list[McpToolInfo] = []
        self.server_info: dict | None = None
        self._session = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()

    def start(self) -> None:
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        if not self.config.enabled:
            self.status = "disabled"
            self._ready.set()  # nothing to wait for
            return
        self.status, self.error = "connecting", None
        self._task = asyncio.create_task(self._serve(), name=f"mcp-{self.config.name}")

    async def wait_ready(self, timeout: float = CONNECT_TIMEOUT) -> None:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except asyncio.TimeoutError:
            if self.status == "connecting":
                self.status, self.error = "error", f"nessuna risposta entro {int(timeout)} s"

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, 10)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001 - shutting down regardless
                self._task.cancel()
        self._session = None
        if self.status != "error":
            self.status = "disabled" if not self.config.enabled else "connecting"

    async def _serve(self) -> None:
        from mcp import ClientSession  # noqa: PLC0415 - heavy import

        try:
            async with AsyncExitStack() as stack:
                read, write = await self._open_transport(stack)
                session = await stack.enter_async_context(ClientSession(read, write))
                init = await asyncio.wait_for(session.initialize(), CONNECT_TIMEOUT)
                info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
                self.server_info = {"name": getattr(info, "name", None), "version": getattr(info, "version", None)}
                listing = await asyncio.wait_for(session.list_tools(), CONNECT_TIMEOUT)
                self.tools = [self._adapt(t) for t in listing.tools]
                self._session = session
                self.status, self.error = "connected", None
                self._ready.set()
                log.info("MCP %s connected with %d tools", self.config.name, len(self.tools))
                await self._stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - includes anyio exception groups
            self.status, self.error = "error", _describe(exc, self.log_path)
            log.warning("MCP %s failed: %s", self.config.name, self.error)
        finally:
            self._session = None
            self._ready.set()
            if self.status == "connected":
                self.status = "disabled" if not self.config.enabled else "error"
                self.error = self.error or "connessione chiusa"

    async def _open_transport(self, stack: AsyncExitStack):
        cfg = self.config
        if cfg.transport == "http":
            from mcp.client.streamable_http import streamable_http_client  # noqa: PLC0415
            from mcp.shared._httpx_utils import create_mcp_http_client  # noqa: PLC0415

            if not cfg.url.startswith(("http://", "https://")):
                raise ValueError("URL non valido: serve http:// o https://")
            headers = {k: unprotect(v) for k, v in cfg.headers.items()}
            client = await stack.enter_async_context(create_mcp_http_client(headers=headers))
            streams = await stack.enter_async_context(streamable_http_client(cfg.url, http_client=client))
            return streams[0], streams[1]

        from mcp import StdioServerParameters  # noqa: PLC0415
        from mcp.client.stdio import stdio_client  # noqa: PLC0415

        if not cfg.command:
            raise ValueError("comando mancante")
        # npx/uvx are .cmd shims on Windows: resolve them through PATHEXT.
        executable = shutil.which(cfg.command) or cfg.command
        env = {**os.environ, **{k: unprotect(v) for k, v in cfg.env.items()}}
        params = StdioServerParameters(command=executable, args=cfg.args, env=env, cwd=cfg.cwd or None)
        errlog = stack.enter_context(self.log_path.open("a", encoding="utf-8", errors="replace"))
        return await stack.enter_async_context(stdio_client(params, errlog=errlog))

    def _adapt(self, tool: Any) -> McpToolInfo:
        annotations = getattr(tool, "annotations", None)
        schema = dict(getattr(tool, "input_schema", None) or {"type": "object", "properties": {}})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        return McpToolInfo(
            name=agent_tool_name(self.config.name, tool.name),
            server_id=self.config.id,
            original_name=tool.name,
            description=(getattr(tool, "description", None) or getattr(tool, "title", None) or tool.name)[:1000],
            input_schema=schema,
            read_only=getattr(annotations, "read_only_hint", None) if annotations else None,
        )

    async def call(self, tool_name: str, arguments: dict) -> dict:
        if self._session is None:
            raise RuntimeError(f"il server MCP '{self.config.name}' non è connesso ({self.error or self.status})")
        result = await asyncio.wait_for(self._session.call_tool(tool_name, arguments), self.config.timeout_seconds)
        return render_result(result)


def render_result(result: Any) -> dict:
    """Turns MCP content blocks into compact JSON for the model."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        kind = getattr(block, "type", "")
        if kind == "text":
            parts.append(block.text)
        elif kind in ("image", "audio"):
            size = len(getattr(block, "data", "") or "") * 3 // 4
            parts.append(f"[{kind} {getattr(block, 'mime_type', '')}, {size} byte: non mostrato al modello]")
        elif kind == "resource":
            resource = block.resource
            parts.append(getattr(resource, "text", None) or f"[risorsa {getattr(resource, 'uri', '')}]")
        elif kind == "resource_link":
            parts.append(f"[link risorsa {getattr(block, 'uri', '')}]")
        else:
            parts.append(f"[contenuto {kind}]")
    text = "\n".join(parts)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n…[troncato]"
    output: dict = {"is_error": bool(getattr(result, "is_error", False)), "content": text}
    structured = getattr(result, "structured_content", None)
    if structured and len(json.dumps(structured, default=str)) < 4000:
        output["structured"] = structured
    return output


def _describe(exc: BaseException, log_path: Path) -> str:
    # anyio wraps failures in exception groups; report the innermost cause.
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    message = f"{type(exc).__name__}: {exc}".strip()
    if isinstance(exc, FileNotFoundError):
        message = f"comando non trovato: {exc.filename or exc}"
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
        if tail:
            message += " | stderr: " + " / ".join(tail)
    except OSError:
        pass
    return message[:600]


# ---------------------------------------------------------------------- manager


class McpManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "mcp.json"
        self.log_dir = data_dir() / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.connections: dict[str, McpConnection] = {}
        self._lock = asyncio.Lock()
        for raw in json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []:
            config = McpServerConfig.model_validate(raw)
            self.connections[config.id] = McpConnection(config, self.log_dir)

    def _save(self) -> None:
        write_json_atomic(self.path, [c.config.model_dump() for c in self.connections.values()])

    async def start(self) -> None:
        for conn in self.connections.values():
            conn.start()

    async def shutdown(self) -> None:
        await asyncio.gather(*(c.stop() for c in self.connections.values()), return_exceptions=True)

    def view(self, server_id: str) -> dict:
        conn = self.connections[server_id]
        return conn.config.public() | {
            "status": conn.status,
            "error": conn.error,
            "server_info": conn.server_info,
            "tools": [t.model_dump(exclude={"input_schema"}) for t in conn.tools],
        }

    def list(self) -> list[dict]:
        return [self.view(sid) for sid in self.connections]

    async def add(self, config: McpServerConfig) -> dict:
        async with self._lock:
            if any(c.config.name.lower() == config.name.lower() for c in self.connections.values()):
                raise ValueError(f"esiste già un server chiamato '{config.name}'")
            config.env = {k: protect(v) for k, v in config.env.items()}
            config.headers = {k: protect(v) for k, v in config.headers.items()}
            conn = McpConnection(config, self.log_dir)
            self.connections[config.id] = conn
            self._save()
            conn.start()
        await conn.wait_ready()
        return self.view(config.id)

    async def update(self, server_id: str, patch: dict) -> dict:
        async with self._lock:
            conn = self.connections[server_id]
            current = conn.config
            merged = current.model_dump() | {k: v for k, v in patch.items() if k != "id"}
            for field in ("env", "headers"):
                if field in patch:
                    old = getattr(current, field)
                    # A masked value means "unchanged".
                    merged[field] = {k: old[k] if v == SECRET_MASK and k in old else protect(v) for k, v in patch[field].items()}
            config = McpServerConfig.model_validate(merged)
            await conn.stop()
            conn = McpConnection(config, self.log_dir)
            self.connections[server_id] = conn
            self._save()
            conn.start()
        await conn.wait_ready()
        return self.view(server_id)

    async def remove(self, server_id: str) -> None:
        async with self._lock:
            conn = self.connections.pop(server_id)
            self._save()
        await conn.stop()

    async def reconnect(self, server_id: str) -> dict:
        conn = self.connections[server_id]
        await conn.stop()
        conn.start()
        await conn.wait_ready()
        return self.view(server_id)

    def tools(self) -> list[McpToolInfo]:
        return [t for c in self.connections.values() if c.status == "connected" for t in c.tools]

    def summary(self) -> str:
        connected = [c for c in self.connections.values() if c.status == "connected"]
        return ", ".join(f"{c.config.name} ({len(c.tools)} tools)" for c in connected) or "none"

    async def call(self, info: McpToolInfo, arguments: dict) -> dict:
        conn = self.connections.get(info.server_id)
        if conn is None:
            raise RuntimeError("server MCP rimosso")
        if conn.status != "connected":
            # One automatic attempt to bring a dropped server back.
            await self.reconnect(info.server_id)
            conn = self.connections[info.server_id]
        return await conn.call(info.original_name, arguments)
