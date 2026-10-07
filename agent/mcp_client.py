"""MCP client: starts the UniAgent MCP server and talks to it.

The server runs as a separate process, and the two sides exchange MCP
messages over the server's stdin/stdout (the "stdio" transport). This is the
same way desktop AI apps connect to local MCP servers.
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import Client, StdioServerParameters
from mcp.types import Tool

from database.database import get_db_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MCPClient:
    """The two MCP operations the agent needs: list the tools, and call one."""

    def __init__(self, client: Client):
        self._client = client

    async def list_tools(self) -> list[Tool]:
        """Ask the server which tools it offers (name, description, input schema)."""
        result = await self._client.list_tools()
        return result.tools

    async def call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Call a tool on the server. Returns (result_text, is_error)."""
        result = await self._client.call_tool(name, arguments)
        text = "\n".join(block.text for block in result.content if block.type == "text")
        return text, result.is_error


@asynccontextmanager
async def connect_to_server():
    """Start the MCP server as a subprocess and yield a connected MCPClient."""
    server = StdioServerParameters(
        command=sys.executable,  # the same Python that is running the app
        args=["-m", "mcp_server.server"],
        cwd=PROJECT_ROOT,
        env={"UNIAGENT_DB_PATH": str(get_db_path())},  # use the same database as the app
    )
    async with Client(server) as client:
        yield MCPClient(client)
