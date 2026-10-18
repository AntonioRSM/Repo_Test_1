"""Agent loop with a scripted model: approvals, denials, tool execution and step budget."""

import asyncio
import json

import pytest

from vault_engine.agent import runner as runner_mod
from vault_engine.agent.runner import AgentRunner
from vault_engine.agent.store import AgentStore, Thread
from vault_engine.config import ModelRef, SettingsStore
from vault_engine.events import EventBus
from vault_engine.providers import StreamResult
from vault_engine.vaults import VaultRegistry


def call(name, **args):
    return {"id": f"c_{name}_{len(json.dumps(args))}", "name": name, "arguments": json.dumps(args)}


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    script: list[StreamResult] = []
    seen: list[list[dict]] = []

    async def fake_stream(endpoints, ref, messages, *, tools, max_tokens, reasoning, on_text, **_):
        seen.append(messages)
        result = script.pop(0)
        if result.content:
            await on_text(result.content)
        return result

    monkeypatch.setattr(runner_mod, "chat_stream", fake_stream)

    async def make():
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        queue = events.subscribe()
        settings = SettingsStore()
        settings.update({"llm": {"provider": "lmstudio", "model": "fake"}, "agent_max_steps": 3})
        store = AgentStore()
        runner = AgentRunner(VaultRegistry(), settings, events, store)
        return runner, store, queue

    return make, script, seen


async def next_event(queue, kind, timeout=5):
    while True:
        event = json.loads(await asyncio.wait_for(queue.get(), timeout))
        if event.get("type") == "agent" and event["kind"] == kind:
            return event


def test_approved_write_then_answer(agent, tmp_path):
    make, script, seen = agent
    target = tmp_path / "out" / "nota.md"
    script += [
        StreamResult(content="", tool_calls=[call("write_file", path=str(target), content="# Ciao")], finish_reason="tool_calls"),
        StreamResult(content="Fatto: file creato.", tool_calls=[], finish_reason="stop"),
    ]

    async def scenario():
        runner, store, queue = await make()
        thread = store.save_thread(Thread())
        runner.send(thread, "Crea una nota")
        approval = await next_event(queue, "approval")
        assert approval["call"]["name"] == "write_file" and approval["call"]["risk"] == "write"
        assert not target.exists()  # nothing happens before approval
        runner.resolve(thread.id, approval["call"]["id"], "allow")
        await next_event(queue, "run_finished")
        messages = store.messages(thread.id)
        assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant"]
        assert messages[-1].content == "Fatto: file creato."
        assert store.thread(thread.id).title == "Crea una nota"

    asyncio.run(scenario())
    assert target.read_text(encoding="utf-8") == "# Ciao"
    # The tool result was sent back to the model on the second step.
    assert seen[1][-1]["role"] == "tool" and '"bytes"' in seen[1][-1]["content"]


def test_denied_call_is_not_executed(agent, tmp_path):
    make, script, seen = agent
    script += [
        StreamResult(content="", tool_calls=[call("run_powershell", command="Remove-Item C:\\x")], finish_reason="tool_calls"),
        StreamResult(content="Ok, non procedo.", tool_calls=[], finish_reason="stop"),
    ]

    async def scenario():
        runner, store, queue = await make()
        thread = store.save_thread(Thread())
        runner.send(thread, "cancella")
        approval = await next_event(queue, "approval")
        runner.resolve(thread.id, approval["call"]["id"], "deny", "troppo rischioso")
        await next_event(queue, "run_finished")
        tool = [m for m in store.messages(thread.id) if m.role == "tool"][0]
        assert tool.meta["decision"] == "deny"
        assert "negato" in tool.content and "troppo rischioso" in tool.content

    asyncio.run(scenario())


def test_allow_always_skips_later_approvals(agent, tmp_path):
    make, script, seen = agent
    (tmp_path / "a.txt").write_text("alfa", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
    script += [
        StreamResult(content="", tool_calls=[call("read_file", path=str(tmp_path / "a.txt"))], finish_reason="tool_calls"),
        StreamResult(content="", tool_calls=[call("read_file", path=str(tmp_path / "b.txt"))], finish_reason="tool_calls"),
        StreamResult(content="alfa e beta", tool_calls=[], finish_reason="stop"),
    ]

    async def scenario():
        runner, store, queue = await make()
        thread = store.save_thread(Thread())
        runner.send(thread, "leggi")
        approval = await next_event(queue, "approval")
        runner.resolve(thread.id, approval["call"]["id"], "allow_always")
        await next_event(queue, "run_finished")
        tools = [m for m in store.messages(thread.id) if m.role == "tool"]
        assert [json.loads(m.content)["content"] for m in tools] == ["alfa", "beta"]
        assert store.thread(thread.id).auto_approve == ["read_file"]

    asyncio.run(scenario())


def test_task_list_needs_no_approval_and_step_budget(agent):
    make, script, seen = agent
    plan = call("task_list", tasks=[{"id": "1", "content": "Cercare", "status": "in_progress"}])
    script += [StreamResult(content="", tool_calls=[dict(plan, id=f"p{i}")], finish_reason="tool_calls") for i in range(3)]
    script.append(StreamResult(content="Riepilogo finale", tool_calls=[], finish_reason="stop"))

    async def scenario():
        runner, store, queue = await make()
        thread = store.save_thread(Thread())
        runner.send(thread, "pianifica")
        await next_event(queue, "run_finished")
        assert store.thread(thread.id).tasks[0].content == "Cercare"
        assert store.messages(thread.id)[-1].content == "Riepilogo finale"

    asyncio.run(scenario())
    # After 3 steps the 4th call is made without tools and with the wrap-up instruction.
    assert "Step budget exhausted" in seen[-1][-1]["content"]
    assert "Current task list" in seen[-1][0]["content"]


def test_bad_arguments_and_unknown_tool_go_back_to_model(agent):
    make, script, seen = agent
    script += [
        StreamResult(content="", tool_calls=[{"id": "x1", "name": "read_file", "arguments": "{not json"}, {"id": "x2", "name": "format_disk", "arguments": "{}"}], finish_reason="tool_calls"),
        StreamResult(content="Mi scuso.", tool_calls=[], finish_reason="stop"),
    ]

    async def scenario():
        runner, store, queue = await make()
        thread = store.save_thread(Thread())
        runner.send(thread, "x")
        await next_event(queue, "run_finished")
        tools = [m for m in store.messages(thread.id) if m.role == "tool"]
        assert "JSON" in tools[0].content and "sconosciuto" in tools[1].content

    asyncio.run(scenario())


def test_cancel_during_approval_leaves_valid_history(agent):
    make, script, seen = agent
    script += [StreamResult(content="", tool_calls=[call("web_search", query="meteo")], finish_reason="tool_calls")]

    async def scenario():
        runner, store, queue = await make()
        thread = store.save_thread(Thread())
        runner.send(thread, "meteo?")
        await next_event(queue, "approval")
        runner.cancel(thread.id)
        await next_event(queue, "run_finished")
        context = runner._context(store.thread(thread.id))
        # The unanswered tool call must not be sent back to the model.
        assert all(not m.get("tool_calls") for m in context if m["role"] == "assistant")

    asyncio.run(scenario())
