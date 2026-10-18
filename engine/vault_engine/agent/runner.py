"""The agent loop: model -> tool calls -> user approval -> tool results -> model, streamed to the UI."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..config import SettingsStore
from ..events import EventBus
from ..providers import ProviderError, chat_stream, ensure_loaded
from ..vaults import VaultRegistry
from .store import AgentStore, Message, Thread, ToolCall
from .tools import TOOLS, ToolContext, ToolError, parse_arguments

log = logging.getLogger(__name__)

Decision = Literal["allow", "allow_always", "deny"]

# Small local models drift on long contexts and every token costs seconds on CPU.
CONTEXT_CHAR_BUDGET = 48000
STORED_RESULT_CHARS = 8000

SYSTEM_PROMPT = """You are Workspace OS, a private assistant that runs entirely on the user's Windows PC.
Today is {today}. Machine: {machine}. User profile folder: {home}.

You can call tools to search the user's document Vaults, read and write local files, run PowerShell,
search the web and fetch pages. The user approves every tool call before it runs and may deny it:
if a call is denied, do not retry it in another way; continue with what you have or ask the user.

How to work:
- For questions about the user's own documents, call vault_search first. Available Vaults: {vaults}.
- Prefer few, well-aimed tool calls: each step is slow on this machine.
- For multi-step tasks, keep a task_list and update it as you progress.
- Base answers on tool results. Cite document sources as (file name, p. N) and web sources as
  (page title, URL). Say clearly when the information was not found.
- Never invent file paths, numbers or quotes.
- Reply in the user's language, concisely, using Markdown."""


@dataclass
class PendingApproval:
    call: ToolCall
    future: asyncio.Future


@dataclass
class Run:
    thread_id: str
    task: asyncio.Task | None = None
    cancelled: bool = False
    pending: dict[str, PendingApproval] = field(default_factory=dict)
    status: str = "running"
    step: int = 0


class AgentRunner:
    def __init__(self, registry: VaultRegistry, settings: SettingsStore, events: EventBus, store: AgentStore) -> None:
        self.registry = registry
        self.settings = settings
        self.events = events
        self.store = store
        self.runs: dict[str, Run] = {}

    # ------------------------------------------------------------------ public API

    def running(self, thread_id: str) -> Run | None:
        run = self.runs.get(thread_id)
        return run if run and run.task and not run.task.done() else None

    def send(self, thread: Thread, content: str) -> Run:
        if self.running(thread.id):
            raise RuntimeError("l'agente sta già lavorando in questa conversazione")
        if thread.title == "Nuova conversazione":
            thread.title = content.strip().splitlines()[0][:70] or thread.title
            self.store.save_thread(thread)
        message = self.store.append(Message(thread_id=thread.id, role="user", content=content))
        self._emit(thread.id, "message", message=message.model_dump())
        run = Run(thread_id=thread.id)
        self.runs[thread.id] = run
        run.task = asyncio.create_task(self._run(run), name=f"agent-{thread.id}")
        return run

    def resolve(self, thread_id: str, call_id: str, decision: Decision, note: str | None = None) -> None:
        run = self.running(thread_id)
        if not run or call_id not in run.pending:
            raise KeyError(call_id)
        pending = run.pending[call_id]
        if not pending.future.done():
            pending.future.set_result((decision, note))

    def cancel(self, thread_id: str) -> None:
        run = self.running(thread_id)
        if not run:
            return
        run.cancelled = True
        for pending in run.pending.values():
            if not pending.future.done():
                pending.future.set_result(("deny", "conversazione interrotta"))
        run.task.cancel()

    def status(self, thread_id: str) -> dict:
        run = self.running(thread_id)
        if not run:
            return {"running": False, "pending": []}
        return {
            "running": True,
            "step": run.step,
            "pending": [{"id": p.call.id, "name": p.call.name, "arguments": p.call.arguments} for p in run.pending.values()],
        }

    # ------------------------------------------------------------------ loop

    def _emit(self, thread_id: str, kind: str, **data) -> None:
        self.events.publish({"type": "agent", "thread_id": thread_id, "kind": kind, **data})

    def _system_prompt(self, thread: Thread) -> str:
        vaults = [v for v in self.registry.list() if not thread.vault_ids or v.config.id in thread.vault_ids]
        names = ", ".join(f"{v.config.name} ({v.count_chunks()} chunks)" for v in vaults) or "none"
        return SYSTEM_PROMPT.format(
            today=datetime.now().strftime("%A %d %B %Y"),
            machine=f"{platform.system()} {platform.release()}",
            home=str(Path.home()),
            vaults=names,
        )

    def _context(self, thread: Thread) -> list[dict]:
        """System prompt + the most recent history that fits the budget, cut at a user turn."""
        history = self.store.messages(thread.id)
        kept: list[Message] = []
        size = 0
        for message in reversed(history):
            size += len(message.content) + sum(len(c.arguments) for c in message.tool_calls or [])
            kept.append(message)
            if size > CONTEXT_CHAR_BUDGET and message.role == "user":
                break
        kept.reverse()
        # Never start with orphaned tool results.
        while kept and kept[0].role != "user":
            kept.pop(0)
        messages = [{"role": "system", "content": self._system_prompt(thread)}]
        if thread.tasks:
            plan = "\n".join(f"- [{t.status}] {t.content}" for t in thread.tasks)
            messages[0]["content"] += f"\n\nCurrent task list:\n{plan}"
        # A run interrupted mid-step leaves tool calls without results; servers reject that.
        answered = {m.tool_call_id for m in kept if m.role == "tool"}
        for m in kept:
            if m.role == "assistant" and m.tool_calls:
                calls = [c for c in m.tool_calls if c.id in answered]
                m.tool_calls = calls or None
            if m.role == "assistant" and not m.content and not m.tool_calls:
                continue  # error placeholders carry no content for the model
            messages.append(m.to_openai())
        return messages

    async def _run(self, run: Run) -> None:
        thread = self.store.thread(run.thread_id)
        settings = self.settings.get()
        model = thread.model or settings.llm
        self._emit(thread.id, "run_started")
        started = time.time()
        try:
            if model is None:
                raise ProviderError("nessun LLM configurato: sceglilo in Impostazioni")
            vault_models = [(v.config.embedding, "embedding") for v in self.registry.list() if not thread.vault_ids or v.config.id in thread.vault_ids]
            await ensure_loaded(settings.endpoints, [(model, "llm"), *vault_models])
            tools = [t.schema() for t in TOOLS.values()]
            for step in range(1, settings.agent_max_steps + 2):
                run.step = step
                final_step = step > settings.agent_max_steps
                messages = self._context(thread)
                if final_step:
                    messages.append(
                        {"role": "user", "content": "Step budget exhausted: do not call tools. Write the final answer now from the information above."}
                    )

                async def on_text(delta: str) -> None:
                    self._emit(thread.id, "delta", text=delta)

                self._emit(thread.id, "thinking", step=step)
                result = await chat_stream(
                    settings.endpoints,
                    model,
                    messages,
                    tools=None if final_step else tools,
                    max_tokens=settings.agent_max_tokens,
                    reasoning=settings.agent_reasoning,
                    on_text=on_text,
                )
                calls = [ToolCall(**c) for c in result.tool_calls]
                assistant = self.store.append(
                    Message(
                        thread_id=thread.id,
                        role="assistant",
                        content=result.content,
                        tool_calls=calls or None,
                        meta={"step": step, "usage": result.usage, "finish_reason": result.finish_reason, "model": model.model},
                    )
                )
                self._emit(thread.id, "message", message=assistant.model_dump())
                if not calls:
                    break
                for call in calls:
                    if run.cancelled:
                        return
                    tool_message = await self._execute(run, thread, call)
                    self._emit(thread.id, "message", message=tool_message.model_dump())
                    thread = self.store.thread(thread.id)  # tasks/auto-approve may have changed
            self._emit(thread.id, "run_finished", seconds=round(time.time() - started, 1))
        except asyncio.CancelledError:
            self.store.append(Message(thread_id=thread.id, role="assistant", content="_Interrotto dall'utente._", meta={"cancelled": True}))
            self._emit(thread.id, "run_finished", cancelled=True)
        except Exception as exc:  # noqa: BLE001 - surface every failure in the chat
            log.exception("agent run failed")
            error = self.store.append(Message(thread_id=thread.id, role="assistant", content="", meta={"error": str(exc)}))
            self._emit(thread.id, "message", message=error.model_dump())
            self._emit(thread.id, "run_finished", error=str(exc))
        finally:
            run.pending.clear()

    async def _execute(self, run: Run, thread: Thread, call: ToolCall) -> Message:
        tool = TOOLS.get(call.name)
        meta: dict = {"tool": call.name}
        started = time.time()
        try:
            if tool is None:
                raise ToolError(f"strumento sconosciuto: {call.name}")
            args = parse_arguments(call.arguments)
            meta["arguments"] = args
            if tool.needs_approval and call.name not in thread.auto_approve:
                future = asyncio.get_running_loop().create_future()
                run.pending[call.id] = PendingApproval(call, future)
                self._emit(thread.id, "approval", call={"id": call.id, "name": call.name, "arguments": args, "risk": tool.risk})
                decision, note = await future
                run.pending.pop(call.id, None)
                meta["decision"] = decision
                self._emit(thread.id, "approval_resolved", call_id=call.id, decision=decision)
                if decision == "deny":
                    reason = f" Motivo: {note}" if note else ""
                    raise ToolError(f"L'utente ha negato questa azione.{reason} Non riprovarla in altro modo.")
                if decision == "allow_always":
                    thread.auto_approve = sorted(set(thread.auto_approve) | {call.name})
                    self.store.save_thread(thread)
            self._emit(thread.id, "tool_started", call_id=call.id, name=call.name)
            ctx = ToolContext(self.registry, self.settings, thread, self.store.save_thread)
            output = await tool.run(ctx, args)
            content = json.dumps(output, ensure_ascii=False, default=str)
            meta["ok"] = True
        except ToolError as exc:
            content = json.dumps({"error": str(exc)}, ensure_ascii=False)
            meta["ok"] = False
            meta["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - unexpected tool crash goes back to the model
            log.exception("tool %s failed", call.name)
            content = json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
            meta["ok"] = False
            meta["error"] = str(exc)
        meta["seconds"] = round(time.time() - started, 2)
        if len(content) > STORED_RESULT_CHARS:
            content = content[:STORED_RESULT_CHARS] + "…[troncato]"
        return self.store.append(Message(thread_id=thread.id, role="tool", content=content, tool_call_id=call.id, name=call.name, meta=meta))
