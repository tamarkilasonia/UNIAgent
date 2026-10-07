"""Tests for the MCP client, using a real MCP server subprocess."""

import asyncio
import json

from agent.mcp_client import connect_to_server


def test_server_runs_as_a_subprocess_over_stdio():
    """The same connection the app uses: a real server process talking over stdin/stdout."""
    async def scenario():
        async with connect_to_server() as mcp_client:
            tools = await mcp_client.list_tools()
            result = await mcp_client.call_tool("check_email_status", {"user_id": "S1002"})
            return tools, result

    tools, (output, is_error) = asyncio.run(scenario())
    assert len(tools) == 5
    assert not is_error
    assert json.loads(output)["email_status"] == "inactive"
