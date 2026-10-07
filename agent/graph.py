"""The UniAgent LangGraph agent.

The graph has two nodes and loops between them until Claude has an answer:

    START --> agent --(Claude asked for a tool)--> tools --+
                ^                                          |
                +------------------------------------------+
              agent --(Claude answered)--> END

- agent: sends the conversation and the tool list to Claude.
- tools: runs the tool calls Claude asked for on the MCP server and adds
  the results to the conversation.

Messages are kept in the Claude API's own format (plain dicts), so the state
holds exactly what gets sent to the API.
"""

import copy
import operator
import os
from typing import Annotated, TypedDict

from anthropic import AsyncAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from mcp.types import Tool

from agent.mcp_client import MCPClient

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are UniAgent, the IT support assistant for Example University. \
You are chatting with a student who is already logged in.

You help with the student's university account, university email, campus Wi-Fi \
and IT support tickets, using your tools.

Rules:
- Only report account, email, Wi-Fi and ticket information that a tool returned. \
Never guess or invent it.
- Your tools always act on the logged-in student. You cannot look up or change another \
student's information. If asked to, explain that you can only help with the student's own account.
- If the student asks for something your tools cannot answer (for example grades, exam dates \
or passwords), say that you don't have access to that information and suggest contacting \
the university IT help desk.
- If a tool returns an error, explain it in simple words. Don't retry with made-up values.
- When a check shows a problem, explain it briefly and ask whether the student wants a \
support ticket.
- Only create a ticket when the student asks for one or says yes to your offer.
- Keep replies short, friendly and in plain language."""


class AgentState(TypedDict):
    # The logged-in student. The app sets this at login; the model never does.
    user_id: str
    # The conversation. `operator.add` tells LangGraph to append each node's
    # new messages to this list instead of replacing it.
    messages: Annotated[list[dict], operator.add]


def to_claude_tool(tool: Tool) -> dict:
    """Convert an MCP tool into Claude's tool format, hiding `user_id`.

    The MCP tools take a user_id, but the model must never choose whose data
    to read. So the model doesn't see that parameter at all, and the tools
    node fills it in from the logged-in session.
    """
    schema = copy.deepcopy(tool.input_schema)
    schema.get("properties", {}).pop("user_id", None)
    schema["required"] = [name for name in schema.get("required", []) if name != "user_id"]
    return {"name": tool.name, "description": tool.description or "", "input_schema": schema}


def tool_calls_in(message: dict) -> list[dict]:
    """Return the tool_use blocks in a message (an empty list if there are none)."""
    if isinstance(message["content"], str):
        return []
    return [block for block in message["content"] if block["type"] == "tool_use"]


async def create_agent(mcp_client: MCPClient, claude: AsyncAnthropic | None = None):
    """Discover the MCP server's tools and build the LangGraph agent."""
    claude = claude or AsyncAnthropic()
    model = os.getenv("UNIAGENT_MODEL", DEFAULT_MODEL)
    tools = [to_claude_tool(tool) for tool in await mcp_client.list_tools()]

    async def agent_node(state: AgentState) -> dict:
        """Ask Claude for the next step: either answer the student or call tools."""
        response = await claude.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=state["messages"],
            output_config={"effort": "low"},  # short support chats don't need deep thinking
            # If a safety filter wrongly declines a request, retry it on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        if response.stop_reason == "refusal":
            reply = "Sorry, I can't help with that request."
            return {"messages": [{"role": "assistant", "content": reply}]}

        # Keep every block (thinking, text, tool_use) exactly as Claude sent it;
        # the API expects them back unchanged on the next request.
        content = [block.to_dict() for block in response.content]
        return {"messages": [{"role": "assistant", "content": content}]}

    async def tools_node(state: AgentState) -> dict:
        """Run each tool Claude asked for on the MCP server."""
        results = []
        for call in tool_calls_in(state["messages"][-1]):
            # SECURITY: always act as the logged-in student. This also overrides
            # any user_id the model might try to sneak into the arguments.
            arguments = {**call["input"], "user_id": state["user_id"]}
            try:
                output, is_error = await mcp_client.call_tool(call["name"], arguments)
            except Exception as error:
                output, is_error = f"The tool call failed: {error}", True

            results.append({
                "type": "tool_result",
                "tool_use_id": call["id"],
                "content": output,
                "is_error": is_error,
            })

        # In the Claude API, tool results go back in a "user" message.
        return {"messages": [{"role": "user", "content": results}]}

    def route_after_agent(state: AgentState) -> str:
        """Go to the tools node if Claude asked for a tool, otherwise finish."""
        return "tools" if tool_calls_in(state["messages"][-1]) else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["tools", END])
    graph.add_edge("tools", "agent")

    # The checkpointer saves the conversation between turns (one per thread_id),
    # which is what gives the agent memory of earlier messages.
    return graph.compile(checkpointer=InMemorySaver())
