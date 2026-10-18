"""Times connect and stop of one stdio MCP connection (fixture server)."""

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from vault_engine.agent.mcp import McpConnection, McpServerConfig

FIXTURE = str(Path(__file__).resolve().parents[1] / "tests" / "mcp_fixture_server.py")


async def main() -> None:
    conn = McpConnection(McpServerConfig(name="probe", command=sys.executable, args=[FIXTURE]), Path(tempfile.gettempdir()))
    start = time.time()
    conn.start()
    await conn.wait_ready()
    print(f"connect {time.time() - start:.1f}s status={conn.status} error={conn.error}")
    start = time.time()
    await conn.stop()
    print(f"stop {time.time() - start:.1f}s task_done={conn._task.done()}")


asyncio.run(main())
