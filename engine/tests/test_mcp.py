"""MCP manager and agent integration against a real local MCP server (stdio and HTTP)."""

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from vault_engine.agent import runner as runner_mod
from vault_engine.agent.mcp import SECRET_MASK, McpManager, McpServerConfig, agent_tool_name
from vault_engine.agent.runner import AgentRunner
from vault_engine.agent.store import AgentStore, Thread
from vault_engine.config import SettingsStore
from vault_engine.events import EventBus
from vault_engine.providers import StreamResult
from vault_engine.vaults import VaultRegistry

FIXTURE = str(Path(__file__).with_name("mcp_fixture_server.py"))


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("WSOS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def stdio_config(**extra) -> McpServerConfig:
    return McpServerConfig(name="fixture", transport="stdio", command=sys.executable, args=[FIXTURE], **extra)


def test_tool_names_are_valid_function_names():
    name = agent_tool_name("Google Drive (work)!", "files.list")
    assert name == "mcp__Google_Drive_work__files_list"
    assert len(agent_tool_name("x" * 80, "y" * 80)) == 64


def test_stdio_server_lifecycle_and_secrets(data):
    async def scenario():
        manager = McpManager()
        view = await manager.add(stdio_config(env={"FIXTURE_SECRET": "s3cret"}))
        assert view["status"] == "connected", view["error"]
        assert {t["original_name"] for t in view["tools"]} == {"add", "read_secret", "explode"}
        assert view["env"] == {"FIXTURE_SECRET": SECRET_MASK}

        # Stored encrypted, never in clear text.
        stored = (data / "mcp.json").read_text(encoding="utf-8")
        assert "s3cret" not in stored and "dpapi:" in stored

        tools = {t.original_name: t for t in manager.tools()}
        assert (await manager.call(tools["add"], {"a": 2, "b": 40}))["content"] == "42"
        assert (await manager.call(tools["read_secret"], {}))["content"] == "s3cret"
        failed = await manager.call(tools["explode"], {})
        # The v2 SDK hides server exception details from clients by default.
        assert failed["is_error"] and "explode" in failed["content"]

        # A masked value in a patch keeps the stored secret.
        view = await manager.update(view["id"], {"env": {"FIXTURE_SECRET": SECRET_MASK}, "timeout_seconds": 30})
        tools = {t.original_name: t for t in manager.tools()}
        assert (await manager.call(tools["read_secret"], {}))["content"] == "s3cret"

        # Disabled servers expose no tools; config survives a restart of the manager.
        await manager.update(view["id"], {"enabled": False})
        assert manager.tools() == []
        await manager.shutdown()
        reloaded = McpManager()
        assert reloaded.list()[0]["enabled"] is False
        await manager.remove(view["id"])

    asyncio.run(scenario())


def test_missing_command_reports_error(data):
    async def scenario():
        manager = McpManager()
        view = await manager.add(McpServerConfig(name="missing", command="definitely-not-a-command-xyz"))
        assert view["status"] == "error"
        assert view["error"]
        await manager.shutdown()

    asyncio.run(scenario())


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_http_server_with_auth_header(data):
    port = free_port()
    proc = subprocess.Popen([sys.executable, FIXTURE, "--http", str(port)])
    try:
        for _ in range(100):
            try:
                httpx.get(f"http://127.0.0.1:{port}/mcp", timeout=0.5)
                break
            except httpx.HTTPError:
                time.sleep(0.1)

        async def scenario():
            manager = McpManager()
            url = f"http://127.0.0.1:{port}/mcp"
            denied = await manager.add(McpServerConfig(name="noauth", transport="http", url=url))
            assert denied["status"] == "error"
            view = await manager.add(
                McpServerConfig(name="web", transport="http", url=url, headers={"Authorization": "Bearer test-token"})
            )
            assert view["status"] == "connected", view["error"]
            tool = next(t for t in manager.tools() if t.original_name == "add")
            assert (await manager.call(tool, {"a": 1, "b": 1}))["content"] == "2"
            await manager.shutdown()

        asyncio.run(scenario())
    finally:
        proc.terminate()
        proc.wait(5)


def test_agent_calls_mcp_tool_after_approval(data, monkeypatch):
    script = []

    async def fake_stream(endpoints, ref, messages, *, tools, max_tokens, reasoning, on_text, **_):
        script_tools.append([t["function"]["name"] for t in tools or []])
        return script.pop(0)

    script_tools: list[list[str]] = []
    monkeypatch.setattr(runner_mod, "chat_stream", fake_stream)

    async def scenario():
        events = EventBus()
        events.bind(asyncio.get_running_loop())
        queue = events.subscribe()
        settings = SettingsStore()
        settings.update({"llm": {"provider": "lmstudio", "model": "fake"}})
        manager = McpManager()
        await manager.add(stdio_config())
        name = agent_tool_name("fixture", "add")
        script.extend(
            [
                StreamResult(content="", tool_calls=[{"id": "m1", "name": name, "arguments": '{"a": 20, "b": 22}'}], finish_reason="tool_calls"),
                StreamResult(content="Fa 42.", tool_calls=[], finish_reason="stop"),
            ]
        )
        store = AgentStore()
        runner = AgentRunner(VaultRegistry(), settings, events, store, manager)
        thread = store.save_thread(Thread())
        runner.send(thread, "quanto fa 20+22?")
        while True:
            event = json.loads(await asyncio.wait_for(queue.get(), 10))
            if event.get("kind") == "approval":
                assert event["call"]["risk"] == "mcp"
                runner.resolve(thread.id, event["call"]["id"], "allow")
            if event.get("kind") == "run_finished":
                break
        tool_msg = [m for m in store.messages(thread.id) if m.role == "tool"][0]
        assert json.loads(tool_msg.content)["content"] == "42"
        assert "fixture (3 tools)" in runner._system_prompt(thread)
        await manager.shutdown()

    asyncio.run(scenario())
    assert agent_tool_name("fixture", "add") in script_tools[0]
