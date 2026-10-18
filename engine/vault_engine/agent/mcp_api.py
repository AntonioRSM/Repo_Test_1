"""HTTP endpoints for MCP server management. Mounted by app.py behind the token dependency."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from .mcp import McpManager, McpServerConfig

router = APIRouter(prefix="/mcp")


class _State:
    manager: McpManager


state = _State()


def init(manager: McpManager) -> None:
    state.manager = manager


def _known(server_id: str) -> None:
    if server_id not in state.manager.connections:
        raise HTTPException(404, "server MCP non trovato")


@router.get("/servers")
def list_servers():
    return state.manager.list()


@router.post("/servers", status_code=201)
async def add_server(body: dict):
    body.pop("id", None)
    try:
        config = McpServerConfig.model_validate(body)
        return await state.manager.add(config)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/servers/{server_id}")
async def update_server(server_id: str, patch: dict):
    _known(server_id)
    try:
        return await state.manager.update(server_id, patch)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/servers/{server_id}", status_code=204)
async def remove_server(server_id: str):
    _known(server_id)
    await state.manager.remove(server_id)


@router.post("/servers/{server_id}/reconnect")
async def reconnect_server(server_id: str):
    _known(server_id)
    return await state.manager.reconnect(server_id)


@router.get("/servers/{server_id}/log")
def server_log(server_id: str, lines: int = 80):
    _known(server_id)
    path = state.manager.connections[server_id].log_path
    if not path.exists():
        return {"lines": []}
    return {"lines": path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]}
