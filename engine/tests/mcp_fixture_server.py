"""Tiny MCP server for tests. stdio by default; `--http PORT` serves streamable HTTP at /mcp
and requires the header `Authorization: Bearer test-token`."""

import os
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("fixture")


@server.tool(description="Add two integers.")
def add(a: int, b: int) -> int:
    return a + b


@server.tool(description="Return the value of the FIXTURE_SECRET environment variable.")
def read_secret() -> str:
    return os.environ.get("FIXTURE_SECRET", "<unset>")


@server.tool(description="Always fails.")
def explode() -> str:
    raise ValueError("boom")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--http":
        import uvicorn
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import PlainTextResponse

        app = server.streamable_http_app()

        async def require_token(request, call_next):
            if request.headers.get("authorization") != "Bearer test-token":
                return PlainTextResponse("unauthorized", status_code=401)
            return await call_next(request)

        app.add_middleware(BaseHTTPMiddleware, dispatch=require_token)
        uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
    else:
        server.run("stdio")
