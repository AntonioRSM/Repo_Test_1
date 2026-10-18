"""HTTP endpoints for agent conversations. Mounted by app.py behind the token dependency."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import ModelRef
from .runner import AgentRunner
from .store import AgentStore, Thread

router = APIRouter(prefix="/agent")


class _State:
    runner: AgentRunner
    store: AgentStore


state = _State()


def init(runner: AgentRunner, store: AgentStore) -> None:
    state.runner = runner
    state.store = store


def _thread(thread_id: str) -> Thread:
    try:
        return state.store.thread(thread_id)
    except KeyError:
        raise HTTPException(404, "conversazione non trovata") from None


def _view(thread: Thread) -> dict:
    return thread.model_dump() | {"status": state.runner.status(thread.id)}


@router.get("/tools")
def list_tools():
    return [{"name": t.name, "description": t.description, "risk": t.risk, "needs_approval": t.needs_approval} for t in state.runner.tools().values()]


@router.get("/threads")
def list_threads():
    return [_view(t) for t in state.store.threads()]


class ThreadCreate(BaseModel):
    title: str | None = None
    model: ModelRef | None = None
    vault_ids: list[str] = Field(default_factory=list)


@router.post("/threads", status_code=201)
def create_thread(body: ThreadCreate):
    thread = Thread(model=body.model, vault_ids=body.vault_ids)
    if body.title:
        thread.title = body.title
    return _view(state.store.save_thread(thread))


@router.get("/threads/{thread_id}")
def read_thread(thread_id: str):
    thread = _thread(thread_id)
    return _view(thread) | {"messages": [m.model_dump() for m in state.store.messages(thread_id)]}


class ThreadPatch(BaseModel):
    title: str | None = None
    model: ModelRef | None = None
    vault_ids: list[str] | None = None
    auto_approve: list[str] | None = None


@router.patch("/threads/{thread_id}")
def update_thread(thread_id: str, body: ThreadPatch):
    thread = _thread(thread_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(thread, field, value)
    return _view(state.store.save_thread(thread))


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str):
    state.runner.cancel(thread_id)
    state.store.delete_thread(thread_id)


class SendBody(BaseModel):
    content: str = Field(min_length=1, max_length=50000)


@router.post("/threads/{thread_id}/messages", status_code=202)
async def send_message(thread_id: str, body: SendBody):
    thread = _thread(thread_id)
    try:
        state.runner.send(thread, body.content)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"accepted": True}


class ApprovalBody(BaseModel):
    decision: Literal["allow", "allow_always", "deny"]
    note: str | None = None


@router.post("/threads/{thread_id}/approvals/{call_id}")
async def resolve_approval(thread_id: str, call_id: str, body: ApprovalBody):
    try:
        state.runner.resolve(thread_id, call_id, body.decision, body.note)
    except KeyError:
        raise HTTPException(404, "nessuna approvazione in attesa con questo id") from None
    return {"resolved": call_id}


@router.post("/threads/{thread_id}/cancel")
async def cancel_run(thread_id: str):
    state.runner.cancel(thread_id)
    return {"cancelled": thread_id}
